"""Where rendered/uploaded images live.

Local (your PC): headless Edge renders to output/, served at /api/media/…, staged on a public host for Meta.
Vercel: the Node function api/render.js renders with serverless Chromium and stores JPGs in Vercel Blob,
which already gives the public HTTPS URLs Meta needs.
"""

import base64
import os
from typing import List, Optional

import requests

from config import ON_VERCEL, OUTPUT_DIR, internal_key
from generator import creative


def _base() -> str:
    host = os.getenv("APP_URL") or os.getenv("VERCEL_PROJECT_PRODUCTION_URL") or os.getenv("VERCEL_URL") or ""
    return host if host.startswith("http") else f"https://{host}"


def _node(payload: dict, timeout: int = 170) -> dict:
    r = requests.post(f"{_base()}/api/render", json=payload, headers={"x-internal-key": internal_key()}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"Renderer error {r.status_code}: {r.text[:300]}")
    return r.json()


def render(doc_html: str, names: List[str], prefix: str) -> List[str]:
    """Render a stacked document of len(names) 1080x1350 pages → list of image URLs (in order)."""
    if ON_VERCEL:
        return _node({"action": "render", "html": doc_html, "names": names, "prefix": prefix})["urls"]
    out = OUTPUT_DIR / prefix
    for n in names:
        (out / n).unlink(missing_ok=True)
    creative.render_to_jpgs(doc_html, len(names), out, names)
    return [f"/api/media/{prefix}/{n}" for n in names]


def put(path: str, data: bytes, content_type: str) -> str:
    if ON_VERCEL:
        return _node({"action": "put", "path": path, "data": base64.b64encode(data).decode(), "contentType": content_type}, 60)["url"]
    p = OUTPUT_DIR / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return f"/api/media/{path}"


def public_url(url: str) -> Optional[str]:
    """Meta downloads images itself, so they must be on public HTTPS."""
    if url.startswith("http"):
        return url
    from utils.media_uploader import upload_to_public_host
    return upload_to_public_host(str(OUTPUT_DIR / url.split("?")[0].removeprefix("/api/media/")))
