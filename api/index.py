"""Vercel Python entry point: serves the FastAPI app (API + static frontend)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "dashboard"))

from app import app  # noqa: E402,F401
