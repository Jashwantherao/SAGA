from types import SimpleNamespace

from saga import llm


class FakeClient:
    def __init__(self):
        self.options = None
        self.request = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )

    def with_options(self, **options):
        self.options = options
        return self

    def create(self, **kwargs):
        self.request = kwargs
        message = SimpleNamespace(content="response")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_explicit_timeout_disables_sdk_retries(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "_get_client", lambda *_args: client)

    result = llm.chat([], model="m", timeout=42)

    assert result == "response"
    assert client.options == {"timeout": 42, "max_retries": 0}
    assert "timeout" not in client.request


def test_unbounded_call_preserves_sdk_default_retry_policy(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "_get_client", lambda *_args: client)

    llm.chat([], model="m")

    assert client.options is None
