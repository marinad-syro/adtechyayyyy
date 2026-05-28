# BrainText — Conversion-Optimized Buy-Side Agent

Upload your product catalog and creatives once; the agent bids only when conversation intent **and** predicted emotional fit align — so you stop paying for placements that are topically right but emotionally wrong.

Built for the Cursor × Thrad hackathon **Buy-Side Agents** track.

## What it does

1. **Intent ranking** — maps user LLM prompts to catalog products (keyword + intent cluster).
2. **TribeV2 emotional fit** — scores user context vs ad copy on ACC, insula, OFC, PCC (reward, self-reference, gut-check).
3. **Tavily market context** — competitor/pricing/social-proof signals during bidding (falls back without API key).
4. **Brand onboarding** — [Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract) scrapes advertiser websites to build ad plans, guardrails, and draft catalog.
5. **p(CVR) + EV bidding** — serves only when expected value is positive; no-bids on low fit.
6. **Learning loop** — bandit weights, pause unprofitable creatives, HITL escalation gates.

See [docs/INTERACTION_FLOW.md](docs/INTERACTION_FLOW.md) for flowcharts of the full user interaction.

## Quick start

```bash
./setup.sh
# Optional: backend/.env
# HF_API_KEY=...        # Llama weights for TribeV2
# TAVILY_API_KEY=...    # live market search

./start.sh
# Unified advertiser UI: http://localhost:8000
# Legacy ContextBid: http://localhost:8000/legacy/contextbid
# Legacy BrainText viz: http://localhost:8000/legacy/brain
```

## API

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/placement/preview` | `{ "user_text", "brand_id?", "include_llm?" }` | Unified preview: auction + decide + Grok |
| POST | `/api/agent/advertiser` | `{ "message", "context" }` | Grok advisor (explains dashboard data) |
| POST | `/api/chat` | `{ "message", "conversation_history?" }` | Legacy ContextBid chat + auction |
| POST | `/api/brand/onboard` | `{ "website_url", "advertiser_notes?", "activate?" }` | Scrape site → ad plan |
| GET | `/api/brand` | — | List onboarded brands |
| POST | `/api/brand/{id}/activate` | — | Use brand catalog for bidding |
| POST | `/api/decide` | `{ "user_text", "session_id?", "brand_id?" }` | Full agent decision |
| POST | `/api/score-fit` | `{ "user_text", "ad_copy" }` | TribeV2 fit for user + ad |
| POST | `/api/outcome` | `{ "placement_id", "event" }` | Log impression/click/conversion |
| GET | `/api/dashboard` | — | CVR, spend, bandit, escalations |
| POST | `/api/simulate/batch` | `{ "n_sessions": 50 }` | Optimized vs baseline A/B |
| POST | `/api/predict` | `{ "text" }` | Raw TribeV2 region activations (viz) |
| GET | `/api/catalog` | — | Synthetic advertiser catalog |

### Example: onboard advertiser from website

Requires `TAVILY_API_KEY` in `backend/.env`. Uses [Tavily Extract](https://docs.tavily.com/welcome) to scrape the site.

```bash
curl -s -X POST http://localhost:8000/api/brand/onboard \
  -H 'Content-Type: application/json' \
  -d '{
    "website_url": "https://www.allbirds.com",
    "advertiser_notes": "Focus on sustainable footwear, avoid hard-sell urgency.",
    "activate": true
  }'
```

Returns `brand_id`, `ad_plan` (brand profile, creative guidelines, guardrails, `suggested_catalog`), and activates the catalog when `activate` is true.

### Example: decide

```bash
curl -s -X POST http://localhost:8000/api/decide \
  -H 'Content-Type: application/json' \
  -d '{"user_text": "My lower back kills me after desk work. Need something that actually helps."}'
```

Response includes `action` (`serve` | `no_bid` | `escalate`), `winner`, ranked `candidates` with `p_cvr`, `tribe_fit`, `bid`, `ev`, and `placement_id` when served.

### Example: baseline comparison

```bash
curl -s -X POST http://localhost:8000/api/simulate/batch \
  -H 'Content-Type: application/json' \
  -d '{"n_sessions": 50}'
```

Returns `optimized` vs `baseline` CVR, spend, and lift metrics.

## Architecture

```
User prompt → Intent rank (fast) → Top-K creatives
    → TribeV2 fit + Tavily (top 3 only) → p(CVR) → EV bid
    → Brand safety / HITL gates → Serve or no-bid
    → Outcomes → Bandit + pause losers
```

## Project layout

```
backend/
  app.py                 # FastAPI routes
  brain_regions.py       # TribeV2 → named regions
  agent/
    orchestrator.py      # decide() pipeline
    ranker.py            # intent + keyword ranking (swap when merging external ranker)
    conversion.py        # p(CVR), tribe fit composite
    tribe_scorer.py      # cached TribeV2 calls
    tavily_client.py      # Extract (brand sites) + Search (market context)
    brand_onboarding.py  # ad plan from advertiser website
    brand_store.py       # persisted brand profiles
    bidding.py           # EV / no-bid
    guardrails.py        # brand safety
    outcomes.py          # SQLite bandit + escalations
    simulator.py         # batch A/B demo
  data/
    catalog.json         # synthetic products + creatives
    policies.json        # budget, CVR floor, HITL thresholds
    outcomes.db          # created at runtime
frontend/                # TribeV2 viz (replace when ad-ranking UI merges)
```

## Merging ad-ranking UI

- Replace `backend/agent/ranker.py` with your external ranker; keep return shape `{ product_id, intent_score, rationale }`.
- Point your UI at `/api/decide`, `/api/dashboard`, `/api/outcome`, `/api/escalations`.
- Existing `frontend/index.html` stays as TribeV2 debug panel until you swap it.

## Human-in-the-loop gates

1. **New creative** — first serve requires approval (`require_creative_approval` in policies).
2. **Spend spike** — spend exceeds 20% of daily budget pace.
3. **Brand safety / insula spike** — blocked terms or gut-check fail on user+ad pair.

Resolve escalations via `POST /api/escalations/resolve`.
