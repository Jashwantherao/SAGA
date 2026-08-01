import subprocess

from saga.agents.qa_agent import (
    _capture_gameplay_video,
    _find_errors,
    _record_attempt,
    _run_dot_maze_objective_probe,
    _run_maze_objective_probe,
    _run_objective_probe,
    _validate_video_verdict,
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
