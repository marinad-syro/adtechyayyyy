import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import app as app  # noqa: F401 — Vercel ASGI entry (legacy path)
