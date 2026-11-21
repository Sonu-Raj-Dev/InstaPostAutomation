"""Read-only Meta configuration audit (Phase 7). Only GET requests; changes nothing at Meta. Tokens never appear in the output.

Checks: token type / validity / expiry / permissions (debug_token) · connected Facebook Page + Instagram professional account ·
app-level webhook subscriptions (needs the app secret → app access token) · Page → app subscription (needs a Page token) ·
which messaging endpoint the current token can use. App mode and Advanced Access are NOT exposed by the Graph API: reported as
"check in the App Dashboard", never guessed.
"""

import os
import time
from typing import Any, Dict, Optional, Tuple

import requests

try:  # use the OS certificate store (corporate proxies / custom CAs), like the rest of the app
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from meta_graph_client import GRAPH_BASE_URL, _saved_token, _scrub

NEEDED = {
    "instagram_basic": "read the account and comments",
    "instagram_content_publish": "publish posts",
    "instagram_manage_comments": "receive comment webhooks / read comments",
    "instagram_manage_messages": "send private replies and DMs",
    "pages_show_list": "find the linked Facebook Page",
    "pages_read_engagement": "read Page / account data",
    "pages_manage_metadata": "subscribe the Page to webhooks",
    "instagram_manage_insights": "analytics",
}


def _get(path: str, token: str, **params) -> Tuple[bool, Dict[str, Any]]:
    try:
        r = requests.request("GET", f"{GRAPH_BASE_URL}/{path}", params={**params, "access_token": token}, timeout=15)
        d = r.json()
    except Exception as e:
        return False, {"message": _scrub(f"{type(e).__name__}: {e}")[:300]}
    if r.status_code == 200 and isinstance(d, dict) and "error" not in d:
        return True, d
    e = (d or {}).get("error", {}) if isinstance(d, dict) else {}
    return False, {"message": _scrub(e.get("message") or r.text[:300]), "code": e.get("code"), "subcode": e.get("error_subcode")}


def run(token: Optional[str] = None, app_id: Optional[str] = None, app_secret: Optional[str] = None,
        ig_user_id: Optional[str] = None) -> Dict[str, Any]:
    token = (token or _saved_token() or os.getenv("META_ACCESS_TOKEN", "")).strip()
    app_id = (app_id or os.getenv("META_APP_ID", "")).strip()
    app_secret = (app_secret or os.getenv("META_APP_SECRET", "")).strip()
    ig_user_id = (ig_user_id or os.getenv("INSTAGRAM_ACCOUNT_ID", "")).strip()
    app_token = f"{app_id}|{app_secret}" if app_id and app_secret else ""
    out: Dict[str, Any] = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "errors": [], "actions": []}
    if not token:
        out["errors"].append("No Instagram access token configured")
        out["actions"].append("Connect Instagram in Settings (paste a long-lived token)")
        return out

    # ---- token
    ok, d = _get("debug_token", app_token or token, input_token=token)
    t = d.get("data", {}) if ok else {}
    scopes = t.get("scopes") or []
    out["token"] = {"valid": bool(t.get("is_valid")), "type": t.get("type"), "app_id": t.get("app_id"), "app_name": t.get("application"),
                    "expires_at": t.get("expires_at"), "data_access_expires_at": t.get("data_access_expires_at"),
                    "never_expires": t.get("expires_at") == 0, "scopes": scopes,
                    "granular": [{"scope": g.get("scope"), "targets": len(g.get("target_ids") or [])} for g in t.get("granular_scopes") or []],
                    "error": None if ok else d.get("message")}
    if app_id and t.get("app_id") and str(t.get("app_id")) != app_id:
        out["errors"].append(f"The token belongs to app {t.get('app_id')}, but META_APP_ID is {app_id}")
    missing = {k: v for k, v in NEEDED.items() if scopes and k not in scopes}
    out["permissions"] = {"granted": [k for k in NEEDED if k in scopes], "missing": missing, "unknown": not scopes}
    for k, why in missing.items():
        out["actions"].append(f"Add permission {k} (needed to {why}) and generate a new token")
    if not ok:  # the check itself failed (network / Meta error): don't call the token invalid
        out["errors"].append(f"Couldn't check the token: {d.get('message')}")
    elif not t.get("is_valid"):
        out["errors"].append(f"Token is not valid: {(t.get('error') or {}).get('message') or 'unknown reason'}")
        out["actions"].append("Generate a new long-lived token and save it in Settings")

    # ---- Page + Instagram account
    page_token, page = "", {}
    if t.get("type") == "PAGE":
        ok_p, page = _get("me", token, fields="id,name,instagram_business_account{id,username,name,followers_count}")
        page_token = token if ok_p else ""
    else:
        ok_p, pages = _get("me/accounts", token, fields="id,name,access_token,instagram_business_account{id,username,name,followers_count}")
        lst = pages.get("data", []) if ok_p else []
        page = next((p for p in lst if (p.get("instagram_business_account") or {}).get("id") == ig_user_id), lst[0] if lst else {})
        page_token = page.pop("access_token", "") if page else ""
        for p in lst:
            p.pop("access_token", None)
        out["pages_found"] = [{"id": p.get("id"), "name": p.get("name"), "instagram": (p.get("instagram_business_account") or {}).get("username")} for p in lst]
        if not ok_p:
            out["errors"].append(f"Couldn't list Facebook Pages: {pages.get('message')}")
    ig = (page or {}).get("instagram_business_account") or {}
    out["page"] = {"id": page.get("id"), "name": page.get("name")} if page else None
    out["instagram"] = {"id": ig.get("id"), "username": ig.get("username"), "followers": ig.get("followers_count"),
                        "type": "Professional (Business or Creator) account linked to the Page" if ig else None,
                        "matches_configured_id": (ig.get("id") == ig_user_id) if ig and ig_user_id else None}
    if not ig:
        out["errors"].append("No Instagram professional account found on the connected Facebook Page")
    elif ig_user_id and ig.get("id") != ig_user_id:
        out["errors"].append(f"INSTAGRAM_ACCOUNT_ID ({ig_user_id}) differs from the account linked to the Page ({ig.get('id')})")

    # ---- app-level webhook subscriptions (app token)
    if app_token:
        ok_s, subs = _get(f"{app_id}/subscriptions", app_token)
        objs = {s.get("object"): s for s in subs.get("data", [])} if ok_s else {}
        insta = objs.get("instagram") or {}
        fields = {f.get("name") for f in insta.get("fields", [])}
        out["webhook_fields"] = {"comments": "comments" in fields, "messages": "messages" in fields, "all": sorted(fields)}
        out["webhook"] = {"active": insta.get("active"), "callback_url": insta.get("callback_url"), "objects": sorted(objs)}
        if not ok_s:
            out["errors"].append(f"Couldn't read app webhook subscriptions: {subs.get('message')}")
        else:
            if not insta:
                out["actions"].append("App Dashboard → Webhooks → Instagram: subscribe with the callback URL and verify token shown in Settings")
            for f in ("comments", "messages"):
                if insta and f not in fields:
                    out["actions"].append(f"App Dashboard → Webhooks → Instagram: subscribe the '{f}' field")
        ok_a, appinfo = _get(app_id, app_token, fields="name,link,category")
        out["app"] = {"id": app_id, "name": appinfo.get("name") if ok_a else t.get("application"), "category": appinfo.get("category") if ok_a else None}
    else:
        out["webhook_fields"] = {"comments": None, "messages": None, "all": []}
        out["app"] = {"id": app_id or t.get("app_id"), "name": t.get("application")}
        out["errors"].append("META_APP_SECRET is not set here, so app-level webhook subscriptions can't be read (and webhooks are rejected)")
        out["actions"].append("Set META_APP_SECRET (App Dashboard → App settings → Basic) in Vercel")
    out["app"]["mode"] = "Not exposed by the Graph API: check the Development/Live switch at the top of the App Dashboard"
    out["app"]["advanced_access"] = "Not exposed by the Graph API: check App Review → Permissions and Features"

    # ---- Page → app subscription (Page token)
    if page_token and page.get("id"):
        ok_sa, sa = _get(f"{page['id']}/subscribed_apps", page_token)
        mine = next((a for a in sa.get("data", []) if not app_id or str(a.get("id")) == app_id), None) if ok_sa else None
        out["page_subscribed"] = bool(mine) if ok_sa else None  # None = couldn't check
        out["page_subscribed_fields"] = (mine or {}).get("subscribed_fields", [])
        if ok_sa and not mine:
            out["actions"].append("Subscribe the Facebook Page to the app (POST /{page-id}/subscribed_apps). This changes Meta config, so it needs your approval")
        if not ok_sa:
            out["errors"].append(f"Couldn't read the Page's subscribed apps: {sa.get('message')}")
            if sa.get("code") == 200 or "pages_manage_metadata" in (sa.get("message") or ""):
                out["actions"].append("Add permission pages_manage_metadata (needed to subscribe the Page to webhooks) and generate a new token")
    else:
        out["page_subscribed"] = None

    # ---- which messaging endpoint works with this token
    if t.get("type") == "PAGE":
        out["messaging"] = {"token_type": "PAGE", "node": "me", "ok": True, "note": "Page token: me/messages works (default)."}
    elif t.get("type") == "USER":
        out["messaging"] = {"token_type": "USER", "node": page.get("id") if page else None, "ok": False,
                            "note": "User token: Instagram private replies and DMs need a Page access token. Set META_PAGE_ACCESS_TOKEN "
                                    "(a long-lived Page token for this Page); publishing keeps using the main token."}
        if not os.getenv("META_PAGE_ACCESS_TOKEN"):
            out["actions"].append("Set META_PAGE_ACCESS_TOKEN in Vercel (long-lived Page token): the main token is a User token, which can't send DMs")
        else:
            out["messaging"].update(ok=True, note="META_PAGE_ACCESS_TOKEN is set and is used for messaging.")
    else:
        out["messaging"] = {"token_type": t.get("type"), "node": None, "ok": None, "note": "Unknown token type"}
    out["actions"] = list(dict.fromkeys(out["actions"]))
    return out
