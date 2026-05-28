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


def _api_key() -> str | None:
    return os.environ.get("TAVILY_API_KEY")


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
        resp = httpx.post("https://api.tavily.com/extract", json=payload, timeout=30.0)
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


def extract_brand_website(website_url: str) -> dict:
    """Scrape advertiser site for brand onboarding (homepage + about query)."""
    domain = urlparse(website_url).netloc or website_url
    query = (
        "brand mission products services value proposition target audience "
        "pricing tone of voice about the company"
    )

    extract = extract_urls(website_url, query=query, extract_depth="advanced")

    content = ""
    for row in extract.get("results", []):
        content += (row.get("raw_content") or "") + "\n"

    if len(content) < 200:
        search_snippet, _ = _tavily_search_cached(
            f"site:{domain} about products brand what they sell"
        )
        content = (content + "\n" + search_snippet).strip()

    return {
        "url": website_url,
        "domain": domain,
        "content": content[:12000],
        "extract_meta": {
            "source": extract.get("source"),
            "failed": extract.get("failed_results", []),
            "chars": len(content),
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
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return "", 0.0

        snippets = [r.get("content", "")[:200] for r in results[:2]]
        combined = " ".join(snippets)
        urgency = 0.5
        lower = combined.lower()
        if any(w in lower for w in ["sale", "discount", "limited", "deal", "off"]):
            urgency += 0.15
        if any(w in lower for w in ["review", "rated", "best", "top"]):
            urgency += 0.10
        if any(w in lower for w in ["cheaper", "competitor", "alternative"]):
            urgency -= 0.10
        return combined[:300], max(0.0, min(1.0, urgency))
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
