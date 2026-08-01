"""Playtest loop driver - runs after the pipeline produces a QA-passed build.

Deliberately a plain CLI loop around the agent functions rather than graph
nodes: a blocking input() inside a LangGraph node would couple graph
execution to a live terminal. When a UI lands, this is the seam where
LangGraph's interrupt() + checkpointer replaces stdin.

Routing (cheapest first, mirroring the Interpreter's cost order):
- tune       -> Coder's tune path for the targeted Level_N.gd script(s)
- reasset    -> field updated in the design doc, Asset Maker and/or Audio
                Agent regenerate, then a fresh Coder+QA pass
- redesign   -> field feedback appended to the user prompt, full rebuild
                from the Game Designer down
- out_of_scope -> printed honestly, never acted on
"""

from pathlib import Path

from saga.agents.asset_maker import asset_maker
from saga.agents.audio_agent import audio_agent
from saga.agents.coder import coder
from saga.agents.game_designer import game_designer
from saga.agents.playtest_feedback import (
    MAX_PLAYTEST_CYCLES,
    capture_playtest_feedback,
    interpret_feedback,
)
from saga.agents.qa_agent import qa_agent
from saga.agents.studio_director import studio_director
from saga.config import settings
from saga.graph import MAX_RETRIES
from saga.state import GraphState

GODOT_EXE = settings.godot_exe


def run_coder_qa(
    state: GraphState,
    level_indices: list[int] | None = None,
    tune_notes_by_level: dict[int, list[str]] | None = None,
) -> bool:
    """The same per-level Coder<->QA loop the graph runs, callable standalone:
    selected design-doc levels are generated and verified in turn, with a fresh
    retry budget per level. Returns whether every selected level passed."""
    total_levels = len((state.get("design_doc") or {}).get("levels") or [None])
    selected = list(range(total_levels)) if level_indices is None else sorted(set(level_indices))
    invalid = [index for index in selected if not 0 <= index < total_levels]
    if invalid:
        raise ValueError(f"Level indices outside the design doc: {invalid}")

    for level_index in selected:
        state["current_level"] = level_index
        state["qa_errors"] = None
        state["qa_passed"] = None
        state["retry_count"] = 0
        state["ship_blocked"] = False
        state["director_action"] = None
        state["tune_notes"] = list((tune_notes_by_level or {}).get(level_index) or []) or None

        while True:
            state.update(coder(state))
            state.update(qa_agent(state))
            if state.get("qa_passed"):
                break
            if state.get("ship_blocked"):
                print(
                    f"[Playtest] Level {level_index + 1} QA is blocked: "
                    f"{state.get('qa_errors')}"
                )
                return False
            if (state.get("retry_count") or 0) >= MAX_RETRIES:
                print(
                    f"[Playtest] Level {level_index + 1} QA failed after "
                    f"MAX_RETRIES={MAX_RETRIES}: {state.get('qa_errors')}"
                )
                return False
            # Same triage the graph runs: the Director decides fix /
            # regenerate / reasset instead of every failure blindly returning
            # to the Coder.
            state.update(studio_director(state))
            if state.get("director_action") == "reasset":
                state.update(asset_maker(state))
    return True


def _revision_levels(revision: dict, total_levels: int, fallback_level: int) -> list[int]:
    """Resolve a FeedbackRevision's 1-based target_level into script indices.

    target_level=0 means every level. The fallback keeps old hand-authored
    revision documents usable while the structured-output schema migrates.
    """
    raw = revision.get("target_level")
    if raw is None:
        return [min(max(fallback_level, 0), total_levels - 1)]
    if raw == 0:
        return list(range(total_levels))
    if isinstance(raw, int) and 1 <= raw <= total_levels:
        return [raw - 1]
    print(f"[Playtest] Ignoring invalid target_level={raw!r}; expected 0-{total_levels}")
    return []


def _read_level_scripts(state: GraphState) -> dict[int, str]:
    """Read the scripts belonging to the current generated build."""
    project_path = state.get("godot_project_path")
    if not project_path:
        raise ValueError("Playtest state has no generated Godot project path")
    project_dir = Path(project_path)
    total_levels = len((state.get("design_doc") or {}).get("levels") or [])
    scripts = {}
    for index in range(total_levels):
        path = project_dir / f"Level_{index}.gd"
        if path.exists():
            scripts[index] = path.read_text(encoding="utf-8")
    if not scripts:
        raise FileNotFoundError(f"No Level_N.gd scripts found in {project_dir}")
    return scripts


def apply_revision_doc(state: GraphState, revision_doc: dict) -> bool:
    """Apply one FeedbackRevision to the pipeline state.

    Returns True when the loop should stop (shipped, or nothing actionable
    remains). Pure routing - no stdin, no API calls - so it is testable with
    hand-authored revision docs.
    """
    if revision_doc["verdict"] == "ship":
        print("[Playtest] Verdict: ship. Done.")
        return True

    revisions = revision_doc["revisions"]

    for rev in revisions:
        if rev["route"] == "out_of_scope":
            print(f"[Playtest] Out of scope: {rev['delta']}")

    actionable = [r for r in revisions if r["route"] != "out_of_scope"]
    if not actionable:
        print("[Playtest] Nothing actionable remains - stopping.")
        return True

    redesigns = [r for r in actionable if r["route"] == "redesign"]
    if redesigns:
        # The rebuild replaces everything downstream, so tune/reasset
        # revisions from the same playtest are dropped (the Interpreter is
        # told to do this too; this is the belt to its suspenders).
        notes = "; ".join(f"{r['target_field']}: {r['delta']}" for r in redesigns)
        state["user_prompt"] = f"{state['user_prompt']} (revision after playtest: {notes})"
        print(f"[Playtest] Redesigning: {notes}")
        state.update(game_designer(state))
        state.update(asset_maker(state))
        state.update(audio_agent(state))
        state["current_level"] = 0
        state["qa_errors"] = None
        state["qa_passed"] = None
        state["retry_count"] = 0
        state["director_history"] = []
        if not run_coder_qa(state):
            print("[Playtest] Redesigned build did not pass QA; stopping the playtest loop.")
            return True
        return False

    reassets = [r for r in actionable if r["route"] == "reasset"]
    rebuilt_assets = False
    if reassets:
        regen_images = False
        regen_audio = False
        for rev in reassets:
            field, value = rev["target_field"], rev["delta"]
            print(f"[Playtest] Re-describing {field}: {value!r}")
            if field == "key_item.description":
                state["design_doc"]["key_item"]["description"] = value
                regen_images = True
            elif field == "art_style":
                state["design_doc"]["art_style"] = value
                regen_images = True
            elif field == "audio_mood":
                state["design_doc"]["audio_mood"] = value
                regen_audio = True
        if regen_images:
            state.update(asset_maker(state))
            rebuilt_assets = True
        if regen_audio:
            state.update(audio_agent(state))
            rebuilt_assets = True

    tunes = [r for r in actionable if r["route"] == "tune"]
    total_levels = len((state.get("design_doc") or {}).get("levels") or [])
    fallback_level = state.get("current_level") or 0
    tune_notes_by_level: dict[int, list[str]] = {}
    if tunes:
        for revision in tunes:
            for level_index in _revision_levels(revision, total_levels, fallback_level):
                tune_notes_by_level.setdefault(level_index, []).append(revision["delta"])
        for level_index, notes in sorted(tune_notes_by_level.items()):
            print(f"[Playtest] Tuning level {level_index + 1}: {notes}")

    if not rebuilt_assets and not tune_notes_by_level:
        print("[Playtest] No valid revisions remained after validation - stopping.")
        return True

    # Re-generated assets can receive new filenames, so every level that
    # references them must be rebuilt. Pure tuning touches only its targets.
    levels_to_build = list(range(total_levels)) if rebuilt_assets else sorted(tune_notes_by_level)
    target_set = set(levels_to_build)
    state["director_history"] = [
        item for item in (state.get("director_history") or []) if item.get("level") not in target_set
    ]
    if not run_coder_qa(state, levels_to_build, tune_notes_by_level):
        print("[Playtest] Revised build did not pass QA; stopping the playtest loop.")
        return True
    return False


def playtest_loop(state: GraphState) -> None:
    for cycle in range(1, MAX_PLAYTEST_CYCLES + 1):
        print(f"\n=== Playtest cycle {cycle}/{MAX_PLAYTEST_CYCLES} ===")
        if state.get("screenshot_path"):
            print(f"Screenshot (check before launching): {state['screenshot_path']}")
        if state.get("gameplay_video_path"):
            print(f"Gameplay video: {state['gameplay_video_path']}")
        for note in state.get("vision_notes") or []:
            print(f"Heads-up from vision QA: {note}")
        for note in state.get("video_notes") or []:
            print(f"Heads-up from video QA: {note}")
        print(f'Play the build:  "{GODOT_EXE}" --path {state["godot_project_path"]}')

        answers = capture_playtest_feedback()
        if answers["ship_or_fix"].lower() == "ship":
            print("[Playtest] Shipped by the human. Done.")
            return

        level_scripts = _read_level_scripts(state)
        revision_doc = interpret_feedback(answers, state["design_doc"], level_scripts)
        if apply_revision_doc(state, revision_doc):
            return

    print(
        f"[Playtest] {MAX_PLAYTEST_CYCLES} cycles did not converge. A design still "
        "wrong after three human passes has a wrong design, not wrong numbers - "
        "ship as-is or re-roll the design with a fresh prompt."
    )
