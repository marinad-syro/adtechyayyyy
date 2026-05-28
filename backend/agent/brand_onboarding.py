"""Create advertiser ad plans by scraping brand websites with Tavily."""

import json
import os
import re
import uuid
from urllib.parse import urlparse

from agent.brand_store import save_brand
from agent.tavily_client import extract_brand_website, normalize_brand_url

TONE_KEYWORDS = {
    "empathy": ["care", "support", "help", "comfort", "wellness", "feel", "relief"],
    "urgency": ["limited", "sale", "today", "now", "deal", "offer", "save"],
    "feature": ["technology", "engineered", "designed", "premium", "quality", "patent"],
}

KEYWORD_STOP = {
    "that", "this", "with", "from", "your", "have", "will", "about",
    "their", "they", "what", "when", "where", "which", "while", "more",
    "than", "into", "also", "just", "only", "been", "being", "each",
    "image", "shop", "store", "footer", "month", "months", "opens", "window",
    "previous", "next", "advertiser", "notes", "learn", "account", "home",
}

_NAV_HEADING = re.compile(
    r"^(shop|account|learn|wallet|store|support|entertainment|business|education|"
    r"health|government|footer|menu|search|cart|sign in)\b",
    re.I,
)
_PRICE = re.compile(r"[$£€]\s?\d|^\d+[\.,]\d{2}\s*$")
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")


def _guess_brand_name(url: str, content: str) -> str:
    domain = urlparse(url).netloc.replace("www.", "")
    base = domain.split(".")[0].replace("-", " ").title()
    for line in content.splitlines()[:40]:
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()[:80]
            if not _NAV_HEADING.match(title) and len(title) > 2:
                return title
        if line.lower().startswith("title:"):
            return line.split(":", 1)[1].strip()[:80]
    return base


def _clean_heading(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+[\$£€]\s*[\d.,]+.*$", "", text).strip()
    words = text.split()
    if len(words) >= 4 and len(words) % 2 == 0 and words[: len(words) // 2] == words[len(words) // 2 :]:
        text = " ".join(words[: len(words) // 2])
    return text[:200]


def _is_usable_heading(text: str) -> bool:
    if len(text) < 12 or len(text) > 180:
        return False
    if _NAV_HEADING.match(text):
        return False
    if re.match(r"^Image \d+:", text, re.I):
        return False
    lower = text.lower()
    if lower in {"shop men", "shop women", "wear all day comfort"}:
        return False
    return True


def _extract_bullets(content: str, max_items: int = 8) -> list[str]:
    bullets = []
    for line in content.splitlines():
        line = line.strip()
        if re.match(r"^[-*•]\s+\S", line):
            bullets.append(re.sub(r"^[-*•]\s+", "", line)[:200])
        elif re.match(r"^\d+\.\s+\S", line):
            bullets.append(re.sub(r"^\d+\.\s+", "", line)[:200])
    return bullets[:max_items]


def _extract_headings(content: str, max_items: int = 10) -> list[str]:
    items = []
    seen: set[str] = set()
    for line in content.splitlines():
        m = _HEADING.match(line.strip())
        if not m:
            continue
        text = _clean_heading(m.group(2))
        key = text.lower()
        if not _is_usable_heading(text) or key in seen:
            continue
        seen.add(key)
        items.append(text)
    return items[:max_items]


def _extract_value_props(content: str) -> list[str]:
    bullets = _extract_bullets(content, 8)
    headings = [h for h in _extract_headings(content, 12) if not _PRICE.search(h)]
    props = []
    seen: set[str] = set()
    for item in bullets + headings:
        if "search context" in item.lower():
            continue
        key = item.lower()[:60]
        if key not in seen and len(item) > 15:
            seen.add(key)
            props.append(item)
    return props[:8]


def _looks_like_product_heading(text: str, following_lines: list[str]) -> bool:
    lower = text.lower()
    if any(skip in lower for skip in ("search context", "shop and learn", "cookie", "footer")):
        return False
    block = " ".join(following_lines[:3]).lower()
    if _PRICE.search(block) or _PRICE.search(text):
        return True
    product_words = (
        "pro", "mini", "max", "edition", "series", "shoe", "shoes", "chair",
        "runner", "sneaker", "earbuds", "headphone", "watch", "phone", "pod",
    )
    return any(w in lower for w in product_words) and len(text) > 18


def _extract_product_candidates(content: str) -> list[str]:
    lines = content.splitlines()
    products = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        m = _HEADING.match(line.strip())
        if not m:
            continue
        text = _clean_heading(m.group(2))
        if not _is_usable_heading(text):
            continue
        following = [ln.strip() for ln in lines[i + 1 : i + 4] if ln.strip()]
        if not _looks_like_product_heading(text, following):
            continue
        key = text.lower()
        if key not in seen:
            seen.add(key)
            products.append(text)
    return products[:6]


def _extract_keywords(content: str, limit: int = 15) -> list[str]:
    words = re.findall(r"[a-zA-Z]{4,}", content.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in KEYWORD_STOP:
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


def _draft_products(
    content: str, brand_name: str, keywords: list[str], product_names: list[str] | None = None
) -> list[dict]:
    """Product drafts from headings or LLM names."""
    names = product_names or _extract_product_candidates(content)
    if not names:
        names = _extract_value_props(content)[:4]

    products = []
    for i, name in enumerate(names[:5]):
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower())[:40].strip("-") or f"product-{i}"
        products.append({
            "id": f"{slug}-{uuid.uuid4().hex[:6]}",
            "name": name[:80],
            "category": "research",
            "keywords": keywords[:8],
            "conversion_value": 50.0,
            "base_bid": 1.25,
            "creatives": [
                {
                    "id": f"{slug}-empathy",
                    "tone": "empathy",
                    "copy": f"{name} — discover how {brand_name} can help.",
                },
                {
                    "id": f"{slug}-feature",
                    "tone": "feature",
                    "copy": f"{brand_name}: {name}",
                },
            ],
        })

    if not products:
        products.append({
            "id": f"{brand_name.lower().replace(' ', '-')}-flagship",
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


def _parse_llm_json(raw: str) -> dict | None:
    text = raw.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _structure_with_llm(content: str, brand_name: str, website_url: str) -> dict | None:
    key = os.environ.get("XAI_API_KEY")
    if not key or len(content.strip()) < 80:
        return None

    from openai import OpenAI

    model = os.environ.get("XAI_MODEL", "grok-3-fast")
    client = OpenAI(base_url="https://api.x.ai/v1", api_key=key)
    prompt = (
        f"Website: {website_url}\n"
        f"Likely brand: {brand_name}\n\n"
        "From the markdown below, extract ONLY facts present in the text. "
        "Return a single JSON object with keys:\n"
        "name (string), summary (1-2 sentences), value_props (string array, 3-6 items), "
        "keywords (string array, 8-12 product/brand terms), voice (warm|bold|professional), "
        "products (array of {name, description} max 5).\n"
        "Ignore nav menus, image labels, duplicate headings, and cookie banners.\n\n"
        f"MARKDOWN:\n{content[:9000]}"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=900,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": "You extract structured brand data. Output valid JSON only, no markdown.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        return _parse_llm_json(resp.choices[0].message.content or "")
    except Exception:
        return None


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

    canonical_url = normalize_brand_url(website_url)
    scraped = extract_brand_website(website_url)
    content = scraped["content"]
    if advertiser_notes:
        content += f"\n\nAdvertiser notes:\n{advertiser_notes}"

    brand_name = _guess_brand_name(canonical_url, content)
    llm = _structure_with_llm(content, brand_name, canonical_url)

    if llm:
        brand_name = (llm.get("name") or brand_name)[:80]
        value_props = llm.get("value_props") or []
        if isinstance(value_props, str):
            value_props = [value_props]
        keywords = llm.get("keywords") or []
        summary = (llm.get("summary") or "")[:500]
        voice = llm.get("voice") if llm.get("voice") in ("warm", "bold", "professional") else "professional"
        llm_products = llm.get("products") or []
        product_names = [
            (p.get("name") or "").strip()
            for p in llm_products
            if isinstance(p, dict) and (p.get("name") or "").strip()
        ]
        structured_by = "llm"
    else:
        value_props = _extract_value_props(content)
        keywords = _extract_keywords(content)
        summary = ""
        voice = "professional"
        product_names = None
        structured_by = "heuristic"

    if not value_props:
        value_props = _extract_value_props(content)
    if not keywords:
        keywords = _extract_keywords(content)

    preferred_tones, avoid_tones = _infer_tones(content)
    lower = content.lower()
    if not llm:
        if any(w in lower for w in ["friendly", "warm", "caring", "sustainable"]):
            voice = "warm"
        elif any(w in lower for w in ["bold", "innovative", "cutting-edge"]):
            voice = "bold"

    if not summary:
        summary = (
            value_props[0]
            if value_props
            else re.sub(r"\s+", " ", content[:400]).strip()
        )[:500]

    blocked_suggestions = []
    for term in ["guaranteed", "miracle", "instant cure", "#1 doctor"]:
        if term in lower:
            blocked_suggestions.append(term)

    ad_plan = {
        "brand_profile": {
            "name": brand_name,
            "website": canonical_url,
            "domain": scraped["domain"],
            "voice": voice,
            "value_props": value_props[:8],
            "keywords": keywords[:15],
            "summary": summary,
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
            "products": _draft_products(content, brand_name, keywords, product_names),
        },
        "campaign_defaults": {
            "daily_budget": daily_budget or 500.0,
            "cvr_floor": 0.02,
            "bid_strategy": "conversion_optimized",
        },
        "source": {
            "tavily_extract": scraped["extract_meta"],
            "content_preview": content[:500],
            "structured_by": structured_by,
        },
    }

    brand_record = {
        "id": str(uuid.uuid4()),
        "website_url": canonical_url,
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
