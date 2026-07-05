"""Asset Maker agent — generates sprites/backgrounds via a local ComfyUI + Flux.1 schnell service.

Derives its asset list directly from the Game Designer's design doc (no
Art Director agent yet): one hero sprite, one collectible/pickup icon, plus
one background per level.
"""

import time
from pathlib import Path

import httpx

from saga.state import GraphState

COMFYUI_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output" / "assets"

STEPS = 4  # Flux schnell's distilled step count

# Icon size for the hero sprite and collectible pickup - small enough to use
# at native resolution in-game with no extra scaling in the Coder's GDScript.
ICON_WIDTH = 128
ICON_HEIGHT = 128

# Backgrounds are generated at exactly the Coder's fixed viewport size
# (see coder.py's PROJECT_GODOT_TEMPLATE) so they can fill the screen
# edge-to-edge with no scaling or letterboxing.
VIEWPORT_WIDTH = 1024
VIEWPORT_HEIGHT = 576


def _build_workflow(prompt: str, filename_prefix: str, seed: int, width: int, height: int) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-schnell-fp8.safetensors", "weight_dtype": "default"}},
        "2": {
            "class_type": "DualCLIPLoader",
            "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn.safetensors", "type": "flux"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": STEPS,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["4", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["3", 0]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": filename_prefix}},
    }


def _check_comfyui_reachable() -> None:
    try:
        httpx.get(f"{COMFYUI_URL}/system_stats", timeout=5).raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(
            f"ComfyUI is not reachable at {COMFYUI_URL}. Start it first: "
            f"cd D:\\ComfyUI\\ComfyUI && ..\\.venv\\Scripts\\python.exe main.py --listen 127.0.0.1 --port 8188"
        ) from e


def _generate_image(
    prompt: str, filename_prefix: str, seed: int, width: int, height: int, timeout: float = 120
) -> Path:
    workflow = _build_workflow(prompt, filename_prefix, seed, width, height)
    resp = httpx.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow}, timeout=30)
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        history = httpx.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).json()
        entry = history.get(prompt_id)
        if entry and entry.get("status", {}).get("completed"):
            image_info = entry["outputs"]["8"]["images"][0]
            image_bytes = httpx.get(
                f"{COMFYUI_URL}/view",
                params={"filename": image_info["filename"], "subfolder": image_info["subfolder"], "type": image_info["type"]},
                timeout=30,
            ).content
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            out_path = OUTPUT_DIR / image_info["filename"]
            out_path.write_bytes(image_bytes)
            return out_path

    raise TimeoutError(f"ComfyUI generation for {filename_prefix!r} did not complete within {timeout}s")


def asset_maker(state: GraphState) -> GraphState:
    _check_comfyui_reachable()
    design_doc = state["design_doc"]
    art_style = design_doc["art_style"]

    requests = [
        (
            f"{design_doc['title']} hero character, {art_style}, game sprite, transparent background",
            "hero_sprite",
            ICON_WIDTH,
            ICON_HEIGHT,
        ),
        (
            f"{design_doc['collectible']}, small pickup icon, centered, {art_style}, transparent background",
            "collectible",
            ICON_WIDTH,
            ICON_HEIGHT,
        ),
    ]
    for i, level in enumerate(design_doc["levels"]):
        requests.append(
            (f"{level['description']}, {art_style}, game background", f"level_{i}_bg", VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
        )

    sprite_paths = []
    for seed, (prompt, name, width, height) in enumerate(requests):
        path = _generate_image(prompt, name, seed=seed, width=width, height=height)
        sprite_paths.append(str(path))
        print(f"[Asset Maker] Generated {name} -> {path}")

    return {"sprite_paths": sprite_paths}
