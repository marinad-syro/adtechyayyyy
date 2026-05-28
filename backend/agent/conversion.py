"""p(CVR) model and TribeV2 conversion fit composite."""

import math

from agent.intent import extract_intent

# Hand-tuned weights for hackathon demo
WEIGHTS = {
    "w0": -1.8,
    "w1": 2.2,   # intent_score
    "w2": 1.6,   # tribe_conversion_fit
    "w3": 0.9,   # tavily_urgency
    "w4": 1.1,   # bandit_bonus
}


def sigmoid(x: float) -> float:
    x = max(-20.0, min(20.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def emotion_profile(activations: dict) -> dict:
    """Extract conversion-relevant region scores from TribeV2 output."""
    act = activations.get("activations", activations)
    return {
        "acc": act.get("acc", 0.5),
        "insula": act.get("insula", 0.5),
        "ofc": act.get("ofc", 0.5),
        "pcc": act.get("pcc", 0.5),
    }


def compute_tribe_fit(
    user_activations: dict,
    ad_activations: dict,
    intent: dict | None = None,
    ad_tone: str = "feature",
) -> dict:
    """
    Alignment between user emotional context and ad creative.
    Higher = better predicted conversion resonance.
    """
    user = emotion_profile(user_activations)
    ad = emotion_profile(ad_activations)
    intent = intent or {}

    ofc_align = 1.0 - abs(user["ofc"] - ad["ofc"])
    pcc_align = 1.0 - abs(user["pcc"] - ad["pcc"])
    acc_align = 1.0 - abs(user["acc"] - ad["acc"])

    fit = 0.35 * ofc_align + 0.30 * pcc_align + 0.20 * acc_align

    if intent.get("self_referential"):
        fit += 0.12 * ad["pcc"]
    if intent.get("deciding") or intent.get("cluster") == "transactional":
        fit += 0.10 * ad["ofc"]

    insula_penalty = 0.0
    if intent.get("frustrated") and ad_tone == "urgency":
        insula_penalty = 0.25 * max(ad["insula"], user["insula"])
    elif ad["insula"] > 0.75 and user["insula"] > 0.65:
        insula_penalty = 0.15 * ad["insula"]

    conversion_fit = max(0.0, min(1.0, fit - insula_penalty))

    explanation = []
    if intent.get("self_referential") and ad["pcc"] > 0.55:
        explanation.append("PCC alignment for self-referential user")
    if intent.get("deciding") and ad["ofc"] > 0.55:
        explanation.append("OFC reward signal for decision intent")
    if insula_penalty > 0.1:
        explanation.append("insula penalty: pushy tone vs frustrated user")
    if not explanation:
        explanation.append("general emotional region alignment")

    return {
        "conversion_fit": round(conversion_fit, 4),
        "ofc_align": round(ofc_align, 4),
        "pcc_align": round(pcc_align, 4),
        "insula_penalty": round(insula_penalty, 4),
        "explanation": "; ".join(explanation),
        "user_profile": user,
        "ad_profile": ad,
    }


def compute_p_cvr(
    intent_score: float,
    tribe_conversion_fit: float,
    tavily_urgency: float,
    bandit_bonus: float,
    use_baseline: bool = False,
) -> float:
    if use_baseline:
        return sigmoid(WEIGHTS["w0"] + WEIGHTS["w1"] * intent_score)

    logit = (
        WEIGHTS["w0"]
        + WEIGHTS["w1"] * intent_score
        + WEIGHTS["w2"] * tribe_conversion_fit
        + WEIGHTS["w3"] * tavily_urgency
        + WEIGHTS["w4"] * bandit_bonus
    )
    return round(sigmoid(logit), 4)
