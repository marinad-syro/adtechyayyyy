"""Load advertiser catalog and policies."""

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    with open(DATA_DIR / "catalog.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_policies() -> dict:
    with open(DATA_DIR / "policies.json", encoding="utf-8") as f:
        return json.load(f)


"""Load advertiser catalog and policies."""

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    with open(DATA_DIR / "catalog.json", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_policies() -> dict:
    with open(DATA_DIR / "policies.json", encoding="utf-8") as f:
        return json.load(f)


def get_products() -> list[dict]:
    from agent.brand_store import get_active_brand

    brand = get_active_brand()
    if brand:
        custom = brand.get("ad_plan", {}).get("suggested_catalog", {}).get("products")
        if custom:
            return custom
    return load_catalog()["products"]


def get_product(product_id: str) -> dict | None:
    for p in get_products():
        if p["id"] == product_id:
            return p
    return None


def get_creative(product_id: str, creative_id: str) -> dict | None:
    product = get_product(product_id)
    if not product:
        return None
    for c in product.get("creatives", []):
        if c["id"] == creative_id:
            return {**c, "product_id": product_id, "product_name": product["name"]}
    return None
