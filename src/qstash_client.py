"""Upstash QStash over its REST API (no SDK dependency).

* publish(): queue a signed HTTP call back to this app (retried by QStash).
* verify(): check the Upstash-Signature JWT on those callbacks: HS256 with the current or next signing key,
  iss=Upstash, sub=the exact destination URL, exp/nbf, and body = base64url(sha256(raw body)).
Docs: https://upstash.com/docs/qstash/howto/signature , /api-reference/messages/publish-a-message
Env: QSTASH_TOKEN, QSTASH_CURRENT_SIGNING_KEY, QSTASH_NEXT_SIGNING_KEY, optional QSTASH_URL; APP_URL = public base URL.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, Dict, Optional, Tuple

import requests

LEEWAY_S = 30  # clock skew allowed on exp/nbf


def configured() -> bool:
    return bool(os.getenv("QSTASH_TOKEN"))


def can_verify() -> bool:
    return bool(os.getenv("QSTASH_CURRENT_SIGNING_KEY") or os.getenv("QSTASH_NEXT_SIGNING_KEY"))


def destination(path: str) -> str:
    """Public URL QStash calls. Must match exactly what verify() checks as `sub`."""
    host = os.getenv("APP_URL") or os.getenv("VERCEL_PROJECT_PRODUCTION_URL") or os.getenv("VERCEL_URL") or ""
    base = host if host.startswith("http") else f"https://{host}"
    return base.rstrip("/") + path


def publish(path: str, payload: Dict[str, Any], dedup_id: str = "", retries: int = 3, timeout: int = 4) -> Dict[str, Any]:
    """→ {"ok": True, "message_id": ...} | {"ok": False, "error": ...}. Short timeout: called inside the webhook request."""
    token = os.getenv("QSTASH_TOKEN", "")
    if not token:
        return {"ok": False, "error": "QStash is not configured (QSTASH_TOKEN missing)"}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Upstash-Retries": str(retries)}
    if dedup_id:
        headers["Upstash-Deduplication-Id"] = re.sub(r"[^A-Za-z0-9_.-]", "_", dedup_id)[:100]
    api = os.getenv("QSTASH_URL", "https://qstash.upstash.io").rstrip("/")
    try:
        r = requests.request("POST", f"{api}/v2/publish/{destination(path)}", data=json.dumps(payload), headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return {"ok": False, "error": f"QStash unreachable: {type(e).__name__}"}
    if r.status_code == 200:
        try:
            d = r.json()
        except ValueError:
            d = {}
        return {"ok": True, "message_id": d.get("messageId", ""), "deduplicated": bool(d.get("deduplicated"))}
    return {"ok": False, "error": f"QStash HTTP {r.status_code}: {r.text[:200]}"}


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def verify(signature: str, body: bytes, url: str, now: Optional[float] = None) -> Tuple[bool, str]:
    keys = [k for k in (os.getenv("QSTASH_CURRENT_SIGNING_KEY", ""), os.getenv("QSTASH_NEXT_SIGNING_KEY", "")) if k]
    if not keys:
        return False, "QStash signing keys are not configured"
    parts = (signature or "").split(".")
    if len(parts) != 3:
        return False, "missing or malformed Upstash-Signature"
    h, p, sig = parts
    try:
        header, claims = json.loads(_b64url_decode(h)), json.loads(_b64url_decode(p))
    except Exception:
        return False, "undecodable signature"
    if header.get("alg") != "HS256":
        return False, "unexpected signing algorithm"
    signed = f"{h}.{p}".encode()
    if not any(hmac.compare_digest(_b64url(hmac.new(k.encode(), signed, hashlib.sha256).digest()), sig.rstrip("=")) for k in keys):
        return False, "invalid signature"
    now = time.time() if now is None else now
    if claims.get("iss") != "Upstash":
        return False, "wrong issuer"
    if (claims.get("sub") or "").rstrip("/") != url.rstrip("/"):
        return False, "signature is for a different URL"
    if not isinstance(claims.get("exp"), (int, float)) or now > claims["exp"] + LEEWAY_S:
        return False, "signature expired"
    if isinstance(claims.get("nbf"), (int, float)) and now < claims["nbf"] - LEEWAY_S:
        return False, "signature not valid yet"
    if not hmac.compare_digest((claims.get("body") or "").rstrip("="), _b64url(hashlib.sha256(body).digest())):
        return False, "body does not match signature"
    return True, ""


# ---------------------------------------------------------------- schedules (Phase 5)
def _api() -> str:
    return os.getenv("QSTASH_URL", "https://qstash.upstash.io").rstrip("/")


def _auth() -> Dict[str, str]:
    return {"Authorization": f"Bearer {os.getenv('QSTASH_TOKEN', '')}"}


def upsert_schedule(schedule_id: str, path: str, cron: str, retries: int = 3) -> Dict[str, Any]:
    """Create or replace (same Upstash-Schedule-Id) a schedule that POSTs to this app's `path`."""
    headers = {**_auth(), "Content-Type": "application/json", "Upstash-Cron": cron, "Upstash-Schedule-Id": schedule_id,
               "Upstash-Retries": str(retries), "Upstash-Method": "POST"}
    try:
        r = requests.request("POST", f"{_api()}/v2/schedules/{destination(path)}", data="{}", headers=headers, timeout=10)
    except requests.RequestException as e:
        return {"ok": False, "error": f"QStash unreachable: {type(e).__name__}"}
    return {"ok": True} if r.status_code == 200 else {"ok": False, "error": f"QStash HTTP {r.status_code}: {r.text[:200]}"}


def list_schedules() -> Dict[str, Any]:
    try:
        r = requests.request("GET", f"{_api()}/v2/schedules", headers=_auth(), timeout=10)
    except requests.RequestException as e:
        return {"ok": False, "error": f"QStash unreachable: {type(e).__name__}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"QStash HTTP {r.status_code}: {r.text[:200]}"}
    try:
        return {"ok": True, "schedules": r.json() or []}
    except ValueError:
        return {"ok": False, "error": "QStash returned invalid JSON"}


def delete_schedule(schedule_id: str) -> Dict[str, Any]:
    try:
        r = requests.request("DELETE", f"{_api()}/v2/schedules/{schedule_id}", headers=_auth(), timeout=10)
    except requests.RequestException as e:
        return {"ok": False, "error": f"QStash unreachable: {type(e).__name__}"}
    return {"ok": True} if r.status_code in (200, 404) else {"ok": False, "error": f"QStash HTTP {r.status_code}: {r.text[:200]}"}
