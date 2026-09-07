"""Compile a creative design into a reproducible gameplay assembly.

The Composition Director is deliberately deterministic and model-free.  It
translates today's DesignDoc into GameSpec v2 (or accepts a supplied GameSpec),
validates the data-only contract, resolves its versioned capabilities, and
persists both inputs to the run workspace before expensive production begins.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from saga.capabilities import canonical_game_spec, resolve_game_spec
from saga.game_spec import translate_legacy_design, validate_game_spec
from saga.state import GraphState


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _compile_action_rpg_design(spec: dict, reviewed_design: dict) -> dict:
    """Materialize GameSpec-authored content into the stable pack's input.

    GameSpec remains the authority for identity, catalog, world and rules.  A
    DesignDoc-shaped view is emitted only because asset/audio agents still use
    those well-established field names.  No content is invented here.
    """
    compiled = copy.deepcopy(reviewed_design)
    identity = spec["identity"]
    presentation = spec["presentation"]
    content = spec["content"]
    compiled.update(
        {
            "title": identity["title"],
            "genre": identity["genre"],
            "mechanic_template": "action_rpg",
            "hero_description": content["hero"]["description"],
            "core_mechanics": list(identity["core_loop"]),
            "story_premise": identity["premise"],
            "theme_thread": identity["theme_thread"],
            "win_condition": spec["rules"]["win"]["description"],
            "lose_condition": spec["rules"]["lose"]["description"],
            "levels": [
                {
                    "name": zone["name"],
                    "description": zone["description"],
                    "outro_beat": zone["outro_beat"],
                    "intensity": zone["intensity"],
                    "pressure_notes": zone["pacing_notes"],
                }
                for zone in spec["world"]["zones"]
            ],
            "art_style": presentation["art_style"],
            "audio_mood": presentation["audio_mood"],
            "extra_sprites": [
                {"name": actor["id"], "description": actor["description"]}
                for actor in content["actors"]
            ],
        }
    )
    if content["items"]:
        item = content["items"][0]
        compiled["key_item"] = {
            "description": item["description"],
            "role": "pickup",
        }
    return compiled


def composition_director(state: GraphState) -> GraphState:
    """Validate and lock the exact capability assembly for this run.

    A supplied GameSpec is treated as a fixed, human-authored contract.  When
    none is supplied, the current DesignDoc is translated without inventing
    mechanics.  Resolution must succeed before either artifact is written, so
    an invalid composition can never leave a plausible-looking partial lock.
    """
    supplied = state.get("game_spec")
    if supplied is not None:
        spec = copy.deepcopy(supplied)
        status = "fixed"
    else:
        design = state.get("design_doc")
        if not design:
            raise ValueError(
                "Composition Director needs a design_doc when game_spec is not supplied"
            )
        spec = translate_legacy_design(design)
        status = "translated"

    problems = validate_game_spec(spec)
    if problems:
        source = "supplied" if supplied is not None else "translated"
        raise ValueError(f"{source} GameSpec is invalid: {'; '.join(problems)}")

    compiled_design = None
    if supplied is not None:
        design = state.get("design_doc")
        if not design:
            raise ValueError("a supplied GameSpec requires its reviewed DesignDoc")
        expected = translate_legacy_design(design)
        if canonical_game_spec(spec) != canonical_game_spec(expected):
            template = (spec.get("legacy") or {}).get("mechanic_template")
            if template != "action_rpg" or design.get("mechanic_template") != "action_rpg":
                raise ValueError(
                    "supplied GameSpec does not match the DesignDoc translation; "
                    "direct custom GameSpec content is currently supported only "
                    "by the Action-RPG stable pack"
                )
            compiled_design = _compile_action_rpg_design(spec, design)
            status = "fixed_compiled"

    assembly_lock = resolve_game_spec(spec)
    run_dir = Path(state["run_dir"])
    game_spec_path = run_dir / "game_spec.json"
    assembly_lock_path = run_dir / "assembly.lock.json"
    _write_json(game_spec_path, spec)
    _write_json(assembly_lock_path, assembly_lock)

    component_count = sum(
        len(mode.get("components") or []) for mode in assembly_lock.get("modes") or []
    )
    print(
        f"[Composition Director/{status}] locked {component_count} capabilities "
        f"as {assembly_lock['assembly_hash'][:12]} -> {assembly_lock_path}"
    )
    result = {
        "game_spec": spec,
        "game_spec_status": status,
        "game_spec_errors": [],
        "assembly_lock": assembly_lock,
        "assembly_hash": assembly_lock["assembly_hash"],
    }
    if compiled_design is not None:
        result["design_doc"] = compiled_design
    return result
