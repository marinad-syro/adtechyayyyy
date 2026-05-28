"""TribeV2 scoring with LRU cache — shared by API and agent."""

import hashlib
import os
import tempfile
from functools import lru_cache

_model = None
_run_prediction = None


def configure(model, run_prediction_fn):
    global _model, _run_prediction
    _model = model
    _run_prediction = run_prediction_fn


def is_ready() -> bool:
    return _model is not None and _run_prediction is not None


@lru_cache(maxsize=256)
def _cached_predict(text_hash: str, text: str) -> dict:
    if not is_ready():
        raise RuntimeError("TribeV2 model not configured")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        text_path = f.name
    try:
        return _run_prediction(text_path)
    finally:
        try:
            os.unlink(text_path)
        except OSError:
            pass


def get_activations(text: str) -> dict:
    text = text.strip()
    if len(text) < 10:
        raise ValueError("Text must be at least 10 characters for TribeV2")
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    return _cached_predict(text_hash, text)


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
    }
