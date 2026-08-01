"""Safe lifecycle controls for SAGA's three allow-listed local services."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Literal

import httpx
import psutil

from saga.config import settings


REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_ROOT = Path(settings.output_root).expanduser().resolve() / "service_logs"


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    label: str
    port: int
    health_url: str
    command: tuple[str, ...]
    cwd: str
    optional: bool = False
    command_hint: str = ""


def _definitions() -> dict[str, ServiceDefinition]:
    ollama_exe = os.environ.get("SAGA_OLLAMA_EXE") or shutil.which("ollama") or "D:\\Ollama\\ollama.exe"
    comfy_dir = Path(os.environ.get("SAGA_COMFYUI_DIR", "D:\\ComfyUI\\ComfyUI"))
    comfy_python = os.environ.get("SAGA_COMFYUI_PYTHON", "D:\\ComfyUI\\.venv\\Scripts\\python.exe")
    music_dir = Path(os.environ.get("SAGA_MUSICGEN_DIR", "D:\\AudioCraft"))
    music_python = os.environ.get("SAGA_MUSICGEN_PYTHON", str(music_dir / ".venv" / "Scripts" / "python.exe"))
    music_script = os.environ.get("SAGA_MUSICGEN_SCRIPT", str(music_dir / "musicgen_server.py"))
    return {
        "ollama": ServiceDefinition(
            "ollama", "Ollama", 11434, f"{settings.ollama_url}/api/tags",
            (ollama_exe, "serve"), str(Path(ollama_exe).parent),
            command_hint="Set SAGA_OLLAMA_EXE if Ollama is installed elsewhere.",
        ),
        "comfyui": ServiceDefinition(
            "comfyui", "ComfyUI", 8188, f"{settings.comfyui_url}/system_stats",
            (comfy_python, "main.py", "--listen", "127.0.0.1", "--port", "8188"), str(comfy_dir),
            command_hint="Set SAGA_COMFYUI_DIR and SAGA_COMFYUI_PYTHON for a custom install.",
        ),
        "musicgen": ServiceDefinition(
            "musicgen", "MusicGen", 8189, f"{settings.musicgen_url}/health",
            (music_python, music_script), str(music_dir), optional=True,
            command_hint="Set SAGA_MUSICGEN_DIR/PYTHON/SCRIPT for a custom install.",
        ),
    }


def _health(definition: ServiceDefinition) -> dict:
    result = asdict(definition)
    result.pop("command")
    result["configured"] = Path(definition.command[0]).is_file() or bool(shutil.which(definition.command[0]))
    result["running"] = False
    result["detail"] = "Not running"
    try:
        response = httpx.get(definition.health_url, timeout=3)
        response.raise_for_status()
        data = response.json()
        result["running"] = True
        if definition.name == "ollama":
            count = len(data.get("models") or [])
            result["detail"] = f"Online · {count} model{'s' if count != 1 else ''}"
        elif definition.name == "musicgen":
            loaded = bool(data.get("model_loaded"))
            result["detail"] = "Online · model ready" if loaded else "Online · model loading"
        else:
            result["detail"] = "Online · GPU service ready"
    except Exception as exc:
        result["detail"] = f"Offline · {type(exc).__name__}"
    return result


def service_statuses() -> list[dict]:
    return [_health(definition) for definition in _definitions().values()]


def _pids_on_port(port: int) -> set[int]:
    pids = set()
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if connection.status == psutil.CONN_LISTEN and connection.laddr and connection.laddr.port == port and connection.pid:
                pids.add(connection.pid)
    except (psutil.AccessDenied, OSError):
        pass
    return pids


def _belongs_to_service(process: psutil.Process, definition: ServiceDefinition) -> bool:
    try:
        command = " ".join(process.cmdline()).lower().replace("\\", "/")
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False
    if definition.name == "ollama":
        return "ollama" in command
    if definition.name == "comfyui":
        return "main.py" in command and "comfyui" in command
    return "musicgen_server.py" in command


def stop_service(name: str) -> dict:
    definition = _definitions()[name]
    stopped = []
    for pid in _pids_on_port(definition.port):
        try:
            process = psutil.Process(pid)
            if not _belongs_to_service(process, definition):
                continue
            process.terminate()
            try:
                process.wait(timeout=8)
            except psutil.TimeoutExpired:
                process.kill()
            stopped.append(pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return {"name": name, "stopped_pids": stopped}


def start_service(name: str) -> dict:
    definition = _definitions()[name]
    status = _health(definition)
    if status["running"]:
        return {"name": name, "status": "already_running", "detail": status["detail"]}
    executable = Path(definition.command[0])
    resolved_executable = str(executable) if executable.is_file() else shutil.which(definition.command[0])
    cwd = Path(definition.cwd)
    if not resolved_executable or not cwd.is_dir():
        return {
            "name": name,
            "status": "not_configured",
            "detail": f"Launch path is missing. {definition.command_hint}",
        }
    command = [resolved_executable, *definition.command[1:]]
    if name == "musicgen" and not Path(command[1]).is_file():
        return {"name": name, "status": "not_configured", "detail": definition.command_hint}
    env = os.environ.copy()
    if name == "ollama" and not env.get("OLLAMA_MODELS"):
        # Ollama serves an empty model list when launched without its models root.
        models_dir = Path(env.get("SAGA_OLLAMA_MODELS", "D:\\ollama\\models"))
        if models_dir.is_dir():
            env["OLLAMA_MODELS"] = str(models_dir)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / f"{name}.log"
    log = log_path.open("a", encoding="utf-8")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=creation_flags,
        )
    finally:
        log.close()
    return {"name": name, "status": "starting", "pid": process.pid, "log_path": str(log_path)}


def control_services(
    action: Literal["start", "restart", "stop"],
    service: Literal["all", "ollama", "comfyui", "musicgen"],
) -> list[dict]:
    names = list(_definitions()) if service == "all" else [service]
    results = []
    for name in names:
        if action == "stop":
            result = stop_service(name)
            result["status"] = "stopped" if result["stopped_pids"] else "not_running"
            results.append(result)
            continue
        if action == "restart":
            stop_service(name)
            time.sleep(0.3)
        results.append(start_service(name))
    return results


def tail_service_log(name: str, lines: int = 120) -> dict:
    if name not in _definitions():
        raise KeyError(name)
    log_path = LOG_ROOT / f"{name}.log"
    if not log_path.is_file():
        return {"name": name, "log_path": str(log_path), "lines": []}
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 256_000))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return {"name": name, "log_path": str(log_path), "lines": []}
    return {"name": name, "log_path": str(log_path), "lines": text.splitlines()[-lines:]}
