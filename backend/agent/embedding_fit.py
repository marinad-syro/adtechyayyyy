"""Lightweight emotional fit from sentence embeddings (Vercel-friendly, no TribeV2)."""

import hashlib
import math
from functools import lru_cache

import numpy as np

EMOTION_KEYS = ("acc", "insula", "ofc", "pcc")


def _sigmoid(x: float) -> float:
    x = max(-20.0, min(20.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _hash_fallback(text: str) -> dict[str, float]:
    digest = hashlib.sha256(text.encode()).digest()
    return {key: digest[i] / 255.0 for i, key in enumerate(EMOTION_KEYS)}


def _vector_to_regions(vec: np.ndarray) -> dict[str, float]:
    chunks = np.array_split(vec, len(EMOTION_KEYS))
    return {
        key: round(_sigmoid(float(chunk.mean()) * 4.0), 4)
        for key, chunk in zip(EMOTION_KEYS, chunks)
    }


def _encode(text: str) -> np.ndarray | None:
    from agent.embedding_ranker import EMBED_MODEL, USE_EMBEDDINGS, _load_embed_model

    if not USE_EMBEDDINGS and EMBED_MODEL is None:
        _load_embed_model()
    if EMBED_MODEL is None:
        return None
    return EMBED_MODEL.encode(text.strip())


@lru_cache(maxsize=256)
def get_activations(text: str) -> dict:
    text = text.strip()
    if len(text) < 10:
        raise ValueError("Text must be at least 10 characters")

    vec = _encode(text)
    if vec is not None:
        activations = _vector_to_regions(vec)
    else:
        activations = _hash_fallback(text)

    return {"activations": activations, **activations}


def score_fit(user_text: str, ad_copy: str) -> dict:
    from agent.conversion import compute_tribe_fit, emotion_profile
    from agent.intent import extract_intent

    user_act = get_activations(user_text)
    ad_act = get_activations(ad_copy)
    intent = extract_intent(user_text)
    fit = compute_tribe_fit(user_act, ad_act, intent=intent)

    return {
        "activations": {
            "user": user_act.get("activations", user_act),
            "ad": ad_act.get("activations", ad_act),
        },
        "conversion_fit": fit["conversion_fit"],
        "fit_detail": fit,
        "user_profile": emotion_profile(user_act),
        "ad_profile": emotion_profile(ad_act),
        "mode": "embedding",
    }


def predict_regions(text: str) -> dict:
    """Shape compatible with legacy /api/predict and brain viz."""
    act = get_activations(text)
    regions = act["activations"]
    top = sorted(regions.items(), key=lambda x: x[1], reverse=True)
    labels = {
        "acc": ("Anterior Cingulate", "Conflict monitoring, decision salience"),
        "insula": ("Insula", "Gut-check, urgency, emotional arousal"),
        "ofc": ("Orbitofrontal Cortex", "Reward valuation, purchase intent"),
        "pcc": ("Posterior Cingulate", "Self-reference, brand identity fit"),
    }
    return {
        "activations": regions,
        "top_regions": [
            {
                "id": rid,
                "name": labels[rid][0],
                "description": labels[rid][1],
                "activation": score,
            }
            for rid, score in top
        ],
        "mode": "embedding",
    }
