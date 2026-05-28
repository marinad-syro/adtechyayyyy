"""Synthetic prompt generation and A/B simulation vs baseline agent."""

import random

from agent.catalog import get_product
from agent.intent import extract_intent
from agent.orchestrator import decide
from agent.outcomes import init_db, record_event, reset_db, reset_session_state

SYNTHETIC_PROMPTS = {
    "pain_relief": [
        "My lower back has been killing me after long days at my desk. I can't focus anymore.",
        "I'm so overwhelmed with work stress I can barely sleep or think straight.",
        "Chronic neck pain is ruining my mornings — I need something that actually helps.",
    ],
    "sleep": [
        "I can't fall asleep no matter what I try. I'm exhausted every morning.",
        "Been waking up at 3am every night for weeks. Any solutions that work?",
    ],
    "research": [
        "What's the best standing desk under $500? I'm comparing options for my home office.",
        "Looking for mattress topper reviews — side sleeper, need pressure relief.",
        "Best noise cancelling headphones for an open office? Need to focus.",
    ],
    "transactional": [
        "Where can I buy good running shoes under $100 for marathon training?",
        "Looking for a meal kit delivery deal — too tired to cook during the week.",
        "Want to subscribe to plant protein powder, what's a good price?",
    ],
}


def _true_fit(user_text: str, product_id: str, tone: str) -> float:
    """Hidden simulator bias: empathetic ads win for frustrated users, etc."""
    intent = extract_intent(user_text)
    product = get_product(product_id)
    if not product:
        return 0.1

    text_lower = user_text.lower()
    kw_hits = sum(1 for kw in product.get("keywords", []) if kw in text_lower)
    base = min(0.7, 0.15 + kw_hits * 0.12)

    if product.get("category") == intent["cluster"]:
        base += 0.15

    if intent.get("frustrated") and tone == "empathy":
        base += 0.25
    elif intent.get("frustrated") and tone == "urgency":
        base -= 0.20

    if intent.get("self_referential") and tone == "empathy":
        base += 0.10

    if intent.get("cluster") == "transactional" and tone == "urgency":
        base += 0.12

    if intent.get("cluster") == "research" and tone == "feature":
        base += 0.15

    return max(0.02, min(0.85, base))


def simulate_outcome(user_text: str, product_id: str, creative_id: str, p_cvr: float) -> str:
    """Return impression event chain: no_click, click, or conversion."""
    product = get_product(product_id)
    tone = "feature"
    for c in product.get("creatives", []):
        if c["id"] == creative_id:
            tone = c.get("tone", "feature")
            break

    true_p = _true_fit(user_text, product_id, tone)
    blended = 0.4 * p_cvr + 0.6 * true_p
    r = random.random()

    if r < blended * 0.35:
        return "conversion"
    if r < blended:
        return "click"
    return "no_click"


def run_batch_simulation(
    n_sessions: int = 50,
    tribe_fn=None,
    seed: int | None = 42,
) -> dict:
    if seed is not None:
        random.seed(seed)

    init_db()
    reset_db()

    prompts = []
    for cluster, texts in SYNTHETIC_PROMPTS.items():
        for t in texts:
            prompts.append(t)
    while len(prompts) < n_sessions:
        prompts.extend(prompts)
    prompts = prompts[:n_sessions]
    random.shuffle(prompts)

    def _run_mode(use_baseline: bool, label: str) -> dict:
        stats = {"impressions": 0, "clicks": 0, "conversions": 0, "spend": 0.0, "no_bids": 0}

        for user_text in prompts:
            result = decide(
                user_text,
                tribe_fn=tribe_fn,
                use_baseline=use_baseline,
                skip_tavily=use_baseline,
                skip_hitl=True,
            )

            if result["action"] == "no_bid" or not result.get("placement_id"):
                stats["no_bids"] += 1
                continue

            if result["action"] == "escalate":
                stats["no_bids"] += 1
                continue

            winner = result["winner"]
            pid = result["placement_id"]
            stats["spend"] += winner.get("bid", 0)

            outcome = simulate_outcome(
                user_text,
                winner["product_id"],
                winner["creative_id"],
                winner["p_cvr"],
            )

            if outcome == "conversion":
                stats["conversions"] += 1
                stats["clicks"] += 1
                stats["impressions"] += 1
                record_event(pid, "impression")
                record_event(pid, "click")
                record_event(pid, "conversion")
            elif outcome == "click":
                stats["clicks"] += 1
                stats["impressions"] += 1
                record_event(pid, "impression")
                record_event(pid, "click")
            else:
                stats["impressions"] += 1
                record_event(pid, "no_click")

        imp = stats["impressions"]
        stats["cvr"] = round(stats["conversions"] / max(imp, 1), 4)
        stats["ctr"] = round(stats["clicks"] / max(imp, 1), 4)
        stats["conv_per_dollar"] = round(
            stats["conversions"] / max(stats["spend"], 0.01), 4
        )
        stats["label"] = label
        return stats

    optimized = _run_mode(False, "optimized")
    reset_db()
    baseline = _run_mode(True, "baseline")

    cvr_lift = 0.0
    if baseline["cvr"] > 0:
        cvr_lift = round((optimized["cvr"] - baseline["cvr"]) / baseline["cvr"], 4)

    spend_savings = 0.0
    if baseline["spend"] > 0:
        spend_savings = round(1 - optimized["spend"] / baseline["spend"], 4)

    return {
        "sessions": n_sessions,
        "optimized": optimized,
        "baseline": baseline,
        "cvr_lift_pct": cvr_lift,
        "spend_savings_pct": spend_savings,
        "prompts_sample": prompts[:5],
    }
