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

from saga.balance import check_level
from saga.corpus import record_level
from saga.state import GraphState

GODOT_EXE = "D:\\Godot\\Godot_v4.7-stable_win64_console.exe"
VISION_MODEL = os.environ.get("SAGA_VISION_MODEL", "gemma4:12b")

# A hosted vision model is enough better than a local 7-12B one to gate on.
# Measured against a real build whose platforms were untextured grey
# rectangles: the local model never mentioned them, while three hosted models
# named them as placeholder art unprompted. nemotron-3-nano-omni was the pick
# at ~3s with no false positives; llama-3.2-90b-vision agreed but took ~16s,
# and nemotron-nano-12b-v2-vl caught the real defect but also invented text
# clipping that was not in the image - which is disqualifying for a gate,
# since a false positive spends a Coder retry on nothing.
VISION_BACKEND = os.environ.get("SAGA_VISION_BACKEND", "local")
VISION_REMOTE_MODEL = os.environ.get(
    "SAGA_VISION_REMOTE_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
)
VISION_BASE_URL = os.environ.get("SAGA_VISION_BASE_URL", "https://integrate.api.nvidia.com/v1")
VISION_KEY_ENV = os.environ.get("SAGA_VISION_KEY_ENV", "NVIDIA_API_KEY")
# Free tiers have been measured hanging for minutes on models they list.
VISION_TIMEOUT = float(os.environ.get("SAGA_VISION_TIMEOUT", "90"))

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


def _vision_prompt(design_doc) -> str:
    hero = (design_doc or {}).get("hero_description", "the player character")
    title = (design_doc or {}).get("title", "the game")
    return (
        f"This is a screenshot of an auto-generated 2D game called {title!r} "
        f"taken about one second into gameplay, at 1024x576. The hero is: "
        f"{hero}. Report only defects you can actually see - do not guess or "
        "invent problems. Answer ONLY with JSON matching: "
        '{"hero_visible": bool, "background_fills_screen": bool, '
        '"text_clipped": bool, "placeholder_art": string or null, '
        '"looks_broken": string or null}. '
        "Set text_clipped true only if some text runs off the screen edge or "
        "is hidden behind another element. Set placeholder_art to a short "
        "description if plain untextured coloured rectangles are standing in "
        "for game objects, otherwise null. Set looks_broken if a sprite is "
        "gigantic, cut off, or floating somewhere nonsensical, otherwise null."
    )


def _vision_raw(screenshot_path: str, design_doc) -> dict:
    """Run the configured vision backend and return the parsed verdict."""
    prompt = _vision_prompt(design_doc)

    if VISION_BACKEND in ("nvidia", "remote", "openai"):
        import base64

        from saga.llm import chat

        b64 = base64.b64encode(Path(screenshot_path).read_bytes()).decode()
        text = chat(
            [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            model=VISION_REMOTE_MODEL,
            max_tokens=4000,
            base_url=VISION_BASE_URL,
            key_env=VISION_KEY_ENV,
            timeout=VISION_TIMEOUT,
        )
        # No JSON mode on every hosted VLM, so salvage the object from prose.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0) if match else text)

    import ollama

    resp = ollama.chat(
        model=VISION_MODEL,
        format="json",
        messages=[{"role": "user", "content": prompt, "images": [screenshot_path]}],
    )
    return json.loads(resp["message"]["content"])


def _vision_review(screenshot_path: str, design_doc) -> tuple[list[str], list[str]]:
    """Review the screenshot and split findings by who can actually fix them.

    Returns (gating, advisory). Gating findings are defects the Coder can
    repair by changing code - a hero that never made it on screen, text
    running off the edge, a background not stretched to fill. Advisory
    findings are real but not the Coder's to fix: placeholder art means the
    Asset Maker never produced a suitable sprite, so failing QA over it would
    spend retries on a problem no rewrite can solve.

    Any failure (model unavailable, timeout, unparseable reply) returns no
    findings at all - the vision pass must never fail a build by breaking.
    """
    try:
        data = _vision_raw(screenshot_path, design_doc)
    except Exception as e:
        print(f"[QA Agent] Vision review skipped ({type(e).__name__}: {e})")
        return [], []

    gating, advisory = [], []
    if data.get("hero_visible") is False:
        gating.append(
            "Visual defect: the hero sprite is not visible on screen. Make sure it is "
            "added to the tree, positioned inside the 1024x576 viewport, and not "
            "scaled to zero or hidden behind the background."
        )
    if data.get("background_fills_screen") is False:
        gating.append(
            "Visual defect: the background does not fill the screen. A background "
            "Sprite2D needs centered = false and position = Vector2.ZERO."
        )
    if data.get("text_clipped") is True:
        gating.append(
            "Visual defect: on-screen text is clipped or hidden behind another "
            "element. Reposition the labels so every one is fully readable."
        )
    if data.get("looks_broken"):
        gating.append(f"Visual defect: {data['looks_broken']}")
    if data.get("placeholder_art"):
        advisory.append(f"Vision (advisory): {data['placeholder_art']}")
    return gating, advisory


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

    # 2b. Actually play it. A scene that runs without errors can still be
    # completely inert - a hero that cannot move, or an objective that never
    # changes, passes every check above. The Autoplay autoload holds each
    # arrow key in turn and reports whether anything moved and whether the
    # status label ever said anything different.
    play = _run(
        ["--headless", "--path", project_dir, scene, "--quit-after", "600", "--", "--autoplay"],
        timeout=60,
    )
    play_out = play.stdout + play.stderr
    verdict = re.search(
        r"\[AUTOPLAY\] idle_rate=([\d.]+) input_rate=([\d.]+) label_states=(\d+)", play_out
    )
    if verdict:
        idle_rate, input_rate = float(verdict.group(1)), float(verdict.group(2))
        label_states = int(verdict.group(3))
        # Held keys must move the world markedly more than it moves on its own.
        # The ratio handles games with busy ambient motion; the absolute floor
        # handles still ones, where a ratio against nearly zero means nothing.
        # Measured on one real build and a copy of it with input disabled:
        # 4.28 vs 0.97 against an identical idle rate of ~0.89.
        moved = input_rate > max(idle_rate * 1.5, 0.5)
        print(
            f"[QA Agent] Autoplay: idle={idle_rate:.2f} input={input_rate:.2f} "
            f"responsive={moved} label_states={label_states}"
        )
        play_errors = []
        if not moved:
            play_errors.append(
                "Playability: holding each arrow key in turn moved nothing on screen. "
                "The player must move in response to ui_left/ui_right/ui_up/ui_down "
                "while state is 'playing'."
            )
        # Label change is NOT a gate. It assumes holding a direction advances
        # the game, which is true of timers, drains and touch-collection but
        # false of any puzzle: an ordered-switch level only updates its label
        # when the right switch is hit in the right order, which random input
        # will not achieve. Measured on a real build that was working fine.
        if label_states <= 1:
            print(
                "[QA Agent] Autoplay note (advisory): the status label did not change "
                "while arrow keys were held. Expected for a puzzle whose progress needs "
                "correct input; a problem for anything driven by a timer or resource."
            )
        if play_errors and retry_count == 0:
            print(f"[QA Agent] FAILED on {len(play_errors)} playability defect(s) - requesting a fix")
            return {"qa_passed": False, "qa_errors": play_errors, "retry_count": retry_count + 1}
        for e in play_errors:
            print(f"[QA Agent] WARNING (unresolved): {e}")
    else:
        # Never fail a build because the probe itself did not report - it is a
        # check, not a requirement, and a silent probe means a broken probe.
        print("[QA Agent] Autoplay produced no verdict (non-blocking)")

    # 3. Balance check. The script runs, but that says nothing about whether
    # its challenge is survivable - a drain that outpaces every refill, or a
    # pursuer faster than the player, compiles perfectly and is unwinnable.
    # Purely static and instant, so it runs before the screenshot pass.
    # Gated on the first attempt only, for the same reason as the vision
    # review: repeating a verdict the Coder failed to satisfy would spend the
    # budget real crashes need.
    script_file = Path(project_dir) / f"Level_{current_level}.gd"
    balance_notes = []
    if script_file.exists():
        template = (state.get("design_doc") or {}).get("mechanic_template", "")
        bal_gating, balance_notes = check_level(script_file.read_text(encoding="utf-8"), template)
        for note in bal_gating + balance_notes:
            print(f"[QA Agent] {note}")
        if bal_gating and retry_count == 0:
            print(f"[QA Agent] FAILED on {len(bal_gating)} balance defect(s) - requesting a fix")
            return {
                "qa_passed": False,
                "qa_errors": bal_gating,
                "retry_count": retry_count + 1,
                "balance_notes": balance_notes,
            }
        if bal_gating:
            print(
                f"[QA Agent] WARNING: {len(bal_gating)} balance defect(s) UNRESOLVED "
                f"after a fix attempt - this level may not be winnable:"
            )
            for note in bal_gating:
                print(f"[QA Agent]   - {note}")
            balance_notes = bal_gating + balance_notes

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

    # 5. Vision review. Code-fixable defects gate; everything else is a lens.
    #
    # Gating is deliberately limited to the first attempt. A screenshot verdict
    # is a judgement rather than a compiler error, so if one correction round
    # does not satisfy it the honest move is to report and move on - looping
    # would spend the retry budget that real crashes need, and the model may
    # simply be wrong. This caps vision at one retry per level.
    vision_notes = []
    if screenshot_path:
        gating, advisory = _vision_review(screenshot_path, state.get("design_doc"))
        vision_notes = gating + advisory
        for note in vision_notes:
            print(f"[QA Agent] {note}")
        if gating and retry_count == 0:
            print(f"[QA Agent] FAILED on {len(gating)} visual defect(s) - requesting a fix")
            return {
                "qa_passed": False,
                "qa_errors": gating,
                "retry_count": retry_count + 1,
                "screenshot_path": screenshot_path,
                "vision_notes": vision_notes,
            }
        if gating:
            # The cap has been spent and the defect is still there. Passing is
            # the lesser evil - looping would burn the budget real crashes need
            # - but reporting a clean PASS is how a visibly broken build
            # reaches a human unremarked, so say so loudly instead.
            print(
                f"[QA Agent] WARNING: {len(gating)} visual defect(s) UNRESOLVED after "
                f"a fix attempt - passing so the run can continue, but this build "
                f"has a known problem:"
            )
            for note in gating:
                print(f"[QA Agent]   - {note}")

    # This is the only point in the pipeline where a script is known-good
    # (compiled, ran, satisfied its template contract) - so it's where the
    # training corpus gets its verified pairs.
    record_level(
        prompt=state.get("coder_prompt"),
        script=script_file.read_text(encoding="utf-8") if script_file.exists() else "",
        template=(state.get("design_doc") or {}).get("mechanic_template", "unknown"),
        model=state.get("coder_model"),
        level_index=current_level,
        retry_count=retry_count,
        design_doc=state.get("design_doc"),
        vision_notes=vision_notes,
    )

    print("[QA Agent] PASSED - scene ran headlessly with no errors")
    return {
        "qa_passed": True,
        "qa_errors": [],
        "screenshot_path": screenshot_path,
        "vision_notes": vision_notes,
        "balance_notes": balance_notes,
    }
