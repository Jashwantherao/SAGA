import json

import pytest

from saga.benchmark import (
    Job,
    apply_human_ratings,
    build_job_environment,
    build_jobs,
    extract_result,
    load_suite,
    score,
    write_reports,
)


def _suite(tmp_path):
    design = tmp_path / "design.json"
    design.write_text("{}", encoding="utf-8")
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({
        "id": "test",
        "profiles": [{
            "id": "model-a", "provider": "NVIDIA NIM", "model": "vendor/model",
            "env": {"SAGA_OPENAI_KEY_ENV": "NVIDIA_API_KEY"},
        }],
        "cases": [{"id": "case-a", "idea": "idea", "design_doc": "design.json"}],
    }), encoding="utf-8")
    return path


def test_suite_uses_key_names_without_containing_secrets(tmp_path):
    suite = load_suite(_suite(tmp_path))
    assert suite["profiles"][0]["env"]["SAGA_OPENAI_KEY_ENV"] == "NVIDIA_API_KEY"


def test_suite_rejects_arbitrary_environment_mutation(tmp_path):
    path = _suite(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["profiles"][0]["env"]["PATH"] = "bad"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe env"):
        load_suite(path)


def test_jobs_filter_and_repeat(tmp_path):
    suite = load_suite(_suite(tmp_path))
    suite["repetitions"] = 2
    assert [job.job_id for job in build_jobs(suite, {"model-a"}, {"case-a"})] == [
        "model-a__case-a__r1", "model-a__case-a__r2"
    ]


def test_coder_benchmark_does_not_inherit_parent_architect(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGA_ARCHITECT_BACKEND", "nvidia")

    env = build_job_environment({"env": {}}, tmp_path / "output")

    assert env["SAGA_ARCHITECT_BACKEND"] == "deterministic"


def test_profile_can_explicitly_opt_into_model_architect(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGA_ARCHITECT_BACKEND", "deterministic")

    env = build_job_environment(
        {"env": {"SAGA_ARCHITECT_BACKEND": "nvidia"}},
        tmp_path / "output",
    )

    assert env["SAGA_ARCHITECT_BACKEND"] == "nvidia"


def test_score_prioritizes_truthful_ship_and_first_pass():
    value, components = score({
        "ship_ready": True,
        "level_results": [{"status": "passed", "retry_count": 0}],
        "objective_result": {"status": "passed", "completion_score": 1},
        "video_qa_result": {"status": "passed"},
    })
    assert value == 100
    assert components["ship"] == 40


def test_score_gives_pipeline_without_manifest_no_quality_credit():
    value, components = score({})
    assert value == 0
    assert not any(components.values())


def test_reports_are_written(tmp_path):
    result = {
        "candidate_id": "anon-1",
        "profile": "p", "provider": "NVIDIA NIM", "model": "m", "case": "c",
        "repetition": 1, "status": "passed", "ship_ready": True,
        "quality_score": 90, "elapsed_seconds": 10, "first_pass_levels": 1,
        "retries": 0, "repair_gate_rejections": 0, "advisory_count": 0,
        "gdscript_lines": 100, "gdscript_functions": 5,
        "director_score": 88, "content_score": 92, "persona_pass_rate": 1,
        "candidate_count": 24, "content_repairs": 1, "content_signature": "abc",
    }
    write_reports([result], tmp_path)
    assert "| 1 | p |" in (tmp_path / "leaderboard.md").read_text(encoding="utf-8")
    assert (tmp_path / "results.csv").exists()
    packet = (tmp_path / "blind_playtest.csv").read_text(encoding="utf-8")
    assert "anon-1,c" in packet
    assert "model" not in packet


def test_blind_human_ratings_are_normalized_and_preserved(tmp_path):
    ratings = tmp_path / "ratings.csv"
    ratings.write_text(
        "candidate_id,case,playability,fun,visual_coherence,originality,notes\n"
        "anon-1,c,5,4,3,4,Good pacing\n",
        encoding="utf-8",
    )
    results = apply_human_ratings([{"candidate_id": "anon-1"}], ratings)

    assert results[0]["human_score"] == 80
    assert results[0]["human_ratings"]["fun"] == 4
    assert results[0]["human_notes"] == "Good pacing"

    packet = tmp_path / "blind_playtest.csv"
    packet.write_text(ratings.read_text(encoding="utf-8"), encoding="utf-8")
    write_reports([{**results[0],
        "profile": "p", "provider": "NVIDIA NIM", "model": "m", "case": "c",
        "repetition": 1, "status": "passed", "ship_ready": True,
        "quality_score": 90, "elapsed_seconds": 10, "first_pass_levels": 1,
        "retries": 0, "repair_gate_rejections": 0, "advisory_count": 0,
        "gdscript_lines": 100, "gdscript_functions": 5,
    }], tmp_path)
    assert "Good pacing" in packet.read_text(encoding="utf-8")


def test_blind_human_ratings_reject_out_of_range_values(tmp_path):
    ratings = tmp_path / "ratings.csv"
    ratings.write_text(
        "candidate_id,playability,fun,visual_coherence,originality\n"
        "anon-1,6,4,3,4\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="between 1 and 5"):
        apply_human_ratings([{"candidate_id": "anon-1"}], ratings)
