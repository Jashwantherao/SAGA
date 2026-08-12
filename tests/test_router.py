import pytest

from saga.agents import coder_backend
from saga.router import DEEPSEEK, LAGUNA, QWEN_LOCAL, resolve_provider


@pytest.fixture(autouse=True)
def _forget_probe():
    """No test inherits another's cached reachability answer."""
    from saga.router import reset_local_probe

    reset_local_probe()
    yield
    reset_local_probe()


@pytest.fixture
def local_up(monkeypatch):
    monkeypatch.setattr("saga.router.local_backend_reachable", lambda **_kwargs: True)


def test_resolver_needs_the_named_key_to_offer_a_hosted_model(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "present")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert resolve_provider(LAGUNA)["key_env"] == "NVIDIA_API_KEY"
    assert resolve_provider(DEEPSEEK) is None
    assert resolve_provider("unknown/model") is None
    assert resolve_provider(None) is None


def test_local_model_resolves_without_any_key(monkeypatch, local_up):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    assert resolve_provider(QWEN_LOCAL) == {"backend": "ollama"}


def test_local_model_is_unroutable_while_the_daemon_is_down(monkeypatch):
    """An offline daemon must read as 'use your fallback', not as a route
    worth two minutes of retries."""
    monkeypatch.setattr("saga.router.local_backend_reachable", lambda **_kwargs: False)

    assert resolve_provider(QWEN_LOCAL) is None


def test_reachability_probe_is_cached_then_refreshed_on_force(monkeypatch):
    from saga import router

    calls = []

    class _Response:
        status_code = 200

    def _get(url, timeout):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(router.httpx, "get", _get)

    assert router.local_backend_reachable() is True
    assert router.local_backend_reachable() is True
    assert len(calls) == 1, "cached answer should not re-probe within the TTL"
    assert calls[0].endswith("/api/tags"), "probe the endpoint doctor already trusts"

    assert router.local_backend_reachable(force=True) is True
    assert len(calls) == 2


def test_probe_reports_unreachable_when_the_daemon_refuses(monkeypatch):
    from saga import router

    def _boom(url, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(router.httpx, "get", _boom)

    assert router.local_backend_reachable() is False


def test_routed_chat_executes_the_specialist_when_available(monkeypatch):
    monkeypatch.setattr(
        "saga.router.resolve_provider",
        lambda _model: {"backend": "openai", "base_url": "https://nim", "key_env": "K"},
    )
    monkeypatch.setattr(
        "saga.llm.chat",
        lambda _messages, *, model, **_kwargs: f"reply from {model}",
    )

    text, executed = coder_backend.routed_chat([], LAGUNA, "coder-model")

    assert text == f"reply from {LAGUNA}"
    assert executed == LAGUNA


def test_routed_chat_falls_back_when_specialist_is_unavailable_or_fails(monkeypatch):
    monkeypatch.setattr(coder_backend, "chat", lambda _messages, model: f"reply from {model}")

    monkeypatch.setattr("saga.router.resolve_provider", lambda _model: None)
    assert coder_backend.routed_chat([], LAGUNA, "coder-model") == (
        "reply from coder-model",
        "coder-model",
    )

    monkeypatch.setattr(
        "saga.router.resolve_provider",
        lambda _model: {"backend": "openai", "base_url": "https://nim", "key_env": "K"},
    )
    monkeypatch.setattr(
        "saga.llm.chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("endpoint down")),
    )
    assert coder_backend.routed_chat([], LAGUNA, "coder-model") == (
        "reply from coder-model",
        "coder-model",
    )


def test_routed_chat_skips_transport_hop_when_specialist_is_the_coder(monkeypatch):
    monkeypatch.setattr(coder_backend, "chat", lambda _messages, model: f"reply from {model}")
    monkeypatch.setattr(
        "saga.router.resolve_provider",
        lambda _model: (_ for _ in ()).throw(AssertionError("resolver should not decide this")),
    )

    assert coder_backend.routed_chat([], "coder-model", "coder-model") == (
        "reply from coder-model",
        "coder-model",
    )
