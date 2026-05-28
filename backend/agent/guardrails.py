"""Brand safety and policy checks."""

from agent.catalog import load_policies
from agent.intent import extract_intent


def check_brand_safety(ad_copy: str, user_text: str = "", brand_id: str | None = None) -> dict:
    from agent.brand_store import get_brand_guardrails

    policies = load_policies()
    blocked = list(policies.get("blocked_terms", []))
    brand_rules = get_brand_guardrails(brand_id)
    blocked.extend(brand_rules.get("blocked_terms", []))
    blocked = list(dict.fromkeys(blocked))
    combined = (ad_copy + " " + user_text).lower()

    violations = [term for term in blocked if term.lower() in combined]
    score = 1.0 - (len(violations) * 0.35)
    score = max(0.0, min(1.0, score))

    intent = extract_intent(user_text) if user_text else {}
    tone_mismatch = False
    avoid_tones = brand_rules.get("avoid_tones", [])
    if intent.get("frustrated") and (
        any(w in ad_copy.lower() for w in ["limited time", "act now", "don't wait", "hurry"])
        or "urgency" in avoid_tones
    ):
        tone_mismatch = True
        score *= 0.6

    passed = score >= policies.get("brand_safety_threshold", 0.35) and not violations
    return {
        "passed": passed,
        "score": round(score, 4),
        "violations": violations,
        "tone_mismatch": tone_mismatch,
    }


def check_insula_spike(user_activations: dict, ad_activations: dict) -> bool:
    """True if pair looks like a gut 'this feels wrong' moment."""
    u_ins = user_activations.get("insula", 0.5)
    a_ins = ad_activations.get("insula", 0.5)
    u_acc = user_activations.get("acc", 0.5)
    return u_ins > 0.75 and a_ins > 0.7 and u_acc > 0.65
