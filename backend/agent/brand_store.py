"""Persist advertiser brand profiles and ad plans."""

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

_default = Path(__file__).parent.parent / "data" / "brands.json"
BRANDS_PATH = Path(os.environ.get("BRANDS_PATH", _default))
if os.environ.get("VERCEL"):
    BRANDS_PATH = Path("/tmp/brands.json")
    if not BRANDS_PATH.exists() and _default.exists():
        shutil.copy(_default, BRANDS_PATH)

_active_brand_id: str | None = None


def _load_all() -> dict:
    if not BRANDS_PATH.exists():
        return {"brands": {}, "active_brand_id": None}
    with open(BRANDS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("brands", {})
    data.setdefault("active_brand_id", None)
    return data


def _save_all(data: dict):
    BRANDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BRANDS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _persist_active_brand_id(brand_id: str | None):
    data = _load_all()
    data["active_brand_id"] = brand_id
    _save_all(data)


def save_brand(profile: dict) -> str:
    data = _load_all()
    brand_id = profile.get("id") or str(uuid.uuid4())
    profile["id"] = brand_id
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["brands"][brand_id] = profile
    _save_all(data)
    return brand_id


def get_brand(brand_id: str) -> dict | None:
    return _load_all()["brands"].get(brand_id)


def list_brands() -> list[dict]:
    return list(_load_all()["brands"].values())


def set_active_brand(brand_id: str | None):
    global _active_brand_id
    if brand_id is not None and get_brand(brand_id) is None:
        raise ValueError(f"Unknown brand_id: {brand_id}")
    _active_brand_id = brand_id
    _persist_active_brand_id(brand_id)


def _ensure_active_loaded():
    global _active_brand_id
    if _active_brand_id is None:
        _active_brand_id = _load_all().get("active_brand_id")


def get_active_brand() -> dict | None:
    _ensure_active_loaded()
    if _active_brand_id:
        return get_brand(_active_brand_id)
    return None


def get_brand_guardrails(brand_id: str | None = None) -> dict:
    """Merged guardrails for guardrail checks during decide()."""
    brand = get_brand(brand_id) if brand_id else get_active_brand()
    if not brand:
        return {}
    plan = brand.get("ad_plan", {})
    return {
        "blocked_terms": plan.get("guardrails", {}).get("blocked_terms", []),
        "preferred_tones": plan.get("creative_guidelines", {}).get("preferred_tones", []),
        "avoid_tones": plan.get("creative_guidelines", {}).get("avoid_tones", []),
        "voice": plan.get("brand_profile", {}).get("voice"),
        "brand_name": plan.get("brand_profile", {}).get("name"),
    }
