from saga.config import Settings


def test_settings_read_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGA_CODER_MODEL", "test-coder")
    monkeypatch.setenv("SAGA_CODER_AGENTIC", "true")
    monkeypatch.setenv("SAGA_AGENT_MAX_TURNS", "7")
    monkeypatch.setenv("SAGA_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setenv("SAGA_VIDEO_QA", "true")
    monkeypatch.setenv("SAGA_VIDEO_MODEL", "test-video-model")
    monkeypatch.setenv("SAGA_ARCHITECT_MODEL", "test-architect")
    monkeypatch.setenv("SAGA_ARCHITECT_TIMEOUT", "42")
    monkeypatch.setenv("SAGA_INCREMENTAL_BUILD", "true")
    monkeypatch.setenv("SAGA_INCREMENTAL_MAX_SYSTEMS", "4")
    monkeypatch.setenv("SAGA_INCREMENTAL_MAX_ATTEMPTS", "3")

    configured = Settings.from_environment()

    assert configured.coder_model == "test-coder"
    assert configured.coder_agentic is True
    assert configured.agent_max_turns == 7
    assert configured.output_root == str(tmp_path)
    assert configured.video_qa_enabled is True
    assert configured.video_model == "test-video-model"
    assert configured.architect_model == "test-architect"
    assert configured.architect_timeout == 42.0
    assert configured.incremental_build is True
    assert configured.incremental_max_systems == 4
    assert configured.incremental_max_attempts == 3


def test_invalid_numeric_setting_has_a_useful_error(monkeypatch):
    monkeypatch.setenv("SAGA_VISION_TIMEOUT", "forever")

    try:
        Settings.from_environment()
    except ValueError as exc:
        assert "SAGA_VISION_TIMEOUT must be a number" in str(exc)
    else:
        raise AssertionError("invalid timeout was accepted")


def test_video_qa_is_opt_in(monkeypatch):
    monkeypatch.delenv("SAGA_VIDEO_QA", raising=False)

    assert Settings.from_environment().video_qa_enabled is False
