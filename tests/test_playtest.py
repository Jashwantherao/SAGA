from pathlib import Path

import saga.playtest as playtest


def _state(level_count=3):
    return {
        "user_prompt": "test",
        "design_doc": {"levels": [{"name": f"L{i}"} for i in range(level_count)]},
        "current_level": level_count - 1,
        "director_history": [],
    }


def test_revision_level_zero_targets_every_level():
    assert playtest._revision_levels({"target_level": 0}, 3, 2) == [0, 1, 2]


def test_revision_level_is_one_based():
    assert playtest._revision_levels({"target_level": 2}, 3, 0) == [1]


def test_run_coder_qa_starts_each_selected_level_with_fresh_state(monkeypatch):
    visited = []

    def fake_coder(state):
        visited.append(("coder", state["current_level"], state.get("tune_notes")))
        return {"godot_project_path": "unused", "tune_notes": None}

    def fake_qa(state):
        visited.append(("qa", state["current_level"], state["retry_count"]))
        return {"qa_passed": True, "qa_errors": []}

    monkeypatch.setattr(playtest, "coder", fake_coder)
    monkeypatch.setattr(playtest, "qa_agent", fake_qa)
    state = _state()

    passed = playtest.run_coder_qa(
        state,
        level_indices=[2, 0],
        tune_notes_by_level={2: ["speed: 100 -> 120"]},
    )

    assert passed is True
    assert visited == [
        ("coder", 0, None),
        ("qa", 0, 0),
        ("coder", 2, ["speed: 100 -> 120"]),
        ("qa", 2, 0),
    ]


def test_run_coder_qa_stops_when_required_qa_probe_is_blocked(monkeypatch):
    director_called = False

    def fake_coder(state):
        return {"godot_project_path": "unused"}

    def fake_qa(state):
        return {
            "qa_passed": False,
            "qa_errors": ["autoplay produced no verdict"],
            "retry_count": 1,
            "ship_blocked": True,
        }

    def fake_director(state):
        nonlocal director_called
        director_called = True
        return {}

    monkeypatch.setattr(playtest, "coder", fake_coder)
    monkeypatch.setattr(playtest, "qa_agent", fake_qa)
    monkeypatch.setattr(playtest, "studio_director", fake_director)

    assert playtest.run_coder_qa(_state(level_count=1)) is False
    assert director_called is False


def test_read_level_scripts_uses_generated_project_path(tmp_path):
    project = tmp_path / "godot_project"
    project.mkdir()
    (project / "Level_0.gd").write_text("extends Node2D", encoding="utf-8")
    state = _state(level_count=1)
    state["godot_project_path"] = str(project)

    assert playtest._read_level_scripts(state) == {0: "extends Node2D"}


def test_tune_revision_builds_only_its_target(monkeypatch):
    captured = {}

    def fake_run(state, levels, notes):
        captured["levels"] = levels
        captured["notes"] = notes
        return True

    monkeypatch.setattr(playtest, "run_coder_qa", fake_run)
    state = _state()
    revision = {
        "verdict": "revise",
        "revisions": [
            {
                "route": "tune",
                "delta": "player_speed: 200 -> 240",
                "target_level": 2,
                "target_field": "",
            }
        ],
    }

    assert playtest.apply_revision_doc(state, revision) is False
    assert captured == {
        "levels": [1],
        "notes": {1: ["player_speed: 200 -> 240"]},
    }
