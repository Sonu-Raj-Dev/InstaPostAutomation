"""Official Meta Instagram Graph API Client (v22.0).

Supports:
- 100% Free, direct Meta publishing (Zero third-party dependencies)
- 60-day auto-refreshing long-lived access tokens
- Multi-image carousels (2-10 slides) via asynchronous container workflow
- Single-image and Reels publishing
- Real-time Insights (reach, impressions, saves, shares, profile views)
"""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MetaGraphClient")

GRAPH_API_VERSION = "v22.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

POLL_TIMEOUT_S = 120   # ponytail: one limit for all image posts; per-format limits if video/Reels publishing is added
POLL_INTERVAL_S = 3
_TOKEN_RE = re.compile(r"(access_token|input_token|client_secret|fb_exchange_token)=[^&\s'\"]+")


def _scrub(text: str) -> str:
    """Request URLs carry the token; never let one reach an error message, log or the database."""
    return _TOKEN_RE.sub(r"\1=***", text or "")


def _hint(e: Dict[str, Any]) -> str:
    code, sub, kind = e.get("code"), e.get("subcode"), e.get("kind")
    if kind == "config":
        return "Connect Instagram in Settings."
    if code == 190:
        return "The Instagram access token is expired or invalid. Renew it in Settings."
    if code == 10 or (isinstance(code, int) and 200 <= code <= 299):
        return "The token is missing a permission (needs instagram_basic + instagram_content_publish). Reconnect with those permissions."
    if code in (4, 17, 32, 613) or sub == 2207042:
        return "Meta rate or publishing limit reached. Wait, then retry."
    if code == 9004 or sub in (2207052, 2207003, 2207020):
        return "Meta could not download an image. Each slide must be a public HTTPS JPEG."
    if sub in (2207026, 2207083, 2207004):
        return "Unsupported image. Use JPEG under 8 MB."
    if code == 36003 or sub == 2207009:
        return "Image aspect ratio not accepted (allowed 4:5 to 1.91:1)."
    if kind in ("timeout", "network"):
        return "Meta did not answer in time."
    if kind == "processing_timeout":
        return "Meta is still processing. Retry in a few minutes."
    if kind == "processing":
        return "Re-render the slides and retry."
    return ""


def _error(http_status: int, body: Dict[str, Any], fallback: str, kind: str, uncertain: bool = False, **extra) -> Dict[str, Any]:
    e = (body or {}).get("error") or {}
    out = {"http_status": http_status, "code": e.get("code"), "subcode": e.get("error_subcode"), "type": e.get("type", ""),
           "message": _scrub(e.get("error_user_msg") or e.get("message") or fallback), "fbtrace_id": e.get("fbtrace_id", ""),
           "kind": kind, "uncertain": uncertain, **extra}
    out["hint"] = _hint(out)
    return out


def format_error(e: Dict[str, Any]) -> str:
    """One readable line for the dashboard: what Meta said, what to do, and the ids support needs."""
    ids = " · ".join(x for x in [f"code {e['code']}" if e.get("code") is not None else "",
                                  f"subcode {e['subcode']}" if e.get("subcode") else "",
                                  f"HTTP {e['http_status']}" if e.get("http_status") else "",
                                  f"fbtrace {e['fbtrace_id']}" if e.get("fbtrace_id") else ""] if x)
    return " ".join(x for x in [e.get("message") or "Unknown error", f"→ {e['hint']}" if e.get("hint") else "",
                                f"[{ids}]" if ids else ""] if x)


def check_image_url(url: str, timeout: int = 15) -> Tuple[bool, str]:
    """Meta downloads each slide itself: it must be public HTTPS, answer 200 and be a JPEG."""
    if not (url or "").startswith("https://"):
        return False, f"not a public HTTPS URL ({(url or '')[:60]})"
    try:
        r = requests.request("HEAD", url, timeout=timeout, allow_redirects=True)
        if r.status_code in (403, 405):  # some hosts refuse HEAD
            r = requests.request("GET", url, timeout=timeout, allow_redirects=True, stream=True)
    except requests.RequestException as e:
        return False, f"unreachable: {_scrub(str(e))[:120]}"
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if r.status_code != 200:
        return False, f"returned HTTP {r.status_code}"
    if ctype not in ("image/jpeg", "image/jpg"):
        return False, f"is {ctype or 'an unknown type'}; Instagram needs image/jpeg"
    return True, ""


def _saved_token() -> str:
    """A token renewed from Settings is stored in the database (works on Vercel, where env vars are read-only)."""
    try:
        from store import get_secret
        return get_secret("meta_access_token")
    except Exception:
        return ""


class MetaGraphClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
    ):
        self.access_token = access_token or os.getenv("META_ACCESS_TOKEN", "").strip()
        self.ig_user_id = ig_user_id or os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()
        self.app_id = app_id or os.getenv("META_APP_ID", "").strip()
        self.app_secret = app_secret or os.getenv("META_APP_SECRET", "").strip()

    def exchange_for_long_lived_token(self, short_lived_token: str) -> Dict[str, Any]:
        """Exchange a 1-2 hour Graph API Explorer token for a 60-day Long-Lived Token."""
        if not self.app_id or not self.app_secret:
            return {"success": False, "error": "META_APP_ID and META_APP_SECRET are required."}

        url = f"{GRAPH_BASE_URL}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.app_id,
            "client_secret": self.app_secret,
            "fb_exchange_token": short_lived_token,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                long_lived_token = data.get("access_token")
                expires_in = data.get("expires_in")
                logger.info(f"Successfully generated 60-day Long-Lived Token! Expires in {expires_in}s")
                return {"success": True, "access_token": long_lived_token, "expires_in": expires_in}
            return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            logger.error(f"Error exchanging token: {e}")
            return {"success": False, "error": str(e)}

    def discover_instagram_account_id(self) -> Dict[str, Any]:
        """Discover the linked Instagram Professional Account ID from your Facebook Pages."""
        if not self.access_token:
            return {"success": False, "error": "META_ACCESS_TOKEN is required."}

        url = f"{GRAPH_BASE_URL}/me/accounts"
        params = {"access_token": self.access_token}
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return {"success": False, "status_code": resp.status_code, "error": resp.text}

            pages = resp.json().get("data", [])
            if not pages:
                return {"success": False, "error": "No Facebook Pages found for this token."}

            for page in pages:
                page_id = page.get("id")
                page_name = page.get("name")
                # Query page for linked Instagram account
                ig_url = f"{GRAPH_BASE_URL}/{page_id}"
                ig_params = {
                    "fields": "instagram_business_account{id,username,name,profile_picture_url}",
                    "access_token": self.access_token,
                }
                ig_resp = requests.get(ig_url, params=ig_params, timeout=10)
                if ig_resp.status_code == 200:
                    ig_data = ig_resp.json().get("instagram_business_account")
                    if ig_data:
                        self.ig_user_id = ig_data.get("id")
                        return {
                            "success": True,
                            "page_name": page_name,
                            "page_id": page_id,
                            "instagram_account_id": self.ig_user_id,
                            "instagram_username": ig_data.get("username"),
                        }

            return {
                "success": False,
                "error": "No Instagram Professional account found linked to your Facebook Pages. Verify Instagram is linked to your Page.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ publishing (structured errors)
    def request(self, method: str, path: str, timeout: int = 30, **params) -> Dict[str, Any]:
        """One Graph call -> {"ok": True, "data": {...}} or {"ok": False, "error": <meta error dict>}. Never raises."""
        if not self.access_token:
            return {"ok": False, "error": _error(0, {}, "No Instagram access token configured", "config")}
        try:
            resp = requests.request(method, f"{GRAPH_BASE_URL}/{path}", timeout=timeout,
                                    params={**params, "access_token": self.access_token})
        except requests.Timeout:
            return {"ok": False, "error": _error(0, {}, f"No answer from Meta within {timeout}s", "timeout", uncertain=True)}
        except requests.RequestException as e:
            return {"ok": False, "error": _error(0, {}, f"Network error: {_scrub(str(e))}", "network", uncertain=True)}
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 200 and isinstance(body, dict) and "error" not in body:
            return {"ok": True, "data": body}
        return {"ok": False, "error": _error(resp.status_code, body if isinstance(body, dict) else {}, _scrub(resp.text[:300]),
                                              "meta", uncertain=resp.status_code >= 500)}

    def token_scopes(self) -> Optional[List[str]]:
        """Granted permissions of the current token, or None when they can't be read."""
        try:
            inspector = f"{self.app_id}|{self.app_secret}" if self.app_id and self.app_secret else self.access_token
            r = requests.request("GET", f"{GRAPH_BASE_URL}/debug_token", timeout=15,
                                 params={"input_token": self.access_token, "access_token": inspector})
            d = r.json().get("data") or {}
            return d.get("scopes") if d.get("is_valid") and isinstance(d.get("scopes"), list) else None
        except Exception:
            return None

    def create_container(self, image_url: str, caption: str = "", carousel_item: bool = False) -> Dict[str, Any]:
        params = {"image_url": image_url}
        if carousel_item:
            params["is_carousel_item"] = "true"
        else:
            params["caption"] = caption
        return self.request("POST", f"{self.ig_user_id}/media", **params)

    def create_carousel_container(self, children_ids: List[str], caption: str) -> Dict[str, Any]:
        return self.request("POST", f"{self.ig_user_id}/media", media_type="CAROUSEL", children=",".join(children_ids), caption=caption)

    def container_status(self, container_id: str) -> Dict[str, Any]:
        """status_code: IN_PROGRESS | FINISHED | ERROR | EXPIRED | PUBLISHED."""
        r = self.request("GET", container_id, timeout=15, fields="status_code,status")
        if r["ok"]:
            r["status_code"], r["status"] = r["data"].get("status_code", ""), r["data"].get("status", "")
        return r

    def wait_container(self, container_id: str, timeout_s: int = 0, interval: int = 0) -> Dict[str, Any]:
        """Poll until FINISHED. Network blips are retried; ERROR/EXPIRED and the time limit are failures."""
        timeout_s, interval = timeout_s or POLL_TIMEOUT_S, interval or POLL_INTERVAL_S
        deadline, last = time.monotonic() + timeout_s, None
        while True:
            r = self.container_status(container_id)
            if r["ok"]:
                code = r["status_code"]
                if code in ("FINISHED", "PUBLISHED"):
                    return r
                if code in ("ERROR", "EXPIRED"):
                    return {"ok": False, "error": _error(200, {}, f"Meta could not process the media ({code}): {r['status'] or 'no detail'}",
                                                         "processing", container_status=code)}
            elif not r["error"].get("uncertain"):
                return r
            last = r
            if time.monotonic() >= deadline:
                detail = f"last status {last['status_code']}" if last and last.get("ok") else "Meta unreachable"
                return {"ok": False, "error": _error(0, {}, f"Media still processing after {timeout_s}s ({detail})", "processing_timeout")}
            time.sleep(interval)

    def publish_creation(self, creation_id: str) -> Dict[str, Any]:
        return self.request("POST", f"{self.ig_user_id}/media_publish", timeout=60, creation_id=creation_id)

    def find_published_media(self, caption: str, since_utc: str) -> Optional[str]:
        """Media id of a post we published but whose id we never received (matched on caption + time)."""
        r = self.request("GET", f"{self.ig_user_id}/media", timeout=15, fields="id,caption,timestamp", limit=10)
        if not r["ok"]:
            return None
        head = (caption or "").strip()[:80]
        since = (since_utc or "")[:19]
        for m in r["data"].get("data", []):
            if (m.get("caption") or "").strip()[:80] == head and (m.get("timestamp") or "")[:19] >= since:
                return m.get("id")
        return None

    # ---- simple wrappers kept for scripts / MCP server (publish_live_carousel.py, mcp_server.py)
    def wait_for_container_ready(self, container_id: str, max_retries: int = 15, delay: int = 3) -> bool:
        return self.wait_container(container_id, timeout_s=max_retries * delay, interval=delay)["ok"]

    def publish_container(self, creation_id: str) -> Dict[str, Any]:
        r = self.publish_creation(creation_id)
        if r["ok"]:
            return {"success": True, "post_id": r["data"].get("id")}
        return {"success": False, "error": format_error(r["error"]), "meta_error": r["error"]}

    def publish_carousel(self, image_urls: List[str], caption: str) -> Dict[str, Any]:
        if not 2 <= len(image_urls) <= 10:
            return {"success": False, "error": "Instagram carousels require between 2 and 10 images."}
        children = []
        for i, u in enumerate(image_urls, 1):
            r = self.create_container(u, carousel_item=True)
            if not r["ok"]:
                return {"success": False, "error": f"Slide {i}: {format_error(r['error'])}", "meta_error": r["error"]}
            children.append(r["data"]["id"])
        for i, ch in enumerate(children, 1):
            w = self.wait_container(ch)
            if not w["ok"]:
                return {"success": False, "error": f"Slide {i}: {format_error(w['error'])}", "meta_error": w["error"]}
        r = self.create_carousel_container(children, caption)
        if not r["ok"]:
            return {"success": False, "error": format_error(r["error"]), "meta_error": r["error"]}
        w = self.wait_container(r["data"]["id"])
        if not w["ok"]:
            return {"success": False, "error": format_error(w["error"]), "meta_error": w["error"]}
        return self.publish_container(r["data"]["id"])

    # ------------------------------------------------------------------ v3 additions
    def _get(self, path: str, **params) -> Dict[str, Any]:
        """GET helper → {"ok": True, "data": ...} or {"ok": False, "error": msg, "code": n}."""
        if not self.access_token:
            return {"ok": False, "error": "No META_ACCESS_TOKEN configured", "code": 0}
        try:
            resp = requests.get(f"{GRAPH_BASE_URL}/{path}", params={**params, "access_token": self.access_token}, timeout=15)
            data = resp.json()
        except Exception as e:
            return {"ok": False, "error": f"Network error: {e}", "code": -1}
        if resp.status_code == 200 and "error" not in data:
            return {"ok": True, "data": data}
        err = data.get("error", {}) if isinstance(data, dict) else {}
        return {"ok": False, "error": err.get("message", resp.text[:300]), "code": err.get("code", resp.status_code),
                "subcode": err.get("error_subcode")}

    def reload(self):
        load_dotenv(override=True)
        self.access_token = (_saved_token() or os.getenv("META_ACCESS_TOKEN", "")).strip()
        self.ig_user_id = os.getenv("INSTAGRAM_ACCOUNT_ID", "").strip()

    def diagnostics(self) -> Dict[str, Any]:
        """Token validity, expiry, scopes and the connected account. Read-only."""
        out: Dict[str, Any] = {"configured": bool(self.access_token and self.ig_user_id),
                               "account_id": self.ig_user_id, "app_id_configured": bool(self.app_id)}
        acct = self._get(self.ig_user_id or "me", fields="id,username,name,followers_count,follows_count,media_count,profile_picture_url")
        out["account"] = acct.get("data") if acct["ok"] else None
        out["token_valid"] = acct["ok"]
        out["error"] = None if acct["ok"] else acct["error"]
        out["error_code"] = None if acct["ok"] else acct.get("code")
        if self.access_token:
            try:  # app token when the secret is configured, otherwise the token can inspect itself
                inspector = f"{self.app_id}|{self.app_secret}" if self.app_id and self.app_secret else self.access_token
                r = requests.get(f"{GRAPH_BASE_URL}/debug_token", timeout=15, params={
                    "input_token": self.access_token, "access_token": inspector})
                d = r.json().get("data", {})
                out["token"] = {"type": d.get("type"), "is_valid": d.get("is_valid"), "expires_at": d.get("expires_at"),
                                "data_access_expires_at": d.get("data_access_expires_at"), "scopes": d.get("scopes", []),
                                "error": (d.get("error") or {}).get("message")}
            except Exception as e:
                out["token"] = {"error": str(e)}
        scopes = set((out.get("token") or {}).get("scopes") or [])
        out["capabilities"] = {
            "publish": "instagram_content_publish" in scopes,
            "insights": "instagram_manage_insights" in scopes,
            "comments": "instagram_manage_comments" in scopes,
            "messaging": "instagram_manage_messages" in scopes,
        }
        return out

    def get_permalink(self, media_id: str) -> str:
        r = self._get(media_id, fields="permalink")
        return r["data"].get("permalink", "") if r["ok"] else ""

    def publish_single_image(self, image_url: str, caption: str) -> Dict[str, Any]:
        r = self.create_container(image_url, caption)
        if not r["ok"]:
            return {"success": False, "error": format_error(r["error"]), "meta_error": r["error"]}
        w = self.wait_container(r["data"]["id"])
        if not w["ok"]:
            return {"success": False, "error": format_error(w["error"]), "meta_error": w["error"]}
        return self.publish_container(r["data"]["id"])

    def get_account_insights(self, days: int = 30) -> Dict[str, Any]:
        """Daily reach + follower_count series and period totals (Graph API v22 metric set)."""
        import time as _t
        until = int(_t.time())
        since = until - min(days, 30) * 86400
        series = self._get(f"{self.ig_user_id}/insights", metric="reach,follower_count", period="day", since=since, until=until)
        totals = self._get(f"{self.ig_user_id}/insights", metric="views,accounts_engaged,total_interactions,likes,comments,saves,shares,profile_views",
                           period="day", metric_type="total_value", since=since, until=until)
        if not series["ok"] and not totals["ok"]:
            return {"success": False, "error": series["error"], "code": series.get("code")}
        out = {"success": True, "series": {}, "totals": {}, "errors": []}
        if series["ok"]:
            for m in series["data"].get("data", []):
                out["series"][m["name"]] = [{"date": v["end_time"][:10], "value": v["value"]} for v in m.get("values", [])]
        else:
            out["errors"].append(series["error"])
        if totals["ok"]:
            for m in totals["data"].get("data", []):
                out["totals"][m["name"]] = (m.get("total_value") or {}).get("value")
        else:
            out["errors"].append(totals["error"])
        return out

    def get_recent_media(self, limit: int = 25) -> Dict[str, Any]:
        r = self._get(f"{self.ig_user_id}/media", limit=limit,
                      fields="id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count,thumbnail_url,media_url")
        if not r["ok"]:
            return {"success": False, "error": r["error"]}
        media = r["data"].get("data", [])
        for m in media:
            metrics = "reach,saved,shares,views,total_interactions"
            ins = self._get(f"{m['id']}/insights", metric=metrics)
            m["insights"] = {x["name"]: (x.get("values") or [{}])[0].get("value") for x in ins["data"].get("data", [])} if ins["ok"] else {}
            if not ins["ok"]:
                m["insights_error"] = ins["error"]
        return {"success": True, "media": media}

    def get_media_insights(self, media_id: str) -> Dict[str, Any]:
        r = self._get(f"{media_id}/insights", metric="saved,shares,reach,total_interactions")
        return {"success": True, "data": r["data"]} if r["ok"] else {"success": False, "error": r["error"]}
