"""Extract intent cluster and features from user prompt."""

import re

CLUSTERS = {
    "pain_relief": [
        "pain", "hurt", "ache", "sore", "chronic", "can't", "struggling",
        "exhausted", "overwhelmed", "stress", "anxiety", "burnout",
    ],
    "research": [
        "best", "compare", "review", "which", "recommend", "vs", "versus",
        "looking for", "options", "worth it",
    ],
    "transactional": [
        "buy", "purchase", "order", "price", "deal", "discount", "under $",
        "cheap", "sale", "subscribe", "where can i get",
    ],
    "sleep": ["sleep", "insomnia", "tired", "wake", "rest", "night"],
}


def extract_intent(user_text: str) -> dict:
    text = user_text.lower().strip()
    scores = {}
    for cluster, terms in CLUSTERS.items():
        hits = sum(1 for t in terms if t in text)
        scores[cluster] = hits / max(len(terms), 1)

    best = max(scores, key=scores.get) if scores else "research"
    if scores.get(best, 0) == 0:
        best = "research"

    self_ref = bool(re.search(r"\b(i|my|me|i'm|i've)\b", text))
    frustrated = any(w in text for w in ["frustrated", "sick of", "hate", "terrible", "awful", "can't stand"])
    deciding = any(w in text for w in ["should i", "worth", "thinking about", "considering"])

    return {
        "cluster": best,
        "cluster_scores": scores,
        "self_referential": self_ref,
        "frustrated": frustrated,
        "deciding": deciding,
    }
