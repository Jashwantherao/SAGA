"""Allow-listed, durable settings for the SAGA Studio UI."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Literal

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field, field_validator


REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = REPO_ROOT / ".env"

AGENT_BACKENDS = {"local", "ollama", "deepseek", "openai", "remote", "claude", "nvidia"}
ENV_FIELDS = {
    "designer_backend": "SAGA_DESIGNER_BACKEND",
    "designer_model": "SAGA_DESIGNER_MODEL",
    "designer_remote_model": "SAGA_DESIGNER_REMOTE_MODEL",
    "designer_timeout": "SAGA_DESIGNER_TIMEOUT",
    "director_backend": "SAGA_DIRECTOR_BACKEND",
    "director_model": "SAGA_DIRECTOR_MODEL",
    "director_remote_model": "SAGA_DIRECTOR_REMOTE_MODEL",
    "architect_backend": "SAGA_ARCHITECT_BACKEND",
    "architect_model": "SAGA_ARCHITECT_MODEL",
    "architect_base_url": "SAGA_ARCHITECT_BASE_URL",
    "coder_backend": "SAGA_CODER_BACKEND",
    "coder_model": "SAGA_CODER_MODEL",
    "coder_remote_model": "SAGA_CODER_REMOTE_MODEL",
    "coder_timeout": "SAGA_CODER_TIMEOUT",
    "dotmaze_model": "SAGA_DOTMAZE_MODEL",
    "vision_backend": "SAGA_VISION_BACKEND",
    "vision_model": "SAGA_VISION_MODEL",
    "vision_remote_model": "SAGA_VISION_REMOTE_MODEL",
    "feedback_backend": "SAGA_FEEDBACK_BACKEND",
    "feedback_model": "SAGA_FEEDBACK_MODEL",
    "video_qa_enabled": "SAGA_VIDEO_QA",
    "video_model": "SAGA_VIDEO_MODEL",
    "openai_base_url": "SAGA_OPENAI_BASE_URL",
    "vision_base_url": "SAGA_VISION_BASE_URL",
    "stop_gpu_services": "SAGA_STOP_GPU_SERVICES",
    "incremental_build": "SAGA_INCREMENTAL_BUILD",
    "incremental_max_systems": "SAGA_INCREMENTAL_MAX_SYSTEMS",
    "incremental_max_attempts": "SAGA_INCREMENTAL_MAX_ATTEMPTS",
    "experience_memory": "SAGA_EXPERIENCE_MEMORY",
}
SECRET_FIELDS = {
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "nvidia_api_key": "NVIDIA_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
}
DEFAULTS = {
    "designer_backend": "local",
    "designer_model": "hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_S",
    "designer_remote_model": "deepseek-v4-pro",
    "designer_timeout": "180",
    "director_backend": "local",
    "director_model": "",
    "director_remote_model": "deepseek-v4-pro",
    "architect_backend": "nvidia",
    "architect_model": "nvidia/nemotron-3-super-120b-a12b",
    "architect_base_url": "https://integrate.api.nvidia.com/v1",
    "coder_backend": "ollama",
    "coder_model": "qwen2.5-coder:14b",
    "coder_remote_model": "deepseek-v4-pro",
    "coder_timeout": "300",
    "dotmaze_model": "batiai/qwen3.6-35b:q3",
    "vision_backend": "local",
    "vision_model": "gemma4:12b",
    "vision_remote_model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "feedback_backend": "local",
    "feedback_model": "qwen2.5-coder:14b",
    "video_qa_enabled": "0",
    "video_model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "openai_base_url": "https://api.deepseek.com",
    "vision_base_url": "https://integrate.api.nvidia.com/v1",
    "stop_gpu_services": "0",
    "incremental_build": "0",
    "incremental_max_systems": "6",
    "incremental_max_attempts": "2",
    "experience_memory": "0",
}
MODEL_PRESETS = {
    "local": [
        "qwen2.5-coder:14b",
        "batiai/qwen3.6-35b:q3",
        "gemma4:12b",
        "hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_S",
    ],
    "deepseek": ["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
    "nvidia": [
        "nvidia/nemotron-3-super-120b-a12b",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "poolside/laguna-xs-2.1",
        "z-ai/glm-5.2",
        "moonshotai/kimi-k2.6",
    ],
    "claude": ["claude-sonnet-5"],
}


class StudioSettingsUpdate(BaseModel):
    designer_backend: Literal["local", "deepseek", "openai", "remote", "claude"]
    designer_model: str = Field(min_length=1, max_length=250)
    designer_remote_model: str = Field(min_length=1, max_length=250)
    designer_timeout: float = Field(default=180, ge=30, le=1800)
    director_backend: Literal[
        "local", "deepseek", "openai", "remote", "claude", "deterministic"
    ]
    director_model: str = Field(default="", max_length=250)
    director_remote_model: str = Field(min_length=1, max_length=250)
    architect_backend: Literal["nvidia", "local", "deterministic", "off"]
    architect_model: str = Field(min_length=1, max_length=250)
    architect_base_url: str = Field(min_length=8, max_length=500)
    coder_backend: Literal["ollama", "deepseek", "openai", "remote"]
    coder_model: str = Field(min_length=1, max_length=250)
    coder_remote_model: str = Field(min_length=1, max_length=250)
    coder_timeout: float = Field(default=300, ge=30, le=1800)
    dotmaze_model: str = Field(min_length=1, max_length=250)
    vision_backend: Literal["local", "nvidia", "openai", "remote"]
    vision_model: str = Field(min_length=1, max_length=250)
    vision_remote_model: str = Field(min_length=1, max_length=250)
    feedback_backend: Literal["local", "deepseek", "openai", "remote", "claude"]
    feedback_model: str = Field(min_length=1, max_length=250)
    video_qa_enabled: bool = False
    video_model: str = Field(min_length=1, max_length=250)
    openai_base_url: str = Field(min_length=8, max_length=500)
    vision_base_url: str = Field(min_length=8, max_length=500)
    stop_gpu_services: bool = False
    incremental_build: bool = False
    incremental_max_systems: int = Field(default=6, ge=1, le=12)
    incremental_max_attempts: int = Field(default=2, ge=1, le=4)
    experience_memory: bool = False
    deepseek_api_key: str | None = Field(default=None, max_length=500)
    nvidia_api_key: str | None = Field(default=None, max_length=500)
    anthropic_api_key: str | None = Field(default=None, max_length=500)

    @field_validator("openai_base_url", "vision_base_url", "architect_base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        clean = value.strip().rstrip("/")
        if not clean.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return clean

    @field_validator(
        "designer_model", "designer_remote_model", "director_model",
        "director_remote_model", "architect_model", "coder_model", "coder_remote_model",
        "dotmaze_model", "vision_model", "vision_remote_model",
        "feedback_model", "video_model",
    )
    @classmethod
    def clean_model(cls, value: str) -> str:
        return value.strip()


def _values() -> dict[str, str]:
    file_values = {key: value or "" for key, value in dotenv_values(ENV_PATH).items()}
    return file_values | {key: value for key, value in os.environ.items() if key in set(ENV_FIELDS.values()) | set(SECRET_FIELDS.values())}


def read_studio_settings() -> dict[str, Any]:
    values = _values()
    result: dict[str, Any] = {}
    for field, env_name in ENV_FIELDS.items():
        raw = values.get(env_name, DEFAULTS[field])
        if field in {
            "video_qa_enabled", "stop_gpu_services", "incremental_build",
            "experience_memory",
        }:
            result[field] = raw.lower() in {"1", "true", "yes", "on"}
        elif field in {"incremental_max_systems", "incremental_max_attempts"}:
            result[field] = int(raw)
        elif field in {"coder_timeout", "designer_timeout"}:
            result[field] = float(raw)
        else:
            result[field] = raw
    result["api_keys"] = {
        field.removesuffix("_api_key"): bool(values.get(env_name))
        for field, env_name in SECRET_FIELDS.items()
    }
    return result


def _write_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.is_file() else []
    remaining = dict(updates)
    output = []
    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match and match.group(1) in remaining:
            key = match.group(1)
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)
    if remaining:
        if output and output[-1]:
            output.append("")
        output.append("# Managed by SAGA Studio")
        output.extend(f"{key}={value}" for key, value in remaining.items())
    temp_path = ENV_PATH.with_suffix(".env.tmp")
    temp_path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temp_path, ENV_PATH)
    os.environ.update(updates)


def save_studio_settings(update: StudioSettingsUpdate) -> dict[str, Any]:
    payload = update.model_dump()
    updates = {
        env_name: ("1" if value else "0") if isinstance(value, bool) else str(value)
        for field, env_name in ENV_FIELDS.items()
        if (value := payload[field]) is not None
    }
    for field, env_name in SECRET_FIELDS.items():
        value = payload.get(field)
        if value and value.strip():
            updates[env_name] = value.strip()
    _write_env(updates)
    return read_studio_settings()


def _provider_models(base_url: str, key: str | None) -> list[str]:
    if not key:
        return []
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8,
        )
        response.raise_for_status()
        return sorted({item["id"] for item in response.json().get("data", []) if item.get("id")})
    except Exception:
        return []


def discover_models() -> dict[str, list[str]]:
    current = read_studio_settings()
    values = _values()
    local = []
    try:
        response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=4)
        response.raise_for_status()
        local = [model.get("name") or model.get("model") for model in response.json().get("models", [])]
    except Exception:
        pass
    return {
        "local": sorted(set(filter(None, local + MODEL_PRESETS["local"]))),
        "deepseek": sorted(set(MODEL_PRESETS["deepseek"] + _provider_models(current["openai_base_url"], values.get("DEEPSEEK_API_KEY")))),
        "nvidia": sorted(set(MODEL_PRESETS["nvidia"] + _provider_models(current["vision_base_url"], values.get("NVIDIA_API_KEY")))),
        "claude": MODEL_PRESETS["claude"],
    }
