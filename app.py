"""Vercel ASGI entrypoint — must live at repo root so runtime can `from app import app`."""

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_spec = importlib.util.spec_from_file_location("backend_app", _BACKEND / "app.py")
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
app = _mod.app
