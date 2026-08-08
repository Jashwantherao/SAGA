"""OpenAI-compatible chat backend - DeepSeek today, anything compatible later.

Both the Game Designer and the Coder can run against a hosted model instead of
a local Ollama one. Nearly every provider worth using speaks the OpenAI wire
format (DeepSeek, Kimi, GLM, ...) and so do local servers (LM Studio, vLLM,
llama.cpp), so a single client covers all of them - only the base URL, key,
and model name change. That keeps provider choice a config decision rather
than a code change.

Defaults point at DeepSeek because it is the cheapest capable option
benchmarked for this project (~$0.003 for a 4-level game, versus roughly
$0.19 on a frontier model), which makes the local-vs-hosted decision about
quality rather than cost.
"""

import os

from saga.config import settings


DEFAULT_BASE_URL = settings.openai_base_url
DEFAULT_KEY_ENV = settings.openai_key_env

# Keyed by (base_url, key_env): agents can legitimately want different
# providers at once - the Coder on one, the vision reviewer on another - and a
# fresh client per call would re-open connections.
_clients: dict[tuple[str, str], object] = {}


def _get_client(base_url: str | None = None, key_env: str | None = None):
    base_url = base_url or DEFAULT_BASE_URL
    key_env = key_env or DEFAULT_KEY_ENV
    cached = _clients.get((base_url, key_env))
    if cached is None:
        from dotenv import load_dotenv
        from openai import OpenAI  # lazy: only needed when a hosted backend runs

        # main.py already does this, but standalone drivers and smoke tests
        # don't - load here so every entry point finds the key.
        load_dotenv()
        api_key = os.environ.get(key_env)
        if not api_key:
            raise RuntimeError(
                f"{key_env} is not set. Export it (or put it in .env) to use a "
                f"hosted backend, or switch back to the local one."
            )
        cached = OpenAI(api_key=api_key, base_url=base_url)
        _clients[(base_url, key_env)] = cached
    return cached


def chat(
    messages: list[dict],
    *,
    model: str,
    json_mode: bool = False,
    max_tokens: int = 8192,
    base_url: str | None = None,
    key_env: str | None = None,
    timeout: float | None = None,
    temperature: float | None = None,
    extra_body: dict | None = None,
) -> str:
    """One completion. Returns the raw assistant text.

    json_mode asks for a JSON object rather than a strict schema - the
    OpenAI-compatible surface offers JSON mode, not schema-constrained output
    like Ollama's `format=<schema>`. The Game Designer's existing _validate()
    plus corrective retry already covers the difference, so schema conformance
    is enforced harness-side either way.

    base_url/key_env override the module defaults for one call, so a second
    provider needs no second module. timeout matters on free tiers, which have
    been measured hanging for minutes on models they nominally serve; callers
    that can degrade gracefully should always set one.
    """
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if temperature is not None:
        kwargs["temperature"] = temperature
    if extra_body:
        kwargs["extra_body"] = extra_body
    client = _get_client(base_url, key_env)
    if timeout is not None:
        # The OpenAI SDK retries timeouts by default, which turns a nominal
        # five-minute ceiling into three opaque five-minute attempts. Callers
        # that supplied a timeout are explicitly asking for a bounded agent
        # step, so make it one attempt and let the pipeline's own retry/repair
        # policy decide what happens next.
        client = client.with_options(timeout=timeout, max_retries=0)
        kwargs.pop("timeout", None)
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def chat_raw(
    messages: list[dict],
    *,
    model: str,
    tools: list[dict] | None = None,
    max_tokens: int = 8192,
    base_url: str | None = None,
    key_env: str | None = None,
    timeout: float | None = None,
):
    """One completion, returning the whole message rather than just its text.

    An agent loop needs the tool_calls the model wants to make, and has to
    append the assistant message back into the conversation verbatim, so
    flattening it to a string here would throw away exactly what it needs.
    """
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        kwargs["tools"] = tools
    if timeout is not None:
        kwargs["timeout"] = timeout
    client = _get_client(base_url, key_env)
    if timeout is not None:
        client = client.with_options(timeout=timeout, max_retries=0)
        kwargs.pop("timeout", None)
    return client.chat.completions.create(**kwargs).choices[0].message
