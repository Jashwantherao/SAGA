"""Compile a DesignDoc into an executable visual production contract.

The Art Director does not generate pixels and does not grade its own output.
It creates the shared visual language consumed by Asset Maker and later quoted
verbatim to screenshot QA.  This closes the old gap where art and runtime code
interpreted the same brief independently.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from saga.state import GraphState


ART_DIRECTION_VERSION = 1

CAMERA_CONTRACTS = {
    "run_and_gun": {
        "projection": "strict 2D side-view orthographic",
        "camera": "horizontal side elevation",
        "gameplay_plane": "flat horizontal traversal band",
        "forbidden": ["top-down view", "isometric angle", "diagonal road", "vanishing-point floor"],
    },
    "action_rpg": {
        "projection": "strict 2D top-down orthographic",
        "camera": "straight down at 90 degrees",
        "gameplay_plane": "flat connected rooms with open combat lanes",
        "forbidden": ["side view", "first-person view", "horizon", "vanishing point", "isometric angle"],
    },
}

DEFAULT_CAMERA = {
    "projection": "strict 2D top-down orthographic",
    "camera": "straight down at 90 degrees",
    "gameplay_plane": "flat readable playfield",
    "forbidden": ["horizon", "vanishing point", "camera tilt", "isometric angle"],
}

PALETTES = (
    {"shadow": "#15202B", "surface": "#34505C", "hero": "#F2C14E", "danger": "#E45756", "reward": "#67D5B5"},
    {"shadow": "#211A2C", "surface": "#54456B", "hero": "#FFB86B", "danger": "#EF5D8C", "reward": "#73D2DE"},
    {"shadow": "#17241D", "surface": "#3E6650", "hero": "#F4D35E", "danger": "#D95D39", "reward": "#7BD389"},
    {"shadow": "#201C29", "surface": "#4D496B", "hero": "#F6AE2D", "danger": "#F26430", "reward": "#86BBD8"},
)


def _camera_for(template: str) -> dict[str, Any]:
    return dict(CAMERA_CONTRACTS.get(template, DEFAULT_CAMERA))


def _contract(
    logical_name: str,
    role: str,
    subject: str,
    camera: dict[str, Any],
    *,
    actor: bool,
    palette_role: str,
) -> dict[str, Any]:
    if actor:
        silhouette = "single complete subject, readable at 48 pixels, no cropped limbs, no merged props"
        separation = "transparent background; subject alone; no scenery, text, border, UI, shadow box, or frame"
    else:
        silhouette = "large calm value shapes behind a high-contrast gameplay layer"
        separation = "environment only; no hero, NPC, enemy, boss, pickup, projectile, UI, text, or fake interactable"
    return {
        "logical_name": logical_name,
        "role": role,
        "subject": subject,
        "projection": camera["projection"],
        "silhouette_contract": silhouette,
        "layer_separation": separation,
        "palette_role": palette_role,
        "forbidden": list(camera["forbidden"]) + (["multiple characters", "busy opaque backdrop"] if actor else []),
    }


def compile_art_direction(design_doc: dict) -> dict[str, Any]:
    """Create a deterministic style bible and role-level asset contracts."""
    template = str(design_doc.get("mechanic_template") or "unknown")
    camera = _camera_for(template)
    identity = "|".join(
        (
            str(design_doc.get("title") or "Untitled"),
            str(design_doc.get("art_style") or "stylized 2D art"),
            str(design_doc.get("theme_thread") or ""),
            template,
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    palette = dict(PALETTES[int(digest[:4], 16) % len(PALETTES)])
    contracts = [
        _contract(
            "hero_sprite", "hero_idle", str(design_doc.get("hero_description") or "hero"),
            camera, actor=True, palette_role="hero",
        ),
        _contract(
            "hero_walk", "hero_motion", str(design_doc.get("hero_description") or "hero"),
            camera, actor=True, palette_role="hero",
        ),
        _contract(
            "key_item", str((design_doc.get("key_item") or {}).get("role") or "pickup"),
            str((design_doc.get("key_item") or {}).get("description") or "quest item"),
            camera, actor=True, palette_role="reward",
        ),
    ]
    for extra in design_doc.get("extra_sprites") or []:
        name = str(extra.get("name") or "extra")
        if any(token in name for token in ("boss", "warden", "golem", "champion")):
            role = "boss"
        elif any(token in name for token in ("npc", "archivist", "hermit", "keeper", "merchant", "guide")):
            role = "npc"
        elif any(token in name for token in ("enemy", "sentinel", "skirmisher", "stalker", "bruiser", "guard", "drone", "creature")):
            role = "enemy"
        else:
            role = "world_actor"
        contracts.append(
            _contract(
                f"extra_{name}", role, str(extra.get("description") or name),
                camera, actor=True, palette_role="reward" if role == "npc" else "danger",
            )
        )
    for index, level in enumerate(design_doc.get("levels") or []):
        contracts.append(
            _contract(
                f"level_{index}_bg", "background", str(level.get("description") or level.get("name") or "environment"),
                camera, actor=False, palette_role="surface",
            )
        )
    direction = {
        "art_direction_version": ART_DIRECTION_VERSION,
        "identity_hash": digest[:16],
        "title": str(design_doc.get("title") or "Untitled"),
        "mechanic_template": template,
        "rendering_language": str(design_doc.get("art_style") or "stylized 2D game art"),
        "camera_contract": camera,
        "palette": palette,
        "value_structure": {
            "background": "low contrast and lower saturation",
            "hero": "highest local contrast and unique warm accent",
            "danger": "distinct danger hue and aggressive silhouette",
            "reward": "bright reward hue with compact symmetric silhouette",
        },
        "scale_hierarchy": {
            "hero_pixels": 48,
            "pickup_pixels": 28,
            "regular_enemy_pixels": 44,
            "boss_pixels": 82,
        },
        "coherence_rules": [
            "one projection and camera language across background and actors",
            "one outline weight and material language across all actors",
            "background contains no painted gameplay actors or fake interactables",
            "hero, danger, and reward remain distinguishable without reading labels",
        ],
        "asset_contracts": contracts,
    }
    errors = validate_art_direction(direction, design_doc)
    if errors:
        raise ValueError("invalid art direction: " + "; ".join(errors))
    return direction


def validate_art_direction(direction: dict, design_doc: dict | None = None) -> list[str]:
    errors: list[str] = []
    if direction.get("art_direction_version") != ART_DIRECTION_VERSION:
        errors.append(f"art_direction_version must be {ART_DIRECTION_VERSION}")
    camera = direction.get("camera_contract") or {}
    if not camera.get("projection") or not camera.get("forbidden"):
        errors.append("camera contract must define projection and forbidden views")
    palette = direction.get("palette") or {}
    if set(palette) != {"shadow", "surface", "hero", "danger", "reward"}:
        errors.append("palette must assign shadow, surface, hero, danger and reward colors")
    contracts = direction.get("asset_contracts") or []
    names = [contract.get("logical_name") for contract in contracts]
    if len(names) != len(set(names)):
        errors.append("asset contract logical names must be unique")
    required = {"hero_sprite", "hero_walk", "key_item"}
    if design_doc:
        required.update(f"extra_{item['name']}" for item in design_doc.get("extra_sprites") or [])
        required.update(f"level_{index}_bg" for index, _ in enumerate(design_doc.get("levels") or []))
    missing = sorted(required - set(names))
    if missing:
        errors.append("missing asset contracts: " + ", ".join(missing))
    for contract in contracts:
        if not contract.get("silhouette_contract") or not contract.get("layer_separation"):
            errors.append(f"asset {contract.get('logical_name')!r} lacks silhouette or layer separation")
    return errors


def art_contract_by_name(direction: dict | None) -> dict[str, dict]:
    return {
        str(contract.get("logical_name")): contract
        for contract in (direction or {}).get("asset_contracts") or []
    }


def asset_prompt_suffix(contract: dict | None, direction: dict | None) -> str:
    if not contract or not direction:
        return ""
    palette = direction.get("palette") or {}
    forbidden = ", ".join(str(item) for item in contract.get("forbidden") or [])
    return (
        f". ART DIRECTOR CONTRACT: {contract['projection']}; "
        f"{contract['silhouette_contract']}; {contract['layer_separation']}; "
        f"palette shadow {palette.get('shadow')}, surface {palette.get('surface')}, "
        f"hero {palette.get('hero')}, danger {palette.get('danger')}, reward {palette.get('reward')}; "
        f"forbid {forbidden}"
    )


def art_director(state: GraphState) -> GraphState:
    design = state.get("design_doc")
    if not design:
        raise ValueError("Art Director requires a reviewed design_doc")
    direction = compile_art_direction(design)
    output = Path(state["run_dir"]) / "art_direction.json"
    output.write_text(json.dumps(direction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[Art Director] locked {len(direction['asset_contracts'])} visual contracts "
        f"as {direction['identity_hash']} -> {output}"
    )
    return {
        "art_direction": direction,
        "art_direction_status": "locked",
        "art_direction_errors": [],
    }
