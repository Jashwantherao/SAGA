from saga.experience import evaluate_objective_personas


def test_classic_objective_evidence_is_normalized_for_four_personas():
    result = evaluate_objective_personas(
        "capture_zones",
        {
            "status": "passed",
            "collected": 4,
            "total": 4,
            "remaining": 0,
            "progress_events": 4,
            "total_zones": 4,
            "completion_seconds": 18.0,
            "max_stall_frames": 12,
            "stuck": False,
            "restart_status": "not_applicable",
            "deaths": 0,
        },
    )

    assert set(result["personas"]) == {
        "achiever", "explorer", "survivor", "speedrunner"
    }
    assert result["passed"] is True
    assert result["telemetry"]["completion_seconds"] == 18.0


def test_persona_evidence_cannot_hide_a_failed_or_stuck_objective():
    result = evaluate_objective_personas(
        "collect",
        {
            "status": "failed",
            "collected": 4,
            "total": 5,
            "remaining": 1,
            "progress_events": 4,
            "completion_seconds": 90.0,
            "max_stall_frames": 900,
            "stuck": True,
            "restart_status": "not_applicable",
            "deaths": 0,
        },
    )

    assert result["passed"] is False
    assert not any(verdict["passed"] for verdict in result["personas"].values())
