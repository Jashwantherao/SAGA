from pathlib import Path

import saga.workspace as workspace


def test_run_workspaces_are_unique_and_paths_stay_inside(monkeypatch, tmp_path):
    runs_root = tmp_path / "runs"
    monkeypatch.setattr(workspace, "RUNS_ROOT", runs_root)

    first = workspace.create_run_dir()
    second = workspace.create_run_dir()

    assert first != second
    assert first.parent == runs_root
    assert second.parent == runs_root
    state = {"run_dir": str(first)}
    assert workspace.assets_dir(state) == first / "assets"
    assert workspace.project_dir(state) == first / "godot_project"


def test_missing_run_dir_is_rejected():
    try:
        workspace.run_dir({})
    except ValueError as exc:
        assert "no run_dir" in str(exc)
    else:
        raise AssertionError("missing run_dir was accepted")
