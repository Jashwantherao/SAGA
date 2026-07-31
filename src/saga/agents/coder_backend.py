"""Model selection and completion transport for the Coder agent."""

import re
import subprocess
import time

from saga.config import settings

import httpx
import ollama


MODEL = settings.coder_model
CODER_BACKEND = settings.coder_backend
REMOTE_MODEL = settings.coder_remote_model
TEMPLATE_MODEL_OVERRIDES = {
    "dot_maze": settings.dotmaze_model,
}

GPU_SERVICE_PORTS = (8188, 8189)


def stop_gpu_services() -> None:
    """Free VRAM held by finished services so a large coder model can load."""
    if not settings.stop_gpu_services:
        return
    for port in GPU_SERVICE_PORTS:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Get-NetTCPConnection -LocalPort {port} -State Listen "
                f"-ErrorAction SilentlyContinue | ForEach-Object "
                f"{{ Stop-Process -Id $_.OwningProcess -Force -Confirm:$false }}",
            ],
            capture_output=True,
        )
    time.sleep(5)
    print(f"[Coder] Stopped GPU services on ports {GPU_SERVICE_PORTS} to free VRAM")


def is_remote() -> bool:
    return CODER_BACKEND in {"deepseek", "openai", "remote"}


def chat(messages: list[dict], model: str) -> str:
    """Return one Coder completion from the configured backend."""
    if is_remote():
        from saga.llm import chat as hosted_chat

        # Reasoning models spend much of the budget before emitting the script.
        return hosted_chat(messages, model=model, max_tokens=32000)

    last_error = None
    for attempt, backoff in enumerate([0, 20, 40, 60]):
        if backoff:
            print(
                f"[Coder] Ollama runner unstable (attempt {attempt}), "
                f"waiting {backoff}s: {last_error}"
            )
            time.sleep(backoff)
        try:
            return ollama.chat(model=model, messages=messages)["message"]["content"]
        except (ollama.ResponseError, httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_error = exc
    raise RuntimeError(
        f"Ollama runner did not recover after 4 attempts for model {model!r}: {last_error}"
    )


def extract_gdscript(text: str) -> str:
    match = re.search(r"```gdscript\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    raise ValueError("Coder agent response did not contain a fenced code block")
