from saga.config import Settings


def test_settings_read_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGA_CODER_MODEL", "test-coder")
    monkeypatch.setenv("SAGA_CODER_AGENTIC", "true")
    monkeypatch.setenv("SAGA_AGENT_MAX_TURNS", "7")
    monkeypatch.setenv("SAGA_OUTPUT_ROOT", str(tmp_path))

    configured = Settings.from_environment()

    assert configured.coder_model == "test-coder"
    assert configured.coder_agentic is True
    assert configured.agent_max_turns == 7
    assert configured.output_root == str(tmp_path)


def test_invalid_numeric_setting_has_a_useful_error(monkeypatch):
    monkeypatch.setenv("SAGA_VISION_TIMEOUT", "forever")

    try:
        Settings.from_environment()
    except ValueError as exc:
        assert "SAGA_VISION_TIMEOUT must be a number" in str(exc)
    else:
        raise AssertionError("invalid timeout was accepted")
