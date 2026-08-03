"""CLI entry point: turn a one-line game idea into a structured design doc.

Usage:
    uv run python -m saga.main "a puzzle platformer about a shape-shifting golem"
"""

import argparse
import json
import sys
from pathlib import Path


# Builder ledger statuses whose script is part of the shipped game. Anything
# else (rejected, superseded, skipped) contributes no code, so it carries no
# acceptance claim either.
LIVE_BUILD_STATUSES = {
    "baseline_compiles",
    "baseline_corrected",
    "integrated",
    "unchanged",
}


def unconfirmed_systems(result: dict) -> list[str]:
    """Blueprint systems that shipped code without behavioral proof.

    Per-level QA proves the game still runs; it does not prove that a system
    did what its acceptance criteria promised. Only some kinds have a probe
    that can say so today (baseline, movement, the objective kinds, and hud
    via video QA), so an unconfirmed system is a gap in evidence rather than
    a known defect - reported as a warning, not a failure. A system whose
    builder hash no longer matches the script QA actually ran is unproven for
    the same reason: the evidence describes different code.
    """
    unconfirmed = []
    for item in result.get("system_build_results") or []:
        if item.get("status") not in LIVE_BUILD_STATUSES:
            continue
        system_id = item.get("system_id") or item.get("id") or item.get("kind") or "?"
        if not item.get("qa_confirmed"):
            unconfirmed.append(f"{system_id}: no acceptance probe confirmed this system")
        elif item.get("builder_hash_matches_qa") is False:
            unconfirmed.append(f"{system_id}: QA evidence describes a different script")
    return unconfirmed


def assess_ship_status(result: dict) -> tuple[str, bool]:
    """Return the truthful aggregate release status for a completed run.

    ``qa_passed`` is the current (normally final) level's status. Shipping
    additionally requires one clean ledger entry for every designed level, so
    a later success cannot erase an earlier defect or a skipped level.
    Advisory-only findings are shippable but explicitly reported as warnings -
    including blueprint systems that shipped without acceptance evidence.
    """
    if result.get("ship_blocked"):
        return "blocked", False

    expected_levels = len((result.get("design_doc") or {}).get("levels") or [])
    level_results = result.get("level_results") or []
    by_index = {
        item.get("level_index"): item
        for item in level_results
        if isinstance(item.get("level_index"), int)
    }
    complete = (
        expected_levels > 0
        and len(by_index) == expected_levels
        and set(by_index) == set(range(expected_levels))
    )
    all_passed = complete and all(
        by_index[index].get("status") == "passed" for index in range(expected_levels)
    )
    if not result.get("qa_passed") or not all_passed:
        return "failed", False

    has_warnings = bool(unconfirmed_systems(result)) or any(
        (item.get("vision_notes") or [])
        or (item.get("balance_notes") or [])
        or (item.get("video_notes") or [])
        for item in by_index.values()
    )
    return ("passed_with_warnings" if has_warnings else "passed"), True


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a game design doc from a one-line idea.")
    parser.add_argument(
        "idea",
        nargs="?",
        help="One-line game idea, e.g. 'a puzzle platformer about a shape-shifting golem'",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check configured models, services, Godot, credentials, and output access, then exit",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Start without dependency checks (useful only when a check is intentionally unavailable)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show a full traceback instead of a concise pipeline failure",
    )
    parser.add_argument(
        "--playtest",
        action="store_true",
        help="After the pipeline finishes, enter the human playtest feedback loop",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help=(
            "Stop after each level passes QA, launch it, and take one line of "
            "feedback before the next level is built - so a wrong mechanic is "
            "fixed once instead of reproduced into every level"
        ),
    )
    parser.add_argument(
        "--levels",
        type=int,
        choices=range(1, 6),
        default=None,
        metavar="N",
        help="Generate exactly N levels (1-5); default is an authored 3-5 level arc",
    )
    parser.add_argument(
        "--design-doc",
        type=Path,
        help="Use a fixed design-doc JSON file (for reproducible replay and benchmarking)",
    )
    parser.add_argument(
        "--blueprint",
        type=Path,
        help="Use a reviewed Game Blueprint JSON contract instead of invoking the architect",
    )
    parser.add_argument(
        "--asset-pack",
        type=Path,
        help="Reuse sprite_paths and bgm_path from an existing SAGA run manifest",
    )
    args = parser.parse_args()

    from saga.doctor import print_report, required_checks_pass, run_checks

    if args.doctor:
        checks = run_checks(include_playtest=True)
        print_report(checks)
        raise SystemExit(0 if required_checks_pass(checks) else 2)
    if not args.idea:
        parser.error("the following arguments are required: idea (unless --doctor is used)")
    if not args.skip_preflight:
        checks = run_checks(include_playtest=args.playtest)
        print_report(checks)
        if not required_checks_pass(checks):
            print(
                "\nPreflight failed. Fix the required checks above or use "
                "--skip-preflight if you intentionally want the pipeline to try anyway.",
                file=sys.stderr,
            )
            raise SystemExit(2)

    fixed_design = None
    if args.design_doc:
        try:
            fixed_design = json.loads(args.design_doc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"cannot read --design-doc: {exc}")
        if not isinstance(fixed_design, dict):
            parser.error("--design-doc must contain a JSON object")

    fixed_blueprint = None
    if args.blueprint:
        try:
            from saga.blueprint import load_blueprint

            fixed_blueprint = load_blueprint(args.blueprint)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"cannot read --blueprint: {exc}")

    frozen_assets = {}
    if args.asset_pack:
        try:
            frozen_assets = json.loads(args.asset_pack.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"cannot read --asset-pack: {exc}")
        sprite_paths = frozen_assets.get("sprite_paths") or []
        missing = [path for path in [*sprite_paths, frozen_assets.get("bgm_path")] if path and not Path(path).is_file()]
        if not sprite_paths or missing:
            parser.error(f"--asset-pack has no sprites or missing files: {missing}")

    try:
        from saga.graph import build_graph

        graph = build_graph(human_gate=args.gate)
        result = graph.invoke(
            {
                "user_prompt": args.idea,
                "requested_levels": args.levels,
                "design_doc": fixed_design,
                "blueprint": fixed_blueprint,
                "sprite_paths": frozen_assets.get("sprite_paths"),
                "bgm_path": frozen_assets.get("bgm_path"),
            }
        )
    except Exception as exc:
        if args.debug:
            raise
        print(f"Pipeline failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    design_doc = result["design_doc"]
    print(json.dumps(design_doc, indent=2))

    output_path = Path(result["run_dir"]) / "design_doc.json"
    output_path.write_text(json.dumps(design_doc, indent=2), encoding="utf-8")
    print(f"\nRun workspace: {result['run_dir']}", file=sys.stderr)
    print(f"Design doc: {output_path}", file=sys.stderr)
    blueprint_path = Path(result["run_dir"]) / "blueprint.json"
    if result.get("blueprint"):
        blueprint_path.write_text(
            json.dumps(result["blueprint"], indent=2), encoding="utf-8"
        )
        print(
            f"Game Blueprint: {blueprint_path} "
            f"({result.get('blueprint_status')}, model={result.get('blueprint_model')})",
            file=sys.stderr,
        )

    for path in result.get("sprite_paths") or []:
        print(f"Sprite/background: {path}", file=sys.stderr)
    if result.get("bgm_path"):
        print(f"BGM: {result['bgm_path']}", file=sys.stderr)
    if result.get("godot_project_path"):
        print(f"Godot project: {result['godot_project_path']}", file=sys.stderr)
    ship_status, ship_ready = assess_ship_status(result)
    if ship_ready:
        label = "PASSED WITH WARNINGS" if ship_status == "passed_with_warnings" else "PASSED"
        total_retries = sum(
            item.get("retry_count") or 0 for item in result.get("level_results") or []
        )
        print(f"QA: {label} ({total_retries} total retries)", file=sys.stderr)
    else:
        print(
            f"QA: {ship_status.upper()}: {result.get('qa_errors') or 'not every level has a clean pass'}",
            file=sys.stderr,
        )
    if result.get("screenshot_path"):
        print(f"Screenshot: {result['screenshot_path']}", file=sys.stderr)
    if result.get("gameplay_video_path"):
        print(f"Gameplay video: {result['gameplay_video_path']}", file=sys.stderr)
    if result.get("objective_result"):
        objective = result["objective_result"]
        print(
            "Gameplay completion: "
            f"{objective.get('status')} score={objective.get('completion_score')} "
            f"time={objective.get('completion_seconds')}s",
            file=sys.stderr,
        )

    if args.playtest and ship_ready:
        from saga.playtest import playtest_loop

        playtest_loop(result)

    # Playtest revisions mutate the same state, so write the final design again
    # and keep a compact machine-readable manifest beside every isolated run.
    output_path.write_text(json.dumps(result["design_doc"], indent=2), encoding="utf-8")
    if result.get("blueprint"):
        blueprint_path.write_text(
            json.dumps(result["blueprint"], indent=2), encoding="utf-8"
        )
    # Playtest may rebuild selected levels, so calculate the release decision
    # again from the updated durable ledger.
    ship_status, ship_ready = assess_ship_status(result)
    level_results = result.get("level_results") or []
    manifest = {
        "manifest_version": 14,
        "run_dir": result["run_dir"],
        "idea": args.idea,
        "title": (result.get("design_doc") or {}).get("title"),
        "blueprint_version": (result.get("blueprint") or {}).get("blueprint_version"),
        "blueprint_path": str(blueprint_path) if result.get("blueprint") else None,
        "blueprint_status": result.get("blueprint_status"),
        "blueprint_model": result.get("blueprint_model"),
        "blueprint_errors": result.get("blueprint_errors") or [],
        "blueprint_build_plan": result.get("blueprint_build_plan") or [],
        "system_build_results": result.get("system_build_results") or [],
        "unconfirmed_systems": unconfirmed_systems(result),
        "status": ship_status,
        "ship_ready": ship_ready,
        "current_level": result.get("current_level"),
        "retry_count": sum(item.get("retry_count") or 0 for item in level_results),
        "level_results": level_results,
        "godot_project_path": result.get("godot_project_path"),
        "sprite_paths": result.get("sprite_paths") or [],
        "asset_replacements": result.get("asset_replacements") or [],
        "bgm_path": result.get("bgm_path"),
        "screenshot_path": result.get("screenshot_path"),
        "gameplay_video_path": result.get("gameplay_video_path"),
        "video_qa_result": result.get("video_qa_result"),
        "video_notes": result.get("video_notes") or [],
        "objective_result": result.get("objective_result"),
        "qa_errors": result.get("qa_errors") or [],
        "vision_notes": result.get("vision_notes") or [],
        "balance_notes": result.get("balance_notes") or [],
        "coder_model": result.get("coder_model"),
    }
    manifest_path = Path(result["run_dir"]) / "run.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Run manifest: {manifest_path}", file=sys.stderr)

    if not ship_ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
