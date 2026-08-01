"""Human review of a level before the rest of the game is built on top of it.

The existing playtest loop runs after the whole pipeline finishes, which is too
late to stop the expensive mistake: a mechanic that is wrong in level 1 gets
faithfully reproduced in every level after it, and the human only sees it once
all of them exist. Observed directly - a herding game whose creatures fled from
any distance and never settled was built three times before anyone played it.

So this gate sits between "level N passed QA" and "start level N+1". It launches
the level, takes one line of typed reaction, and turns that into concrete
revisions routed back into the Coder's tune path for the SAME level.

Its whole value depends on being cheap. A gate that costs twenty minutes of
debugging makes SAGA a slow way to write a game by hand; the target is under a
minute - play briefly, type what is wrong in plain words, press enter. Turning
a vague sentence into instructions the Coder can act on is this module's job,
not the human's.
"""

import json
import subprocess

from saga.config import settings
from saga.state import GraphState

# Vague reactions are the norm from a real playtester ("feels floaty", "the cat
# just slides"), and the tune prompt needs literal changes. One cheap call
# converts one into the other; the human should never have to phrase a diff.
INTERPRET_SYSTEM_PROMPT = (
    "You turn a playtester's reaction to a 2D Godot game into concrete "
    "revisions for the programmer who wrote it. You are given the level's "
    "GDScript and one line of feedback. Reply with ONLY a JSON object: "
    '{"revisions": ["...", "..."]}. Each revision must be a single specific '
    "instruction naming what to change and, where it is a number, the "
    "variable and its new value - the script's tuning variables are declared "
    "at the top. Prefer the smallest change that addresses the complaint. "
    "Give at most four revisions, and none at all (an empty array) if the "
    "feedback is praise or does not describe a problem. Never restate the "
    "feedback; translate it into an action."
)


def _launch(project_dir: str, level_index: int) -> "subprocess.Popen | None":
    """Open the level so it can actually be played. Never fatal - a human who
    cannot launch it can still type a reaction from the screenshot.

    Godot's output is discarded rather than inherited. It prints benign
    shutdown noise on every exit ("ObjectDB instances were leaked", "resources
    still in use"), and inheriting the terminal dumps that on top of the
    feedback prompt at exactly the moment the human is trying to answer it.
    """
    try:
        return subprocess.Popen(
            [
                settings.godot_exe,
                "--path",
                project_dir,
                f"res://Level_{level_index}.tscn",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[Gate] Could not launch the level ({type(e).__name__}: {e}) - play it manually.")
        return None


def _interpret(feedback: str, script: str) -> list[str]:
    """Convert one line of human reaction into revisions the Coder can apply."""
    try:
        from saga.llm import chat

        raw = chat(
            [
                {"role": "system", "content": INTERPRET_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Level script:\n```gdscript\n{script}\n```\n\nPlaytester said: {feedback}\n",
                },
            ],
            model=settings.gate_model,
            json_mode=True,
            max_tokens=8000,
        )
        revisions = [r for r in (json.loads(raw).get("revisions") or []) if isinstance(r, str) and r.strip()]
        return revisions[:4]
    except Exception as e:
        # Falling back to the raw sentence is better than dropping it: the tune
        # prompt can often act on it directly, and losing a human's only note
        # to a parse error is the one outcome this gate cannot afford.
        print(f"[Gate] Could not interpret the feedback ({type(e).__name__}: {e}) - passing it through verbatim.")
        return [feedback]


def level_gate(state: GraphState) -> GraphState:
    """Show the human the level that just passed, and collect revisions.

    Returns tune_notes to send this level back through the Coder, or nothing to
    let the graph move on.
    """
    level_index = state.get("current_level") or 0
    project_dir = state.get("godot_project_path")
    total = len(((state.get("design_doc") or {}).get("levels")) or [None])

    print(f"\n{'=' * 62}")
    print(f"  Level {level_index + 1} of {total} passed QA. Play it before the rest is built.")
    for note in (
        (state.get("vision_notes") or [])
        + (state.get("balance_notes") or [])
        + (state.get("video_notes") or [])
    ):
        print(f"  note: {note}")
    print(f"{'=' * 62}")
    proc = _launch(project_dir, level_index) if project_dir else None
    if proc is not None:
        print("  Play it, then close the game window to leave your note.")
        try:
            # Waiting means the prompt appears on a clean terminal after play,
            # rather than behind a live game window. The timeout is only a
            # guard against a window left open and forgotten - a human still
            # playing is exactly what this gate is for, so it is generous.
            proc.wait(timeout=settings.gate_play_timeout)
        except subprocess.TimeoutExpired:
            print("  (still open - leaving it running)")
        except KeyboardInterrupt:
            proc.terminate()

    try:
        feedback = input("\nWhat's wrong with it? (blank = looks fine, carry on)\n> ").strip()
    except EOFError:
        # Non-interactive stdin: treat as approval rather than hanging a run.
        print("[Gate] No terminal attached - continuing without review.")
        return {}

    if not feedback:
        print("[Gate] Approved - building the next level.")
        return {}

    script_path = f"{project_dir}/Level_{level_index}.gd" if project_dir else None
    script = ""
    if script_path:
        try:
            with open(script_path, encoding="utf-8") as f:
                script = f.read()
        except OSError:
            pass

    revisions = _interpret(feedback, script)
    if not revisions:
        print("[Gate] Nothing actionable in that - building the next level.")
        return {}

    print(f"[Gate] Sending {len(revisions)} revision(s) back to the Coder:")
    for r in revisions:
        print(f"       - {r}")
    # A human revision gets a fresh retry budget: it is new work, not a
    # continuation of whatever the Coder was already struggling with.
    return {"tune_notes": revisions, "retry_count": 0}
