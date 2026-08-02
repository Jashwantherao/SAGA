import subprocess
from types import SimpleNamespace

from saga import repair_gate


def _configure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        repair_gate,
        "settings",
        SimpleNamespace(godot_exe="godot-test", output_root=str(tmp_path / "output")),
    )
    project = tmp_path / "project"
    project.mkdir()
    script = project / "Level_0.gd"
    script.write_text("extends Node\n# last known playable\n", encoding="utf-8")
    return project, script


def test_invalid_repair_restores_previous_script(tmp_path, monkeypatch):
    project, script = _configure(tmp_path, monkeypatch)

    def invalid_runner(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            "",
            "SCRIPT ERROR: Cannot convert argument 2 from Vector2 to bool.\n"
            "   at: _process (res://Level_0.gd:247)",
        )

    result = repair_gate.validate_and_promote_repair(
        script,
        "extends Node\n# broken candidate\n",
        project_dir=project,
        scene="res://Level_0.tscn",
        runner=invalid_runner,
    )

    assert result.passed is False
    assert result.restored_previous is True
    assert "last known playable" in script.read_text(encoding="utf-8")
    assert not list(project.glob("*.saga-*"))
    assert "Cannot convert argument 2" in result.errors[0]


def test_valid_repair_is_promoted_atomically(tmp_path, monkeypatch):
    project, script = _configure(tmp_path, monkeypatch)

    def clean_runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, "Godot Engine\n", "")

    result = repair_gate.validate_and_promote_repair(
        script,
        "extends Node\n# validated candidate\n",
        project_dir=project,
        scene="res://Level_0.tscn",
        runner=clean_runner,
    )

    assert result.passed is True
    assert result.restored_previous is False
    assert "validated candidate" in script.read_text(encoding="utf-8")
    assert not list(project.glob("*.saga-*"))


def test_interrupted_repair_checkpoint_is_recovered(tmp_path):
    script = tmp_path / "Level_0.gd"
    script.write_text("broken candidate", encoding="utf-8")
    backup = tmp_path / "Level_0.gd.saga-backup"
    backup.write_text("last known script", encoding="utf-8")
    (tmp_path / "Level_0.gd.saga-candidate").write_text("partial", encoding="utf-8")

    recovered = repair_gate.recover_interrupted_repair(script)

    assert recovered is True
    assert script.read_text(encoding="utf-8") == "last known script"
    assert not backup.exists()
    assert not (tmp_path / "Level_0.gd.saga-candidate").exists()


def test_timeout_rejects_candidate_and_restores_previous(tmp_path, monkeypatch):
    project, script = _configure(tmp_path, monkeypatch)

    def timeout_runner(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, 30, output="starting")

    result = repair_gate.validate_and_promote_repair(
        script,
        "extends Node\n# hanging candidate\n",
        project_dir=project,
        scene="res://Level_0.tscn",
        runner=timeout_runner,
    )

    assert result.passed is False
    assert result.restored_previous is True
    assert "timed out" in result.errors[0]
    assert "last known playable" in script.read_text(encoding="utf-8")
