"""Local control API for the SAGA desktop application.

The server deliberately binds to loopback and keeps credentials, filesystem
access, and process control on the Python side of the desktop boundary.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from saga.config import settings
from saga.doctor import required_checks_pass, run_checks
from saga.service_manager import control_services, service_statuses, tail_service_log
from saga.system_stats import system_stats
from saga.studio_settings import (
    StudioSettingsUpdate,
    discover_models,
    read_studio_settings,
    save_studio_settings,
)
from saga.workspace import RUNS_ROOT


API_HOST = "127.0.0.1"
API_PORT = 8765
MAX_IDEA_LENGTH = 4000
RUN_LINE = re.compile(r"Run workspace:\s*(.+)$")


class GenerationRequest(BaseModel):
    idea: str = Field(min_length=3, max_length=MAX_IDEA_LENGTH)
    levels: int = Field(default=1, ge=1, le=5)
    skip_preflight: bool = False


class OpenRequest(BaseModel):
    target: str = Field(pattern="^(folder|godot|play)$")


class ServiceActionRequest(BaseModel):
    action: Literal["start", "restart", "stop"]
    service: Literal["all", "ollama", "comfyui", "musicgen"] = "all"


class Job:
    def __init__(self, request: GenerationRequest) -> None:
        self.id = uuid4().hex[:12]
        self.idea = request.idea.strip()
        self.levels = request.levels
        self.skip_preflight = request.skip_preflight
        self.status = "queued"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.finished_at: str | None = None
        self.run_id: str | None = None
        self.exit_code: int | None = None
        self.logs: list[str] = []
        self.process: asyncio.subprocess.Process | None = None
        self.cancel_requested = False

    def as_dict(self, include_logs: bool = True) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "idea": self.idea,
            "levels": self.levels,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "run_id": self.run_id,
            "exit_code": self.exit_code,
        }
        if include_logs:
            payload["logs"] = self.logs[-300:]
        return payload


class EventHub:
    def __init__(self) -> None:
        self.listeners: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self.listeners):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self.listeners.add(queue)
        try:
            yield queue
        finally:
            self.listeners.discard(queue)


hub = EventHub()
current_job: Job | None = None
job_task: asyncio.Task[None] | None = None
job_history: list[Job] = []
JOB_HISTORY_LIMIT = 50


def _within_runs(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(RUNS_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path is outside the SAGA run library") from exc
    return resolved


def _run_path(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    path = _within_runs(RUNS_ROOT / run_id)
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    return path


def _read_manifest(path: Path) -> dict[str, Any]:
    manifest_path = path / "run.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    design_path = path / "design_doc.json"
    if not data.get("title") and design_path.is_file():
        try:
            design = json.loads(design_path.read_text(encoding="utf-8"))
            data["title"] = design.get("title")
            data["idea"] = data.get("idea") or design.get("story_premise")
        except (OSError, json.JSONDecodeError):
            pass
    data["id"] = path.name
    data["updated_at"] = datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    ).isoformat()
    data["complete"] = manifest_path.is_file()
    return data


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
AUDIO_EXTS = {".wav", ".mp3", ".ogg"}
VIDEO_EXTS = {".mp4", ".webm"}
SKIP_DIRS = {".godot", ".import", "__pycache__"}


def _list_run_files(path: Path) -> dict[str, Any]:
    """Classify the media and code inside a run workspace for the gallery view."""
    images: list[dict[str, Any]] = []
    audio: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    script_count = 0
    total_bytes = 0
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(path)
        if SKIP_DIRS & {part.lower() for part in rel.parts[:-1]}:
            continue
        suffix = item.suffix.lower()
        if suffix in {".uid", ".tmp"}:
            continue
        total_bytes += item.stat().st_size
        rel_posix = rel.as_posix()
        if rel_posix.startswith("godot_project/assets/"):
            continue  # duplicates of the top-level assets folder
        entry = {"path": rel_posix, "name": item.name, "size": item.stat().st_size}
        if suffix in IMAGE_EXTS:
            images.append(entry)
        elif suffix in AUDIO_EXTS:
            audio.append(entry)
        elif suffix in VIDEO_EXTS:
            videos.append(entry)
        elif suffix in {".gd", ".tscn"}:
            script_count += 1
    return {
        "images": images[:80],
        "audio": audio[:20],
        "videos": videos[:12],
        "script_count": script_count,
        "total_bytes": total_bytes,
        "has_design_doc": (path / "design_doc.json").is_file(),
    }


def list_runs() -> list[dict[str, Any]]:
    if not RUNS_ROOT.is_dir():
        return []
    paths = sorted(
        (item for item in RUNS_ROOT.iterdir() if item.is_dir()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [_read_manifest(path) for path in paths]


async def _emit_job(job: Job) -> None:
    await hub.publish({"type": "job", "job": job.as_dict()})


def _generation_command(job: Job) -> list[str]:
    command = [
        sys.executable,
        "-u",
        "-m",
        "saga.main",
        job.idea,
        "--levels",
        str(job.levels),
    ]
    if job.skip_preflight:
        command.append("--skip-preflight")
    return command


async def _run_generation(job: Job) -> None:
    global current_job
    command = _generation_command(job)
    job.status = "running"
    await _emit_job(job)
    try:
        job.process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(Path(__file__).resolve().parents[2]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=os.environ.copy(),
        )
        assert job.process.stdout is not None
        async for raw_line in job.process.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            job.logs.append(line)
            match = RUN_LINE.search(line)
            if match:
                job.run_id = Path(match.group(1).strip()).name
            await hub.publish({"type": "log", "job_id": job.id, "line": line})
        job.exit_code = await job.process.wait()
        if job.cancel_requested:
            job.status = "cancelled"
        else:
            job.status = "completed" if job.exit_code == 0 else "failed"
        if not job.run_id:
            recent = list_runs()
            if recent:
                job.run_id = recent[0]["id"]
    except Exception as exc:
        job.status = "failed"
        job.logs.append(f"UI runner failed ({type(exc).__name__}): {exc}")
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()
        await _emit_job(job)
        await hub.publish({"type": "runs_changed"})
        current_job = job


app = FastAPI(title="SAGA Studio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    checks = await asyncio.to_thread(run_checks, False)
    current_settings = read_studio_settings()
    return {
        "ready": required_checks_pass(checks),
        "checks": [asdict(check) | {"marker": check.marker} for check in checks],
        "settings": {
            "output_root": settings.output_root,
            "coder_backend": current_settings["coder_backend"],
            "coder_model": (
                current_settings["coder_remote_model"]
                if current_settings["coder_backend"] in {"deepseek", "openai", "remote"}
                else current_settings["coder_model"]
            ),
            "video_qa": current_settings["video_qa_enabled"],
        },
    }


@app.get("/api/services")
async def services() -> list[dict[str, Any]]:
    return await asyncio.to_thread(service_statuses)


@app.post("/api/services/actions", status_code=202)
async def service_action(request: ServiceActionRequest) -> dict[str, Any]:
    if (
        request.action in {"restart", "stop"}
        and current_job
        and current_job.status in {"queued", "running"}
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Services cannot {request.action} during game generation",
        )
    results = await asyncio.to_thread(control_services, request.action, request.service)
    return {"action": request.action, "results": results}


@app.get("/api/services/{name}/logs")
async def service_logs(name: str, lines: int = 120) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(tail_service_log, name, max(1, min(lines, 500)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown service") from exc


@app.get("/api/system")
async def system() -> dict[str, Any]:
    return await asyncio.to_thread(system_stats)


@app.get("/api/settings")
async def studio_settings() -> dict[str, Any]:
    return await asyncio.to_thread(read_studio_settings)


@app.put("/api/settings")
async def update_studio_settings(update: StudioSettingsUpdate) -> dict[str, Any]:
    if current_job and current_job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Model settings cannot change during game generation")
    return await asyncio.to_thread(save_studio_settings, update)


@app.get("/api/models")
async def models() -> dict[str, list[str]]:
    return await asyncio.to_thread(discover_models)


@app.get("/api/runs")
async def runs() -> list[dict[str, Any]]:
    return await asyncio.to_thread(list_runs)


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_read_manifest, _run_path(run_id))


@app.get("/api/runs/{run_id}/files")
async def run_files(run_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_list_run_files, _run_path(run_id))


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str) -> dict[str, str]:
    if current_job and current_job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Runs cannot be deleted during game generation")
    path = _run_path(run_id)
    await asyncio.to_thread(shutil.rmtree, path)
    await hub.publish({"type": "runs_changed"})
    return {"status": "deleted", "id": run_id}


@app.get("/api/artifacts/{run_id}/{artifact_path:path}")
async def artifact(run_id: str, artifact_path: str) -> FileResponse:
    path = _within_runs(_run_path(run_id) / artifact_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)


@app.post("/api/generations", status_code=202)
async def start_generation(request: GenerationRequest) -> dict[str, Any]:
    global current_job, job_task
    if current_job and current_job.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="A generation is already running")
    current_job = Job(request)
    # Return the same state the background task will publish. Otherwise the
    # queued POST response can arrive after the running WebSocket event and
    # overwrite the newer state in the client.
    current_job.status = "running"
    job_history.insert(0, current_job)
    del job_history[JOB_HISTORY_LIMIT:]
    job_task = asyncio.create_task(_run_generation(current_job))
    return current_job.as_dict()


@app.get("/api/generations")
async def generation_history() -> list[dict[str, Any]]:
    return [job.as_dict(include_logs=False) for job in job_history]


@app.get("/api/generations/current")
async def generation_status() -> dict[str, Any] | None:
    return current_job.as_dict() if current_job else None


@app.post("/api/generations/{job_id}/cancel")
async def cancel_generation(job_id: str) -> dict[str, Any]:
    if not current_job or current_job.id != job_id:
        raise HTTPException(status_code=404, detail="Generation not found")
    if current_job.status not in {"queued", "running"}:
        return current_job.as_dict()
    current_job.cancel_requested = True
    if current_job.process and current_job.process.returncode is None:
        current_job.process.terminate()
    return current_job.as_dict()


@app.post("/api/runs/{run_id}/open", status_code=202)
async def open_run(run_id: str, request: OpenRequest) -> dict[str, str]:
    path = _run_path(run_id)
    if request.target == "folder":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        project = path / "godot_project"
        if not project.is_dir():
            raise HTTPException(status_code=404, detail="Godot project not found")
        args = [settings.godot_exe, "--path", str(project)]
        if request.target == "godot":
            args.append("--editor")
        subprocess.Popen(args, cwd=project)
    return {"status": "opened", "target": request.target}


@app.websocket("/api/events")
async def events(websocket: WebSocket) -> None:
    await websocket.accept()
    async with hub.subscribe() as queue:
        # Subscribe before sending the snapshot so a state transition between
        # those operations is queued instead of being lost.
        if current_job:
            await websocket.send_json({"type": "job", "job": current_job.as_dict()})
        try:
            while True:
                await websocket.send_json(await queue.get())
        except WebSocketDisconnect:
            pass


def main() -> None:
    import uvicorn

    uvicorn.run("saga.ui_api:app", host=API_HOST, port=API_PORT, reload=False)


if __name__ == "__main__":
    main()
