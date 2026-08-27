"""Asset Maker agent — generates sprites/backgrounds via a local ComfyUI + Flux.1 schnell service.

Consumes the Art Director's locked visual bible and role contracts: one hero
sprite, one key-item icon (its gameplay
role - pickup, hazard, switch, creature, or zone marker - is decided by the
design doc, not here), plus one background per level.
"""

import shutil
import time
from pathlib import Path

import httpx

from saga.config import settings
from saga.agents.art_director import (
    art_contract_by_name,
    asset_prompt_suffix,
    compile_art_direction,
)
from saga.state import GraphState
from saga.workspace import assets_dir

COMFYUI_URL = settings.comfyui_url

STEPS = 4  # Flux schnell's distilled step count

# Icon size for the hero sprite and collectible pickup - small enough to use
# at native resolution in-game with no extra scaling in the Coder's GDScript.
ICON_WIDTH = 128
ICON_HEIGHT = 128

# Shared by every hero pose so they render as the same character. Any fixed
# value works; what matters is that the poses do not each get their own.
HERO_SEED = 424242

# With the fixed hero seed, Flux consistently composes side-view characters
# facing screen-left. Make that an explicit generation contract and let the
# Anim autoload mirror the texture for rightward movement. Leaving the native
# direction implicit made every otherwise-correct controller look reversed.
HERO_NATIVE_FACING = "screen-left, head and body pointing toward the left edge"

# Icons are GENERATED larger than their final size: Flux composes complete,
# well-framed subjects far more reliably at 512 than at 128, and the
# post-process (rembg cut -> alpha crop -> downscale) lands on 128 anyway.
ICON_GEN_SIZE = 512

# Backgrounds are generated at exactly the Coder's fixed viewport size
# (see coder.py's PROJECT_GODOT_TEMPLATE) so they can fill the screen
# edge-to-edge with no scaling or letterboxing.
VIEWPORT_WIDTH = 1024
VIEWPORT_HEIGHT = 576


def _inspect_asset(
    path: Path,
    logical_name: str,
    expected_width: int,
    expected_height: int,
    transparent_actor: bool,
) -> dict:
    """Run cheap structural checks before an asset can reach the runtime."""
    errors: list[str] = []
    observed: dict = {}
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.load()
            observed["size"] = [image.width, image.height]
            observed["mode"] = image.mode
            if image.size != (expected_width, expected_height):
                errors.append(
                    f"expected {expected_width}x{expected_height}, got {image.width}x{image.height}"
                )
            if transparent_actor:
                rgba = image.convert("RGBA")
                alpha = rgba.getchannel("A")
                bbox = alpha.getbbox()
                observed["alpha_bbox"] = list(bbox) if bbox else None
                if not bbox:
                    errors.append("actor has no visible alpha subject")
                else:
                    coverage = sum(1 for value in alpha.get_flattened_data() if value > 16) / (image.width * image.height)
                    observed["alpha_coverage"] = round(coverage, 4)
                    if coverage < 0.05:
                        errors.append("actor occupies less than 5% of its frame")
                    if coverage > 0.90:
                        errors.append("actor cutout leaves no readable transparent separation")
                    if bbox[0] == 0 or bbox[1] == 0 or bbox[2] == image.width or bbox[3] == image.height:
                        errors.append("actor silhouette touches the frame edge")
    except Exception as exc:
        errors.append(f"image inspection failed: {type(exc).__name__}: {exc}")
    return {
        "logical_name": logical_name,
        "path": str(path),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "observed": observed,
    }


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
    output_dir: Path | None = None,
) -> Path:
    if output_dir is None:
        raise ValueError("output_dir is required for isolated asset generation")
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
            output_dir.mkdir(parents=True, exist_ok=True)
            # ComfyUI adds a numeric suffix that changes on every request.
            # Store a stable logical filename inside this run so re-assets can
            # overwrite the image without invalidating every generated script.
            out_path = output_dir / f"{filename_prefix}.png"
            if strip_bg:
                image_bytes = _strip_background(image_bytes)
            out_path.write_bytes(image_bytes)
            return out_path

    raise TimeoutError(f"ComfyUI generation for {filename_prefix!r} did not complete within {timeout}s")


def _asset_requests(design_doc: dict, art_direction: dict | None = None) -> list[tuple]:
    """Build the stable asset plan used by both initial and repair runs.

    Every request carries an explicit seed. Filtering this plan for a targeted
    repair therefore cannot accidentally change a seed just because earlier
    batch entries were omitted.
    """
    art_style = design_doc["art_style"]
    art_direction = art_direction or compile_art_direction(design_doc)
    contracts = art_contract_by_name(art_direction)
    template = design_doc.get("mechanic_template")
    if template == "run_and_gun":
        actor_view = f"side view, {HERO_NATIVE_FACING}"
        idle_pose = "at rest, standing still, relaxed, still facing screen-left"
        motion_pose = "walking toward screen-left, legs apart mid-stride, leaning left into the movement"
    else:
        actor_view = (
            "strict top-down orthographic actor viewed directly from above, "
            "head oriented toward the top edge, no side-view pose, no isometric angle"
        )
        idle_pose = "at rest in a compact readable top-down stance"
        motion_pose = "moving toward the top edge with a distinct active limb pose"
    hero_common = (
        f"{design_doc['hero_description']}, full body, whole character visible from "
        f"head to feet, {actor_view}, game sprite, centered, "
        f"{art_style}, plain solid background"
    )
    requests = [
        (
            f"{design_doc['hero_description']}, {idle_pose}, {hero_common}"
            f"{asset_prompt_suffix(contracts.get('hero_sprite'), art_direction)}",
            "hero_sprite", ICON_GEN_SIZE, ICON_GEN_SIZE, True, HERO_SEED,
        ),
        (
            f"{design_doc['hero_description']}, {motion_pose}, {hero_common}"
            f"{asset_prompt_suffix(contracts.get('hero_walk'), art_direction)}",
            "hero_walk", ICON_GEN_SIZE, ICON_GEN_SIZE, True, HERO_SEED,
        ),
        (
            f"{design_doc['key_item']['description']}, whole object fully visible, small game "
            f"icon, centered, {art_style}, plain solid background"
            f"{asset_prompt_suffix(contracts.get('key_item'), art_direction)}",
            "key_item", ICON_GEN_SIZE, ICON_GEN_SIZE, True, 2,
        ),
    ]
    for index, extra in enumerate(design_doc.get("extra_sprites") or [], start=3):
        requests.append(
            (
                f"{extra['description']}, whole object fully visible, game sprite, "
                f"centered, {art_style}, plain solid background"
                f"{asset_prompt_suffix(contracts.get('extra_' + extra['name']), art_direction)}",
                f"extra_{extra['name']}", ICON_GEN_SIZE, ICON_GEN_SIZE, True, index,
            )
        )
    background_seed = 3 + len(design_doc.get("extra_sprites") or [])
    for index, level in enumerate(design_doc["levels"]):
        template = design_doc.get("mechanic_template")
        if template == "run_and_gun":
            background_subject = (
                f"distant atmospheric backdrop for {level.get('name', 'the stage')} "
                f"in a {design_doc.get('genre', 'side-view action game')}, using only "
                "non-interactive far scenery, sky, clouds, weather, and distant "
                "silhouettes, empty foreground, no floor, no platforms, no roads, "
                "no rails, no vehicles, no trains, no buildings in the foreground, "
                "no people, no characters, no creatures, no weapons, no pickups"
            )
            viewpoint = (
                "strict 2D side-view orthographic platformer background, camera facing "
                "horizontally at the side of the level, horizontal ground and skyline, "
                "parallel side elevation, layered parallax scenery, no top-down view, "
                "no isometric angle, no diagonal travel path, no vanishing-point floor, "
                "no characters, no enemies, no UI, no text, background scenery only"
            )
        elif template == "action_rpg":
            background_subject = (
                f"top-down environment for {level.get('name', 'the dungeon')} in a "
                f"{design_doc.get('genre', 'fantasy action RPG')}, floor, walls, "
                "ruins, paths and non-interactive environmental details only, empty "
                "play space, no hero, no NPC, no enemies, no boss, no pickups, no UI"
            )
            viewpoint = (
                "strict 2D top-down orthographic game background, camera facing "
                "straight down at 90 degrees, readable connected rooms and open "
                "combat floor, no perspective, no horizon, no vanishing point, no "
                "camera tilt, no isometric angle, no characters, no UI, no text"
            )
        else:
            background_subject = level["description"]
            viewpoint = (
                "strict top-down orthographic view, camera facing straight down at 90 "
                "degrees, flat floor plan, no perspective, no horizon, no vanishing "
                "point, no camera tilt, no isometric angle, walls and objects shown "
                "from directly above only"
            )
        requests.append(
            (
                f"{background_subject}, {art_style}, game background, {viewpoint}"
                f"{asset_prompt_suffix(contracts.get(f'level_{index}_bg'), art_direction)}",
                f"level_{index}_bg", VIEWPORT_WIDTH, VIEWPORT_HEIGHT, False,
                background_seed + index,
            )
        )
    return requests


def _target_names(request: dict) -> set[str]:
    field = request["field"]
    if field == "hero_description":
        return {"hero_sprite", "hero_walk"}
    if field == "key_item.description":
        return {"key_item"}
    if field == "level_background":
        return {f"level_{request['level_index']}_bg"}
    if field.startswith("extra:"):
        return {f"extra_{field[6:]}"}
    raise ValueError(f"Unsupported targeted asset field: {field!r}")


def _record_replacement_in_ledger(ledger: list[dict], event: dict) -> list[dict]:
    """Attach repair provenance immediately, before the rebuilt QA attempt."""
    updated = [dict(item) for item in ledger]
    level_index = event["level_index"]
    for index, entry in enumerate(updated):
        if entry.get("level_index") != level_index:
            continue
        replacements = list(entry.get("asset_replacements") or [])
        replacements.append(event)
        updated[index] = {**entry, "asset_replacements": replacements}
        break
    return updated


def asset_maker(state: GraphState) -> GraphState:
    # Reproducible coder benchmarks and replays can preload one frozen asset
    # pack. Reuse those exact files instead of introducing image-model noise.
    if state.get("sprite_paths") and not state.get("reasset_request"):
        print(f"[Asset Maker] Reusing {len(state['sprite_paths'])} frozen assets")
        update: GraphState = {"sprite_paths": list(state["sprite_paths"])}
        if state.get("art_direction"):
            request_map = {
                name: (width, height, strip_bg)
                for _prompt, name, width, height, strip_bg, _seed in _asset_requests(
                    state["design_doc"], state["art_direction"]
                )
            }
            results = []
            for raw_path in state["sprite_paths"]:
                path = Path(raw_path)
                logical_name = path.stem
                if logical_name in request_map:
                    width, height, strip_bg = request_map[logical_name]
                    delivered_width = ICON_WIDTH if strip_bg else width
                    delivered_height = ICON_HEIGHT if strip_bg else height
                    results.append(
                        _inspect_asset(
                            path, logical_name, delivered_width, delivered_height, strip_bg
                        )
                    )
            update["asset_contract_results"] = results
        return update

    _check_comfyui_reachable()
    design_doc = state["design_doc"]
    output_dir = assets_dir(state)

    # Icons get the rembg pass (strip_bg); level backgrounds keep every pixel.
    # "plain solid background" in the icon prompts gives rembg a clean subject
    # boundary to cut along - asking Flux for "transparent background" is
    # futile (no alpha channel) and produces busy checkerboard fakes.
    # The hero is drawn twice, in a resting pose and a walking one, so the
    # game can swap between them instead of sliding one still image around.
    # Both share HERO_SEED and differ only in the pose clause: holding the seed
    # and the description fixed is what keeps them reading as the same
    # character. Measured on a tabby cat, that gives a usable sit/walk pair -
    # the palette, collar and style carry over, though eye colour and stripe
    # detail drift a little. It is not enough control for a multi-frame walk
    # cycle, which is why there is only one walking pose; the bob and lean in
    # the Anim autoload supply the stepping motion.
    requests = _asset_requests(design_doc, state.get("art_direction"))
    reasset_request = state.get("reasset_request")
    target_names = _target_names(reasset_request) if reasset_request else None
    if target_names:
        requests = [request for request in requests if request[1] in target_names]
        if {request[1] for request in requests} != target_names:
            raise RuntimeError(f"Targeted asset plan is incomplete for {sorted(target_names)}")
        print(f"[Asset Maker] Targeted repair: {', '.join(sorted(target_names))}")

    sprite_paths = list(state.get("sprite_paths") or []) if reasset_request else []
    contract_results = [
        result for result in (state.get("asset_contract_results") or [])
        if result.get("logical_name") not in {request[1] for request in requests}
    ]
    replaced_files = []
    for request in requests:
        prompt, name, width, height, strip_bg, seed = request
        active_path = output_dir / f"{name}.png"
        previous_path = None
        if reasset_request and active_path.exists():
            revision_dir = output_dir / "revisions"
            revision_dir.mkdir(parents=True, exist_ok=True)
            previous_path = revision_dir / (
                f"level_{reasset_request['level_index']}_retry_"
                f"{reasset_request['retry']}_{name}.png"
            )
            shutil.copy2(active_path, previous_path)
        path = _generate_image(
            prompt,
            name,
            seed=seed,
            width=width,
            height=height,
            strip_bg=strip_bg,
            output_dir=output_dir,
        )
        path_string = str(path)
        if path_string not in sprite_paths:
            sprite_paths.append(path_string)
        delivered_width = ICON_WIDTH if strip_bg else width
        delivered_height = ICON_HEIGHT if strip_bg else height
        contract_results.append(
            _inspect_asset(
                path, name, delivered_width, delivered_height, strip_bg
            )
        )
        if reasset_request:
            replaced_files.append(
                {
                    "name": name,
                    "active_path": path_string,
                    "previous_path": str(previous_path) if previous_path else None,
                }
            )
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

    update: GraphState = {
        "sprite_paths": sprite_paths,
        "asset_contract_results": contract_results,
    }
    if reasset_request:
        event = {
            **reasset_request,
            "files": replaced_files,
            "status": "replaced",
        }
        replacements = list(state.get("asset_replacements") or []) + [event]
        update.update(
            {
                "reasset_request": None,
                "asset_replacements": replacements,
                "level_results": _record_replacement_in_ledger(
                    state.get("level_results") or [], event
                ),
            }
        )
    return update
