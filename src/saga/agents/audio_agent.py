"""Audio Agent — generates BGM via a local MusicGen (transformers) service.

Derives its music prompt directly from the Game Designer's design doc
(no Art Director agent yet).
"""

import shutil
from pathlib import Path

import httpx

from saga.state import GraphState

MUSICGEN_URL = "http://127.0.0.1:8189"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output" / "assets"


def _musicgen_ready() -> str | None:
    """None if BGM can be generated, otherwise why it can't."""
    try:
        resp = httpx.get(f"{MUSICGEN_URL}/health", timeout=5)
        resp.raise_for_status()
        if not resp.json().get("model_loaded"):
            return "the service is up but the model hasn't finished loading"
    except httpx.HTTPError as e:
        return f"not reachable at {MUSICGEN_URL} ({type(e).__name__})"
    return None


def audio_agent(state: GraphState) -> GraphState:
    # Music is the least essential output, the Coder already handles its
    # absence, and the harness's Music autoload simply stays silent - so an
    # unavailable service should cost the build its soundtrack, not the whole
    # game. Every other failure still raises: a service that is up but broken
    # is a real problem worth surfacing.
    unavailable = _musicgen_ready()
    if unavailable:
        print(
            f"[Audio Agent] Skipping BGM - MusicGen {unavailable}. Start it with: "
            f"cd D:\\AudioCraft; .venv\\Scripts\\python.exe musicgen_server.py"
        )
        return {"bgm_path": None}

    design_doc = state["design_doc"]

    prompt = f"{design_doc['audio_mood']} background music for a {design_doc['genre']} game called {design_doc['title']}"

    resp = httpx.post(
        f"{MUSICGEN_URL}/generate",
        json={"prompt": prompt, "duration_seconds": 15.0},
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    src_path = Path(result["path"])
    dest_path = OUTPUT_DIR / src_path.name
    shutil.copy(src_path, dest_path)

    print(f"[Audio Agent] Generated {result['duration_seconds']:.1f}s of BGM in {result['generation_time_seconds']:.1f}s -> {dest_path}")
    return {"bgm_path": str(dest_path)}
