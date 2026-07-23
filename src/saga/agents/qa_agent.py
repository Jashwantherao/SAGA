"""QA agent - runs the generated Godot project headlessly and checks for errors.

Two checks, cheapest first: import assets, then an actual bounded headless
run of the scene. (There used to be a parse-only --check-only pass between
them, but it cannot see autoload singletons like Sfx, so a correct script
that calls an autoload fails it - the scene run catches real compile errors
anyway, since a broken script fails to load.) After both pass, a
non-blocking windowed pass captures a screenshot (via the harness-owned
screenshot.gd autoload) so a human - or later, a vision model - can check
the build's look without launching it. The screenshot is a lens, not a
gate: its failure never fails QA. If a local vision model is available via
Ollama, it reviews the screenshot too (is the hero visible? does anything
look broken?) - also non-gating, since 7B vision verdicts are too noisy to
burn Coder retries on, but its findings are surfaced as vision_notes for
the human and the playtest loop.
"""

import json
import os
import re
import subprocess
from pathlib import Path

from saga.state import GraphState

GODOT_EXE = "D:\\Godot\\Godot_v4.7-stable_win64_console.exe"
VISION_MODEL = os.environ.get("SAGA_VISION_MODEL", "gemma4:12b")

ERROR_PATTERNS = re.compile(
    r"SCRIPT ERROR|Parse Error|Invalid call|Nonexistent function|ERROR:",
    re.IGNORECASE,
)

# Godot's forced `--quit-after` shutdown doesn't wait for the AudioServer to
# release an autoplaying stream, so any project with BGM prints these on exit
# regardless of whether the generated GDScript is correct. Real GDScript bugs
# never produce this specific shutdown-order noise, so it's safe to ignore.
BENIGN_EXIT_NOISE = re.compile(
    r"resources? still in use at exit|Leaked instance:|ObjectDB instances were leaked at exit|"
    r"Orphan StringName|unclaimed string names at exit|RID allocations of type",
    re.IGNORECASE,
)


def _run(args: list[str], cwd: str | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [GODOT_EXE, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _find_errors(output: str) -> list[str]:
    """Collect error lines, deduplicated and capped: a per-frame runtime bug
    repeats identically hundreds of times, which would otherwise flood the
    Coder's fix prompt and break the model's output format. The following
    'at: ...' line is attached when present - it carries the script location
    the model needs to find the bug."""
    lines = output.splitlines()
    found = []
    for i, line in enumerate(lines):
        if ERROR_PATTERNS.search(line) and not BENIGN_EXIT_NOISE.search(line):
            entry = line.strip()
            if i + 1 < len(lines) and lines[i + 1].lstrip().startswith("at:"):
                entry += f" ({lines[i + 1].strip()})"
            entry = entry[:300]
            if entry not in found:
                found.append(entry)
            if len(found) >= 10:
                break
    return found


def _vision_review(screenshot_path: str, design_doc) -> list[str]:
    """Ask a local vision model whether the screenshot looks like a working
    game. Non-gating: any failure (model not pulled, bad JSON) returns []."""
    try:
        import ollama

        hero = (design_doc or {}).get("hero_description", "the player character")
        title = (design_doc or {}).get("title", "the game")
        prompt = (
            f"This is a screenshot of an auto-generated 2D game called {title!r} "
            f"taken about one second into gameplay. The hero is: {hero}. "
            "Review it for visual defects and answer ONLY with JSON matching: "
            '{"hero_visible": bool, "background_fills_screen": bool, '
            '"ui_text_readable": bool, "looks_broken": string or null}. '
            "Set looks_broken to a short description if any sprite is "
            "gigantic, cut off, a plain opaque rectangle, or floating "
            "somewhere nonsensical - otherwise null."
        )
        resp = ollama.chat(
            model=VISION_MODEL,
            format="json",
            messages=[{"role": "user", "content": prompt, "images": [screenshot_path]}],
        )
        data = json.loads(resp["message"]["content"])
        findings = []
        if data.get("hero_visible") is False:
            findings.append("Vision: hero sprite not clearly visible")
        if data.get("background_fills_screen") is False:
            findings.append("Vision: background does not fill the screen")
        if data.get("ui_text_readable") is False:
            findings.append("Vision: UI text not readable")
        if data.get("looks_broken"):
            findings.append(f"Vision: {data['looks_broken']}")
        return findings
    except Exception as e:
        print(f"[QA Agent] Vision review skipped ({type(e).__name__}: {e})")
        return []


def qa_agent(state: GraphState) -> GraphState:
    project_dir = state["godot_project_path"]
    retry_count = state.get("retry_count") or 0
    current_level = state.get("current_level") or 0
    scene = f"res://Level_{current_level}.tscn"

    # 1. Import assets
    import_result = _run(["--headless", "--path", project_dir, "--import", "--quit"])
    import_errors = _find_errors(import_result.stdout + import_result.stderr)
    if import_result.returncode != 0 or import_errors:
        print(f"[QA Agent] FAILED at import step: {import_errors or 'non-zero exit'}")
        return {"qa_passed": False, "qa_errors": import_errors or ["Import step failed"], "retry_count": retry_count + 1}

    # 2. Actually run THIS level's scene for a bounded number of frames -
    # this also catches compile errors (a broken script fails to load),
    # which is why no separate --check-only pass is needed (or safe: it
    # can't see autoloads).
    run_result = _run(["--headless", "--path", project_dir, scene, "--quit-after", "120"], timeout=30)
    run_errors = _find_errors(run_result.stdout + run_result.stderr)
    if run_result.returncode != 0 or run_errors:
        print(f"[QA Agent] FAILED at scene run: {run_errors or f'exit code {run_result.returncode}'}")
        return {
            "qa_passed": False,
            "qa_errors": run_errors or [f"Scene run exited with code {run_result.returncode}"],
            "retry_count": retry_count + 1,
        }

    # 4. Non-blocking windowed screenshot pass (a window flashes for ~1.5s).
    # screenshot.gd saves frame 60 to res://screenshot.png; it no-ops in the
    # headless runs above.
    screenshot_path = None
    screenshot_file = Path(project_dir) / f"screenshot_Level{current_level}.png"
    try:
        screenshot_file.unlink(missing_ok=True)  # never report a stale frame
        _run(["--path", project_dir, scene, "--quit-after", "90"], timeout=30)
        if screenshot_file.exists():
            screenshot_path = str(screenshot_file)
            print(f"[QA Agent] Screenshot captured -> {screenshot_path}")
        else:
            print("[QA Agent] Screenshot pass produced no image (non-blocking)")
    except Exception as e:
        print(f"[QA Agent] Screenshot pass failed (non-blocking): {e}")

    # 5. Local vision review of the screenshot - also a lens, not a gate.
    vision_notes = []
    if screenshot_path:
        vision_notes = _vision_review(screenshot_path, state.get("design_doc"))
        for note in vision_notes:
            print(f"[QA Agent] {note}")

    print("[QA Agent] PASSED - scene ran headlessly with no errors")
    return {
        "qa_passed": True,
        "qa_errors": [],
        "screenshot_path": screenshot_path,
        "vision_notes": vision_notes,
    }
