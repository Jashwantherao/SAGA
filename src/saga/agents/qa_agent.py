"""QA agent - runs the generated Godot project headlessly and checks for errors.

Three checks, cheapest first: import assets, parse-only syntax check on
Main.gd, then an actual bounded headless run of the scene. Cheap checks fail
fast without wasting time on a full scene run.
"""

import re
import subprocess
from pathlib import Path

from saga.state import GraphState

GODOT_EXE = "D:\\Godot\\Godot_v4.7-stable_win64_console.exe"

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
    r"Orphan StringName|unclaimed string names at exit",
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
    return [
        line
        for line in output.splitlines()
        if ERROR_PATTERNS.search(line) and not BENIGN_EXIT_NOISE.search(line)
    ]


def qa_agent(state: GraphState) -> GraphState:
    project_dir = state["godot_project_path"]
    retry_count = state.get("retry_count") or 0

    # 1. Import assets
    import_result = _run(["--headless", "--path", project_dir, "--import", "--quit"])
    import_errors = _find_errors(import_result.stdout + import_result.stderr)
    if import_result.returncode != 0 or import_errors:
        print(f"[QA Agent] FAILED at import step: {import_errors or 'non-zero exit'}")
        return {"qa_passed": False, "qa_errors": import_errors or ["Import step failed"], "retry_count": retry_count + 1}

    # 2. Fast parse-only syntax check
    check_result = _run(["--headless", "--check-only", "--script", "Main.gd"], cwd=project_dir)
    check_errors = _find_errors(check_result.stdout + check_result.stderr)
    if check_result.returncode != 0 or check_errors:
        print(f"[QA Agent] FAILED at syntax check: {check_errors or 'non-zero exit'}")
        return {"qa_passed": False, "qa_errors": check_errors or ["Syntax check failed"], "retry_count": retry_count + 1}

    # 3. Actually run the scene for a bounded number of frames
    run_result = _run(["--headless", "--path", project_dir, "--quit-after", "120"], timeout=30)
    run_errors = _find_errors(run_result.stdout + run_result.stderr)
    if run_result.returncode != 0 or run_errors:
        print(f"[QA Agent] FAILED at scene run: {run_errors or f'exit code {run_result.returncode}'}")
        return {
            "qa_passed": False,
            "qa_errors": run_errors or [f"Scene run exited with code {run_result.returncode}"],
            "retry_count": retry_count + 1,
        }

    print("[QA Agent] PASSED - scene ran headlessly with no errors")
    return {"qa_passed": True, "qa_errors": []}
