from saga.main import assess_ship_status


def _result(level_results, *, qa_passed=True, blocked=False):
    return {
        "design_doc": {"levels": [{"name": "L1"}, {"name": "L2"}]},
        "qa_passed": qa_passed,
        "ship_blocked": blocked,
        "level_results": level_results,
    }


def test_every_designed_level_needs_a_clean_ledger_entry():
    status, ready = assess_ship_status(
        _result([{"level_index": 1, "status": "passed"}])
    )
    assert (status, ready) == ("failed", False)


def test_failed_earlier_level_cannot_be_hidden_by_final_success():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "failed"},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )
    assert (status, ready) == ("failed", False)


def test_advisories_are_explicit_but_remain_shippable():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "passed", "vision_notes": ["placeholder"]},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )
    assert (status, ready) == ("passed_with_warnings", True)


def test_clean_complete_ledger_passes():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "passed"},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )
    assert (status, ready) == ("passed", True)


def test_required_probe_failure_blocks_shipping():
    status, ready = assess_ship_status(_result([], qa_passed=False, blocked=True))
    assert (status, ready) == ("blocked", False)


def test_video_advisory_is_reported_as_a_shippable_warning():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "passed", "video_notes": ["minor art drift"]},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )

    assert (status, ready) == ("passed_with_warnings", True)
