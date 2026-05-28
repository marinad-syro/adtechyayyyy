"""FastAPI backend: accepts text, runs TribeV2, returns named brain region activations."""

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
from pydantic import BaseModel

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="BrainText API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_model = None
_model_ready = False
_model_loading = True
_model_error: str | None = None


def _patch_skip_stt():
    """Skip WhisperX entirely — estimate word timings from audio duration instead.

    TribeModel needs an audio signal (from gTTS) AND word-level timing to align
    text features to the right time windows. We keep the TTS step but replace the
    STT roundtrip with uniform timing estimation: total_audio_duration / word_count.
    gTTS speech is uniform enough that this is a good approximation.
    """
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

        # ExtractWordsFromAudio checks for existing Word events and skips itself,
        # so the rest of the pipeline (AddSentenceToWords, AddContextToWords, etc.) still runs.
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
        cache = str(Path(__file__).parent / "model_cache")
        if torch.cuda.is_available():
            brain_device = "cuda"
            feature_device = "cuda"
        elif torch.backends.mps.is_available():
            brain_device = "mps"
            feature_device = "cpu"  # neuralset doesn't support mps
        else:
            brain_device = "cpu"
            feature_device = "cpu"
        # The HF config hardcodes device='cuda'; override all feature extractors.
        config_update = {
            "data.text_feature.device": feature_device,
            "data.audio_feature.device": feature_device,
            "data.num_workers": 4,
        }
        _model = TribeModel.from_pretrained(
            "facebook/tribev2", cache_folder=cache, device=brain_device,
            config_update=config_update,
        )
        _model_ready = True
        print("TribeV2 model loaded.", flush=True)
    except Exception as exc:
        _model_error = str(exc)
        print(f"Model load failed: {exc}", file=sys.stderr, flush=True)
    finally:
        _model_loading = False


threading.Thread(target=_load_model, daemon=True).start()


class TextRequest(BaseModel):
    text: str


@app.get("/api/health")
def health():
    return {"ready": _model_ready, "loading": _model_loading, "error": _model_error}


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


def _run_prediction(text_path: str) -> dict:
    from brain_regions import get_region_activations

    events = _model.get_events_dataframe(text_path=text_path)
    preds, _ = _model.predict(events, verbose=False)
    avg_pred = preds.mean(axis=0)
    return get_region_activations(avg_pred)


# Serve the frontend
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
