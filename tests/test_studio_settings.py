from saga import studio_settings


def _payload(**overrides):
    data = {
        "designer_backend": "local",
        "designer_model": "designer-local",
        "designer_remote_model": "designer-remote",
        "director_backend": "local",
        "director_model": "",
        "director_remote_model": "director-remote",
        "architect_backend": "nvidia",
        "architect_model": "nvidia/nemotron-3-super-120b-a12b",
        "architect_base_url": "https://integrate.api.nvidia.com/v1/",
        "coder_backend": "deepseek",
        "coder_model": "coder-local",
        "coder_remote_model": "coder-remote",
        "dotmaze_model": "dotmaze-local",
        "vision_backend": "nvidia",
        "vision_model": "vision-local",
        "vision_remote_model": "vision-remote",
        "feedback_backend": "local",
        "feedback_model": "feedback-local",
        "video_qa_enabled": True,
        "video_model": "video-remote",
        "openai_base_url": "https://api.example.test/v1/",
        "vision_base_url": "https://vision.example.test/v1/",
        "stop_gpu_services": False,
        "incremental_build": True,
        "incremental_max_systems": 4,
        "incremental_max_attempts": 3,
        "deepseek_api_key": "new-secret",
    }
    return studio_settings.StudioSettingsUpdate(**(data | overrides))


def test_save_settings_preserves_comments_and_masks_keys(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("# keep me\nSAGA_CODER_MODEL=old\nDEEPSEEK_API_KEY=old-secret\n", encoding="utf-8")
    monkeypatch.setattr(studio_settings, "ENV_PATH", env_path)
    for name in set(studio_settings.ENV_FIELDS.values()) | set(studio_settings.SECRET_FIELDS.values()):
        monkeypatch.delenv(name, raising=False)

    result = studio_settings.save_studio_settings(_payload())

    content = env_path.read_text(encoding="utf-8")
    assert "# keep me" in content
    assert "SAGA_CODER_MODEL=coder-local" in content
    assert "DEEPSEEK_API_KEY=new-secret" in content
    assert result["api_keys"]["deepseek"] is True
    assert "new-secret" not in str(result)


def test_model_urls_are_normalized():
    update = _payload()
    assert update.openai_base_url == "https://api.example.test/v1"
    assert update.vision_base_url == "https://vision.example.test/v1"
    assert update.architect_base_url == "https://integrate.api.nvidia.com/v1"
