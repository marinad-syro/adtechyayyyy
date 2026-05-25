"""
╔═══════════════════════════════════════════════════╗
║   ContextBid  Real-Time Ad Auction Engine        ║
║   Second-price (Vickrey) auction for AI chats     ║
╚═══════════════════════════════════════════════════╝

How it works:
  1. User sends a chat message
  2. We extract semantic intent via embeddings
  3. Each advertiser's target context is scored for relevance
  4. effective_CPM = max_CPM × relevance_score
  5. Second-price auction: winner pays runner-up price + $0.01
  6. Winning ad + Claude's response returned together
"""

import os
import time
import uuid
from typing import List, Optional

# AYA
# import anthropic
from openai import OpenAI


import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─────────────────────────────────────────────────────
# EMBEDDING MODEL (downloads ~90MB on first run)
# ─────────────────────────────────────────────────────
try:
    from sentence_transformers import SentenceTransformer
    print("⏳ Loading embedding model (first run may take 30s to download)...")
    EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    USE_EMBEDDINGS = True
    print("✅ Semantic embedding model loaded.")
except ImportError:
    EMBED_MODEL = None
    USE_EMBEDDINGS = False
    print("⚠️  sentence-transformers not installed. Falling back to keyword matching.")
    print("   Run: pip install sentence-transformers")


# ─────────────────────────────────────────────────────
# ADVERTISER REGISTRY
# In production: a live database + bidding API per advertiser
# ─────────────────────────────────────────────────────
ADVERTISERS = [
    {
        "id": "adv_001",
        "name": "LaptopZone Pro",
        "logo": "🖥️",
        "category": "Electronics",
        "target_context": (
            "laptop computer notebook ultrabook portable computing "
            "travel work remote productivity device performance specs"
        ),
        "max_cpm": 45.00,
        "ad_copy": "Premium ultrabooks from $899. Free next-day delivery on 200+ models.",
        "cta": "Compare Laptops →",
        "brand_safety_tier": "safe",
    },
    {
        "id": "adv_002",
        "name": "CloudWork Suite",
        "logo": "☁️",
        "category": "Software",
        "target_context": (
            "productivity software work remote collaboration tools apps "
            "subscription saas business team project management"
        ),
        "max_cpm": 38.00,
        "ad_copy": "The all-in-one workspace for remote teams. Video, docs, tasks — unified.",
        "cta": "Start Free Trial →",
        "brand_safety_tier": "safe",
    },
    {
        "id": "adv_003",
        "name": "TravelPack Gear",
        "logo": "🎒",
        "category": "Travel",
        "target_context": (
            "travel backpack bag luggage carry-on lightweight portable "
            "gear accessories trip commute flight airport"
        ),
        "max_cpm": 28.00,
        "ad_copy": "TSA-approved laptop bags engineered for carry-on travel. Starting at $79.",
        "cta": "Shop Bags →",
        "brand_safety_tier": "safe",
    },
    {
        "id": "adv_004",
        "name": "BudgetBuy Electronics",
        "logo": "💰",
        "category": "Electronics",
        "target_context": (
            "cheap affordable budget price deal discount electronics "
            "refurbished buy save money cost inexpensive value"
        ),
        "max_cpm": 22.00,
        "ad_copy": "Certified refurbished laptops from $349. Same performance, 60% less cost.",
        "cta": "View Deals →",
        "brand_safety_tier": "safe",
    },
    {
        "id": "adv_005",
        "name": "SecureVPN Pro",
        "logo": "🔒",
        "category": "Security",
        "target_context": (
            "security privacy internet vpn online safe network "
            "protection wifi public hotspot data breach hacking"
        ),
        "max_cpm": 31.00,
        "ad_copy": "Stay private on any network. 3 months free with your annual plan.",
        "cta": "Get Protected →",
        "brand_safety_tier": "safe",
    },
]

# Pre-compute advertiser embeddings at startup
if USE_EMBEDDINGS:
    for adv in ADVERTISERS:
        adv["_embedding"] = EMBED_MODEL.encode(adv["target_context"])
    print(f"✅ Pre-computed embeddings for {len(ADVERTISERS)} advertisers.")


# ─────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────
app = FastAPI(
    title="ContextBid",
    description="Real-time second-price ad auction engine for AI conversations",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory auction log (use Redis/Postgres in production)
auction_log: list = []

# Anthropic client (reads ANTHROPIC_API_KEY from env)
# AYA
# ai_client = anthropic.Anthropic()
ai_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ.get("OPENROUTER_API_KEY"),
)


# ─────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────
def compute_relevance(context: str, advertiser: dict) -> float:
    """Return a 0.0–1.0 relevance score between context and advertiser target."""
    if USE_EMBEDDINGS:
        ctx_vec = EMBED_MODEL.encode(context)
        adv_vec = advertiser["_embedding"]
        # Cosine similarity (can be slightly negative; clamp to 0)
        score = float(
            np.dot(ctx_vec, adv_vec)
            / (np.linalg.norm(ctx_vec) * np.linalg.norm(adv_vec) + 1e-9)
        )
        return max(0.0, score)
    else:
        # Keyword overlap fallback
        ctx_words = set(context.lower().split())
        tgt_words = set(advertiser["target_context"].lower().split())
        overlap = len(ctx_words & tgt_words)
        return min(1.0, overlap / max(len(tgt_words), 1) * 4)


# ─────────────────────────────────────────────────────
# AUCTION ENGINE — Second-Price (Vickrey)
# ─────────────────────────────────────────────────────
def run_auction(context: str) -> dict:
    """
    Run a real-time second-price auction.

    Steps:
      1. Score each advertiser against the conversation context
      2. Compute effective_CPM = max_CPM × relevance
      3. Rank all bids descending
      4. Winner = highest effective_CPM
      5. Clearing price = second-highest effective_CPM + $0.01
    """
    auction_id = str(uuid.uuid4())[:8].upper()
    start_ns = time.perf_counter_ns()

    bids = []
    for adv in ADVERTISERS:
        relevance = compute_relevance(context, adv)
        effective_cpm = round(adv["max_cpm"] * relevance, 6)

        bids.append(
            {
                "advertiser_id": adv["id"],
                "advertiser_name": adv["name"],
                "logo": adv["logo"],
                "category": adv["category"],
                "max_cpm": adv["max_cpm"],
                "relevance_score": round(relevance, 6),
                "effective_cpm": effective_cpm,
                "ad_copy": adv["ad_copy"],
                "cta": adv["cta"],
                "brand_safety_tier": adv["brand_safety_tier"],
            }
        )

    # Rank by effective CPM (highest first)
    bids.sort(key=lambda x: x["effective_cpm"], reverse=True)

    # Second-price rule
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
    }

    auction_log.append(record)
    return record


# ─────────────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    conversation_history: Optional[List[dict]] = []


@app.get("/")
async def root():
    return FileResponse("static/index.html")



@app.post("/api/chat")
async def chat_endpoint(payload: ChatRequest):
    try:
        auction = run_auction(payload.message)

        messages = payload.conversation_history + [
            {"role": "user", "content": payload.message}
        ]

        ai_response = ai_client.chat.completions.create(
            model="openrouter/auto",            
            max_tokens=400,
            messages=[
                {"role": "system", "content": "You are a helpful, concise assistant. Respond in 2-3 sentences. Be natural and direct."}
            ] + messages,
        )
        return {
            "response": ai_response.choices[0].message.content,
            "auction": auction,
        }

    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        raise



# @app.post("/api/chat")
# async def chat_endpoint(payload: ChatRequest):
#     """
#     Single endpoint that:
#       1. Runs an ad auction on the user message
#       2. Gets a Claude response
#       3. Returns both together
#     """
#     # Run auction (fast, ~1-5ms with embeddings)
#     auction = run_auction(payload.message)

#     # Build message history for Claude
#     messages = payload.conversation_history + [
#         {"role": "user", "content": payload.message}
#     ]

#     # Claude response
#     # AYA
#     # ai_response = ai_client.messages.create(
#     #     model="claude-haiku-4-5-20251001",  # Fast + cheap for demo; upgrade to claude-sonnet-4-6 if desired
#     #     max_tokens=400,
#     #     system=(
#     #         "You are a helpful, concise assistant. "
#     #         "Respond in 2–3 sentences. Be natural and direct. "
#     #         "Do not mention ads, sponsored content, or bidding systems."
#     #     ),
#     #     messages=messages,
#     # )

#     # return {
#     #     "response": ai_response.content[0].text,
#     #     "auction": auction,
#     # }
#     ai_response = ai_client.chat.completions.create(
#         model="meta-llama/llama-3.2-3b-instruct:free",
#         max_tokens=400,
#         messages=[
#             {"role": "system", "content": "You are a helpful, concise assistant. Respond in 2-3 sentences. Be natural and direct."}
#         ] + messages,
#     )
#     return {
#         "response": ai_response.choices[0].message.content,
#         "auction": auction,
#     }


@app.get("/api/auctions")
async def get_auctions():
    """Return the last 50 auctions (most recent first)."""
    return {
        "auctions": list(reversed(auction_log[-50:])),
        "total": len(auction_log),
    }


@app.get("/api/stats")
async def get_stats():
    """Aggregate stats across all auctions this session."""
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
    total_revenue = sum(a["winner"]["clearing_price_cpm"] for a in auction_log)

    win_counts: dict = {}
    for a in auction_log:
        name = a["winner"]["advertiser_name"]
        win_counts[name] = win_counts.get(name, 0) + 1

    top = max(win_counts, key=win_counts.get) if win_counts else None

    return {
        "total_auctions": total,
        "avg_latency_ms": round(avg_latency, 3),
        "total_revenue_cpm": round(total_revenue, 6),
        "top_advertiser": top,
        "win_counts": win_counts,
    }


# ─────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    # AYA
    # key = os.environ.get("ANTHROPIC_API_KEY", "")
    # if not key:
    #     print("\n❌  ANTHROPIC_API_KEY environment variable is not set.")
    #     print("    Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
    #     exit(1)

    print("\n╔══════════════════════════════════════╗")
    print("║   ContextBid — Auction Engine        ║")
    print("╠══════════════════════════════════════╣")
    print("║  Dashboard →  http://localhost:8000  ║")
    print("║  API docs  →  http://localhost:8000/docs ║")
    print("╚══════════════════════════════════════╝\n")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")