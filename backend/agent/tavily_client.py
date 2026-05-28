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

CRAWL_INSTRUCTIONS = (
    "Find product pages, product listings, shop and collection pages, and brand "
    "about/mission pages. Include product names, descriptions, features, and "
    "pricing when present."
)

CRAWL_SELECT_PATHS = [
    r"/products?/.*",
    r"/.*/products/.*",
    r"/.*/(men|women|kids|baby)/.*",
    r"/feature/.*",
    r"/special-feature/.*",
    r"/shop/.*",
    r"/collections?/.*",
    r"/catalog/.*",
    r"/store/.*",
    r"/about.*",
    r"/company.*",
    r"/our-story.*",
    r"/pages/.*",
]

CRAWL_EXCLUDE_PATHS = [
    r"/cart.*",
    r"/checkout.*",
    r"/account.*",
    r"/login.*",
    r"/signup.*",
    r"/register.*",
    r"/privacy.*",
    r"/terms.*",
    r"/legal.*",
    r"/blog/.*",
    r"/news/.*",
    r"/careers.*",
    r"/jobs.*",
    r"/support/.*",
    r"/help/.*",
    r"/faq/.*",
]

_PRODUCT_URL_HINT = re.compile(
    r"/products?/|/shop/|/collections?/|/(men|women|kids|baby)/|/feature/|/special-feature/",
    re.I,
)
_LOCALE_STOREFRONT = re.compile(
    r"https?://[^\s)\]\"']+/(?:us|uk|ca|au|jp|eu)/(?:en|[a-z]{2})/?",
    re.I,
)
_CATEGORY_LINK = re.compile(
    r"https?://[^\s)\]\"']+/(?:men|women|kids|baby|feature|special-feature|products|shop)/[^\s)\]\"']*",
    re.I,
)
_ABOUT_URL_HINT = re.compile(r"/about|/company|/our-story", re.I)
_CATEGORY_BUCKET = re.compile(
    r"/(?:feature/sale/)?(men|women|kids|baby|home|accessories)(?:/|$)",
    re.I,
)
_BUCKET_PRIORITY = ("men", "women", "kids", "baby", "products", "home", "accessories", "general")

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


def _crawl_enabled() -> bool:
    if os.environ.get("TAVILY_USE_CRAWL", "true").lower() in ("0", "false", "no"):
        return False
    return bool(_api_key())


def _crawl_settings() -> dict:
    def _int(name: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(hi, int(os.environ.get(name, default))))
        except (TypeError, ValueError):
            return default

    return {
        "max_depth": _int("TAVILY_CRAWL_MAX_DEPTH", 2, 1, 5),
        "max_breadth": _int("TAVILY_CRAWL_MAX_BREADTH", 15, 1, 500),
        "limit": _int("TAVILY_CRAWL_LIMIT", 25, 1, 100),
        "timeout": _int("TAVILY_CRAWL_TIMEOUT", 120, 10, 150),
    }


def _auth_headers() -> dict[str, str]:
    key = _api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _has_locale_path(url: str) -> bool:
    return bool(re.search(r"/(us|uk|ca|au|jp|eu)/(en|[a-z]{2})/?", url, re.I))


def normalize_brand_url(website_url: str) -> str:
    """Strip tracking params and return site root for brand-focused scraping."""
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url
    parsed = urlparse(website_url)
    if not parsed.netloc:
        return website_url
    return f"{parsed.scheme}://{parsed.netloc}/"


def resolve_storefront_url(website_url: str) -> str:
    """
    Pick a crawl/extract entry URL. Global roots (e.g. uniqlo.com/) often need
    a locale path such as /us/en/ before product pages are discoverable.
    """
    root = normalize_brand_url(website_url)
    if _has_locale_path(root):
        return root

    extract = extract_urls(root, extract_depth="basic")
    content = "\n".join(
        (row.get("raw_content") or "") for row in extract.get("results", [])
    )
    if not content.strip():
        return root

    for match in _LOCALE_STOREFRONT.findall(content):
        url = match.rstrip("/") + "/"
        if urlparse(url).netloc == urlparse(root).netloc:
            return url

    rel = re.search(r"/(us|uk|ca|au|jp|eu)/(en|[a-z]{2})/?", content, re.I)
    if rel:
        return root.rstrip("/") + "/" + rel.group(0).lstrip("/")

    return root


def discover_category_urls(website_url: str, max_urls: int = 10) -> list[str]:
    """Pull shop/category links from the storefront homepage markdown."""
    storefront = resolve_storefront_url(website_url)
    root = normalize_brand_url(website_url)
    domain = urlparse(root).netloc

    extract = extract_urls(storefront, extract_depth="basic")
    content = "\n".join(
        (row.get("raw_content") or "") for row in extract.get("results", [])
    )

    seen: set[str] = set()
    urls: list[str] = []

    def _add(url: str) -> None:
        url = url.split("?")[0].split("#")[0]
        if domain not in urlparse(url).netloc:
            return
        key = url.rstrip("/")
        if key in seen or len(urls) >= max_urls:
            return
        seen.add(key)
        urls.append(url)

    _add(storefront.rstrip("/") + "/")

    for url in re.findall(r"\]\((https?://[^)]+)\)", content):
        if re.search(
            r"/(men|women|kids|baby|feature|special-feature|products|shop|linen|t-shirts|tops|bottoms)/",
            url,
            re.I,
        ):
            _add(url)

    if len(urls) <= 1:
        for path in ("/men", "/women", "/kids"):
            if _has_locale_path(storefront):
                _add(f"{storefront.rstrip('/')}{path}")
            else:
                _add(f"{root.rstrip('/')}{path}")

    return urls[:max_urls]


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


def _page_sort_key(row: dict) -> tuple[int, int]:
    url = row.get("url") or ""
    if _PRODUCT_URL_HINT.search(url):
        priority = 0
    elif _ABOUT_URL_HINT.search(url):
        priority = 1
    else:
        priority = 2
    content_len = len((row.get("raw_content") or "").strip())
    return (priority, -content_len)


def url_category_bucket(url: str) -> str:
    """Rough department bucket from URL path (men/women/kids/baby/…)."""
    if _PRODUCT_URL_HINT.search(url):
        path = url.lower()
        for part in ("men", "women", "kids", "baby"):
            if f"/{part}/" in path or path.rstrip("/").endswith(f"/{part}"):
                return part
        return "products"
    match = _CATEGORY_BUCKET.search(url)
    if match:
        return match.group(1).lower()
    return "general"


def crawl_urls(
    url: str,
    *,
    instructions: str | None = None,
    select_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
    max_depth: int | None = None,
    max_breadth: int | None = None,
    limit: int | None = None,
    extract_depth: str = "advanced",
    timeout: int | None = None,
    allow_external: bool = False,
) -> dict:
    """
    Crawl a site via Tavily Crawl API.
    See: https://docs.tavily.com/documentation/api-reference/endpoint/crawl
    """
    api_key = _api_key()
    if not api_key:
        return {"results": [], "failed_results": [], "source": "no_api_key"}

    settings = _crawl_settings()
    payload: dict = {
        "url": url,
        "format": "markdown",
        "extract_depth": extract_depth,
        "max_depth": max_depth if max_depth is not None else settings["max_depth"],
        "max_breadth": max_breadth if max_breadth is not None else settings["max_breadth"],
        "limit": limit if limit is not None else settings["limit"],
        "allow_external": allow_external,
        "timeout": timeout if timeout is not None else settings["timeout"],
    }
    if instructions:
        payload["instructions"] = instructions
        payload["chunks_per_source"] = 5
    if select_paths:
        payload["select_paths"] = select_paths
    if exclude_paths:
        payload["exclude_paths"] = exclude_paths

    headers = _auth_headers()
    if not headers:
        return {"results": [], "failed_results": [], "source": "no_api_key"}

    try:
        resp = httpx.post(
            "https://api.tavily.com/crawl",
            json=payload,
            headers=headers,
            timeout=float(payload["timeout"]) + 15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        data["source"] = "tavily_crawl"
        return data
    except Exception as exc:
        return {
            "results": [],
            "failed_results": [{"url": url, "error": str(exc)}],
            "source": "error",
        }


def _merge_crawl_sections(results: list[dict], max_chars: int = 22000) -> tuple[str, list[str]]:
    """Combine crawled pages; round-robin across departments so one category doesn't dominate."""
    by_bucket: dict[str, list[dict]] = {}
    for row in results:
        raw = (row.get("raw_content") or "").strip()
        if not raw:
            continue
        bucket = url_category_bucket(row.get("url") or "")
        by_bucket.setdefault(bucket, []).append(row)

    for rows in by_bucket.values():
        rows.sort(key=_page_sort_key)

    ordered_buckets = [b for b in _BUCKET_PRIORITY if b in by_bucket]
    ordered_buckets.extend(b for b in by_bucket if b not in ordered_buckets)

    sections: list[str] = []
    urls: list[str] = []
    total = 0
    indices = {b: 0 for b in by_bucket}
    progress = True

    while progress and total < max_chars:
        progress = False
        for bucket in ordered_buckets:
            rows = by_bucket.get(bucket) or []
            idx = indices[bucket]
            if idx >= len(rows):
                continue
            row = rows[idx]
            indices[bucket] = idx + 1
            progress = True

            raw = (row.get("raw_content") or "").strip()
            page_url = (row.get("url") or "").strip()
            header = f"## Page: {page_url}\n\n" if page_url else ""
            block = header + raw
            if total + len(block) > max_chars:
                remaining = max_chars - total
                if remaining < 400:
                    break
                block = block[:remaining] + "\n\n[truncated]"
            sections.append(block)
            if page_url:
                urls.append(page_url)
            total += len(block)
            if total >= max_chars:
                break

    return "\n\n---\n\n".join(sections), urls


def _supplement_crawl_with_categories(
    website_url: str, results: list[dict], *, max_extra: int = 6
) -> list[dict]:
    """Extract men/women/kids (and related) pages missing from a shallow crawl."""
    seeds = discover_category_urls(website_url, max_urls=10)
    seen = {(r.get("url") or "").rstrip("/").lower() for r in results}
    priority: list[str] = []
    other: list[str] = []

    for url in seeds:
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        if re.search(r"/(men|women|kids|baby|tops|bottoms|t-shirts)(/|$)", url, re.I):
            priority.append(url)
        else:
            other.append(url)

    to_fetch = (priority + other)[:max_extra]
    if not to_fetch:
        return results

    extra = extract_urls(
        to_fetch,
        query="products collections prices features new arrivals",
        extract_depth="advanced",
    )
    merged = list(results)
    for row in extra.get("results") or []:
        key = (row.get("url") or "").rstrip("/").lower()
        if key and key not in seen:
            seen.add(key)
            merged.append(row)
    return merged


def crawl_brand_website(website_url: str) -> dict:
    """Crawl advertiser site for product + brand pages (preferred for onboarding)."""
    root = normalize_brand_url(website_url)
    entry = resolve_storefront_url(website_url)
    domain = urlparse(root).netloc or website_url
    settings = _crawl_settings()

    crawl = crawl_urls(
        entry,
        instructions=CRAWL_INSTRUCTIONS,
        select_paths=None,
        exclude_paths=CRAWL_EXCLUDE_PATHS,
        allow_external=False,
    )

    results = crawl.get("results") or []
    results = _supplement_crawl_with_categories(website_url, results)
    content, urls_crawled = _merge_crawl_sections(results)
    quality = _content_quality(content)

    return {
        "url": root,
        "domain": domain,
        "content": content,
        "extract_meta": {
            "source": crawl.get("source"),
            "method": "crawl",
            "storefront_url": entry,
            "failed": crawl.get("failed_results", []),
            "chars": len(content),
            "pages_crawled": len(urls_crawled),
            "urls_crawled": urls_crawled[:40],
            "content_quality": round(quality, 3),
            "crawl_settings": {
                "max_depth": settings["max_depth"],
                "max_breadth": settings["max_breadth"],
                "limit": settings["limit"],
            },
        },
    }


def _extract_brand_website_legacy(website_url: str) -> dict:
    """Category pages via Extract (fallback when crawl is thin or disabled)."""
    root = normalize_brand_url(website_url)
    domain = urlparse(root).netloc or website_url
    urls = discover_category_urls(website_url)

    extract = extract_urls(
        urls,
        query="products collections prices features new arrivals",
        extract_depth="advanced",
    )

    sections: list[str] = []
    scraped_urls: list[str] = []
    for row in extract.get("results", []):
        raw = (row.get("raw_content") or "").strip()
        page_url = (row.get("url") or "").strip()
        if raw:
            header = f"## Page: {page_url}\n\n" if page_url else ""
            sections.append(header + raw)
            if page_url:
                scraped_urls.append(page_url)

    content = "\n\n---\n\n".join(sections)
    quality = _content_quality(content)

    return {
        "url": root,
        "domain": domain,
        "content": content,
        "extract_meta": {
            "source": extract.get("source"),
            "method": "extract",
            "storefront_url": resolve_storefront_url(website_url),
            "failed": extract.get("failed_results", []),
            "chars": len(content),
            "urls_scraped": scraped_urls or urls,
            "content_quality": round(quality, 3),
        },
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
    """
    Scrape advertiser site for onboarding.

    Prefers Tavily Crawl (product/shop/about pages). Falls back to Extract on
    homepage + about paths when crawl is disabled, fails, or returns thin content.
    """
    root = normalize_brand_url(website_url)
    domain = urlparse(root).netloc or website_url

    scraped: dict | None = None
    if _crawl_enabled():
        try:
            scraped = crawl_brand_website(website_url)
        except Exception:
            scraped = None

    meta = (scraped or {}).get("extract_meta") or {}
    content = (scraped or {}).get("content") or ""
    quality = meta.get("content_quality", _content_quality(content))
    pages = meta.get("pages_crawled", 0)

    if not scraped or pages == 0 or len(content) < 400 or quality < 0.35:
        legacy = _extract_brand_website_legacy(website_url)
        legacy_content = legacy["content"]
        legacy_meta = legacy["extract_meta"]

        if content.strip() and legacy_content.strip():
            content = f"{content}\n\n---\n\n{legacy_content}"
            method = "crawl+extract"
        elif legacy_content.strip():
            content = legacy_content
            method = "extract"
        else:
            method = meta.get("method", "crawl")

        quality = _content_quality(content)
        scraped = {
            "url": root,
            "domain": domain,
            "content": content,
            "extract_meta": {
                **legacy_meta,
                "method": method,
                "crawl_pages": pages,
                "crawl_urls": meta.get("urls_crawled", []),
                "crawl_failed": meta.get("failed", []),
                "crawl_settings": meta.get("crawl_settings"),
                "content_quality": round(quality, 3),
                "chars": len(content),
            },
        }
    else:
        scraped["extract_meta"]["method"] = "crawl"

    content = scraped["content"]
    quality = scraped["extract_meta"].get("content_quality", _content_quality(content))

    if len(content) < 400 or quality < 0.45:
        search_blob = _search_brand_context(domain)
        if search_blob:
            content = f"## Market / brand search context\n{search_blob}\n\n{content}".strip()
            scraped["content"] = content
            scraped["extract_meta"]["chars"] = len(content)
            scraped["extract_meta"]["search_enriched"] = True

    scraped["content"] = content[:22000]
    scraped["extract_meta"]["chars"] = len(scraped["content"])
    return scraped


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
