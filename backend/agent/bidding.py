"""Expected value and bid calculation."""

from agent.catalog import get_product, load_policies


def compute_bid(
    product_id: str,
    p_cvr: float,
    intent_score: float,
    conversion_value: float | None = None,
) -> dict:
    policies = load_policies()
    product = get_product(product_id)
    if not product:
        return {"bid": 0.0, "ev": 0.0, "action": "no_bid", "reason": "unknown product"}

    base_bid = product["base_bid"]
    conv_val = conversion_value if conversion_value is not None else product["conversion_value"]
    cap = base_bid * policies.get("bid_cap_multiplier", 2.5)

    bid = min(cap, base_bid * p_cvr * max(intent_score, 0.1))
    ev = p_cvr * conv_val * intent_score - bid

    cvr_floor = policies.get("cvr_floor", 0.02)
    if p_cvr < cvr_floor:
        return {
            "bid": 0.0,
            "ev": 0.0,
            "action": "no_bid",
            "reason": f"p_cvr {p_cvr:.3f} below floor {cvr_floor}",
        }

    if ev <= 0:
        return {
            "bid": round(bid, 4),
            "ev": round(ev, 4),
            "action": "no_bid",
            "reason": "negative expected value",
        }

    return {
        "bid": round(bid, 4),
        "ev": round(ev, 4),
        "action": "bid",
        "reason": None,
        "conversion_value": conv_val,
    }
