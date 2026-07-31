from saga.doctor import CheckResult, required_checks_pass


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
