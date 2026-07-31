"""Dependency preflight for the SAGA pipeline."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import httpx

from saga.config import settings


REMOTE_BACKENDS = {"deepseek", "openai", "remote"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    required: bool
    detail: str

    @property
    def marker(self) -> str:
        if self.ok:
            return "PASS"
        return "FAIL" if self.required else "WARN"


def _http_json(name: str, url: str, *, required: bool) -> tuple[CheckResult, dict | None]:
    try:
        response = httpx.get(url, timeout=5)
        response.raise_for_status()
        return CheckResult(name, True, required, f"{url} returned {response.status_code}"), response.json()
    except Exception as exc:
        return (
            CheckResult(name, False, required, f"{url}: {type(exc).__name__}: {exc}"),
            None,
        )


def _godot_check() -> CheckResult:
    configured = settings.godot_exe
    executable = configured if Path(configured).is_file() else shutil.which(configured)
    if not executable:
        return CheckResult(
            "Godot",
            False,
            True,
            f"not found at {configured!r}; set SAGA_GODOT_EXE",
        )
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("Godot", False, True, f"{type(exc).__name__}: {exc}")
    version = (result.stdout or result.stderr).strip().splitlines()
    detail = version[0] if version else f"exit code {result.returncode}"
    return CheckResult("Godot", result.returncode == 0, True, detail)


def _ffmpeg_check() -> CheckResult:
    configured = settings.ffmpeg_exe
    executable = configured if Path(configured).is_file() else shutil.which(configured)
    if not executable:
        return CheckResult(
            "FFmpeg",
            False,
            True,
            f"not found at {configured!r}; install FFmpeg or set SAGA_FFMPEG_EXE",
        )
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("FFmpeg", False, True, f"{type(exc).__name__}: {exc}")
    version = (result.stdout or result.stderr).strip().splitlines()
    detail = version[0] if version else f"exit code {result.returncode}"
    return CheckResult("FFmpeg", result.returncode == 0, True, detail)


def _output_check() -> CheckResult:
    root = Path(settings.output_root).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".saga-write-", dir=root, delete=True):
            pass
    except OSError as exc:
        return CheckResult("Output directory", False, True, f"{root}: {exc}")
    return CheckResult("Output directory", True, True, f"writable: {root.resolve()}")


def _credential_checks(include_playtest: bool = False) -> list[CheckResult]:
    checks = []
    backends = [
        settings.designer_backend,
        settings.director_backend,
        settings.coder_backend,
    ]
    if include_playtest:
        backends.append(settings.feedback_backend)
    needs_openai = any(
        backend in REMOTE_BACKENDS
        for backend in backends
    )
    if needs_openai:
        present = bool(os.environ.get(settings.openai_key_env))
        checks.append(
            CheckResult(
                settings.openai_key_env,
                present,
                True,
                "set" if present else "missing for a hosted agent backend",
            )
        )
    if settings.vision_backend in {"nvidia", "remote", "openai"}:
        present = bool(os.environ.get(settings.vision_key_env))
        checks.append(
            CheckResult(
                settings.vision_key_env,
                present,
                True,
                "set" if present else "missing for hosted vision QA",
            )
        )
    if settings.video_qa_enabled and not any(
        check.name == settings.video_key_env for check in checks
    ):
        present = bool(os.environ.get(settings.video_key_env))
        checks.append(
            CheckResult(
                settings.video_key_env,
                present,
                True,
                "set" if present else "missing for NVIDIA gameplay video QA",
            )
        )
    if "claude" in backends:
        present = bool(os.environ.get("ANTHROPIC_API_KEY"))
        checks.append(
            CheckResult(
                "ANTHROPIC_API_KEY",
                present,
                True,
                "set" if present else "missing for a Claude backend",
            )
        )
    return checks


def run_checks(include_playtest: bool = False) -> list[CheckResult]:
    checks = [
        CheckResult(
            "Python",
            sys.version_info >= (3, 10),
            True,
            sys.version.split()[0],
        ),
        _output_check(),
        _godot_check(),
    ]
    if settings.video_qa_enabled:
        checks.append(_ffmpeg_check())

    needs_ollama = (
        settings.designer_backend == "local"
        or settings.director_backend == "local"
        or settings.coder_backend == "ollama"
        or settings.vision_backend == "local"
        or (include_playtest and settings.feedback_backend == "local")
    )
    if needs_ollama:
        ollama, data = _http_json(
            "Ollama",
            f"{settings.ollama_url}/api/tags",
            required=True,
        )
        if ollama.ok and not (data or {}).get("models"):
            ollama = CheckResult("Ollama", False, True, "service is up but reports no models")
        checks.append(ollama)

    comfy, _ = _http_json(
        "ComfyUI",
        f"{settings.comfyui_url}/system_stats",
        required=True,
    )
    checks.append(comfy)

    musicgen, music_data = _http_json(
        "MusicGen",
        f"{settings.musicgen_url}/health",
        required=False,
    )
    if musicgen.ok and not (music_data or {}).get("model_loaded"):
        musicgen = CheckResult(
            "MusicGen",
            False,
            False,
            "service is up but the model is still loading; BGM will be skipped",
        )
    checks.append(musicgen)
    checks.extend(_credential_checks(include_playtest))
    return checks


def print_report(checks: list[CheckResult]) -> None:
    print("SAGA preflight")
    for check in checks:
        print(f"[{check.marker:4}] {check.name}: {check.detail}")


def required_checks_pass(checks: list[CheckResult]) -> bool:
    return all(check.ok for check in checks if check.required)


def main() -> None:
    checks = run_checks(include_playtest=True)
    print_report(checks)
    raise SystemExit(0 if required_checks_pass(checks) else 2)
