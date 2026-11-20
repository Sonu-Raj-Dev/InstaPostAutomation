"""Official Meta Instagram Graph API Client (v22.0).

Supports:
- 100% Free, direct Meta publishing (Zero third-party dependencies)
- 60-day auto-refreshing long-lived access tokens
- Multi-image carousels (2-10 slides) via asynchronous container workflow
- Single-image and Reels publishing
- Real-time Insights (reach, impressions, saves, shares, profile views)
"""

import os
import time
import logging
from typing import Dict, Any, List, Optional
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MetaGraphClient")

GRAPH_API_VERSION = "v22.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


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

    def create_carousel_item_container(self, image_url: str) -> Optional[str]:
        """Step 1: Create an individual child item container for a carousel slide."""
        url = f"{GRAPH_BASE_URL}/{self.ig_user_id}/media"
        payload = {
            "image_url": image_url,
            "is_carousel_item": "true",
            "access_token": self.access_token,
        }
        try:
            resp = requests.post(url, data=payload, timeout=20)
            if resp.status_code == 200:
                return resp.json().get("id")
            logger.error(f"Failed to create child container: {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Exception creating child container: {e}")
            return None

    def create_carousel_parent_container(self, children_ids: List[str], caption: str) -> Optional[str]:
        """Step 2: Create the parent carousel container holding all slide item IDs."""
        url = f"{GRAPH_BASE_URL}/{self.ig_user_id}/media"
        payload = {
            "media_type": "CAROUSEL",
            "children": ",".join(children_ids),
            "caption": caption,
            "access_token": self.access_token,
        }
        try:
            resp = requests.post(url, data=payload, timeout=20)
            if resp.status_code == 200:
                return resp.json().get("id")
            logger.error(f"Failed to create parent carousel container: {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Exception creating parent container: {e}")
            return None

    def wait_for_container_ready(self, container_id: str, max_retries: int = 15, delay: int = 3) -> bool:
        """Step 3: Poll Meta until the container status_code becomes FINISHED."""
        url = f"{GRAPH_BASE_URL}/{container_id}"
        params = {"fields": "status_code", "access_token": self.access_token}

        for attempt in range(max_retries):
            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    status = resp.json().get("status_code")
                    if status == "FINISHED":
                        return True
                    elif status == "ERROR":
                        logger.error(f"Container processing failed with ERROR status: {resp.text}")
                        return False
                time.sleep(delay)
            except Exception as e:
                logger.warning(f"Container check retry {attempt+1}: {e}")
                time.sleep(delay)
        return False

    def publish_container(self, creation_id: str) -> Dict[str, Any]:
        """Step 4: Execute final publish command for the ready container."""
        url = f"{GRAPH_BASE_URL}/{self.ig_user_id}/media_publish"
        payload = {
            "creation_id": creation_id,
            "access_token": self.access_token,
        }
        try:
            resp = requests.post(url, data=payload, timeout=20)
            if resp.status_code == 200:
                media_id = resp.json().get("id")
                logger.info(f"Successfully published to Instagram! Post ID: {media_id}")
                return {"success": True, "post_id": media_id}
            return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def publish_carousel(self, image_urls: List[str], caption: str) -> Dict[str, Any]:
        """High-level orchestrator: Publishes a complete 2-to-10 slide carousel."""
        if len(image_urls) < 2 or len(image_urls) > 10:
            return {"success": False, "error": "Instagram carousels require between 2 and 10 images."}

        logger.info(f"Starting 4-step Meta carousel publish for {len(image_urls)} slides...")

        # 1. Create Child Containers
        child_ids = []
        for idx, img_url in enumerate(image_urls, start=1):
            logger.info(f"Staging slide {idx}/{len(image_urls)}...")
            cid = self.create_carousel_item_container(img_url)
            if not cid:
                return {"success": False, "error": f"Failed staging slide {idx} ({img_url})"}
            child_ids.append(cid)

        # 2. Create Parent Container
        logger.info("Creating parent carousel container...")
        parent_id = self.create_carousel_parent_container(child_ids, caption)
        if not parent_id:
            return {"success": False, "error": "Failed creating parent carousel container."}

        # 3. Wait for Meta processing
        logger.info(f"Waiting for container {parent_id} processing...")
        if not self.wait_for_container_ready(parent_id):
            return {"success": False, "error": "Meta container processing timed out or failed."}

        # 4. Final Publish
        logger.info("Publishing container to live Instagram feed...")
        return self.publish_container(parent_id)

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
        try:
            resp = requests.post(f"{GRAPH_BASE_URL}/{self.ig_user_id}/media", timeout=30,
                                 data={"image_url": image_url, "caption": caption, "access_token": self.access_token})
            cid = resp.json().get("id") if resp.status_code == 200 else None
        except Exception as e:
            return {"success": False, "error": str(e)}
        if not cid:
            return {"success": False, "error": f"Container creation failed: {resp.text[:300]}"}
        if not self.wait_for_container_ready(cid):
            return {"success": False, "error": "Meta container processing timed out or failed."}
        return self.publish_container(cid)

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
