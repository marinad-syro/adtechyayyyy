"""Semantic ad ranking via sentence-transformers (from ContextBid / main branch)."""

import os
import threading

USE_EMBEDDINGS = False
EMBED_MODEL = None
_model_loading = False
_model_error: str | None = None
_VERCEL = bool(os.environ.get("VERCEL"))

if not _VERCEL:
    import numpy as np

    _product_embeddings: dict[str, np.ndarray] = {}
    _legacy_embeddings: dict[str, np.ndarray] = {}
else:
    np = None  # type: ignore
    _product_embeddings = {}
    _legacy_embeddings = {}

# Legacy advertisers from main — used when catalog is empty or as extra bidders
LEGACY_ADVERTISERS = [
    {
        "id": "adv_001",
        "name": "LaptopZone Pro",
        "logo": "🖥️",
        "category": "Electronics",
        "target_context": (
            "laptop computer notebook ultrabook portable computing "
            "travel work remote productivity device performance specs"
        ),
        "max_cpm": 45.00,
        "ad_copy": "Premium ultrabooks from $899. Free next-day delivery on 200+ models.",
        "cta": "Compare Laptops →",
    },
    {
        "id": "adv_002",
        "name": "CloudWork Suite",
        "logo": "☁️",
        "category": "Software",
        "target_context": (
            "productivity software work remote collaboration tools apps "
            "subscription saas business team project management"
        ),
        "max_cpm": 38.00,
        "ad_copy": "The all-in-one workspace for remote teams. Video, docs, tasks — unified.",
        "cta": "Start Free Trial →",
    },
    {
        "id": "adv_003",
        "name": "TravelPack Gear",
        "logo": "🎒",
        "category": "Travel",
        "target_context": (
            "travel backpack bag luggage carry-on lightweight portable "
            "gear accessories trip commute flight airport"
        ),
        "max_cpm": 28.00,
        "ad_copy": "TSA-approved laptop bags engineered for carry-on travel. Starting at $79.",
        "cta": "Shop Bags →",
    },
    {
        "id": "adv_004",
        "name": "BudgetBuy Electronics",
        "logo": "💰",
        "category": "Electronics",
        "target_context": (
            "cheap affordable budget price deal discount electronics "
            "refurbished buy save money cost inexpensive value"
        ),
        "max_cpm": 22.00,
        "ad_copy": "Certified refurbished laptops from $349. Same performance, 60% less cost.",
        "cta": "View Deals →",
    },
    {
        "id": "adv_005",
        "name": "SecureVPN Pro",
        "logo": "🔒",
        "category": "Security",
        "target_context": (
            "security privacy internet vpn online safe network "
            "protection wifi public hotspot data breach hacking"
        ),
        "max_cpm": 31.00,
        "ad_copy": "Stay private on any network. 3 months free with your annual plan.",
        "cta": "Get Protected →",
    },
]

CATEGORY_LOGOS = {
    "pain_relief": "🩹",
    "sleep": "😴",
    "research": "🔍",
    "transactional": "🛒",
    "Electronics": "🖥️",
    "Software": "☁️",
    "Travel": "🎒",
    "Security": "🔒",
}


def _load_embed_model():
    global EMBED_MODEL, USE_EMBEDDINGS, _model_loading, _model_error
    if _VERCEL or EMBED_MODEL is not None or _model_error:
        return
    _model_loading = True
    try:
        from sentence_transformers import SentenceTransformer
        EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        USE_EMBEDDINGS = True
        _refresh_embeddings()
    except ImportError as exc:
        _model_error = str(exc)
        USE_EMBEDDINGS = False
    finally:
        _model_loading = False


if not _VERCEL:
    threading.Thread(target=_load_embed_model, daemon=True).start()


def embedding_status() -> dict:
    if _VERCEL:
        return {"ready": False, "loading": False, "error": None, "mode": "keyword"}
    return {
        "ready": USE_EMBEDDINGS,
        "loading": _model_loading,
        "error": _model_error,
    }


def _product_target_context(product: dict) -> str:
    kws = " ".join(product.get("keywords", []))
    creatives = " ".join(c.get("copy", "") for c in product.get("creatives", [])[:2])
    return f"{product['name']} {kws} {creatives}".strip()


def _legacy_bidders() -> list[dict]:
    return [
        dict(a, product_id=a["id"], advertiser_name=a["name"], is_own_brand=False, bidder_type="competitor")
        for a in LEGACY_ADVERTISERS
    ]


def _other_brand_bidders() -> list[dict]:
    """Products from other onboarded brands — compete in the same auction."""
    from agent.brand_store import get_active_brand, list_brands

    active = get_active_brand()
    active_id = active["id"] if active else None
    bidders: list[dict] = []

    for brand in list_brands():
        if brand.get("id") == active_id:
            continue
        brand_name = (
            brand.get("ad_plan", {}).get("brand_profile", {}).get("name")
            or brand.get("website_url", "Competitor")
        )
        products = (
            brand.get("ad_plan", {})
            .get("suggested_catalog", {})
            .get("products", [])[:3]
        )
        for p in products:
            creative = p.get("creatives", [{}])[0]
            bidders.append({
                "id": f"comp-{p['id']}",
                "product_id": p["id"],
                "name": p["name"],
                "advertiser_name": brand_name,
                "logo": CATEGORY_LOGOS.get(p.get("category", ""), "🏷️"),
                "category": p.get("category", "general").replace("_", " ").title(),
                "target_context": _product_target_context(p),
                "max_cpm": round(float(p.get("base_bid", 1.0)) * 22, 2),
                "ad_copy": creative.get("copy", p["name"]),
                "cta": "Learn more →",
                "creative_id": creative.get("id"),
                "brand_safety_tier": "safe",
                "is_own_brand": False,
                "bidder_type": "competitor",
            })
    return bidders


def _catalog_to_bidders() -> list[dict]:
    from agent.catalog import get_products

    bidders = []
    for p in get_products():
        creative = p.get("creatives", [{}])[0]
        bidders.append({
            "id": p["id"],
            "product_id": p["id"],
            "name": p["name"],
            "advertiser_name": p["name"],
            "logo": CATEGORY_LOGOS.get(p.get("category", ""), "📦"),
            "category": p.get("category", "general").replace("_", " ").title(),
            "target_context": _product_target_context(p),
            "max_cpm": round(float(p.get("base_bid", 1.0)) * 25, 2),
            "ad_copy": creative.get("copy", p["name"]),
            "cta": "Learn more →",
            "creative_id": creative.get("id"),
            "brand_safety_tier": "safe",
            "is_own_brand": True,
            "bidder_type": "own",
        })
    return bidders


def get_all_bidders(include_competitors: bool | None = None) -> list[dict]:
    from agent.catalog import load_policies

    policies = load_policies()
    if include_competitors is None:
        include_competitors = policies.get("include_competitor_bids", True)

    catalog = _catalog_to_bidders()
    if not catalog:
        return _legacy_bidders()

    if not include_competitors:
        return catalog

    seen_names: set[str] = {b["advertiser_name"].lower() for b in catalog}
    merged = list(catalog)
    for bidder in _other_brand_bidders() + _legacy_bidders():
        key = bidder["advertiser_name"].lower()
        if key in seen_names:
            continue
        seen_names.add(key)
        merged.append(bidder)
    return merged


def _refresh_embeddings():
    if not USE_EMBEDDINGS or EMBED_MODEL is None:
        return
    _product_embeddings.clear()
    _legacy_embeddings.clear()
    for b in get_all_bidders():
        vec = EMBED_MODEL.encode(b["target_context"])
        _product_embeddings[b["id"]] = vec


def compute_relevance(context: str, bidder: dict) -> float:
    """Return 0.0–1.0 relevance between user context and advertiser target."""
    if USE_EMBEDDINGS and EMBED_MODEL is not None:
        bid = bidder["id"]
        if bid not in _product_embeddings:
            _product_embeddings[bid] = EMBED_MODEL.encode(bidder["target_context"])
        ctx_vec = EMBED_MODEL.encode(context)
        adv_vec = _product_embeddings[bid]
        score = float(
            np.dot(ctx_vec, adv_vec)
            / (np.linalg.norm(ctx_vec) * np.linalg.norm(adv_vec) + 1e-9)
        )
        return max(0.0, min(1.0, score))

    ctx_words = set(context.lower().split())
    tgt_words = set(bidder["target_context"].lower().split())
    overlap = len(ctx_words & tgt_words)
    return min(1.0, overlap / max(len(tgt_words), 1) * 4)


def rank_products_semantic(user_text: str, top_k: int = 5) -> list[dict]:
    """Rank catalog/legacy bidders — same shape as agent.ranker.rank_products."""
    bidders = get_all_bidders()
    scored = []
    for b in bidders:
        rel = compute_relevance(user_text, b)
        scored.append({
            "product_id": b.get("product_id", b["id"]),
            "product_name": b["name"],
            "category": b.get("category", "general"),
            "intent_score": round(rel, 4),
            "rationale": (
                f"keyword relevance: {rel * 100:.1f}%"
                if _VERCEL
                else f"semantic relevance: {rel * 100:.1f}%"
            ),
            "relevance_score": round(rel, 6),
            "max_cpm": b.get("max_cpm"),
        })
    scored.sort(key=lambda x: x["intent_score"], reverse=True)
    return scored[:top_k]
