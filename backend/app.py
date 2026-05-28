"""FastAPI backend: embedding emotional fit + conversion-optimized buy-side agent (Vercel demo)."""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_env_dir = Path(__file__).parent
load_dotenv(_env_dir / ".env")
load_dotenv(_env_dir.parent / ".env", override=False)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DEMO_MODE = os.environ.get("DEMO_MODE", "embedding")

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _resolve_frontend_dir() -> Path | None:
    """Locate static files. Prefer repo frontend/ in dev; bundled copies for Vercel."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here.parent / "frontend",
        here / "frontend",
        here / "_frontend",
        here.parent / "_frontend",
        here.parent / "backend" / "_frontend",
        here.parent / "public",
        Path.cwd() / "frontend",
        Path.cwd() / "_frontend",
        Path.cwd() / "backend" / "_frontend",
        Path.cwd() / "public",
    ):
        if candidate.is_dir() and (candidate / "app.html").is_file():
            return candidate
    return None


FRONTEND_DIR = _resolve_frontend_dir()

app = FastAPI(title="BrainText Buy-Side Agent API (Vercel demo)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    try:
        from agent.outcomes import init_db

        init_db()
    except Exception as exc:
        print(f"init_db failed: {exc}", flush=True)


class TextRequest(BaseModel):
    text: str


class DecideRequest(BaseModel):
    user_text: str
    session_id: str | None = None
    use_baseline: bool = False
    skip_hitl: bool = False
    brand_id: str | None = None


class BrandOnboardRequest(BaseModel):
    website_url: str
    advertiser_notes: str = ""
    daily_budget: float | None = None
    activate: bool = False


class ScoreFitRequest(BaseModel):
    user_text: str
    ad_copy: str


class OutcomeRequest(BaseModel):
    placement_id: str
    event: str = Field(..., pattern="^(impression|click|conversion|no_click)$")


class EscalationResolveRequest(BaseModel):
    escalation_id: str
    approved: bool


class SimulateRequest(BaseModel):
    n_sessions: int = 50
    seed: int | None = 42


class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []
    include_decision: bool = False


class PlacementPreviewRequest(BaseModel):
    user_text: str
    brand_id: str | None = None
    session_id: str | None = None
    skip_hitl: bool = False
    include_llm: bool = True
    conversation_history: list[dict] = []


class AuctionLiveRequest(BaseModel):
    user_text: str


class AdvertiserAgentRequest(BaseModel):
    message: str
    context: dict = Field(default_factory=dict)


def _tribe_fn(text: str) -> dict:
    from agent.tribe_scorer import get_activations

    return get_activations(text)


@app.get("/api/health")
def health():
    from agent.embedding_ranker import embedding_status

    emb = embedding_status()
    here = Path(__file__).resolve().parent
    return {
        "ready": True,
        "loading": emb.get("loading", False),
        "error": emb.get("error"),
        "mode": "keyword" if os.environ.get("VERCEL") else DEMO_MODE,
        "tribe_available": True,
        "embeddings": emb,
        "frontend": {
            "ready": FRONTEND_DIR is not None,
            "path": str(FRONTEND_DIR) if FRONTEND_DIR else None,
        },
        "deploy": {
            "vercel": bool(os.environ.get("VERCEL")),
            "cwd": str(Path.cwd()),
            "app_file": str(here / "app.py"),
            "has_app_html": any(
                (p / "app.html").is_file()
                for p in (
                    here / "_frontend",
                    here.parent / "_frontend",
                    here.parent / "public",
                    Path.cwd() / "public",
                )
            ),
        },
    }


def _llm_reply(
    message: str,
    conversation_history: list[dict],
    placement: dict | None = None,
) -> str:
    key = os.environ.get("XAI_API_KEY")
    if not key:
        return _llm_reply_fallback(message, placement)

    from openai import OpenAI

    model = os.environ.get("XAI_MODEL", "grok-3-fast")
    client = OpenAI(base_url="https://api.x.ai/v1", api_key=key)

    system = (
        "You are a helpful, concise assistant. Respond in 2-4 sentences. "
        "Be natural, warm, and direct—like a knowledgeable friend, not a marketer."
    )
    user_content = message
    if placement and placement.get("product_name"):
        name = placement["product_name"]
        copy = placement.get("copy") or placement.get("ad_copy") or ""
        system += (
            " The user should receive a useful answer first. When a sponsored product fits, "
            "mention it by name inside your reply as a natural recommendation—not a separate ad block. "
            "Weave one concrete detail from the product copy into your suggestion. "
            "Keep the sponsored mention to one short sentence and briefly note it is sponsored."
        )
        user_content = (
            f"{message}\n\n"
            f"[Sponsored product to integrate naturally if relevant: {name}. "
            f"Product detail: {copy}]"
        )

    messages = conversation_history + [{"role": "user", "content": user_content}]
    ai_response = client.chat.completions.create(
        model=model,
        max_tokens=450,
        messages=[{"role": "system", "content": system}] + messages,
    )
    return ai_response.choices[0].message.content


def _llm_reply_fallback(message: str, placement: dict | None = None) -> str:
    snippet = message[:80] + ("…" if len(message) > 80 else "")
    if placement and placement.get("product_name"):
        name = placement["product_name"]
        copy = placement.get("copy") or placement.get("ad_copy") or ""
        return (
            f"Based on what you shared — \"{snippet}\" — I'd focus on practical relief first. "
            f"If you want a specific option to try, {name} might be worth a look: {copy} "
            f"(Sponsored suggestion.) Set XAI_API_KEY for live Grok replies."
        )
    return (
        f"Got it — you're asking about \"{snippet}\". "
        "Set XAI_API_KEY for live Grok replies; the ad auction still ran."
    )


def _placement_for_llm(decision: dict, auction: dict) -> dict | None:
    """Only pass a product to Grok when the agent actually serves a placement."""
    if decision.get("action") == "serve" and decision.get("winner"):
        return decision["winner"]
    return None


def _advertiser_advisor_reply(message: str, context: dict) -> str:
    key = os.environ.get("XAI_API_KEY")
    import json

    context_blob = json.dumps(context, default=str)[:12000]
    if not key:
        return (
            "Set XAI_API_KEY to enable the advertiser advisor. "
            f"Your question was: \"{message[:100]}\". "
            "Use the Conversion and Brain tabs for decision details."
        )

    from openai import OpenAI

    model = os.environ.get("XAI_MODEL", "grok-3-fast")
    client = OpenAI(base_url="https://api.x.ai/v1", api_key=key)
    ai_response = client.chat.completions.create(
        model=model,
        max_tokens=500,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a buy-side advertising advisor for an AI chat placement platform. "
                    "Explain decisions using ONLY the JSON context provided—never invent metrics. "
                    "Focus on conversion (p_cvr, EV), emotional fit, and when to no-bid. "
                    "When hitl or escalation_queue items are present, tell the advertiser a human "
                    "must approve before spending continues (budget caps, zero-conversion creatives, "
                    "new creatives). Be concise (3-5 sentences)."
                ),
            },
            {
                "role": "user",
                "content": f"Context JSON:\n{context_blob}\n\nAdvertiser question: {message}",
            },
        ],
    )
    return ai_response.choices[0].message.content


@app.post("/api/placement/preview")
async def api_placement_preview(req: PlacementPreviewRequest):
    """Unified preview: auction + conversion decide + optional consumer LLM reply."""
    from agent.auction import run_auction
    from agent.orchestrator import decide
    from agent.outcomes import get_dashboard_stats

    user_text = req.user_text.strip()
    if len(user_text) < 3:
        raise HTTPException(422, "user_text too short")

    loop = asyncio.get_event_loop()

    def _run():
        auction = run_auction(user_text)
        decision = decide(
            user_text,
            session_id=req.session_id,
            tribe_fn=_tribe_fn,
            skip_hitl=req.skip_hitl,
            brand_id=req.brand_id,
        )
        decision["tribe_available"] = True
        decision["fit_mode"] = DEMO_MODE
        llm_response = None
        placement_ctx = _placement_for_llm(decision, auction)
        if req.include_llm:
            try:
                llm_response = _llm_reply(
                    user_text, req.conversation_history, placement_ctx
                )
            except Exception as exc:
                llm_response = f"LLM unavailable ({exc}). Placement decision still computed."
        dashboard_snapshot = get_dashboard_stats()
        return auction, decision, llm_response, dashboard_snapshot

    auction, decision, llm_response, dashboard_snapshot = await loop.run_in_executor(
        None, _run
    )

    return {
        "llm": {"response": llm_response},
        "auction": auction,
        "decision": decision,
        "dashboard_snapshot": dashboard_snapshot,
    }


@app.post("/api/agent/advertiser")
async def api_agent_advertiser(req: AdvertiserAgentRequest):
    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(
            None,
            lambda: _advertiser_advisor_reply(req.message.strip(), req.context),
        )
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"response": response}


@app.post("/api/chat")
async def api_chat(payload: ChatRequest):
    """ContextBid chat: semantic auction + optional LLM reply (+ conversion decide)."""
    from agent.auction import run_auction

    message = payload.message.strip()
    if not message:
        raise HTTPException(422, "message required")

    loop = asyncio.get_event_loop()
    auction = await loop.run_in_executor(None, lambda: run_auction(message))

    try:
        response_text = await loop.run_in_executor(
            None,
            lambda: _llm_reply(message, payload.conversation_history),
        )
    except Exception as exc:
        response_text = f"LLM unavailable ({exc}). Auction results are still shown."

    result = {"response": response_text, "auction": auction}

    if payload.include_decision:
        from agent.orchestrator import decide

        decision = await loop.run_in_executor(
            None,
            lambda: decide(message, tribe_fn=_tribe_fn, skip_hitl=True),
        )
        result["decision"] = decision

    return result


@app.get("/api/auctions")
def api_auctions():
    from agent.auction import get_auction_history

    return get_auction_history()


@app.post("/api/auction/live")
async def api_auction_live(req: AuctionLiveRequest):
    """Run a live second-price auction with your catalog + competitor brands."""
    from agent.auction import run_live_auction

    user_text = req.user_text.strip()
    if len(user_text) < 3:
        raise HTTPException(422, "user_text too short")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: run_live_auction(user_text))


@app.get("/api/stats")
def api_stats():
    from agent.auction import get_auction_stats

    return get_auction_stats()


@app.get("/api/policies")
def api_policies():
    from agent.catalog import load_policies

    return load_policies()


@app.get("/")
async def root_page():
    if not FRONTEND_DIR:
        raise HTTPException(500, "Frontend bundle missing on server")
    return FileResponse(FRONTEND_DIR / "app.html")


@app.get("/legacy/contextbid")
async def legacy_contextbid():
    if not FRONTEND_DIR:
        raise HTTPException(500, "Frontend bundle missing on server")
    return FileResponse(FRONTEND_DIR / "legacy" / "contextbid.html")


@app.get("/legacy/brain")
async def legacy_brain():
    if not FRONTEND_DIR:
        raise HTTPException(500, "Frontend bundle missing on server")
    return FileResponse(FRONTEND_DIR / "legacy" / "brain.html")


@app.get("/brain")
async def brain_page():
    if not FRONTEND_DIR:
        raise HTTPException(500, "Frontend bundle missing on server")
    return FileResponse(FRONTEND_DIR / "legacy" / "brain.html")


@app.post("/api/predict")
async def predict(req: TextRequest):
    from agent.embedding_fit import predict_regions

    text = req.text.strip()
    if len(text) < 10:
        raise HTTPException(422, "Please enter at least 10 characters of text.")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: predict_regions(text))


@app.post("/api/decide")
async def api_decide(req: DecideRequest):
    from agent.orchestrator import decide

    user_text = req.user_text.strip()
    if len(user_text) < 5:
        raise HTTPException(422, "user_text too short")

    tribe_fn = None if req.use_baseline else _tribe_fn

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: decide(
            user_text,
            session_id=req.session_id,
            tribe_fn=tribe_fn,
            use_baseline=req.use_baseline,
            skip_hitl=req.skip_hitl,
            brand_id=req.brand_id,
        ),
    )
    result["tribe_available"] = tribe_fn is not None
    result["fit_mode"] = DEMO_MODE
    return result


@app.post("/api/score-fit")
async def api_score_fit(req: ScoreFitRequest):
    if len(req.user_text.strip()) < 10 or len(req.ad_copy.strip()) < 10:
        raise HTTPException(422, "Both texts need at least 10 characters")

    from agent.tribe_scorer import score_fit

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: score_fit(req.user_text.strip(), req.ad_copy.strip())
    )


@app.post("/api/outcome")
def api_outcome(req: OutcomeRequest):
    from agent.outcomes import record_event

    return record_event(req.placement_id, req.event)


@app.get("/api/dashboard")
def api_dashboard():
    from agent.outcomes import get_dashboard_stats

    return get_dashboard_stats()


@app.post("/api/dashboard/reset")
def api_dashboard_reset():
    """Clear impression/click/conversion counters for a fresh demo."""
    from agent.outcomes import reset_db

    reset_db()
    return {"ok": True}


@app.get("/api/escalations")
def api_escalations():
    from agent.outcomes import get_escalation_queue

    return {"items": get_escalation_queue()}


@app.post("/api/escalations/resolve")
def api_resolve_escalation(req: EscalationResolveRequest):
    from agent.outcomes import resolve_escalation

    ok = resolve_escalation(req.escalation_id, req.approved)
    if not ok:
        raise HTTPException(404, "Escalation not found")
    return {"ok": True}


@app.post("/api/simulate/batch")
async def api_simulate_batch(req: SimulateRequest):
    from agent.simulator import run_batch_simulation

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_batch_simulation(
            n_sessions=min(req.n_sessions, 200),
            tribe_fn=_tribe_fn,
            seed=req.seed,
        ),
    )


@app.get("/api/catalog")
def api_catalog():
    from agent.catalog import load_catalog, get_products
    from agent.brand_store import get_active_brand

    return {
        "products": get_products(),
        "active_brand": get_active_brand(),
        "default_catalog": load_catalog(),
    }


@app.post("/api/brand/onboard")
async def api_brand_onboard(req: BrandOnboardRequest):
    """Scrape advertiser website via Tavily Crawl (+ Extract fallback) and generate an ad plan."""
    from agent.brand_onboarding import create_ad_plan_from_website
    from agent.brand_store import set_active_brand

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: create_ad_plan_from_website(
            req.website_url,
            advertiser_notes=req.advertiser_notes,
            daily_budget=req.daily_budget,
        ),
    )
    if req.activate:
        set_active_brand(result["brand_id"])
        result["activated"] = True
    return result


@app.get("/api/brand")
def api_list_brands():
    from agent.brand_store import get_active_brand, list_brands

    active = get_active_brand()
    return {"brands": list_brands(), "active_brand_id": active["id"] if active else None}


@app.get("/api/brand/{brand_id}")
def api_get_brand(brand_id: str):
    from agent.brand_store import get_brand

    brand = get_brand(brand_id)
    if not brand:
        raise HTTPException(404, "Brand not found")
    return brand


@app.post("/api/brand/{brand_id}/activate")
def api_activate_brand(brand_id: str):
    from agent.brand_store import get_brand, set_active_brand

    if not get_brand(brand_id):
        raise HTTPException(404, "Brand not found")
    set_active_brand(brand_id)
    return {"ok": True, "active_brand_id": brand_id}


@app.post("/api/brand/deactivate")
def api_deactivate_brand():
    from agent.brand_store import set_active_brand

    set_active_brand(None)
    return {"ok": True, "active_brand_id": None}


if FRONTEND_DIR:
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
