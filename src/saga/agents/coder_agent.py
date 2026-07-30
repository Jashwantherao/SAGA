"""Coder as an agent that can look at its own work, rather than one blind call.

The non-agentic Coder emits a whole level from a single completion and never
sees the result. Everything it learns arrives second-hand: a filtered error
string, one retry at a time, with no memory between attempts and no way to
inspect anything. It cannot read the level it wrote for the previous level of
the same game, cannot run Godot, cannot look at a screenshot, and cannot change
three lines - a one-character fix costs a full regeneration, which re-rolls
every other decision in the file along with it.

None of that is a model limitation. It is the harness handing a capable model a
blindfold. Given tools, the same model writes, runs, reads the real error, looks
at the rendered frame and fixes what it actually sees, which is what separates a
build that merely compiles from one that is playable.

QA still runs afterwards and independently. The agent self-corrects; QA remains
the impartial gate, because a model marking its own homework is exactly the
failure this project keeps rediscovering.
"""

import json
import os
import re
import subprocess
from pathlib import Path

from saga.state import GraphState

MAX_TURNS = int(os.environ.get("SAGA_AGENT_MAX_TURNS", "14"))
MODEL = os.environ.get("SAGA_CODER_REMOTE_MODEL", "deepseek-v4-pro")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file from the Godot project - a previous level of this same "
                "game, or a harness autoload like anim.gd or game.gd to check an API "
                "before calling it."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "e.g. 'Level_0.gd' or 'anim.gd'"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files in the Godot project, including every generated asset.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_level",
            "description": (
                "Write this level's complete GDScript. Overwrites the previous "
                "version. Call test_level afterwards to find out whether it works."
            ),
            "parameters": {
                "type": "object",
                "properties": {"gdscript": {"type": "string", "description": "The complete script, no code fence"}},
                "required": ["gdscript"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "test_level",
            "description": (
                "Run the level in Godot headlessly and play it: reports compile and "
                "runtime errors, and whether holding the arrow keys actually moves "
                "the world compared with leaving it alone."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "look",
            "description": (
                "Render the level and have a vision model describe the frame. Use it "
                "to check the game LOOKS right - sprites placed sensibly, nothing "
                "gigantic or off-screen, text readable - which errors never reveal."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Declare the level done. Only call this after test_level reports no errors.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string", "description": "One line on what you built"}},
                "required": ["summary"],
            },
        },
    },
]

AGENT_SYSTEM_SUFFIX = (
    "\n\nYou are working as an agent with tools, not writing one file blind. "
    "Write the level, run it, and fix what you find - do not stop at the first "
    "version that compiles. A level that runs is the floor, not the goal.\n\n"
    "Work in this order: write_level, then test_level, then fix any errors and "
    "test again. Once it runs clean, call look at least once - errors cannot "
    "tell you that a sprite is gigantic, that the hero is off-screen, or that "
    "two labels overlap, and those are the defects that make a build feel "
    "unfinished. Fix what you see and look again. Only then call finish.\n\n"
    "read_file is there so you do not have to guess: check a harness autoload's "
    "real API before calling it, or read the previous level of this same game to "
    "keep the feel consistent. Prefer rewriting the whole script when you fix "
    "something - write_level replaces the file - but change only what needs "
    "changing and keep everything that already worked."
)


def _diff_summary(before: str, after: str) -> tuple[int, int]:
    """Lines added and removed between the draft and the polished version."""
    import difflib

    delta = list(difflib.ndiff(before.splitlines(), after.splitlines()))
    return (
        sum(1 for d in delta if d.startswith("+ ")),
        sum(1 for d in delta if d.startswith("- ")),
    )


def _safe_path(project_dir: Path, raw: str) -> Path | None:
    """Resolve a model-supplied path inside the project, or refuse it.

    The path comes from a language model, so it is untrusted input: without this
    a hallucinated '../../.env' would be read straight back into the context.
    """
    try:
        target = (project_dir / raw.lstrip("/\\")).resolve()
        target.relative_to(project_dir.resolve())
        return target
    except (ValueError, OSError):
        return None


def _test_level(project_dir: Path, level: int) -> str:
    from saga.agents.qa_agent import GODOT_EXE, _find_errors

    scene = f"res://Level_{level}.tscn"
    try:
        subprocess.run(
            [GODOT_EXE, "--headless", "--path", str(project_dir), "--import", "--quit"],
            capture_output=True, text=True, timeout=120,
        )
        run = subprocess.run(
            [GODOT_EXE, "--headless", "--path", str(project_dir), scene,
             "--quit-after", "900", "--", "--autoplay"],
            capture_output=True, text=True, timeout=90,
        )
    except subprocess.TimeoutExpired:
        return "The level timed out. It is probably stuck in an infinite loop."

    out = run.stdout + run.stderr
    errors = _find_errors(out)
    if errors:
        return "Errors:\n" + "\n".join(f"- {e}" for e in errors)

    verdict = re.search(r"\[AUTOPLAY\] idle_rate=([\d.]+) input_rate=([\d.]+) label_states=(\d+)", out)
    if not verdict:
        return "No errors. (The autoplay probe did not report, so responsiveness is unknown.)"
    idle, inp, labels = float(verdict.group(1)), float(verdict.group(2)), int(verdict.group(3))
    responsive = inp > max(idle * 1.5, 0.5)
    lines = [f"No errors. Autoplay: idle_rate={idle:.2f} input_rate={inp:.2f} label_states={labels}."]
    if responsive:
        lines.append("Holding the arrow keys moves the world, so the player is connected to the game.")
    else:
        lines.append(
            "PROBLEM: holding the arrow keys barely moved anything beyond what moves on its "
            "own. The player is not responding to input - check that movement is applied "
            "while state is 'playing'."
        )
    if labels <= 1:
        lines.append(
            "The status label never changed. Expected if progress needs correct input "
            "(a puzzle); a bug if it should show a timer or a resource."
        )
    return "\n".join(lines)


def _look(project_dir: Path, level: int, design_doc: dict) -> str:
    from saga.agents.qa_agent import GODOT_EXE, VISION_BASE_URL, VISION_KEY_ENV, VISION_REMOTE_MODEL

    shot = project_dir / f"screenshot_Level{level}.png"
    shot.unlink(missing_ok=True)
    try:
        subprocess.run(
            [GODOT_EXE, "--path", str(project_dir), f"res://Level_{level}.tscn", "--quit-after", "90"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        pass
    if not shot.exists():
        return "Could not capture a frame."

    try:
        import base64

        from saga.llm import chat

        b64 = base64.b64encode(shot.read_bytes()).decode()
        return chat(
            [{"role": "user", "content": [
                {"type": "text", "text": (
                    f"This is a frame from a 2D game called "
                    f"{design_doc.get('title', 'a game')!r}, at 1024x576. The hero is: "
                    f"{design_doc.get('hero_description', 'the player')}. Describe what "
                    "you actually see - what is on screen and where. Then list any "
                    "visual defects: sprites far too large or small, anything cut off "
                    "or off-screen, overlapping or unreadable text, objects floating "
                    "somewhere nonsensical, or plain untextured rectangles standing in "
                    "for game objects. Report only what is visible; do not invent "
                    "problems."
                )},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            model=VISION_REMOTE_MODEL, max_tokens=3000,
            base_url=VISION_BASE_URL, key_env=VISION_KEY_ENV, timeout=90,
        )
    except Exception as e:
        return f"Could not review the frame ({type(e).__name__}). Judge it from the code instead."


def coder_agent(state: GraphState) -> GraphState:
    """Polish one level by running it, looking at it, and revising.

    The one-shot Coder runs first and produces the draft. That is deliberate:
    it already carries the template few-shots, the contract checks, the Godot 4
    guard-rail and all the harness boilerplate, so it starts from a much better
    place than an agent improvising from nothing - and reusing it means the
    agentic path cannot silently diverge from the non-agentic one. The agent's
    job is the part the one-shot Coder structurally cannot do: see the result
    and act on it.
    """
    from saga.agents.coder import PROJECT_DIR, coder
    from saga.llm import chat_raw

    level = state.get("current_level") or 0
    design_doc = state["design_doc"]
    project_dir = Path(PROJECT_DIR)

    draft = coder(state)
    draft_script = (project_dir / f"Level_{level}.gd").read_text(encoding="utf-8")
    print(f"[Coder/agent] Draft written ({len(draft_script.splitlines())} lines); polishing.")

    messages = [
        {"role": "system", "content": (
            "You are the Coder agent in an automated game studio, polishing a level "
            "of a 2D Godot 4 game you have just written." + AGENT_SYSTEM_SUFFIX
        )},
        {"role": "user", "content": (
            f"Game: {design_doc.get('title')} ({design_doc.get('genre')}) - "
            f"{design_doc.get('story_premise', '')}\n"
            f"This is level {level + 1}: {(design_doc.get('levels') or [{}])[level].get('name', '')} - "
            f"{(design_doc.get('levels') or [{}])[level].get('description', '')}\n"
            f"Win condition: {design_doc.get('win_condition')}\n"
            f"Lose condition: {design_doc.get('lose_condition')}\n\n"
            f"The draft is already written to Level_{level}.gd:\n"
            f"```gdscript\n{draft_script}\n```\n\n"
            "Test it, look at it, and fix what is actually wrong. Keep everything "
            "that already works."
        )},
    ]

    # The draft counts: if the agent achieves nothing, the level is still the
    # one-shot Coder's output rather than an empty file.
    wrote_anything = True
    for turn in range(MAX_TURNS):
        message = chat_raw(messages, model=MODEL, tools=TOOLS, max_tokens=32000)
        messages.append(message.model_dump(exclude_none=True))

        if not message.tool_calls:
            break

        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "write_level":
                script = args.get("gdscript") or ""
                script = re.sub(r"^```(?:gdscript|gd)?\n|```$", "", script.strip())
                (project_dir / f"Level_{level}.gd").write_text(script, encoding="utf-8")
                wrote_anything = True
                result = f"Written, {len(script.splitlines())} lines."
            elif name == "test_level":
                result = _test_level(project_dir, level)
            elif name == "look":
                result = _look(project_dir, level, design_doc)
            elif name == "read_file":
                target = _safe_path(project_dir, args.get("path", ""))
                if target is None or not target.is_file():
                    result = f"No such file in the project: {args.get('path')!r}"
                else:
                    result = target.read_text(encoding="utf-8", errors="replace")[:20000]
            elif name == "list_files":
                names = sorted(p.name for p in project_dir.iterdir() if p.is_file())
                assets = sorted(p.name for p in (project_dir / "assets").glob("*") if p.suffix != ".import")
                result = "Project files:\n" + "\n".join(names) + "\n\nAssets:\n" + "\n".join(assets)
            elif name == "finish":
                print(f"[Coder/agent] Level {level + 1} done in {turn + 1} turns: {args.get('summary', '')}")
                result = "Acknowledged."
            else:
                result = f"Unknown tool {name!r}."

            print(f"[Coder/agent] turn {turn + 1}: {name}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        if any(c.function.name == "finish" for c in message.tool_calls):
            break
    else:
        print(f"[Coder/agent] Hit the {MAX_TURNS}-turn budget; keeping the last written version.")

    final = (project_dir / f"Level_{level}.gd").read_text(encoding="utf-8")
    # An agent loop costs many times a single completion, so what it actually
    # changed has to be visible rather than assumed. Line counts are not
    # evidence; the diff is. The draft is kept next to the level so a run can
    # be judged after the fact instead of on faith.
    (project_dir / f"Level_{level}.draft.gd").write_text(draft_script, encoding="utf-8")
    added, removed = _diff_summary(draft_script, final)
    print(
        f"[Coder/agent] Level {level + 1}: {len(draft_script.splitlines())} -> "
        f"{len(final.splitlines())} lines, +{added}/-{removed} changed "
        f"(draft kept as Level_{level}.draft.gd)"
    )
    # Carry the draft's own return through so the corpus still records the
    # brief the level actually came from, with the model tagged as agentic.
    return {**draft, "coder_model": f"{MODEL} (agentic)"}
