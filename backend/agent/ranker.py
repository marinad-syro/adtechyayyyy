"""Fast product ranking by intent + keyword overlap, with semantic fallback."""

import re

from agent.catalog import get_products
from agent.intent import extract_intent


def _keyword_rank(user_text: str, top_k: int) -> list[dict]:
    intent = extract_intent(user_text)
    text_lower = user_text.lower()
    words = set(re.findall(r"[a-z0-9']+", text_lower))

    ranked = []
    for product in get_products():
        keywords = product.get("keywords", [])
        kw_hits = sum(1 for kw in keywords if kw in text_lower or any(w in kw for w in words))
        kw_score = min(1.0, kw_hits / max(len(keywords) * 0.4, 1))

        category = product.get("category", "research")
        cluster_score = intent["cluster_scores"].get(category, 0)
        if category == intent["cluster"]:
            cluster_score = max(cluster_score, 0.5)

        intent_score = 0.65 * kw_score + 0.35 * min(1.0, cluster_score * 3)
        if kw_hits == 0:
            intent_score = min(intent_score, 0.1)

        rationale_parts = []
        if kw_hits:
            rationale_parts.append(f"{kw_hits} keyword match(es)")
        if category == intent["cluster"]:
            rationale_parts.append(f"intent cluster: {intent['cluster']}")
        if not rationale_parts:
            rationale_parts.append("weak topical match")

        ranked.append({
            "product_id": product["id"],
            "product_name": product["name"],
            "category": category,
            "intent_score": round(intent_score, 4),
            "rationale": "; ".join(rationale_parts),
        })

    ranked.sort(key=lambda x: x["intent_score"], reverse=True)
    return ranked[:top_k]


def rank_products(user_text: str, top_k: int = 5) -> list[dict]:
    """Prefer semantic embeddings (main branch); fall back to keyword ranker."""
    try:
        from agent.embedding_ranker import rank_products_semantic

        semantic = rank_products_semantic(user_text, top_k)
        if semantic:
            return semantic
    except Exception:
        pass
    return _keyword_rank(user_text, top_k)
