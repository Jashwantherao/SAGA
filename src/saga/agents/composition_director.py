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

    if supplied is not None:
        design = state.get("design_doc")
        if not design:
            raise ValueError("a supplied GameSpec requires its reviewed DesignDoc")
        expected = translate_legacy_design(design)
        if canonical_game_spec(spec) != canonical_game_spec(expected):
            raise ValueError(
                "supplied GameSpec does not match the DesignDoc translation. "
                "Composition Kernel v1 will not claim custom content that the "
                "current builders do not yet consume"
            )

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
    return {
        "game_spec": spec,
        "game_spec_status": status,
        "game_spec_errors": [],
        "assembly_lock": assembly_lock,
        "assembly_hash": assembly_lock["assembly_hash"],
    }
