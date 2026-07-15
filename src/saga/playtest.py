"""Playtest loop driver - runs after the pipeline produces a QA-passed build.

Deliberately a plain CLI loop around the agent functions rather than graph
nodes: a blocking input() inside a LangGraph node would couple graph
execution to a live terminal. When a UI lands, this is the seam where
LangGraph's interrupt() + checkpointer replaces stdin.

Routing (cheapest first, mirroring the Interpreter's cost order):
- tune       -> Coder's tune path (surgical numeric edits to Main.gd)
- reasset    -> field updated in the design doc, Asset Maker and/or Audio
                Agent regenerate, then a fresh Coder+QA pass
- redesign   -> field feedback appended to the user prompt, full rebuild
                from the Game Designer down
- out_of_scope -> printed honestly, never acted on
"""

from pathlib import Path

from saga.agents.asset_maker import asset_maker
from saga.agents.audio_agent import audio_agent
from saga.agents.coder import PROJECT_DIR, coder
from saga.agents.game_designer import game_designer
from saga.agents.playtest_feedback import (
    MAX_PLAYTEST_CYCLES,
    capture_playtest_feedback,
    interpret_feedback,
)
from saga.agents.qa_agent import qa_agent
from saga.graph import MAX_RETRIES
from saga.state import GraphState

GODOT_EXE = "D:\\Godot\\Godot_v4.7-stable_win64_console.exe"


def run_coder_qa(state: GraphState) -> None:
    """The same per-level Coder<->QA loop the graph runs, callable standalone:
    each of the design doc's levels is generated and verified in turn, with a
    fresh retry budget per level."""
    total_levels = len((state.get("design_doc") or {}).get("levels") or [None])
    if not state.get("current_level"):
        state["current_level"] = 0
    while True:
        state.update(coder(state))
        state.update(qa_agent(state))
        if state.get("qa_passed"):
            if (state.get("current_level") or 0) + 1 < total_levels:
                state["current_level"] = (state.get("current_level") or 0) + 1
                state["qa_errors"] = None
                state["retry_count"] = 0
                continue
            return
        if (state.get("retry_count") or 0) >= MAX_RETRIES:
            print(f"[Playtest] QA failed after MAX_RETRIES={MAX_RETRIES}: {state.get('qa_errors')}")
            return


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
        state["qa_errors"] = None
        state["retry_count"] = 0
        run_coder_qa(state)
        return False

    reassets = [r for r in actionable if r["route"] == "reasset"]
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
        if regen_audio:
            state.update(audio_agent(state))

    tunes = [r for r in actionable if r["route"] == "tune"]
    if tunes:
        state["tune_notes"] = [r["delta"] for r in tunes]
        print(f"[Playtest] Tuning: {state['tune_notes']}")

    state["qa_errors"] = None
    state["retry_count"] = 0
    run_coder_qa(state)
    return False


def playtest_loop(state: GraphState) -> None:
    for cycle in range(1, MAX_PLAYTEST_CYCLES + 1):
        print(f"\n=== Playtest cycle {cycle}/{MAX_PLAYTEST_CYCLES} ===")
        if state.get("screenshot_path"):
            print(f"Screenshot (check before launching): {state['screenshot_path']}")
        for note in state.get("vision_notes") or []:
            print(f"Heads-up from vision QA: {note}")
        print(f'Play the build:  "{GODOT_EXE}" --path {state["godot_project_path"]}')

        answers = capture_playtest_feedback()
        if answers["ship_or_fix"].lower() == "ship":
            print("[Playtest] Shipped by the human. Done.")
            return

        main_gd = (PROJECT_DIR / "Main.gd").read_text(encoding="utf-8")
        revision_doc = interpret_feedback(answers, state["design_doc"], main_gd)
        if apply_revision_doc(state, revision_doc):
            return

    print(
        f"[Playtest] {MAX_PLAYTEST_CYCLES} cycles did not converge. A design still "
        "wrong after three human passes has a wrong design, not wrong numbers - "
        "ship as-is or re-roll the design with a fresh prompt."
    )
