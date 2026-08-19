"""Central configuration for SAGA.

The settings module loads ``.env`` before reading any environment-backed
value. Importing agent modules through ``saga.graph`` therefore cannot freeze
defaults before the CLI has a chance to load the user's configuration.
"""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


@dataclass(frozen=True)
class Settings:
    openai_base_url: str
    openai_key_env: str

    designer_backend: str
    designer_model: str
    designer_remote_model: str
    designer_timeout: float

    director_backend: str
    director_model: str | None
    director_remote_model: str

    architect_backend: str
    architect_model: str
    architect_base_url: str
    architect_key_env: str
    architect_timeout: float

    coder_backend: str
    coder_model: str
    coder_remote_model: str
    coder_timeout: float
    dotmaze_model: str
    coder_agentic: bool
    skill_context: bool
    skill_context_limit: int
    experience_memory: bool
    experience_memory_limit: int
    experience_memory_max_chars: int
    incremental_build: bool
    incremental_max_systems: int
    incremental_max_attempts: int
    stop_gpu_services: bool
    agent_max_turns: int

    vision_backend: str
    vision_model: str
    vision_remote_model: str
    vision_base_url: str
    vision_key_env: str
    vision_timeout: float

    video_qa_enabled: bool
    video_model: str
    video_base_url: str
    video_key_env: str
    video_timeout: float
    ffmpeg_exe: str

    ollama_url: str
    comfyui_url: str
    musicgen_url: str
    output_root: str
    godot_exe: str
    gate_model: str
    gate_play_timeout: float

    feedback_backend: str
    feedback_model: str

    @classmethod
    def from_environment(cls) -> "Settings":
        coder_model = _env("SAGA_CODER_MODEL", "qwen2.5-coder:14b")
        coder_remote_model = _env("SAGA_CODER_REMOTE_MODEL", "deepseek-v4-pro")
        feedback_backend = _env("SAGA_FEEDBACK_BACKEND", "local").lower()
        if feedback_backend == "claude":
            feedback_default = "claude-sonnet-5"
        elif feedback_backend in {"deepseek", "openai", "remote"}:
            feedback_default = coder_remote_model
        else:
            feedback_default = coder_model
        return cls(
            openai_base_url=_env("SAGA_OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            openai_key_env=_env("SAGA_OPENAI_KEY_ENV", "DEEPSEEK_API_KEY"),
            designer_backend=_env("SAGA_DESIGNER_BACKEND", "local").lower(),
            designer_model=_env(
                "SAGA_DESIGNER_MODEL",
                "hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_S",
            ),
            designer_remote_model=_env("SAGA_DESIGNER_REMOTE_MODEL", "deepseek-v4-pro"),
            designer_timeout=_float_env("SAGA_DESIGNER_TIMEOUT", 180.0),
            director_backend=_env("SAGA_DIRECTOR_BACKEND", "local").lower(),
            director_model=_optional_env("SAGA_DIRECTOR_MODEL"),
            director_remote_model=_env("SAGA_DIRECTOR_REMOTE_MODEL", "deepseek-v4-pro"),
            architect_backend=_env("SAGA_ARCHITECT_BACKEND", "nvidia").lower(),
            architect_model=_env(
                "SAGA_ARCHITECT_MODEL",
                "nvidia/nemotron-3-super-120b-a12b",
            ),
            architect_base_url=_env(
                "SAGA_ARCHITECT_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ).rstrip("/"),
            architect_key_env=_env("SAGA_ARCHITECT_KEY_ENV", "NVIDIA_API_KEY"),
            architect_timeout=_float_env("SAGA_ARCHITECT_TIMEOUT", 180.0),
            coder_backend=_env("SAGA_CODER_BACKEND", "ollama").lower(),
            coder_model=coder_model,
            coder_remote_model=coder_remote_model,
            coder_timeout=_float_env("SAGA_CODER_TIMEOUT", 300.0),
            dotmaze_model=_env("SAGA_DOTMAZE_MODEL", "batiai/qwen3.6-35b:q3"),
            coder_agentic=_bool_env("SAGA_CODER_AGENTIC"),
            skill_context=_bool_env("SAGA_SKILL_CONTEXT"),
            skill_context_limit=_int_env("SAGA_SKILL_CONTEXT_LIMIT", 2),
            experience_memory=_bool_env("SAGA_EXPERIENCE_MEMORY"),
            experience_memory_limit=_int_env("SAGA_EXPERIENCE_MEMORY_LIMIT", 1),
            experience_memory_max_chars=_int_env(
                "SAGA_EXPERIENCE_MEMORY_MAX_CHARS", 12_000
            ),
            incremental_build=_bool_env("SAGA_INCREMENTAL_BUILD"),
            incremental_max_systems=_int_env("SAGA_INCREMENTAL_MAX_SYSTEMS", 6),
            incremental_max_attempts=_int_env("SAGA_INCREMENTAL_MAX_ATTEMPTS", 2),
            stop_gpu_services=_bool_env("SAGA_STOP_GPU_SERVICES"),
            agent_max_turns=_int_env("SAGA_AGENT_MAX_TURNS", 14),
            vision_backend=_env("SAGA_VISION_BACKEND", "local").lower(),
            vision_model=_env("SAGA_VISION_MODEL", "gemma4:12b"),
            vision_remote_model=_env(
                "SAGA_VISION_REMOTE_MODEL",
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            ),
            vision_base_url=_env(
                "SAGA_VISION_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ).rstrip("/"),
            vision_key_env=_env("SAGA_VISION_KEY_ENV", "NVIDIA_API_KEY"),
            vision_timeout=_float_env("SAGA_VISION_TIMEOUT", 90.0),
            video_qa_enabled=_bool_env("SAGA_VIDEO_QA"),
            video_model=_env(
                "SAGA_VIDEO_MODEL",
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            ),
            video_base_url=_env(
                "SAGA_VIDEO_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ).rstrip("/"),
            video_key_env=_env("SAGA_VIDEO_KEY_ENV", "NVIDIA_API_KEY"),
            video_timeout=_float_env("SAGA_VIDEO_TIMEOUT", 120.0),
            ffmpeg_exe=_env("SAGA_FFMPEG_EXE", "ffmpeg"),
            ollama_url=_env("SAGA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            comfyui_url=_env("SAGA_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/"),
            musicgen_url=_env("SAGA_MUSICGEN_URL", "http://127.0.0.1:8189").rstrip("/"),
            output_root=_env(
                "SAGA_OUTPUT_ROOT",
                str(Path(__file__).resolve().parents[2] / "output"),
            ),
            godot_exe=_env(
                "SAGA_GODOT_EXE",
                "D:\\Godot\\Godot_v4.7-stable_win64_console.exe",
            ),
            gate_model=_env("SAGA_GATE_MODEL", "deepseek-v4-pro"),
            gate_play_timeout=_float_env("SAGA_GATE_PLAY_TIMEOUT", 900.0),
            feedback_backend=feedback_backend,
            feedback_model=_env("SAGA_FEEDBACK_MODEL", feedback_default),
        )


settings = Settings.from_environment()
# The Ollama SDK reads OLLAMA_HOST. Mirror SAGA's central URL unless the user
# explicitly configured the SDK variable themselves.
os.environ.setdefault("OLLAMA_HOST", settings.ollama_url)
