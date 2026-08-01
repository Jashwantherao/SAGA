"""Local hardware telemetry for the SAGA Studio dashboard."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import psutil

GPU_QUERY = (
    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
)


def _gpu_stats() -> dict[str, Any] | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        result = subprocess.run(
            [nvidia_smi, GPU_QUERY, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return parse_gpu_line(result.stdout.strip().splitlines()[0])


def parse_gpu_line(line: str) -> dict[str, Any] | None:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 6:
        return None

    def number(value: str) -> float | None:
        try:
            return float(value)
        except ValueError:
            return None

    return {
        "name": parts[0],
        "utilization": number(parts[1]),
        "memory_used_mb": number(parts[2]),
        "memory_total_mb": number(parts[3]),
        "temperature": number(parts[4]),
        "power_draw": number(parts[5]),
    }


def system_stats() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("D:\\" if psutil.WINDOWS else "/")
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_used": memory.used,
        "memory_total": memory.total,
        "memory_percent": memory.percent,
        "disk_used": disk.used,
        "disk_total": disk.total,
        "gpu": _gpu_stats(),
    }
