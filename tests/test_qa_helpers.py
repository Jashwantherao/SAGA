import subprocess

from saga.agents.qa_agent import (
    _capture_gameplay_video,
    _find_errors,
    _reconcile_visual_evidence,
    _record_attempt,
    _run_dot_maze_objective_probe,
    _run_maze_objective_probe,
    _run_objective_probe,
    _validate_video_verdict,
    _vision_review,
    _video_review,
    qa_agent,
)


def _objective_metrics(
    *, seconds=4.0, progress=4, stall=90, stuck="false", restart="not_tested", deaths=0
):
    return (
        f"[OBJECTIVE_METRICS] completion_seconds={seconds} progress_events={progress} "
        f"max_stall_frames={stall} stuck={stuck} restart={restart} deaths={deaths}\n"
    )


def _switch_metrics(
    *, length=4, activations=6, wrong="true", reload="true", progress=4
):
    return (
        f"[SWITCH_METRICS] sequence_length={length} activations={activations} "
        f"wrong_order_reset={wrong} clean_reload={reload} correct_progress={progress}\n"
    )


def _survival_metrics(
    *, lives=3, damage=3, single="true", lose="true", restart="true", win="true"
):
    return (
        f"[SURVIVAL_METRICS] starting_lives={lives} damage_events={damage} "
        f"single_hit_exact={single} lose_verified={lose} "
        f"clean_restart={restart} timer_win={win}\n"
    )


def _depletion_metrics(
    *, resource_max=100.0, drained=0.5, refilled=0.5, drain="true",
    refill="true", lose="true", restart="true", win="true"
):
    return (
        f"[DEPLETION_METRICS] resource_max={resource_max} drained_amount={drained} "
        f"refilled_amount={refilled} drain_verified={drain} refill_verified={refill} "
        f"lose_verified={lose} clean_restart={restart} timer_win={win}\n"
    )


def _hybrid_metrics(**overrides):
    values = dict(drain_first=2.5, drain_second=2.6, refill=0.4, fuel_used=0.3,
                  hazard_damage=15.0, ramp="true", refill_ok="true", fuel_ok="true",
                  hazard_ok="true", lose="true", restart_ok="true", timer_win="true")
    values.update(overrides)
    return ("[HYBRID_METRICS] drain_first={drain_first} drain_second={drain_second} refill={refill} "
            "fuel_used={fuel_used} hazard_damage={hazard_damage} ramp={ramp} refill_ok={refill_ok} "
            "fuel_ok={fuel_ok} hazard_ok={hazard_ok} lose={lose} restart_ok={restart_ok} timer_win={timer_win}\n").format(**values)


def _capture_metrics(**overrides):
    values = dict(
        capture_gain=1.0,
        decay=1.0,
        owned=3,
        zones=3,
        capture="true",
        contest="true",
        ownership="true",
        win="true",
    )
    values.update(overrides)
    return (
        "[CAPTURE_METRICS] capture_gain={capture_gain} decay={decay} "
        "owned={owned} zones={zones} capture={capture} contest={contest} "
        "ownership={ownership} win={win}\n"
    ).format(**values)


def _herd_metrics(**overrides):
    values = dict(
        still_drift=0.0,
        flee_distance=3.0,
        goal_gain=500.0,
        settled=3,
        creatures=3,
        still="true",
        flee="true",
        settle="true",
        persistent="true",
        win="true",
    )
    values.update(overrides)
    return (
        "[HERD_METRICS] still_drift={still_drift} flee_distance={flee_distance} "
        "goal_gain={goal_gain} settled={settled} creatures={creatures} still={still} "
        "flee={flee} settle={settle} persistent={persistent} win={win}\n"
    ).format(**values)


def test_find_errors_deduplicates_and_keeps_location():
    output = """
SCRIPT ERROR: Invalid call
    at: res://Level_0.gd:12
SCRIPT ERROR: Invalid call
    at: res://Level_0.gd:12
"""
    assert _find_errors(output) == [
        "SCRIPT ERROR: Invalid call (at: res://Level_0.gd:12)"
    ]


def test_find_errors_ignores_benign_shutdown_noise():
    assert _find_errors("ERROR: Resources still in use at exit") == []


def test_level_ledger_keeps_failed_and_successful_attempts():
    state = {
        "design_doc": {"levels": [{"name": "First Light"}]},
        "current_level": 0,
        "retry_count": 0,
        "coder_model": "test-model",
    }
    first = _record_attempt(
        state,
        passed=False,
        stage="playability",
        errors=["player did not move"],
    )
    state.update({"level_results": first, "retry_count": 1})
    second = _record_attempt(
        state,
        passed=True,
        stage="complete",
        screenshot_path="level0.png",
    )

    assert second[0]["status"] == "passed"
    assert second[0]["retry_count"] == 1
    assert [attempt["status"] for attempt in second[0]["attempts"]] == [
        "failed",
        "passed",
    ]
    assert second[0]["attempts"][0]["errors"] == ["player did not move"]


def test_rejected_repair_records_ledger_without_running_godot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Godot must not run")),
    )
    state = {
        "godot_project_path": str(tmp_path),
        "current_level": 0,
        "retry_count": 2,
        "design_doc": {"levels": [{"name": "Neon Circuit"}]},
        "level_results": [],
        "coder_model": "deepseek-v4-pro",
        "repair_rejected": True,
        "repair_validation_errors": ["Candidate validation: SCRIPT ERROR"],
    }

    result = qa_agent(state)

    assert result["retry_count"] == 3
    assert result["repair_rejected"] is False
    assert result["level_results"][0]["attempts"][-1]["stage"] == "repair_gate"
    assert result["level_results"][0]["qa_errors"] == [
        "Candidate validation: SCRIPT ERROR"
    ]


def test_unresolved_playability_failure_never_becomes_a_pass(monkeypatch, tmp_path):
    script = tmp_path / "Level_0.gd"
    script.write_text("extends Node2D", encoding="utf-8")

    def fake_run(args, cwd=None, timeout=60):
        output = ""
        if "--autoplay" in args:
            # Input motion is not 1.5x the busy idle scene, so this is a
            # playability failure even though this is already a retry.
            output = "[AUTOPLAY] idle_rate=5.0 input_rate=6.0 label_states=2"
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr("saga.agents.qa_agent._run", fake_run)
    state = {
        "godot_project_path": str(tmp_path),
        "design_doc": {"mechanic_template": "dot_maze", "levels": [{"name": "L1"}]},
        "current_level": 0,
        "retry_count": 1,
        "level_results": [
            {
                "level_index": 0,
                "status": "failed",
                "attempts": [{"attempt": 1, "status": "failed"}],
            }
        ],
    }

    result = qa_agent(state)

    assert result["qa_passed"] is False
    assert result["retry_count"] == 2
    assert result["level_results"][0]["status"] == "failed"
    assert len(result["level_results"][0]["attempts"]) == 2
    assert result["level_results"][0]["attempts"][-1]["stage"] == "playability"


def test_harness_parse_error_blocks_without_coder_triage(monkeypatch, tmp_path):
    (tmp_path / "Level_0.gd").write_text("extends Node2D", encoding="utf-8")
    output = (
        'SCRIPT ERROR: Parse Error: Unexpected identifier "get_tree" in class body. '
        "(at: GDScript::reload (res://autoplay.gd:95))"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )
    state = {
        "godot_project_path": str(tmp_path),
        "design_doc": {"mechanic_template": "collect", "levels": [{"name": "L1"}]},
        "current_level": 0,
        "retry_count": 0,
    }

    result = qa_agent(state)

    assert result["qa_passed"] is False
    assert result["ship_blocked"] is True
    assert result["level_results"][0]["status"] == "blocked"
    assert result["level_results"][0]["attempts"][-1]["stage"] == "harness"


def test_dot_maze_objective_probe_parses_complete_win(monkeypatch):
    output = _objective_metrics(progress=42) + (
        "[OBJECTIVE] status=passed template=dot_maze reason=none "
        "collected=42 total=42 remaining=0 frames=1800"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_dot_maze_objective_probe("project", "scene")

    assert errors == []
    assert blocked is False
    assert result == {
        "status": "passed",
        "template": "dot_maze",
        "reason": "none",
        "collected": 42,
        "total": 42,
        "remaining": 0,
        "frames": 1800,
        "completion_seconds": 4.0,
        "progress_events": 42,
        "max_stall_frames": 90,
        "stuck": False,
        "restart_status": "not_tested",
        "deaths": 0,
        "completion_score": 100,
    }


def test_maze_chase_objective_probe_passes_template_to_godot(monkeypatch):
    output = _objective_metrics() + (
        "[OBJECTIVE] status=passed template=maze_chase reason=none "
        "collected=4 total=4 remaining=0 frames=240"
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr("saga.agents.qa_agent._run", fake_run)

    result, errors, blocked = _run_maze_objective_probe(
        "project", "scene", "maze_chase"
    )

    assert errors == []
    assert blocked is False
    assert result["template"] == "maze_chase"
    assert "--objective-template=maze_chase" in calls[0]


def test_objective_probe_template_mismatch_blocks_shipping(monkeypatch):
    output = _objective_metrics() + (
        "[OBJECTIVE] status=passed template=dot_maze reason=none "
        "collected=4 total=4 remaining=0 frames=240"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_maze_objective_probe(
        "project", "scene", "maze_chase"
    )

    assert result["template"] == "dot_maze"
    assert blocked is True
    assert "while testing 'maze_chase'" in errors[0]


def test_dot_maze_unreachable_pickup_is_a_generated_level_failure(monkeypatch):
    output = _objective_metrics(progress=8, stuck="true") + (
        "[OBJECTIVE_DETAIL] node=@Area2D@54 position=(380.0,160.0) ignored=false\n"
        "[OBJECTIVE] status=failed template=dot_maze reason=unreachable_pickup "
        "collected=8 total=9 remaining=1 frames=900"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_dot_maze_objective_probe("project", "scene")

    assert result["reason"] == "unreachable_pickup"
    assert result["blocked_positions"] == [[380.0, 160.0]]
    assert blocked is False
    assert "collected 8/9" in errors[0]
    assert "(380, 160)" in errors[0]


def test_collect_objective_reports_completion_quality(monkeypatch):
    output = _objective_metrics(
        seconds=3.25, progress=3, stall=72, restart="not_applicable"
    ) + (
        "[OBJECTIVE] status=passed template=collect reason=none "
        "collected=3 total=3 remaining=0 frames=195"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe("project", "scene", "collect")

    assert errors == []
    assert blocked is False
    assert result["completion_seconds"] == 3.25
    assert result["progress_events"] == 3
    assert result["max_stall_frames"] == 72
    assert result["stuck"] is False
    assert result["restart_status"] == "not_applicable"
    assert result["completion_score"] == 100


def test_collect_completion_over_quality_ceiling_requests_generated_fix(monkeypatch):
    output = _objective_metrics(
        seconds=61.0, progress=3, restart="not_applicable"
    ) + (
        "[OBJECTIVE] status=passed template=collect reason=none "
        "collected=3 total=3 remaining=0 frames=3660"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe("project", "scene", "collect")

    assert result["completion_score"] == 100
    assert blocked is False
    assert "quality ceiling" in errors[0]


def test_missing_objective_metrics_blocks_shipping(monkeypatch):
    output = (
        "[OBJECTIVE] status=passed template=collect reason=none "
        "collected=3 total=3 remaining=0 frames=195"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe("project", "scene", "collect")

    assert result["status"] == "passed"
    assert blocked is True
    assert "no metrics verdict" in errors[0]


def test_ordered_switch_probe_verifies_wrong_order_reload_and_win(monkeypatch):
    output = (
        _objective_metrics(
            seconds=8.5, progress=6, stall=110, restart="passed"
        )
        + _switch_metrics()
        + "[OBJECTIVE] status=passed template=ordered_switches reason=none "
        "collected=4 total=4 remaining=0 frames=510"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe(
        "project", "scene", "ordered_switches"
    )

    assert errors == []
    assert blocked is False
    assert result["wrong_order_reset"] is True
    assert result["clean_reload"] is True
    assert result["correct_progress"] == 4
    assert result["sequence_length"] == 4
    assert result["activations"] == 6
    assert result["restart_status"] == "passed"
    assert result["completion_score"] == 100


def test_ordered_switch_missing_wrong_reset_is_generated_failure(monkeypatch):
    output = (
        _objective_metrics(seconds=8.5, progress=5, restart="passed")
        + _switch_metrics(activations=5, wrong="false")
        + "[OBJECTIVE] status=passed template=ordered_switches reason=none "
        "collected=4 total=4 remaining=0 frames=510"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe(
        "project", "scene", "ordered_switches"
    )

    assert result["wrong_order_reset"] is False
    assert blocked is False
    assert "did not reset" in errors[0]


def test_ordered_switch_missing_sequence_metrics_blocks_shipping(monkeypatch):
    output = _objective_metrics(seconds=8.5, progress=6, restart="passed") + (
        "[OBJECTIVE] status=passed template=ordered_switches reason=none "
        "collected=4 total=4 remaining=0 frames=510"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    _result, errors, blocked = _run_objective_probe(
        "project", "scene", "ordered_switches"
    )

    assert blocked is True
    assert "no sequence metrics" in errors[0]


def test_survival_probe_verifies_damage_lose_restart_and_timer_win(monkeypatch):
    output = (
        _objective_metrics(
            seconds=5.2, progress=4, stall=100, restart="passed", deaths=1
        )
        + _survival_metrics()
        + "[OBJECTIVE] status=passed template=survive_hazards reason=none "
        "collected=4 total=4 remaining=0 frames=312"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe(
        "project", "scene", "survive_hazards"
    )

    assert errors == []
    assert blocked is False
    assert result["single_hit_exact"] is True
    assert result["lose_verified"] is True
    assert result["clean_restart"] is True
    assert result["timer_win_verified"] is True
    assert result["damage_events"] == result["starting_lives"] == 3
    assert result["deaths"] == 1
    assert result["restart_status"] == "passed"
    assert result["completion_score"] == 100


def test_survival_collision_failure_is_a_generated_game_defect(monkeypatch):
    output = (
        _objective_metrics(
            seconds=2.0, progress=0, stall=120, stuck="true", restart="failed"
        )
        + _survival_metrics(damage=0, single="false", lose="false", restart="false", win="false")
        + "[OBJECTIVE_DETAIL] node=Hazard position=(400.0,200.0) ignored=false\n"
        + "[OBJECTIVE] status=failed template=survive_hazards "
        "reason=collision_did_not_damage collected=0 total=4 remaining=4 frames=120"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe(
        "project", "scene", "survive_hazards"
    )

    assert result["reason"] == "collision_did_not_damage"
    assert result["blocked_positions"] == [[400.0, 200.0]]
    assert blocked is False
    assert "Collision damage" in errors[0]
    assert "Hazard under test" in errors[0]


def test_survival_missing_metrics_blocks_shipping(monkeypatch):
    output = _objective_metrics(
        seconds=5.2, progress=4, restart="passed", deaths=1
    ) + (
        "[OBJECTIVE] status=passed template=survive_hazards reason=none "
        "collected=4 total=4 remaining=0 frames=312"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    _result, errors, blocked = _run_objective_probe(
        "project", "scene", "survive_hazards"
    )

    assert blocked is True
    assert "no survival metrics" in errors[0]


def test_survival_harness_error_blocks_instead_of_requesting_coder_fix(monkeypatch):
    output = (
        'SCRIPT ERROR: Parse Error: Unexpected identifier. '
        '(at: GDScript::reload (res://survival_probe.gd:10))'
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe(
        "project", "scene", "survive_hazards"
    )

    assert result is None
    assert blocked is True
    assert "survival_probe.gd" in errors[0]


def test_depletion_probe_verifies_drain_refill_lose_restart_and_win(monkeypatch):
    output = (
        _objective_metrics(
            seconds=4.5, progress=5, stall=80, restart="passed", deaths=1
        )
        + _depletion_metrics()
        + "[OBJECTIVE] status=passed template=depletion reason=none "
        "collected=5 total=5 remaining=0 frames=270"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe("project", "scene", "depletion")

    assert errors == []
    assert blocked is False
    assert result["drain_verified"] is True
    assert result["refill_verified"] is True
    assert result["lose_verified"] is True
    assert result["clean_restart"] is True
    assert result["timer_win_verified"] is True
    assert result["drained_amount"] > 0
    assert result["refilled_amount"] > 0
    assert result["deaths"] == 1
    assert result["completion_score"] == 100


def test_depletion_refill_failure_is_a_generated_game_defect(monkeypatch):
    output = (
        _objective_metrics(
            seconds=3.0, progress=1, stall=180, stuck="true", restart="failed"
        )
        + _depletion_metrics(refilled=0.0, refill="false", lose="false", restart="false", win="false")
        + "[OBJECTIVE_DETAIL] node=RefillZone position=(512.0,150.0) ignored=false\n"
        + "[OBJECTIVE] status=failed template=depletion reason=resource_did_not_refill "
        "collected=1 total=5 remaining=4 frames=180"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe("project", "scene", "depletion")

    assert result["reason"] == "resource_did_not_refill"
    assert blocked is False
    assert "Resource must drain" in errors[0]
    assert "Refill zone under test" in errors[0]


def test_depletion_missing_resource_metrics_blocks_shipping(monkeypatch):
    output = _objective_metrics(
        seconds=4.5, progress=5, restart="passed", deaths=1
    ) + (
        "[OBJECTIVE] status=passed template=depletion reason=none "
        "collected=5 total=5 remaining=0 frames=270"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    _result, errors, blocked = _run_objective_probe("project", "scene", "depletion")

    assert blocked is True
    assert "no resource metrics" in errors[0]


def test_hybrid_probe_verifies_every_combined_milestone(monkeypatch):
    output = (_objective_metrics(seconds=6, progress=7, restart="passed", deaths=1)
              + _hybrid_metrics()
              + "[OBJECTIVE] status=passed template=survive_and_deplete reason=none collected=7 total=7 remaining=0 frames=360")
    monkeypatch.setattr("saga.agents.qa_agent._run", lambda *a, **k: subprocess.CompletedProcess(a, 0, output, ""))
    result, errors, blocked = _run_objective_probe("project", "scene", "survive_and_deplete")
    assert errors == [] and blocked is False
    assert result["drain_second"] > result["drain_first"]
    assert result["fuel_used"] > 0 and result["hazard_damage"] > 0
    assert result["completion_score"] == 100


def test_hybrid_missing_metrics_blocks_shipping(monkeypatch):
    output = _objective_metrics(seconds=6, progress=7, restart="passed", deaths=1) + "[OBJECTIVE] status=passed template=survive_and_deplete reason=none collected=7 total=7 remaining=0 frames=360"
    monkeypatch.setattr("saga.agents.qa_agent._run", lambda *a, **k: subprocess.CompletedProcess(a, 0, output, ""))
    _result, errors, blocked = _run_objective_probe("project", "scene", "survive_and_deplete")
    assert blocked is True and "no hybrid metrics" in errors[0]


def test_capture_probe_verifies_capture_contest_ownership_and_win(monkeypatch):
    output = (
        _objective_metrics(
            seconds=8, progress=4, restart="not_applicable", deaths=0
        )
        + _capture_metrics()
        + "[OBJECTIVE] status=passed template=capture_zones reason=none "
        "collected=4 total=4 remaining=0 frames=480"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe(
        "project", "scene", "capture_zones"
    )

    assert errors == [] and blocked is False
    assert result["capture_gain"] > 0 and result["decay_amount"] > 0
    assert result["owned_zones"] == result["total_zones"] == 3
    assert result["completion_score"] == 100


def test_capture_missing_metrics_blocks_shipping(monkeypatch):
    output = _objective_metrics(
        seconds=8, progress=4, restart="not_applicable", deaths=0
    ) + (
        "[OBJECTIVE] status=passed template=capture_zones reason=none "
        "collected=4 total=4 remaining=0 frames=480"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    _result, errors, blocked = _run_objective_probe(
        "project", "scene", "capture_zones"
    )

    assert blocked is True
    assert "no capture metrics" in errors[0]


def test_capture_behavior_failure_is_repairable_not_blocked(monkeypatch):
    output = (
        _objective_metrics(
            seconds=6, progress=1, stuck="true", restart="not_applicable", deaths=0
        )
        + _capture_metrics(
            decay=0.0,
            owned=1,
            capture="true",
            contest="false",
            ownership="false",
            win="false",
        )
        + "[OBJECTIVE] status=failed template=capture_zones "
        "reason=contest_did_not_decay collected=1 total=4 remaining=3 frames=360"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    _result, errors, blocked = _run_objective_probe(
        "project", "scene", "capture_zones"
    )

    assert blocked is False
    assert "contest_did_not_decay" in errors[0]


def test_herd_probe_verifies_still_flee_settle_persistence_and_win(monkeypatch):
    output = (
        _objective_metrics(
            seconds=22, progress=5, restart="not_applicable", deaths=0
        )
        + _herd_metrics()
        + "[OBJECTIVE] status=passed template=herd_to_goal reason=none "
        "collected=5 total=5 remaining=0 frames=1320"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    result, errors, blocked = _run_objective_probe(
        "project", "scene", "herd_to_goal"
    )

    assert errors == [] and blocked is False
    assert result["still_drift"] == 0
    assert result["flee_distance"] > 0 and result["goal_gain"] > 0
    assert result["settled_creatures"] == result["total_creatures"] == 3
    assert result["completion_score"] == 100


def test_herd_missing_metrics_blocks_shipping(monkeypatch):
    output = _objective_metrics(
        seconds=22, progress=5, restart="not_applicable", deaths=0
    ) + (
        "[OBJECTIVE] status=passed template=herd_to_goal reason=none "
        "collected=5 total=5 remaining=0 frames=1320"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    _result, errors, blocked = _run_objective_probe(
        "project", "scene", "herd_to_goal"
    )

    assert blocked is True
    assert "no herd metrics" in errors[0]


def test_herd_behavior_failure_is_repairable_not_blocked(monkeypatch):
    output = (
        _objective_metrics(
            seconds=12, progress=1, stuck="true", restart="not_applicable", deaths=0
        )
        + _herd_metrics(
            flee_distance=0.0,
            goal_gain=0.0,
            settled=0,
            still="true",
            flee="false",
            settle="false",
            persistent="false",
            win="false",
        )
        + "[OBJECTIVE] status=failed template=herd_to_goal "
        "reason=creature_did_not_flee_toward_goal collected=1 total=5 remaining=4 frames=720"
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )

    _result, errors, blocked = _run_objective_probe(
        "project", "scene", "herd_to_goal"
    )

    assert blocked is False
    assert "creature_did_not_flee_toward_goal" in errors[0]


def test_missing_objective_verdict_blocks_shipping(monkeypatch):
    monkeypatch.setattr(
        "saga.agents.qa_agent._run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )

    result, errors, blocked = _run_dot_maze_objective_probe("project", "scene")

    assert result is None
    assert blocked is True
    assert "produced no verdict" in errors[0]


def test_gameplay_capture_records_autoplay_and_transcodes_mp4(monkeypatch, tmp_path):
    godot_calls = []
    ffmpeg_calls = []

    def fake_godot(args, **kwargs):
        godot_calls.append(args)
        (tmp_path / "gameplay_Level0.avi").write_bytes(b"avi")
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_ffmpeg(args, **kwargs):
        ffmpeg_calls.append(args)
        (tmp_path / "gameplay_Level0.mp4").write_bytes(b"mp4")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("saga.agents.qa_agent._run", fake_godot)
    monkeypatch.setattr("saga.agents.qa_agent.subprocess.run", fake_ffmpeg)

    path, errors, blocked = _capture_gameplay_video(
        str(tmp_path), "res://Level_0.tscn", 0
    )

    assert errors == []
    assert blocked is False
    assert path == str(tmp_path / "gameplay_Level0.mp4")
    assert "--write-movie" in godot_calls[0]
    assert "--autoplay" in godot_calls[0]
    assert "libx264" in ffmpeg_calls[0]
    assert not (tmp_path / "gameplay_Level0.avi").exists()


def _video_verdict(**overrides):
    result = {
        "player_visible": True,
        "player_motion": "moves",
        "movement_facing": "correct",
        "animation": "animated",
        "hud_readable": True,
        "scene_stable": True,
        "code_defects": [],
        "art_advisories": [],
        "evidence": "The player traverses the scene in four directions.",
    }
    result.update(overrides)
    return result


def test_video_review_gates_reversed_facing(monkeypatch):
    monkeypatch.setattr(
        "saga.agents.qa_agent._video_raw",
        lambda *_args: _video_verdict(movement_facing="reversed"),
    )

    result, gating, advisory, error = _video_review("game.mp4", {})

    assert result["status"] == "failed"
    assert advisory == []
    assert error is None
    assert "faces opposite" in gating[0]


def test_video_visibility_overrules_false_missing_hero_screenshot():
    screenshot = ["Visual defect: the hero sprite is not visible on screen."]

    gating, notes = _reconcile_visual_evidence(
        screenshot, [], _video_verdict(player_visible=True)
    )

    assert gating == []
    assert "contradicted" in notes[0]
    assert "video shows the player" in notes[0]


def test_video_readability_overrules_false_clipped_hud_screenshot():
    screenshot = ["Visual defect: on-screen text is clipped or hidden."]

    gating, notes = _reconcile_visual_evidence(
        screenshot, [], _video_verdict(hud_readable=True)
    )

    assert gating == []
    assert "readable HUD" in notes[0]


def test_uncontradicted_screenshot_defect_remains_gating():
    screenshot = ["Visual defect: the background does not fill the screen."]

    gating, notes = _reconcile_visual_evidence(
        screenshot, ["Vision (advisory): simple art"], _video_verdict()
    )

    assert gating == screenshot
    assert notes == screenshot + ["Vision (advisory): simple art"]


def test_free_form_broken_visual_claim_is_advisory(monkeypatch):
    monkeypatch.setattr(
        "saga.agents.qa_agent._vision_raw",
        lambda *_args: {
            "hero_visible": True,
            "background_fills_screen": True,
            "text_clipped": False,
            "placeholder_art": None,
            "looks_broken": "the composition feels unfinished",
        },
    )

    gating, advisory = _vision_review("frame.png", {})

    assert gating == []
    assert advisory == ["Vision (advisory): the composition feels unfinished"]


def test_video_verdict_requires_complete_structured_evidence():
    problems = _validate_video_verdict({"player_visible": True})

    assert "player_motion" in " ".join(problems)
    assert "evidence must be a string" in problems


def test_enabled_video_gate_blocks_on_missing_nvidia_verdict(monkeypatch, tmp_path):
    (tmp_path / "Level_0.gd").write_text("extends Node2D", encoding="utf-8")

    def fake_run(args, **kwargs):
        if "--autoplay" in args:
            output = "[AUTOPLAY] idle_rate=1.0 input_rate=3.0 label_states=2"
        elif "--objective-probe" in args:
            output = _objective_metrics(
                seconds=3.0, progress=3, restart="not_applicable"
            ) + (
                "[OBJECTIVE] status=passed template=collect reason=none "
                "collected=3 total=3 remaining=0 frames=180"
            )
        else:
            output = ""
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr("saga.agents.qa_agent.VIDEO_QA_ENABLED", True)
    monkeypatch.setattr("saga.agents.qa_agent._run", fake_run)
    monkeypatch.setattr(
        "saga.agents.qa_agent._capture_gameplay_video",
        lambda *_args: (str(tmp_path / "gameplay_Level0.mp4"), [], False),
    )
    monkeypatch.setattr(
        "saga.agents.qa_agent._video_review",
        lambda *_args: (None, [], [], "invalid response"),
    )
    state = {
        "godot_project_path": str(tmp_path),
        "design_doc": {"mechanic_template": "collect", "levels": [{"name": "L1"}]},
        "current_level": 0,
        "retry_count": 0,
    }

    result = qa_agent(state)

    assert result["ship_blocked"] is True
    assert result["level_results"][0]["attempts"][-1]["stage"] == "video_qa_probe"
    assert result["gameplay_video_path"].endswith("gameplay_Level0.mp4")
