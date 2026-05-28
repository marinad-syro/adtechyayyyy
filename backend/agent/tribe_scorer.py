"""Emotional fit scoring — embedding-based on vercel-demo (no TribeV2)."""

from agent.embedding_fit import get_activations, predict_regions, score_fit

__all__ = ["get_activations", "score_fit", "predict_regions", "is_ready", "configure"]


def configure(model=None, run_prediction_fn=None):
    """No-op for API compatibility with TribeV2 branch."""


def is_ready() -> bool:
    return True
