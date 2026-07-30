"""Persistent local FastAPI service wrapping MusicGen (facebook/musicgen-small).

Loads the model once at startup so callers don't pay the cold-load cost on
every request. The Audio Agent calls /generate over HTTP and never imports
transformers itself, which keeps MusicGen's CUDA torch build independent of
SAGA's own venv.

This runs outside SAGA - see README, "MusicGen FastAPI server", for the venv
setup. Copy it next to that venv and run:
    .venv/Scripts/python.exe musicgen_server.py
"""

import time
from contextlib import asynccontextmanager
from pathlib import Path

import scipy.io.wavfile
import torch
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoProcessor, MusicgenForConditionalGeneration

MODEL_ID = "facebook/musicgen-small"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
TOKENS_PER_SECOND = 50  # MusicGen's audio framerate

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Loading {MODEL_ID}...")
    t0 = time.time()
    _state["processor"] = AutoProcessor.from_pretrained(MODEL_ID)
    _state["model"] = MusicgenForConditionalGeneration.from_pretrained(MODEL_ID).to("cuda")
    print(f"Model loaded in {time.time() - t0:.1f}s")
    yield
    _state.clear()


app = FastAPI(lifespan=lifespan)


class GenerateRequest(BaseModel):
    prompt: str
    duration_seconds: float = 10.0


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": "model" in _state}


@app.post("/generate")
def generate(req: GenerateRequest) -> dict:
    processor = _state["processor"]
    model = _state["model"]

    inputs = processor(text=[req.prompt], padding=True, return_tensors="pt").to("cuda")
    max_new_tokens = int(req.duration_seconds * TOKENS_PER_SECOND)

    t0 = time.time()
    audio_values = model.generate(**inputs, max_new_tokens=max_new_tokens)
    gen_time = time.time() - t0

    sampling_rate = model.config.audio_encoder.sampling_rate
    audio = audio_values[0, 0].cpu().numpy()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"bgm_{int(time.time())}.wav"
    out_path = OUTPUT_DIR / filename
    scipy.io.wavfile.write(str(out_path), rate=sampling_rate, data=audio)

    return {
        "path": str(out_path),
        "duration_seconds": len(audio) / sampling_rate,
        "generation_time_seconds": gen_time,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8189)
