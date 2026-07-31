from types import SimpleNamespace

from saga.doctor import CheckResult, _ffmpeg_check, required_checks_pass


def test_optional_failure_does_not_fail_preflight():
    checks = [
        CheckResult("Godot", True, True, "ok"),
        CheckResult("MusicGen", False, False, "optional"),
    ]
    assert required_checks_pass(checks) is True


def test_required_failure_fails_preflight():
    checks = [
        CheckResult("Godot", False, True, "missing"),
        CheckResult("MusicGen", True, False, "ok"),
    ]
    assert required_checks_pass(checks) is False


def test_video_ffmpeg_check_reports_missing_executable(monkeypatch):
    monkeypatch.setattr(
        "saga.doctor.settings",
        SimpleNamespace(ffmpeg_exe="definitely-missing-ffmpeg"),
    )
    monkeypatch.setattr("saga.doctor.shutil.which", lambda _name: None)

    result = _ffmpeg_check()

    assert result.ok is False
    assert result.required is True
    assert "SAGA_FFMPEG_EXE" in result.detail
