from pathlib import Path

from saga.protected_builder import (
    attach_qa_evidence,
    protected_incremental_build,
    script_hash,
)
from saga.repair_gate import RepairValidation


def _blueprint():
    return {
        "systems": [
            {"id": "movement", "kind": "movement", "description": "move", "acceptance": ["moves"]},
            {"id": "hud", "kind": "hud", "description": "show state", "acceptance": ["readable"]},
            {"id": "maze", "kind": "maze", "description": "clear dots", "acceptance": ["all reachable"]},
        ]
    }


def _plan():
    return [
        {"system_id": "movement", "kind": "movement", "depends_on": [], "recommended_model": "local"},
        {"system_id": "hud", "kind": "hud", "depends_on": ["movement"], "recommended_model": "local"},
        {"system_id": "maze", "kind": "maze", "depends_on": ["hud"], "recommended_model": "nemotron"},
    ]


def _promote(script_file: Path, candidate: str, **_kwargs):
    script_file.write_text(candidate, encoding="utf-8")
    return RepairValidation(True, [], False)


def test_systems_integrate_in_dependency_order_and_preserve_hashes(tmp_path):
    script = tmp_path / "Level_0.gd"
    script.write_text("extends Node\n", encoding="utf-8")
    replies = iter(
        [
            "```gdscript\nextends Node\n# movement\n```",
            "```gdscript\nextends Node\n# movement\n# hud\n```",
            "```gdscript\nextends Node\n# movement\n# hud\n# maze\n```",
        ]
    )

    results = protected_incremental_build(
        script_file=script,
        project_dir=tmp_path,
        scene="res://Level_0.tscn",
        level_index=0,
        blueprint=_blueprint(),
        build_plan=_plan(),
        model="executed-model",
        chat=lambda _messages, _model: next(replies),
        extract_gdscript=lambda text: text.split("```gdscript\n", 1)[1].rsplit("```", 1)[0],
        candidate_errors=lambda _candidate: [],
        promote=_promote,
    )

    active = script.read_text(encoding="utf-8")
    assert [item["status"] for item in results] == [
        "baseline_compiles",
        "integrated",
        "integrated",
        "integrated",
    ]
    assert results[-1]["recommended_model"] == "nemotron"
    assert results[-1]["executed_model"] == "executed-model"
    assert results[-1]["active_sha256"] == script_hash(active)
    assert "# maze" in active


def test_rejected_system_blocks_dependents_and_keeps_last_working_script(tmp_path):
    script = tmp_path / "Level_0.gd"
    script.write_text("extends Node\n", encoding="utf-8")
    replies = iter(
        [
            "```gdscript\nextends Node\n# movement\n```",
            "```gdscript\nextends Node\n# movement\nUNSAFE\n```",
        ]
    )

    results = protected_incremental_build(
        script_file=script,
        project_dir=tmp_path,
        scene="res://Level_0.tscn",
        level_index=0,
        blueprint=_blueprint(),
        build_plan=_plan(),
        model="coder",
        chat=lambda _messages, _model: next(replies),
        extract_gdscript=lambda text: text.split("```gdscript\n", 1)[1].rsplit("```", 1)[0],
        candidate_errors=lambda candidate: ["unsafe candidate"] if "UNSAFE" in candidate else [],
        promote=_promote,
    )

    by_id = {item["system_id"]: item for item in results}
    assert by_id["hud"]["status"] == "rejected_static"
    assert by_id["maze"]["status"] == "blocked_dependency"
    assert script.read_text(encoding="utf-8") == "extends Node\n# movement\n"


def test_static_baseline_gets_one_bounded_correction_before_system_work(tmp_path):
    script = tmp_path / "Level_0.gd"
    script.write_text("extends Node\nMISSING_CONTRACT\n", encoding="utf-8")
    replies = iter(
        [
            "```gdscript\nextends Node\n# contract fixed\n```",
            "```gdscript\nextends Node\n# contract fixed\n# movement\n```",
        ]
    )

    results = protected_incremental_build(
        script_file=script,
        project_dir=tmp_path,
        scene="res://Level_0.tscn",
        level_index=0,
        blueprint={"systems": [_blueprint()["systems"][0]]},
        build_plan=[_plan()[0]],
        model="coder",
        chat=lambda _messages, _model: next(replies),
        extract_gdscript=lambda text: text.split("```gdscript\n", 1)[1].rsplit("```", 1)[0],
        candidate_errors=lambda candidate: ["missing contract"] if "MISSING_CONTRACT" in candidate else [],
        promote=_promote,
    )

    assert [item["status"] for item in results] == ["baseline_corrected", "integrated"]
    assert "# movement" in script.read_text(encoding="utf-8")


def test_godot_gate_failure_also_gets_baseline_correction(tmp_path):
    script = tmp_path / "Level_0.gd"
    script.write_text("extends Node\nBROKEN_PARSE\n", encoding="utf-8")
    calls = 0

    def promote_after_correction(script_file: Path, candidate: str, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return RepairValidation(False, ["Parse Error: bad baseline"], True)
        script_file.write_text(candidate, encoding="utf-8")
        return RepairValidation(True, [], False)

    replies = iter(
        [
            "```gdscript\nextends Node\n# parse fixed\n```",
            "```gdscript\nextends Node\n# parse fixed\n# movement\n```",
        ]
    )
    results = protected_incremental_build(
        script_file=script,
        project_dir=tmp_path,
        scene="res://Level_0.tscn",
        level_index=0,
        blueprint={"systems": [_blueprint()["systems"][0]]},
        build_plan=[_plan()[0]],
        model="coder",
        chat=lambda _messages, _model: next(replies),
        extract_gdscript=lambda text: text.split("```gdscript\n", 1)[1].rsplit("```", 1)[0],
        candidate_errors=lambda _candidate: [],
        promote=promote_after_correction,
    )

    assert [item["status"] for item in results] == ["baseline_corrected", "integrated"]
    assert calls == 3


def test_specialist_passes_execute_on_the_routed_model(tmp_path):
    script = tmp_path / "Level_0.gd"
    script.write_text("extends Node\n", encoding="utf-8")
    seen: list[str | None] = []

    def route_chat(_messages, preferred):
        seen.append(preferred)
        executed = preferred if preferred == "nemotron" else "coder"
        return f"```gdscript\nextends Node\n# by {executed} for {len(seen)}\n```", executed

    results = protected_incremental_build(
        script_file=script,
        project_dir=tmp_path,
        scene="res://Level_0.tscn",
        level_index=0,
        blueprint=_blueprint(),
        build_plan=_plan(),
        model="coder",
        chat=lambda _messages, _model: "```gdscript\nextends Node\n```",
        route_chat=route_chat,
        extract_gdscript=lambda text: text.split("```gdscript\n", 1)[1].rsplit("```", 1)[0],
        candidate_errors=lambda _candidate: [],
        promote=_promote,
    )

    assert seen == ["local", "local", "nemotron"]
    by_id = {item["system_id"]: item for item in results}
    assert by_id["maze"]["executed_model"] == "nemotron"
    assert by_id["maze"]["recommended_model"] == "nemotron"
    assert by_id["hud"]["executed_model"] == "coder"


def test_qa_evidence_does_not_overclaim_unobserved_hud_behavior():
    active = "extends Node\n"
    base = [
        {"level_index": 0, "system_id": "movement", "kind": "movement", "status": "integrated", "active_sha256": script_hash(active)},
        {"level_index": 0, "system_id": "hud", "kind": "hud", "status": "integrated", "active_sha256": script_hash(active)},
        {"level_index": 0, "system_id": "maze", "kind": "maze", "status": "integrated", "active_sha256": script_hash(active)},
    ]

    updated = attach_qa_evidence(
        base,
        level_index=0,
        active_script=active,
        objective_result={"status": "passed"},
        video_qa_result=None,
    )

    assert updated[0]["qa_confirmed"] is True
    assert updated[1]["qa_confirmed"] is False
    assert updated[2]["qa_confirmed"] is True
