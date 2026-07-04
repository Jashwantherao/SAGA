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


def _check_musicgen_reachable() -> None:
    try:
        resp = httpx.get(f"{MUSICGEN_URL}/health", timeout=5)
        resp.raise_for_status()
        if not resp.json().get("model_loaded"):
            raise RuntimeError("MusicGen service is up but the model hasn't finished loading yet.")
    except httpx.HTTPError as e:
        raise RuntimeError(
            f"MusicGen service is not reachable at {MUSICGEN_URL}. Start it first: "
            f"cd D:\\AudioCraft && .venv\\Scripts\\python.exe musicgen_server.py"
        ) from e


def audio_agent(state: GraphState) -> GraphState:
    _check_musicgen_reachable()
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
