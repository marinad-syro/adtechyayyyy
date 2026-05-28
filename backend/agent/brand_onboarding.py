"""Create advertiser ad plans by scraping brand websites with Tavily."""

import re
import uuid
from urllib.parse import urlparse

from agent.brand_store import save_brand
from agent.tavily_client import extract_brand_website

TONE_KEYWORDS = {
    "empathy": ["care", "support", "help", "comfort", "wellness", "feel", "relief"],
    "urgency": ["limited", "sale", "today", "now", "deal", "offer", "save"],
    "feature": ["technology", "engineered", "designed", "premium", "quality", "patent"],
}


def _guess_brand_name(url: str, content: str) -> str:
    domain = urlparse(url).netloc.replace("www.", "")
    base = domain.split(".")[0].replace("-", " ").title()
    for line in content.splitlines()[:30]:
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()[:80]
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip()[:80]
    return base


def _extract_bullets(content: str, max_items: int = 8) -> list[str]:
    bullets = []
    for line in content.splitlines():
        line = line.strip()
        if re.match(r"^[-*•]\s+\S", line):
            bullets.append(re.sub(r"^[-*•]\s+", "", line)[:200])
        elif re.match(r"^\d+\.\s+\S", line):
            bullets.append(re.sub(r"^\d+\.\s+", "", line)[:200])
    return bullets[:max_items]


def _extract_keywords(content: str, limit: int = 15) -> list[str]:
    words = re.findall(r"[a-zA-Z]{4,}", content.lower())
    stop = {
        "that", "this", "with", "from", "your", "have", "will", "about",
        "their", "they", "what", "when", "where", "which", "while", "more",
        "than", "into", "also", "just", "only", "been", "being", "each",
    }
    freq: dict[str, int] = {}
    for w in words:
        if w not in stop:
            freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq, key=freq.get, reverse=True)
    return ranked[:limit]


def _infer_tones(content: str) -> tuple[list[str], list[str]]:
    lower = content.lower()
    scores = {tone: sum(1 for kw in kws if kw in lower) for tone, kws in TONE_KEYWORDS.items()}
    preferred = sorted(scores, key=scores.get, reverse=True)
    preferred = [t for t in preferred if scores[t] > 0][:2] or ["empathy", "feature"]
    avoid = []
    if "frustrated" not in lower and scores.get("urgency", 0) > scores.get("empathy", 0):
        avoid.append("urgency")
    return preferred, avoid


def _draft_products(content: str, brand_name: str, keywords: list[str]) -> list[dict]:
    """Heuristic product drafts from page content — advertiser can refine in UI."""
    bullets = _extract_bullets(content, 6)
    products = []
    for i, bullet in enumerate(bullets[:4]):
        slug = re.sub(r"[^a-z0-9]+", "-", bullet.lower())[:40].strip("-") or f"product-{i}"
        products.append({
            "id": f"{slug}-{uuid.uuid4().hex[:6]}",
            "name": bullet[:80] if len(bullet) > 10 else f"{brand_name} Offering {i + 1}",
            "category": "research",
            "keywords": keywords[:8],
            "conversion_value": 50.0,
            "base_bid": 1.25,
            "creatives": [
                {
                    "id": f"{slug}-empathy",
                    "tone": "empathy",
                    "copy": f"{bullet} — discover how {brand_name} can help.",
                },
                {
                    "id": f"{slug}-feature",
                    "tone": "feature",
                    "copy": f"{brand_name}: {bullet}",
                },
            ],
        })
    if not products:
        products.append({
            "id": f"{brand_name.lower().replace(' ', '-')}- flagship",
            "name": f"{brand_name} Flagship",
            "category": "research",
            "keywords": keywords[:10],
            "conversion_value": 75.0,
            "base_bid": 1.50,
            "creatives": [
                {
                    "id": "flagship-empathy",
                    "tone": "empathy",
                    "copy": f"See why customers choose {brand_name}.",
                },
            ],
        })
    return products


def create_ad_plan_from_website(
    website_url: str,
    advertiser_notes: str = "",
    daily_budget: float | None = None,
) -> dict:
    """
    Scrape advertiser website via Tavily Extract and build an ad plan
    the agent can use for bidding, guardrails, and creative selection.
    """
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url

    scraped = extract_brand_website(website_url)
    content = scraped["content"]
    if advertiser_notes:
        content += f"\n\nAdvertiser notes:\n{advertiser_notes}"

    brand_name = _guess_brand_name(website_url, content)
    value_props = _extract_bullets(content, 8)
    keywords = _extract_keywords(content)
    preferred_tones, avoid_tones = _infer_tones(content)

    voice = "professional"
    lower = content.lower()
    if any(w in lower for w in ["friendly", "warm", "caring"]):
        voice = "warm"
    elif any(w in lower for w in ["bold", "innovative", "cutting-edge"]):
        voice = "bold"

    blocked_suggestions = []
    for term in ["guaranteed", "miracle", "instant cure", "#1 doctor"]:
        if term in lower:
            blocked_suggestions.append(term)

    ad_plan = {
        "brand_profile": {
            "name": brand_name,
            "website": website_url,
            "domain": scraped["domain"],
            "voice": voice,
            "value_props": value_props,
            "keywords": keywords,
            "summary": (value_props[0] if value_props else content[:300].replace("\n", " ")),
        },
        "creative_guidelines": {
            "preferred_tones": preferred_tones,
            "avoid_tones": avoid_tones,
            "notes": advertiser_notes or None,
        },
        "guardrails": {
            "blocked_terms": blocked_suggestions,
            "blocked_topics": [],
        },
        "suggested_catalog": {
            "products": _draft_products(content, brand_name, keywords),
        },
        "campaign_defaults": {
            "daily_budget": daily_budget or 500.0,
            "cvr_floor": 0.02,
            "bid_strategy": "conversion_optimized",
        },
        "source": {
            "tavily_extract": scraped["extract_meta"],
            "content_preview": content[:500],
        },
    }

    brand_record = {
        "id": str(uuid.uuid4()),
        "website_url": website_url,
        "ad_plan": ad_plan,
    }
    brand_id = save_brand(brand_record)

    return {
        "brand_id": brand_id,
        "ad_plan": ad_plan,
        "message": (
            "Ad plan created from website. Review suggested_catalog and "
            "activate with POST /api/brand/{brand_id}/activate."
        ),
    }
