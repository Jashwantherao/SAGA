import hashlib
import json
import subprocess

from saga.capabilities import resolve_game_spec
from saga.capability_evidence import (
    evaluate_capability_coverage,
    runtime_evidence,
    validate_capability_coverage,
)
from saga.game_spec import game_spec_from_legacy_design
from saga.agents import qa_agent


def _lock(*probes):
    body = {
        "lock_version": 1,
        "game_spec_version": 2,
        "game_spec_hash": "a" * 64,
        "title": "Capability Proof",
        "modes": [{
            "id": "primary",
            "perspective": "top_down_2d",
            "entry": True,
            "declared_capabilities": [{"id": "combat.test", "version": 1}],
            "components": [{
                "id": "combat.test",
                "version": 1,
                "implementation": "legacy_generated",
                "manifest_id": "proof_test",
                "component_digest": "b" * 64,
                "declared": True,
                "runtime_files": [],
                "runtime_digests": {},
                "required_probes": list(probes),
            }],
        }],
        "state_owners": {"state.combat_test": "combat.test"},
        "state_facts": {},
        "required_probes": list(probes),
    }
    body["assembly_hash"] = hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    return body


def test_nested_playthrough_is_exposed_as_independent_input_evidence():
    evidence = runtime_evidence(
        objective_result={
            "status": "passed",
            "input_playthrough": {"movement_verified": True},
        },
        playability_result={"responsive": True, "hud_observed": True},
    )

    assert evidence["objective.status"] == "passed"
    assert evidence["input.movement_verified"] is True
    assert evidence["playability.responsive"] is True


def test_every_declared_probe_produces_a_passing_coverage_row():
    result = evaluate_capability_coverage(
        _lock("objective.status", "input.movement_verified"),
        objective_result={
            "status": "passed",
            "input_playthrough": {"movement_verified": True},
        },
        playability_result={},
    )

    assert result["status"] == "passed"
    assert result["capabilities_passed"] == 1
    assert result["capabilities"][0]["status"] == "passed"
    assert result["capabilities"][0]["declared"] is True
    assert result["capabilities"][0]["configured"] is True
    assert result["capabilities"][0]["exercised"] is True
    assert result["capabilities"][0]["observed"] is True
    assert result["capabilities"][0]["passed"] is True
    assert validate_capability_coverage(_lock("objective.status", "input.movement_verified"), result) == []


def test_aggregate_pass_string_cannot_forge_an_empty_coverage_matrix():
    forged = {
        "coverage_version": 1,
        "assembly_hash": _lock("objective.status")["assembly_hash"],
        "status": "passed",
        "capabilities_total": 0,
        "capabilities_passed": 0,
        "missing_evidence": [],
        "failed_evidence": [],
        "capabilities": [],
    }

    problems = validate_capability_coverage(_lock("objective.status"), forged)

    assert any("missing rows" in problem for problem in problems)


def test_empty_assembly_lock_produces_blocked_not_passing_coverage():
    result = evaluate_capability_coverage(
        {},
        objective_result={"status": "passed"},
        playability_result={"responsive": True},
    )

    assert result["status"] == "blocked"
    assert result["capabilities_total"] == 0
    assert any("assembly lock" in item for item in result["missing_evidence"])
    assert validate_capability_coverage({}, result)


def test_false_evidence_is_a_real_failure_not_an_infrastructure_block():
    result = evaluate_capability_coverage(
        _lock("objective.win_verified"),
        objective_result={"win_verified": False},
        playability_result={},
    )

    assert result["status"] == "failed"
    assert result["missing_evidence"] == []
    assert result["failed_evidence"] == ["combat.test:objective.win_verified"]


def test_missing_evidence_blocks_truthful_release_coverage():
    result = evaluate_capability_coverage(
        _lock("objective.unimplemented_probe"),
        objective_result={"status": "passed"},
        playability_result={},
    )

    assert result["status"] == "blocked"
    assert result["capabilities"][0]["status"] == "blocked"
    assert result["capabilities"][0]["exercised"] is True
    assert result["capabilities"][0]["observed"] is False
    assert result["capabilities"][0]["passed"] is False
    assert result["missing_evidence"] == [
        "combat.test:objective.unimplemented_probe"
    ]


def test_missing_probe_source_is_neither_exercised_nor_observed():
    result = evaluate_capability_coverage(
        _lock("objective.status"),
        objective_result=None,
        playability_result={},
    )

    assert result["capabilities"][0]["exercised"] is False
    assert result["capabilities"][0]["observed"] is False


def _design(template):
    return {
        "title": "Proof Game",
        "genre": "test",
        "mechanic_template": template,
        "hero_description": "a readable test hero",
        "core_mechanics": ["move", "complete the objective"],
        "story_premise": "Prove the assembled game.",
        "theme_thread": "Every capability has evidence.",
        "win_condition": "Win.",
        "lose_condition": "Lose health.",
        "levels": [{
            "name": "Proof",
            "description": "A deterministic test arena.",
            "outro_beat": "Proof complete.",
            "intensity": 5,
            "pressure_notes": "Use stable pressure.",
        }],
        "art_style": "readable",
        "audio_mood": "focused",
        "key_item": {"description": "proof token", "role": "pickup"},
        "extra_sprites": [],
    }


def test_real_action_rpg_manifest_probes_are_all_backed_by_parser_evidence(monkeypatch):
    output = "\n".join([
        "[OBJECTIVE_METRICS] completion_seconds=20.0 progress_events=15 max_stall_frames=30 stuck=false restart=passed deaths=1",
        "[ACTION_RPG_METRICS] movement=true melee=true enemy_state=true pickup=true inventory=true dialogue=true quest=true room=true world_graph=true save=true loss=true restart=true boss_phase=true win=true narrative=true",
        "[OBJECTIVE] status=passed template=action_rpg reason=none collected=15 total=15 remaining=0 frames=1200",
        "[ACTION_RPG_PLAYTHROUGH] status=passed movement=true melee=true pickup=true inventory=true dialogue=true quest=true rooms=true rooms_visited=5 rooms_total=5 branch=true shortcut=true checkpoint=true dash=true boss_phase=true win=true frames=3000 attacks=28 interactions=3 deaths=0 reason=none",
    ])
    monkeypatch.setattr(
        qa_agent,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )
    objective, errors, blocked = qa_agent._run_objective_probe(
        "project", "scene", "action_rpg"
    )
    playthrough, playthrough_errors, playthrough_blocked = (
        qa_agent._run_action_rpg_playthrough("project", "scene")
    )
    objective["input_playthrough"] = playthrough
    lock = resolve_game_spec(game_spec_from_legacy_design(_design("action_rpg")))

    coverage = evaluate_capability_coverage(
        lock,
        objective_result=objective,
        playability_result={"responsive": True, "hud_observed": True},
    )

    assert errors == [] and blocked is False
    assert playthrough_errors == [] and playthrough_blocked is False
    assert coverage["status"] == "passed"
    assert coverage["capabilities_passed"] == coverage["capabilities_total"] == 9


def test_real_run_and_gun_manifest_probes_are_all_backed_by_parser_evidence(monkeypatch):
    output = "\n".join([
        "[OBJECTIVE_METRICS] completion_seconds=20.0 progress_events=7 max_stall_frames=30 stuck=false restart=passed deaths=1",
        "[RUN_AND_GUN_METRICS] fire=true checkpoint=true lose=true restart=true enemy=true boss_damage=true win=true",
        "[RUN_AND_GUN_STRUCTURE] layout=bridge platforms=6 encounters=5 hazards=3 pickups=2 roles=4 valid=true",
        "[RUN_AND_GUN_COMBAT] pulse=true spread=true launcher=true pickup=true wave_spawn=true wave_clear=true roles=true budget=true restart=true boss_phases=true threat_spent=8 threat_limit=10",
        "[RUN_AND_GUN_PROGRESSION] reward=true duplicate=true upgrade=true save_reload=true carryover=true corrupt_fallback=true schema=true currency=4 xp=10",
        "[OBJECTIVE] status=passed template=run_and_gun reason=none collected=7 total=7 remaining=0 frames=1200",
    ])
    monkeypatch.setattr(
        qa_agent,
        "_run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, output, ""),
    )
    objective, errors, blocked = qa_agent._run_objective_probe(
        "project", "scene", "run_and_gun"
    )
    lock = resolve_game_spec(game_spec_from_legacy_design(_design("run_and_gun")))

    coverage = evaluate_capability_coverage(
        lock,
        objective_result=objective,
        playability_result={"responsive": True, "hud_observed": True},
    )

    assert errors == [] and blocked is False
    assert coverage["status"] == "passed"
    assert coverage["capabilities_passed"] == coverage["capabilities_total"] == 9
