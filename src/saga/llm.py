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

DEFAULT_BASE_URL = os.environ.get("SAGA_OPENAI_BASE_URL", "https://api.deepseek.com")
DEFAULT_KEY_ENV = os.environ.get("SAGA_OPENAI_KEY_ENV", "DEEPSEEK_API_KEY")

_client = None


def _get_client():
    """Build the client once; a fresh one per call would re-open connections."""
    global _client
    if _client is None:
        from dotenv import load_dotenv
        from openai import OpenAI  # lazy: only needed when a hosted backend runs

        # main.py already does this, but standalone drivers and smoke tests
        # don't - load here so every entry point finds the key.
        load_dotenv()
        api_key = os.environ.get(DEFAULT_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                f"{DEFAULT_KEY_ENV} is not set. Export it (or put it in .env) to use a "
                f"hosted backend, or switch back to the local one."
            )
        _client = OpenAI(api_key=api_key, base_url=DEFAULT_BASE_URL)
    return _client


def chat(messages: list[dict], *, model: str, json_mode: bool = False, max_tokens: int = 8192) -> str:
    """One completion. Returns the raw assistant text.

    json_mode asks for a JSON object rather than a strict schema - DeepSeek's
    OpenAI-compatible surface offers JSON mode, not schema-constrained output
    like Ollama's `format=<schema>`. The Game Designer's existing _validate()
    plus corrective retry already covers the difference, so schema conformance
    is enforced harness-side either way.
    """
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = _get_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""
