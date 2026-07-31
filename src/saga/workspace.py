"""Per-run workspace allocation.

Every pipeline invocation owns a directory below ``output/runs``. Keeping
generated assets, scripts, screenshots, and the design document together makes
the result reproducible and prevents concurrent runs from overwriting one
another or inheriting stale files from an older, longer game.
"""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from saga.config import settings
from saga.state import GraphState


OUTPUT_ROOT = Path(settings.output_root).expanduser().resolve()
RUNS_ROOT = OUTPUT_ROOT / "runs"


def create_run_dir() -> Path:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        path = RUNS_ROOT / name
        try:
            path.mkdir()
        except FileExistsError:
            continue
        return path
    raise RuntimeError(f"Could not allocate a unique run directory below {RUNS_ROOT}")


def run_dir(state: GraphState) -> Path:
    value = state.get("run_dir")
    if not value:
        raise ValueError("Graph state has no run_dir; initialize the run through the Studio Director")
    path = Path(value).resolve()
    try:
        path.relative_to(RUNS_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"Run directory must stay below {RUNS_ROOT.resolve()}: {path}") from exc
    return path


def assets_dir(state: GraphState) -> Path:
    return run_dir(state) / "assets"


def project_dir(state: GraphState) -> Path:
    return run_dir(state) / "godot_project"
