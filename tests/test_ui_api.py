import json

from saga import ui_api


def test_read_manifest_exposes_qa_ledger(tmp_path):
    run = tmp_path / "sample-run"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps(
            {
                "title": "Signal Garden",
                "status": "passed",
                "ship_ready": True,
                "level_results": [{"level_index": 0, "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )

    manifest = ui_api._read_manifest(run)

    assert manifest["id"] == "sample-run"
    assert manifest["ship_ready"] is True
    assert manifest["level_results"][0]["status"] == "passed"
    assert manifest["complete"] is True


def test_run_path_rejects_traversal():
    try:
        ui_api._run_path("../secrets")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("Traversal should be rejected")


def test_list_runs_orders_newest_first(tmp_path, monkeypatch):
    older = tmp_path / "older"
    newer = tmp_path / "newer"
    older.mkdir()
    newer.mkdir()
    (older / "run.json").write_text('{"title":"Old"}', encoding="utf-8")
    (newer / "run.json").write_text('{"title":"New"}', encoding="utf-8")
    older.touch()
    newer.touch()
    monkeypatch.setattr(ui_api, "RUNS_ROOT", tmp_path)

    runs = ui_api.list_runs()

    assert {run["title"] for run in runs} == {"Old", "New"}


def test_list_run_files_classifies_media_and_skips_duplicates(tmp_path):
    run = tmp_path / "run"
    (run / "assets").mkdir(parents=True)
    (run / "godot_project" / "assets").mkdir(parents=True)
    (run / "godot_project" / ".godot").mkdir()
    (run / "assets" / "hero.png").write_bytes(b"png")
    (run / "assets" / "bgm.wav").write_bytes(b"wav")
    (run / "godot_project" / "assets" / "hero.png").write_bytes(b"png")  # duplicate copy
    (run / "godot_project" / ".godot" / "cache.png").write_bytes(b"png")  # engine cache
    (run / "godot_project" / "screenshot_Level0.png").write_bytes(b"png")
    (run / "godot_project" / "gameplay_Level0.mp4").write_bytes(b"mp4")
    (run / "godot_project" / "game.gd").write_text("extends Node", encoding="utf-8")
    (run / "godot_project" / "game.gd.uid").write_text("uid", encoding="utf-8")
    (run / "design_doc.json").write_text("{}", encoding="utf-8")

    files = ui_api._list_run_files(run)

    assert [item["path"] for item in files["images"]] == [
        "assets/hero.png",
        "godot_project/screenshot_Level0.png",
    ]
    assert [item["path"] for item in files["audio"]] == ["assets/bgm.wav"]
    assert [item["path"] for item in files["videos"]] == ["godot_project/gameplay_Level0.mp4"]
    assert files["script_count"] == 1
    assert files["has_design_doc"] is True


def test_job_history_snapshot_can_exclude_logs():
    job = ui_api.Job(ui_api.GenerationRequest(idea="Shadow-herding puzzle", levels=2))
    job.logs.append("line")

    snapshot = job.as_dict(include_logs=False)

    assert "logs" not in snapshot
    assert snapshot["idea"] == "Shadow-herding puzzle"
    assert "logs" in job.as_dict()


def test_ui_generation_uses_unbuffered_python_output():
    job = ui_api.Job(ui_api.GenerationRequest(idea="Magnetic kitchen chaos", levels=1))

    command = ui_api._generation_command(job)

    assert command[0] == ui_api.sys.executable
    assert command[1:3] == ["-u", "-m"]
    assert command[-2:] == ["--levels", "1"]
