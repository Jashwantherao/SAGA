"""Transactional validation for model-generated gameplay repairs.

A repair is a candidate until Godot can load and run its scene.  The previous
script is kept on disk as a crash-recovery checkpoint and restored whenever
the candidate introduces a compiler/runtime startup regression.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Callable

from saga.config import settings


SCRIPT_ERROR = re.compile(
    r"SCRIPT ERROR|Parse Error|Invalid call|Nonexistent function|"
    r"Cannot convert|Failed to load script|Could not resolve",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RepairValidation:
    passed: bool
    errors: list[str]
    restored_previous: bool


def _backup_path(script_file: Path) -> Path:
    return script_file.with_name(f"{script_file.name}.saga-backup")


def _candidate_path(script_file: Path) -> Path:
    return script_file.with_name(f"{script_file.name}.saga-candidate")


def recover_interrupted_repair(script_file: Path) -> bool:
    """Restore a checkpoint left behind if SAGA stopped during validation."""
    backup = _backup_path(script_file)
    candidate = _candidate_path(script_file)
    if not backup.is_file():
        candidate.unlink(missing_ok=True)
        return False
    os.replace(backup, script_file)
    candidate.unlink(missing_ok=True)
    return True


def _godot_environment() -> dict[str, str]:
    """Keep Godot's editor/cache/temp writes inside SAGA's D:-local output."""
    environment = os.environ.copy()
    profile = Path(settings.output_root).expanduser().resolve() / ".godot_profile"
    roaming = profile / "Roaming"
    local = profile / "Local"
    temporary = profile / "Temp"
    for path in (roaming, local, temporary):
        path.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "APPDATA": str(roaming),
            "LOCALAPPDATA": str(local),
            "TEMP": str(temporary),
            "TMP": str(temporary),
        }
    )
    return environment


def _script_errors(output: str) -> list[str]:
    errors = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not SCRIPT_ERROR.search(line):
            continue
        error = line.strip()
        if index + 1 < len(lines) and lines[index + 1].lstrip().startswith("at:"):
            error += f" ({lines[index + 1].strip()})"
        if error not in errors:
            errors.append(error[:400])
        if len(errors) >= 10:
            break
    return errors


def _run_scene(
    project_dir: Path,
    scene: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> subprocess.CompletedProcess:
    command = [
        settings.godot_exe,
        "--headless",
        "--path",
        str(project_dir),
        scene,
        "--quit-after",
        "120",
    ]
    try:
        return runner(
            command,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=_godot_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return subprocess.CompletedProcess(command, 124, stdout, f"{stderr}\nGodot candidate smoke test timed out")
    except OSError as exc:
        return subprocess.CompletedProcess(
            command,
            127,
            "",
            f"Could not start Godot: {type(exc).__name__}: {exc}",
        )


def validate_and_promote_repair(
    script_file: Path,
    candidate_script: str,
    *,
    project_dir: Path,
    scene: str,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> RepairValidation:
    """Temporarily install a candidate, promoting it only after a clean run."""
    if not script_file.is_file():
        return RepairValidation(False, ["No previous gameplay script exists to protect"], False)

    recover_interrupted_repair(script_file)
    backup = _backup_path(script_file)
    candidate = _candidate_path(script_file)
    backup.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")
    candidate.write_text(candidate_script, encoding="utf-8")
    os.replace(candidate, script_file)

    result = _run_scene(project_dir, scene, runner=runner)
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    errors = _script_errors(output)
    if result.returncode != 0 and not errors:
        detail = next((line.strip() for line in reversed(output.splitlines()) if line.strip()), "no diagnostic")
        errors = [f"Godot candidate smoke test exited {result.returncode}: {detail[:300]}"]

    if errors:
        os.replace(backup, script_file)
        candidate.unlink(missing_ok=True)
        return RepairValidation(False, errors, True)

    backup.unlink(missing_ok=True)
    candidate.unlink(missing_ok=True)
    return RepairValidation(True, [], False)
