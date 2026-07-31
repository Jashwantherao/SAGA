"""Install and run the collectible-maze objective probe in a project copy.

This is intentionally a developer smoke tool, not part of the generation
pipeline. Point it at a disposable copy of a generated Godot project.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from saga.agents.coder import OBJECTIVE_PROBE_GD
from saga.agents.qa_agent import OBJECTIVE_VERDICT
from saga.config import settings


def install_probe(project_dir: Path) -> None:
    (project_dir / "objective_probe.gd").write_text(OBJECTIVE_PROBE_GD, encoding="utf-8")
    project_file = project_dir / "project.godot"
    config = project_file.read_text(encoding="utf-8")
    marker = 'Autoplay="*res://autoplay.gd"'
    addition = marker + '\nObjectiveProbe="*res://objective_probe.gd"'
    if "ObjectiveProbe=" not in config:
        if marker not in config:
            raise RuntimeError(f"Could not find Autoplay autoload in {project_file}")
        project_file.write_text(config.replace(marker, addition), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument(
        "--template",
        choices=("dot_maze", "maze_chase"),
        default="dot_maze",
    )
    args = parser.parse_args()

    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        parser.error(f"project directory does not exist: {project_dir}")
    install_probe(project_dir)

    scene = f"res://Level_{args.level}.tscn"
    completed = subprocess.run(
        [
            settings.godot_exe,
            "--headless",
            "--path",
            str(project_dir),
            scene,
            "--quit-after",
            "12030",
            "--",
            "--objective-probe",
            f"--objective-template={args.template}",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = completed.stdout + completed.stderr
    print(output, end="")
    verdict = OBJECTIVE_VERDICT.search(output)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    if not verdict:
        print("Smoke test failed: objective probe produced no verdict.", file=sys.stderr)
        raise SystemExit(2)
    if verdict.group(2) != args.template:
        print(
            f"Smoke test failed: expected {args.template}, got {verdict.group(2)}.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if verdict.group(1) != "passed":
        print(f"Smoke test failed: {verdict.group(0)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
