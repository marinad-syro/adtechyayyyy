"""Persist advertiser brand profiles and ad plans."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

BRANDS_PATH = Path(__file__).parent.parent / "data" / "brands.json"

_active_brand_id: str | None = None


def _load_all() -> dict:
    if not BRANDS_PATH.exists():
        return {"brands": {}}
    with open(BRANDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_all(data: dict):
    BRANDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BRANDS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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


def get_active_brand() -> dict | None:
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
