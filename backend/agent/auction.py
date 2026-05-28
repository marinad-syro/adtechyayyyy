"""Second-price (Vickrey) auction using semantic relevance scores."""

import time
import uuid

from agent.embedding_ranker import compute_relevance, get_all_bidders
from agent.catalog import load_policies

auction_log: list[dict] = []


def run_auction(context: str) -> dict:
    """
    Score bidders, rank by effective CPM, run second-price auction.
    Compatible with ContextBid UI from main branch.
    """
    auction_id = str(uuid.uuid4())[:8].upper()
    start_ns = time.perf_counter_ns()

    bids = []
    for adv in get_all_bidders():
        relevance = compute_relevance(context, adv)
        effective_cpm = round(float(adv.get("max_cpm", 1.0)) * relevance, 6)
        bids.append({
            "advertiser_id": adv["id"],
            "product_id": adv.get("product_id", adv["id"]),
            "advertiser_name": adv.get("advertiser_name", adv["name"]),
            "logo": adv.get("logo", "📦"),
            "category": adv.get("category", "General"),
            "max_cpm": adv.get("max_cpm", 1.0),
            "relevance_score": round(relevance, 6),
            "effective_cpm": effective_cpm,
            "ad_copy": adv.get("ad_copy", ""),
            "cta": adv.get("cta", "Learn more →"),
            "brand_safety_tier": adv.get("brand_safety_tier", "safe"),
            "creative_id": adv.get("creative_id"),
            "is_own_brand": adv.get("is_own_brand", False),
            "bidder_type": adv.get("bidder_type", "competitor" if not adv.get("is_own_brand") else "own"),
        })

    bids.sort(key=lambda x: x["effective_cpm"], reverse=True)

    policies = load_policies()
    relevance_floor = policies.get("relevance_score_floor", 0.18)

    if (
        not bids
        or bids[0]["effective_cpm"] <= 0
        or bids[0]["relevance_score"] < relevance_floor
    ):
        latency_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000, 3)
        best_rel = bids[0]["relevance_score"] if bids else 0.0
        empty_winner = {
            "advertiser_id": "none",
            "advertiser_name": "No bid",
            "logo": "—",
            "category": "—",
            "relevance_score": best_rel,
            "effective_cpm": 0.0,
            "clearing_price_cpm": 0.0,
            "savings_vs_max": 0.0,
            "ad_copy": (
                f"No relevant ad (top relevance {best_rel:.2f} below floor {relevance_floor:.2f})."
                if bids
                else "No relevant ad for this context."
            ),
            "cta": "",
        }
        record = {
            "auction_id": auction_id,
            "timestamp": time.time(),
            "context_snippet": context[:120] + ("…" if len(context) > 120 else ""),
            "winner": empty_winner,
            "all_bids": bids,
            "latency_ms": latency_ms,
            "total_bidders": len(bids),
            "relevance_floor": relevance_floor,
            "no_recommend_reason": (
                f"Top relevance {best_rel:.2f} below floor {relevance_floor:.2f}"
                if bids
                else None
            ),
        }
        auction_log.append(record)
        return record

    winner = bids[0].copy()
    runner_up_cpm = bids[1]["effective_cpm"] if len(bids) > 1 else winner["effective_cpm"]
    clearing_price = round(runner_up_cpm + 0.01, 6)
    winner["clearing_price_cpm"] = clearing_price
    winner["savings_vs_max"] = round(winner["effective_cpm"] - clearing_price, 6)

    latency_ms = round((time.perf_counter_ns() - start_ns) / 1_000_000, 3)

    record = {
        "auction_id": auction_id,
        "timestamp": time.time(),
        "context_snippet": context[:120] + ("…" if len(context) > 120 else ""),
        "winner": winner,
        "all_bids": bids,
        "latency_ms": latency_ms,
        "total_bidders": len(bids),
        "own_brand_count": sum(1 for b in bids if b.get("is_own_brand")),
        "competitor_count": sum(1 for b in bids if not b.get("is_own_brand")),
    }
    auction_log.append(record)
    return record


def run_live_auction(context: str) -> dict:
    """Run a competitor-inclusive auction for demo / simulation."""
    return run_auction(context)


def get_auction_history(limit: int = 50) -> dict:
    return {
        "auctions": list(reversed(auction_log[-limit:])),
        "total": len(auction_log),
    }


def get_auction_stats() -> dict:
    if not auction_log:
        return {
            "total_auctions": 0,
            "avg_latency_ms": 0,
            "total_revenue_cpm": 0.0,
            "top_advertiser": None,
            "win_counts": {},
        }

    total = len(auction_log)
    avg_latency = sum(a["latency_ms"] for a in auction_log) / total
    total_revenue = sum(a["winner"].get("clearing_price_cpm", 0) for a in auction_log)

    win_counts: dict = {}
    for a in auction_log:
        name = a["winner"].get("advertiser_name", "Unknown")
        win_counts[name] = win_counts.get(name, 0) + 1

    top = max(win_counts, key=win_counts.get) if win_counts else None

    return {
        "total_auctions": total,
        "avg_latency_ms": round(avg_latency, 3),
        "total_revenue_cpm": round(total_revenue, 6),
        "top_advertiser": top,
        "win_counts": win_counts,
    }
