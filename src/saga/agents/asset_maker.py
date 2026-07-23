"""Asset Maker agent — generates sprites/backgrounds via a local ComfyUI + Flux.1 schnell service.

Derives its asset list directly from the Game Designer's design doc (no
Art Director agent yet): one hero sprite, one key-item icon (its gameplay
role - pickup, hazard, switch, creature, or zone marker - is decided by the
design doc, not here), plus one background per level.
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

# Icons are GENERATED larger than their final size: Flux composes complete,
# well-framed subjects far more reliably at 512 than at 128, and the
# post-process (rembg cut -> alpha crop -> downscale) lands on 128 anyway.
ICON_GEN_SIZE = 512

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


def _strip_background(png_bytes: bytes) -> bytes:
    """Flux cannot emit an alpha channel no matter what the prompt says, so
    every icon arrives with an opaque background square baked in. rembg
    (U2-Net, fully local) cuts the subject out, then the result is cropped
    to its alpha bounding box, padded square, and downscaled to icon size -
    without the crop, a subject occupying a corner of the generation ships
    off-center and part-cropped (the "floating head" defect vision QA kept
    flagging)."""
    import io

    from PIL import Image
    from rembg import remove  # lazy: onnxruntime import is slow

    cut = Image.open(io.BytesIO(remove(png_bytes))).convert("RGBA")
    bbox = cut.split()[3].getbbox()  # bounding box of non-transparent pixels
    if bbox:
        cut = cut.crop(bbox)
    side = int(max(cut.size) * 1.08)  # 8% breathing room
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(cut, ((side - cut.width) // 2, (side - cut.height) // 2))
    canvas = canvas.resize((ICON_WIDTH, ICON_HEIGHT), Image.LANCZOS)
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _generate_image(
    prompt: str,
    filename_prefix: str,
    seed: int,
    width: int,
    height: int,
    strip_bg: bool = False,
    timeout: float = 120,
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
            if strip_bg:
                image_bytes = _strip_background(image_bytes)
            out_path.write_bytes(image_bytes)
            return out_path

    raise TimeoutError(f"ComfyUI generation for {filename_prefix!r} did not complete within {timeout}s")


def asset_maker(state: GraphState) -> GraphState:
    _check_comfyui_reachable()
    design_doc = state["design_doc"]
    art_style = design_doc["art_style"]

    # Icons get the rembg pass (strip_bg); level backgrounds keep every pixel.
    # "plain solid background" in the icon prompts gives rembg a clean subject
    # boundary to cut along - asking Flux for "transparent background" is
    # futile (no alpha channel) and produces busy checkerboard fakes.
    requests = [
        (
            f"{design_doc['hero_description']}, full body, whole character visible from head "
            f"to feet, standing, game sprite, centered, plain solid background",
            "hero_sprite",
            ICON_GEN_SIZE,
            ICON_GEN_SIZE,
            True,
        ),
        (
            f"{design_doc['key_item']['description']}, whole object fully visible, small game "
            f"icon, centered, {art_style}, plain solid background",
            "key_item",
            ICON_GEN_SIZE,
            ICON_GEN_SIZE,
            True,
        ),
    ]
    for i, level in enumerate(design_doc["levels"]):
        requests.append(
            (
                f"{level['description']}, {art_style}, game background, strict top-down "
                f"orthographic view, camera facing straight down at 90 degrees, flat floor "
                f"plan, no perspective, no horizon, no vanishing point, no camera tilt, "
                f"no isometric angle, walls and objects shown from directly above only",
                f"level_{i}_bg",
                VIEWPORT_WIDTH,
                VIEWPORT_HEIGHT,
                False,
            )
        )

    sprite_paths = []
    for seed, (prompt, name, width, height, strip_bg) in enumerate(requests):
        path = _generate_image(prompt, name, seed=seed, width=width, height=height, strip_bg=strip_bg)
        sprite_paths.append(str(path))
        print(f"[Asset Maker] Generated {name} -> {path}")

    # Release ComfyUI's VRAM now that the art batch is done: the Coder's
    # code model loads next, and a full image batch leaves ComfyUI holding
    # most of the card (observed: a 13GB coder model's llama-server dying
    # with a CUDA init failure when loaded on top). The phases are strictly
    # sequential, so the GPU should hand over between them.
    try:
        httpx.post(
            f"{COMFYUI_URL}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=15,
        )
        print("[Asset Maker] Asked ComfyUI to release VRAM for the code phase")
        # /free returns before the driver has actually reclaimed the memory;
        # the Coder's first Ollama load reproducibly crashed immediately
        # after this call across 3/3 observed runs without this settle time
        # (Coder also retries with backoff as a second line of defense).
        time.sleep(8)
    except Exception as e:
        print(f"[Asset Maker] ComfyUI VRAM release skipped ({type(e).__name__}: {e})")

    return {"sprite_paths": sprite_paths}
