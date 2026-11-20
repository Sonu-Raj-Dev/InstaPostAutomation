"""Shared paths and constants. CMS_DB_PATH / CMS_OUTPUT_DIR env vars override (used by tests)."""

import os
import hashlib
from datetime import timedelta, timezone
from pathlib import Path

CMS_ROOT = Path(__file__).resolve().parent.parent
ON_VERCEL = bool(os.getenv("VERCEL"))
DB_PATH = Path(os.getenv("CMS_DB_PATH") or CMS_ROOT / "data" / "content_store.db")
OUTPUT_DIR = Path(os.getenv("CMS_OUTPUT_DIR") or ("/tmp/output" if ON_VERCEL else CMS_ROOT / "output"))


def internal_key() -> str:
    """Shared by the Python app and the Node render function (api/render.js) — derived, so no extra env var."""
    base = os.getenv("APP_SECRET") or os.getenv("APP_PASSWORD") or "local-dev"
    return hashlib.sha256(f"render:{base}".encode()).hexdigest()
ENV_PATH = CMS_ROOT / ".env"

# India has no DST, so a fixed offset is exact and avoids a tzdata dependency.
IST = timezone(timedelta(hours=5, minutes=30), "IST")

CATEGORIES = [
    "AI Industry News",
    "Trending GitHub",
    "AI Developer Tools",
    "AI Creator Tools",
    "Video & Animation",
    "Open-Source Projects",
    "Tutorials & Workflows",
]

# Legacy category names in existing rows -> new taxonomy
LEGACY_CATEGORY_MAP = {
    "Developer Tools": "AI Developer Tools",
    "Creator & Video Tools": "AI Creator Tools",
    "AI Tools Discovery": "AI Developer Tools",
}
