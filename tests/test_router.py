from saga.agents import coder_backend
from saga.router import DEEPSEEK, LAGUNA, QWEN_LOCAL, resolve_provider


def test_resolver_needs_the_named_key_to_offer_a_hosted_model(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "present")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert resolve_provider(LAGUNA)["key_env"] == "NVIDIA_API_KEY"
    assert resolve_provider(DEEPSEEK) is None
    assert resolve_provider("unknown/model") is None
    assert resolve_provider(None) is None


def test_local_model_resolves_without_any_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    assert resolve_provider(QWEN_LOCAL) == {"backend": "ollama"}


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
