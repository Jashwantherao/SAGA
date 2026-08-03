"""Task-kind -> coder-model routing, seeded by the coder-pilot-v1 benchmark.

The pilot's evidence (output/benchmarks/coder-pilot-v1/leaderboard.md):
Nemotron-3-Super led on quality (66.1, 67% ship) but Laguna-XS-2.1 tied
its ship rate at 61% of the wall time, so Laguna is the default and
Nemotron is reserved for the systems where architecture quality earns
its extra minutes. DeepSeek's strength in the corpus is simulation and
targeted repair; the local Qwen is free, so it gets boilerplate and
cheap fixes. Kimi's 0% was a 1.6-second API failure, not a quality
result, so it earns no route until a clean run says otherwise.

Route keys are task kinds: the blueprint's SYSTEM_KINDS plus pipeline
tasks ("architecture", "repair") that are not buildable systems.
"""

import os
import time

import httpx

from saga.config import settings

NEMOTRON = "nvidia/nemotron-3-super-120b-a12b"
LAGUNA = "poolside/laguna-xs-2.1"
DEEPSEEK = "deepseek-v4-pro"
QWEN_LOCAL = "qwen2.5-coder:14b"

NVIDIA_NIM_URL = "https://integrate.api.nvidia.com/v1"

# Transport facts for every routable model. Specs name the environment
# variable that holds a key - the same no-secrets rule as benchmark suites.
MODEL_PROVIDERS = {
    NEMOTRON: {"backend": "openai", "base_url": NVIDIA_NIM_URL, "key_env": "NVIDIA_API_KEY"},
    LAGUNA: {"backend": "openai", "base_url": NVIDIA_NIM_URL, "key_env": "NVIDIA_API_KEY"},
    DEEPSEEK: {"backend": "openai", "base_url": "https://api.deepseek.com", "key_env": "DEEPSEEK_API_KEY"},
    QWEN_LOCAL: {"backend": "ollama"},
}


# A routed local specialist that waits on a dead daemon is pure cost: the
# retry ladder in coder_backend._local_chat spends two minutes before the
# fallback model gets a turn, and six kinds route local-first, so an offline
# Ollama used to add ~12 minutes of sleep to a build. Probing is cheap, but
# not per-call cheap, so the answer is cached briefly - short enough that a
# daemon started mid-run is picked up, long enough to cost one probe a pass.
LOCAL_PROBE_TTL_SECONDS = 60.0
LOCAL_PROBE_TIMEOUT_SECONDS = 2.0

_local_probe: tuple[float, bool] | None = None


def local_backend_reachable(*, force: bool = False) -> bool:
    """True when the Ollama daemon answers its model listing right now.

    Uses the same endpoint doctor and service_manager health-check against,
    so "reachable" means one thing across SAGA. Pass ``force`` to bypass the
    cache when a stale answer would be misleading - mid-retry, for instance.
    """
    global _local_probe
    now = time.monotonic()
    if not force and _local_probe and now - _local_probe[0] < LOCAL_PROBE_TTL_SECONDS:
        return _local_probe[1]
    try:
        response = httpx.get(
            f"{settings.ollama_url}/api/tags", timeout=LOCAL_PROBE_TIMEOUT_SECONDS
        )
        reachable = response.status_code == 200
    except Exception:
        reachable = False
    _local_probe = (now, reachable)
    return reachable


def reset_local_probe() -> None:
    """Drop the cached reachability answer (service restarts, and tests)."""
    global _local_probe
    _local_probe = None


def resolve_provider(model_id: str | None) -> dict | None:
    """Transport spec for a routed model, or None when it cannot be called
    right now (unknown id, its API key is absent, or - for local models - the
    Ollama daemon is down) - the caller then uses its own fallback model
    instead of failing the pass."""
    spec = MODEL_PROVIDERS.get(model_id or "")
    if not spec:
        return None
    key_env = spec.get("key_env")
    if key_env and not os.environ.get(key_env):
        return None
    if spec["backend"] == "ollama" and not local_backend_reachable():
        return None
    return dict(spec)

DEFAULT_ROUTE = [LAGUNA, NEMOTRON]

ROUTES = {
    # Whole-game structure and the systems that live or die on coherence.
    "architecture": [NEMOTRON, LAGUNA],
    "boss": [NEMOTRON, LAGUNA],
    "enemy_ai": [NEMOTRON, DEEPSEEK],
    # Rule- and resource-heavy simulation.
    "combat": [DEEPSEEK, NEMOTRON],
    "progression": [DEEPSEEK, LAGUNA],
    "save_load": [DEEPSEEK, LAGUNA],
    "resource": [DEEPSEEK, LAGUNA],
    # Small, well-trodden fixes should not spend cloud money.
    "repair": [QWEN_LOCAL, DEEPSEEK],
    # Boilerplate the local model already ships.
    "movement": [QWEN_LOCAL, LAGUNA],
    "pickup": [QWEN_LOCAL, LAGUNA],
    "hud": [QWEN_LOCAL, LAGUNA],
    "objective": [QWEN_LOCAL, LAGUNA],
    "switch": [QWEN_LOCAL, DEEPSEEK],
    # Navigation and multi-actor spatial rules were the pilot's clearest
    # discriminator: Nemotron was the only model to ship the dot maze.
    "maze": [NEMOTRON, LAGUNA],
    "hazard": [NEMOTRON, DEEPSEEK],
    "zone_control": [NEMOTRON, LAGUNA],
    "herding": [NEMOTRON, LAGUNA],
}


def candidates(kind: str, overrides: dict[str, list[str]] | None = None) -> list[str]:
    """Ordered model candidates for a task kind: first entry is the pick,
    the rest are fallbacks when the pick fails or is unreachable."""
    routes = {**ROUTES, **(overrides or {})}
    return list(routes.get(kind, DEFAULT_ROUTE))
