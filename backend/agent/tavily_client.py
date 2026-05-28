"""Market context and website extraction via Tavily."""

import os
import re
from functools import lru_cache
from urllib.parse import urlparse

import httpx

CATEGORY_FALLBACKS = {
    "pain_relief": {
        "snippet": "Category avg: ergonomic supports see 12–18% higher CTR when copy leads with empathy vs urgency.",
        "urgency": 0.55,
    },
    "sleep": {
        "snippet": "Sleep aids trending; competitors offering 30-day trials. Social proof lifts conversion ~15%.",
        "urgency": 0.60,
    },
    "research": {
        "snippet": "Comparison shoppers respond to feature-led copy and third-party ratings.",
        "urgency": 0.50,
    },
    "transactional": {
        "snippet": "Price-sensitive queries: free shipping and return policies improve CVR by ~20%.",
        "urgency": 0.65,
    },
}

BRAND_QUERY = (
    "brand mission products services value proposition target audience "
    "pricing tone of voice about the company sustainability"
)

ABOUT_PATHS = (
    "",
    "/about",
    "/about-us",
    "/about_us",
    "/company",
    "/our-story",
    "/pages/about-us",
)

_NOISE_LINE = re.compile(
    r"^(Image \d+:|Shop (Men|Women)|Previous|Next|Opens in|^\d+\s*$|"
    r"^(Home|Menu|Search|Cart|Sign in|Cookie))",
    re.I,
)


def _api_key() -> str | None:
    return os.environ.get("TAVILY_API_KEY")


def normalize_brand_url(website_url: str) -> str:
    """Strip tracking params and return site root for brand-focused scraping."""
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url
    parsed = urlparse(website_url)
    if not parsed.netloc:
        return website_url
    return f"{parsed.scheme}://{parsed.netloc}/"


def brand_extract_urls(website_url: str, max_urls: int = 5) -> list[str]:
    """Homepage plus common about paths (deduped)."""
    root = normalize_brand_url(website_url).rstrip("/")
    seen: set[str] = set()
    urls: list[str] = []
    for path in ABOUT_PATHS:
        url = root + path if path else root + "/"
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= max_urls:
            break
    return urls


def _content_quality(text: str) -> float:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    noise = sum(1 for ln in lines if _NOISE_LINE.search(ln) or _is_duplicate_nav(ln))
    return max(0.0, 1.0 - noise / len(lines))


def _is_duplicate_nav(line: str) -> bool:
    """Detect headings like 'Shop and Learn Shop and Learn'."""
    text = re.sub(r"^#+\s*", "", line).strip()
    words = text.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2
        return words[:half] == words[half:]
    return False


def extract_urls(
    urls: str | list[str],
    query: str | None = None,
    extract_depth: str = "basic",
) -> dict:
    """
    Extract webpage content via Tavily Extract API.
    See: https://docs.tavily.com/documentation/api-reference/endpoint/extract
    """
    api_key = _api_key()
    if not api_key:
        return {"results": [], "failed_results": [], "source": "no_api_key"}

    if isinstance(urls, str):
        urls = [urls]

    payload: dict = {
        "api_key": api_key,
        "urls": urls,
        "format": "markdown",
        "extract_depth": extract_depth,
    }
    if query:
        payload["query"] = query
        payload["chunks_per_source"] = 5

    try:
        resp = httpx.post("https://api.tavily.com/extract", json=payload, timeout=45.0)
        resp.raise_for_status()
        data = resp.json()
        data["source"] = "tavily_extract"
        return data
    except Exception as exc:
        return {
            "results": [],
            "failed_results": [{"url": urls[0] if urls else "", "error": str(exc)}],
            "source": "error",
        }


def _search_brand_context(domain: str, brand_hint: str = "") -> str:
    """Site-scoped search for mission/products when extract is thin or noisy."""
    hint = brand_hint or domain.replace("www.", "").split(".")[0]
    queries = [
        f"site:{domain} about mission what does {hint} sell products",
        f"{hint} brand story value proposition products",
    ]
    parts: list[str] = []
    for q in queries:
        snippet, _ = _tavily_search_cached(q)
        if snippet and snippet not in parts:
            parts.append(snippet)
        if sum(len(p) for p in parts) > 600:
            break
    return "\n".join(parts)


def extract_brand_website(website_url: str) -> dict:
    """Scrape advertiser site: normalized root + about pages + search enrichment."""
    root = normalize_brand_url(website_url)
    domain = urlparse(root).netloc or website_url
    urls = brand_extract_urls(website_url)

    extract = extract_urls(urls, query=BRAND_QUERY, extract_depth="advanced")

    sections: list[str] = []
    for row in extract.get("results", []):
        raw = (row.get("raw_content") or "").strip()
        if raw:
            sections.append(raw)

    content = "\n\n---\n\n".join(sections)
    quality = _content_quality(content)

    if len(content) < 400 or quality < 0.45:
        search_blob = _search_brand_context(domain)
        if search_blob:
            content = f"## Market / brand search context\n{search_blob}\n\n{content}".strip()

    return {
        "url": root,
        "domain": domain,
        "content": content[:14000],
        "extract_meta": {
            "source": extract.get("source"),
            "failed": extract.get("failed_results", []),
            "chars": len(content),
            "urls_scraped": urls,
            "content_quality": round(quality, 3),
        },
    }


@lru_cache(maxsize=128)
def _tavily_search_cached(query: str) -> tuple[str, float]:
    api_key = _api_key()
    if not api_key:
        return "", 0.0

    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 3,
            },
            timeout=12.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return "", 0.0

        snippets = [r.get("content", "")[:350] for r in results[:3]]
        combined = " ".join(snippets)
        urgency = 0.5
        lower = combined.lower()
        if any(w in lower for w in ["sale", "discount", "limited", "deal", "off"]):
            urgency += 0.15
        if any(w in lower for w in ["review", "rated", "best", "top"]):
            urgency += 0.10
        if any(w in lower for w in ["cheaper", "competitor", "alternative"]):
            urgency -= 0.10
        return combined[:800], max(0.0, min(1.0, urgency))
    except Exception:
        return "", 0.0


def fetch_market_context(product_name: str, category: str, user_text: str = "") -> dict:
    query = f"{product_name} reviews price comparison {user_text[:80]}".strip()
    snippet, urgency = _tavily_search_cached(query)

    if not snippet:
        fb = CATEGORY_FALLBACKS.get(category, CATEGORY_FALLBACKS["research"])
        return {
            "snippet": fb["snippet"],
            "urgency": fb["urgency"],
            "source": "fallback",
        }

    return {
        "snippet": snippet,
        "urgency": round(urgency, 4),
        "source": "tavily",
    }
