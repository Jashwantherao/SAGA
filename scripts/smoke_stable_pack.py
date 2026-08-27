"""Build a stable-pack project without external generation services.

This is a local development smoke tool: it composes the reviewed design,
reuses an existing run's frozen assets, and invokes the same Coder scaffolder
as the production graph.  Godot probes can then be run against the printed
project path without contacting an LLM, ComfyUI or MusicGen.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from saga.agents.coder import coder
from saga.capabilities import resolve_game_spec
from saga.game_spec import translate_legacy_design


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design-doc", type=Path, required=True)
    parser.add_argument("--asset-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    design = json.loads(args.design_doc.read_text(encoding="utf-8"))
    manifest = json.loads(args.asset_run.read_text(encoding="utf-8"))
    sprite_paths = [path for path in manifest.get("sprite_paths") or [] if Path(path).is_file()]
    if not sprite_paths:
        raise SystemExit("asset run has no readable sprite_paths")
    spec = translate_legacy_design(design)
    lock = resolve_game_spec(spec)
    args.output.mkdir(parents=True, exist_ok=True)
    result = coder(
        {
            "run_dir": str(args.output),
            "design_doc": design,
            "game_spec": spec,
            "assembly_lock": lock,
            "assembly_hash": lock["assembly_hash"],
            "sprite_paths": sprite_paths,
            "bgm_path": None,
            "current_level": 0,
            "qa_errors": [],
            "tune_notes": [],
        }
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
