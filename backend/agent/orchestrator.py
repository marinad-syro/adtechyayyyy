"""Main buy-side decision pipeline."""

import uuid
from typing import Callable

from agent.bidding import compute_bid
from agent.catalog import get_product, load_policies
from agent.conversion import compute_p_cvr, compute_tribe_fit
from agent.guardrails import check_brand_safety, check_insula_spike
from agent.intent import extract_intent
from agent.outcomes import (
    add_escalation,
    check_creative_no_conversions_hitl,
    check_hitl_spend,
    check_spend_spike,
    creative_never_served,
    get_bandit_bonus,
    is_paused,
    log_served,
)
from agent.ranker import rank_products
from agent.tavily_client import fetch_market_context

TribeFn = Callable[[str], dict]


def _build_candidates(ranked: list[dict], max_creatives_per_product: int = 2) -> list[dict]:
    candidates = []
    for rank in ranked:
        product = get_product(rank["product_id"])
        if not product:
            continue
        for creative in product.get("creatives", [])[:max_creatives_per_product]:
            if is_paused(creative["id"]):
                continue
            candidates.append({
                "product_id": product["id"],
                "product_name": product["name"],
                "category": product.get("category", "research"),
                "creative_id": creative["id"],
                "tone": creative.get("tone", "feature"),
                "copy": creative["copy"],
                "intent_score": rank["intent_score"],
                "rank_rationale": rank["rationale"],
            })
    return candidates


def decide(
    user_text: str,
    session_id: str | None = None,
    tribe_fn: TribeFn | None = None,
    use_baseline: bool = False,
    skip_tavily: bool = False,
    skip_hitl: bool = False,
    brand_id: str | None = None,
) -> dict:
    """
    Full agent decision: rank → score finalists → bid → HITL gates.

    use_baseline=True: intent-only p_cvr, no Tribe/Tavily (for A/B demo).
    """
    policies = load_policies()
    session_id = session_id or str(uuid.uuid4())
    intent = extract_intent(user_text)
    trace = []

    ranked = rank_products(user_text, top_k=policies.get("top_k_products", 5))
    trace.append({"step": "rank", "count": len(ranked)})

    candidates = _build_candidates(ranked)
    candidates.sort(key=lambda c: c["intent_score"], reverse=True)

    finalist_count = policies.get("top_k_finalists", 3)
    finalists = candidates[: max(finalist_count, 1)]
    trace.append({"step": "finalists", "count": len(finalists)})

    user_activations = None
    if tribe_fn and not use_baseline and user_text.strip():
        try:
            user_activations = tribe_fn(user_text)
        except Exception as exc:
            trace.append({"step": "tribe_user", "error": str(exc)})

    scored = []
    for cand in finalists:
        entry = {**cand}
        product = get_product(cand["product_id"])

        if tribe_fn and not use_baseline and user_activations:
            try:
                ad_act = tribe_fn(cand["copy"])
                fit = compute_tribe_fit(
                    user_activations, ad_act, intent=intent, ad_tone=cand["tone"]
                )
                entry["tribe_fit"] = fit["conversion_fit"]
                entry["tribe_detail"] = fit
                entry["user_activations"] = user_activations.get("activations", user_activations)
                entry["ad_activations"] = ad_act.get("activations", ad_act)
            except Exception as exc:
                entry["tribe_fit"] = 0.5
                entry["tribe_error"] = str(exc)
        else:
            entry["tribe_fit"] = 0.5

        if not skip_tavily and not use_baseline:
            market = fetch_market_context(
                cand["product_name"], cand["category"], user_text
            )
            entry["tavily_snippet"] = market["snippet"]
            entry["tavily_urgency"] = market["urgency"]
            entry["tavily_source"] = market["source"]
        else:
            entry["tavily_urgency"] = 0.5
            entry["tavily_snippet"] = None

        bandit = get_bandit_bonus(cand["creative_id"], intent["cluster"])
        entry["bandit_bonus"] = bandit

        entry["p_cvr"] = compute_p_cvr(
            intent_score=cand["intent_score"],
            tribe_conversion_fit=entry["tribe_fit"],
            tavily_urgency=entry["tavily_urgency"],
            bandit_bonus=bandit,
            use_baseline=use_baseline,
        )

        safety = check_brand_safety(cand["copy"], user_text, brand_id=brand_id)
        entry["brand_safety"] = safety

        bid_result = compute_bid(cand["product_id"], entry["p_cvr"], cand["intent_score"])
        entry.update(bid_result)

        scored.append(entry)

    scored.sort(key=lambda x: (x.get("ev", 0), x.get("p_cvr", 0)), reverse=True)

    intent_floor = policies.get("intent_score_floor", 0.18)
    best_intent = max((c["intent_score"] for c in scored), default=0.0)
    if not scored or best_intent < intent_floor:
        trace.append({
            "step": "intent_floor",
            "best_intent": best_intent,
            "floor": intent_floor,
        })
        return {
            "session_id": session_id,
            "intent": intent,
            "action": "no_bid",
            "winner": None,
            "candidates": [_public_candidate(c) for c in scored],
            "placement_id": None,
            "escalate_reasons": [],
            "trace": trace,
            "mode": "baseline" if use_baseline else "optimized",
            "brand_id": brand_id,
            "no_recommend_reason": (
                f"Top intent score {best_intent:.2f} below floor {intent_floor:.2f}"
            ),
            "recommendation_threshold": intent_floor,
        }

    winner = None
    action = "no_bid"
    escalate_reasons = []
    hitl_intervention = None

    if not skip_hitl:
        spend_hitl = check_hitl_spend()
        if spend_hitl:
            gate, msg = spend_hitl
            escalate_reasons.append(msg)
            add_escalation(gate, msg, {})
            hitl_intervention = {"required": True, "gate": gate, "message": msg}
            return {
                "session_id": session_id,
                "intent": intent,
                "action": "escalate",
                "winner": None,
                "candidates": [_public_candidate(c) for c in scored],
                "placement_id": None,
                "escalate_reasons": escalate_reasons,
                "hitl_intervention": hitl_intervention,
                "trace": trace,
                "mode": "baseline" if use_baseline else "optimized",
                "brand_id": brand_id,
            }

    for cand in scored:
        if not cand["brand_safety"]["passed"]:
            escalate_reasons.append(f"brand safety: {cand['creative_id']}")
            continue

        if (
            user_activations
            and cand.get("ad_activations")
            and check_insula_spike(
                cand.get("user_activations", {}),
                cand.get("ad_activations", {}),
            )
        ):
            escalate_reasons.append(f"insula spike: {cand['creative_id']}")
            add_escalation(
                "insula_spike",
                f"Gut-check fail for {cand['creative_id']}",
                {"creative_id": cand["creative_id"]},
            )
            continue

        if cand["action"] != "bid":
            continue

        perf_hitl = check_creative_no_conversions_hitl(cand["creative_id"])
        if perf_hitl and not skip_hitl:
            gate, msg = perf_hitl
            escalate_reasons.append(msg)
            add_escalation(
                gate,
                msg,
                {"creative_id": cand["creative_id"], "copy": cand["copy"]},
            )
            winner = cand
            action = "escalate"
            hitl_intervention = {"required": True, "gate": gate, "message": msg}
            break

        if policies.get("require_creative_approval") and creative_never_served(cand["creative_id"]):
            if skip_hitl:
                pass
            else:
                escalate_reasons.append(f"new creative approval: {cand['creative_id']}")
                add_escalation(
                    "new_creative",
                    f"First serve requires approval: {cand['creative_id']}",
                    {"creative_id": cand["creative_id"], "copy": cand["copy"]},
                )
                winner = cand
                action = "escalate"
                hitl_intervention = {
                    "required": True,
                    "gate": "new_creative",
                    "message": f"First serve requires approval: {cand['creative_id']}",
                }
                break

        if check_spend_spike() and not skip_hitl:
            escalate_reasons.append("spend spike")
            add_escalation("spend_spike", "Spend rate exceeds daily pace threshold")
            winner = cand
            action = "escalate"
            hitl_intervention = {
                "required": True,
                "gate": "spend_spike",
                "message": "Spend rate exceeds daily pace threshold",
            }
            break

        winner = cand
        action = "serve"
        break

    placement_id = None
    if winner and action == "serve":
        placement_id = log_served(
            session_id=session_id,
            product_id=winner["product_id"],
            creative_id=winner["creative_id"],
            intent_cluster=intent["cluster"],
            p_cvr=winner["p_cvr"],
            bid=winner["bid"],
            action="serve",
        )
    elif winner and action == "escalate":
        placement_id = log_served(
            session_id=session_id,
            product_id=winner["product_id"],
            creative_id=winner["creative_id"],
            intent_cluster=intent["cluster"],
            p_cvr=winner["p_cvr"],
            bid=0.0,
            action="escalate",
        )

    return {
        "session_id": session_id,
        "intent": intent,
        "action": action,
        "winner": _public_candidate(winner) if winner else None,
        "candidates": [_public_candidate(c) for c in scored],
        "placement_id": placement_id,
        "escalate_reasons": escalate_reasons,
        "hitl_intervention": hitl_intervention,
        "trace": trace,
        "mode": "baseline" if use_baseline else "optimized",
        "brand_id": brand_id,
    }


def _public_candidate(c: dict | None) -> dict | None:
    if not c:
        return None
    return {
        "product_id": c["product_id"],
        "product_name": c["product_name"],
        "creative_id": c["creative_id"],
        "tone": c["tone"],
        "copy": c["copy"],
        "intent_score": c["intent_score"],
        "tribe_fit": c.get("tribe_fit"),
        "tribe_detail": c.get("tribe_detail"),
        "tavily_snippet": c.get("tavily_snippet"),
        "tavily_urgency": c.get("tavily_urgency"),
        "bandit_bonus": c.get("bandit_bonus"),
        "p_cvr": c.get("p_cvr"),
        "bid": c.get("bid"),
        "ev": c.get("ev"),
        "action": c.get("action"),
        "brand_safety": c.get("brand_safety"),
        "user_activations": c.get("user_activations"),
        "ad_activations": c.get("ad_activations"),
    }
