"""FastAPI backend: TribeV2 scoring + conversion-optimized buy-side agent."""

import asyncio
import os
import sys
import tempfile
import threading
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="BrainText Buy-Side Agent API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_model = None
_model_ready = False
_model_loading = True
_model_error: str | None = None


def _patch_skip_stt():
    """Skip WhisperX — estimate word timings from gTTS audio duration."""
    import hashlib
    import re
    import pandas as _pd
    from pathlib import Path as _Path
    from mutagen.mp3 import MP3
    from tribev2.demo_utils import TextToEvents, get_audio_and_text_events

    def _fast_get_events(self):
        from gtts import gTTS
        from langdetect import detect

        text_hash = hashlib.md5(self.text.encode()).hexdigest()
        audio_dir = _Path(self.infra.folder) / "tts_cache" / text_hash
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / "audio.mp3"

        if not audio_path.exists():
            lang = detect(self.text)
            gTTS(self.text, lang=lang).save(str(audio_path))

        total_dur = MP3(str(audio_path)).info.length

        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', self.text.strip()) if s.strip()]
        if not sentences:
            sentences = [self.text.strip()]

        all_words = []
        for seq_id, sentence in enumerate(sentences):
            for w in sentence.split():
                all_words.append((w, sentence, seq_id))

        word_dur = total_dur / max(len(all_words), 1)
        word_rows = [
            {
                "type": "Word",
                "text": w,
                "start": i * word_dur,
                "duration": word_dur,
                "sequence_id": seq_id,
                "sentence": sentence,
                "timeline": "default",
                "subject": "default",
                "language": "english",
            }
            for i, (w, sentence, seq_id) in enumerate(all_words)
        ]

        audio_event = {
            "type": "Audio",
            "filepath": str(audio_path),
            "start": 0,
            "timeline": "default",
            "subject": "default",
        }

        return get_audio_and_text_events(_pd.DataFrame([audio_event] + word_rows))

    TextToEvents.get_events = _fast_get_events


def _load_model():
    global _model, _model_ready, _model_loading, _model_error
    try:
        _patch_skip_stt()
        hf_token = os.environ.get("HF_API_KEY")
        if hf_token:
            from huggingface_hub import login
            login(token=hf_token, add_to_git_credential=False)
        import torch
        from tribev2 import TribeModel
        from agent.tribe_scorer import configure

        cache = str(Path(__file__).parent / "model_cache")
        if torch.cuda.is_available():
            brain_device = "cuda"
            feature_device = "cuda"
        elif torch.backends.mps.is_available():
            brain_device = "mps"
            feature_device = "cpu"
        else:
            brain_device = "cpu"
            feature_device = "cpu"
        config_update = {
            "data.text_feature.device": feature_device,
            "data.audio_feature.device": feature_device,
            "data.num_workers": 4,
        }
        _model = TribeModel.from_pretrained(
            "facebook/tribev2", cache_folder=cache, device=brain_device,
            config_update=config_update,
        )
        configure(_model, _run_prediction)
        _model_ready = True
        print("TribeV2 model loaded.", flush=True)
    except Exception as exc:
        _model_error = str(exc)
        print(f"Model load failed: {exc}", file=sys.stderr, flush=True)
    finally:
        _model_loading = False


threading.Thread(target=_load_model, daemon=True).start()


@app.on_event("startup")
def startup():
    from agent.outcomes import init_db
    init_db()


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


def _run_prediction(text_path: str) -> dict:
    from brain_regions import get_region_activations

    events = _model.get_events_dataframe(text_path=text_path)
    preds, _ = _model.predict(events, verbose=False)
    avg_pred = preds.mean(axis=0)
    return get_region_activations(avg_pred)


def _tribe_fn(text: str) -> dict:
    from agent.tribe_scorer import get_activations
    return get_activations(text)


@app.get("/api/health")
def health():
    from agent.embedding_ranker import embedding_status

    return {
        "ready": _model_ready,
        "loading": _model_loading,
        "error": _model_error,
        "embeddings": embedding_status(),
    }


def _llm_reply(message: str, conversation_history: list[dict]) -> str:
    key = os.environ.get("XAI_API_KEY")
    if not key:
        snippet = message[:80] + ("…" if len(message) > 80 else "")
        return (
            f"Got it — you're asking about \"{snippet}\". "
            "Set XAI_API_KEY for live Grok replies; the ad auction still ran."
        )

    from openai import OpenAI

    model = os.environ.get("XAI_MODEL", "grok-3-fast")
    client = OpenAI(base_url="https://api.x.ai/v1", api_key=key)
    messages = conversation_history + [{"role": "user", "content": message}]
    ai_response = client.chat.completions.create(
        model=model,
        max_tokens=400,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful, concise assistant. "
                    "Respond in 2-3 sentences. Be natural and direct."
                ),
            }
        ]
        + messages,
    )
    return ai_response.choices[0].message.content


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

        tribe_fn = _tribe_fn if _model_ready else None
        decision = await loop.run_in_executor(
            None,
            lambda: decide(message, tribe_fn=tribe_fn, skip_hitl=True),
        )
        result["decision"] = decision

    return result


@app.get("/api/auctions")
def api_auctions():
    from agent.auction import get_auction_history
    return get_auction_history()


@app.get("/api/stats")
def api_stats():
    from agent.auction import get_auction_stats
    return get_auction_stats()


@app.get("/brain")
async def brain_page():
    return FileResponse(FRONTEND_DIR / "brain.html")


@app.post("/api/predict")
async def predict(req: TextRequest):
    if not _model_ready:
        if _model_error:
            raise HTTPException(500, f"Model failed to load: {_model_error}")
        raise HTTPException(503, "Model is still loading — please try again shortly.")

    text = req.text.strip()
    if len(text) < 10:
        raise HTTPException(422, "Please enter at least 10 characters of text.")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        text_path = f.name

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_prediction, text_path)
        return result
    finally:
        try:
            os.unlink(text_path)
        except OSError:
            pass


@app.post("/api/decide")
async def api_decide(req: DecideRequest):
    from agent.orchestrator import decide

    user_text = req.user_text.strip()
    if len(user_text) < 5:
        raise HTTPException(422, "user_text too short")

    tribe_fn = None
    if _model_ready and not req.use_baseline:
        tribe_fn = _tribe_fn

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
    result["tribe_available"] = _model_ready
    return result


@app.post("/api/score-fit")
async def api_score_fit(req: ScoreFitRequest):
    if not _model_ready:
        raise HTTPException(503, "TribeV2 model not ready")

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

    tribe_fn = _tribe_fn if _model_ready else None
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_batch_simulation(
            n_sessions=min(req.n_sessions, 200),
            tribe_fn=tribe_fn,
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
    """Scrape advertiser website via Tavily Extract and generate an ad plan."""
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


# ContextBid UI at / ; TribeV2 brain viz at /brain
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
