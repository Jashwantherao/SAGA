import re
import subprocess

from saga.agents import coder as coder_module
from saga.agents import qa_agent
from saga.agents.asset_maker import _asset_requests
from saga.agents.coder_contracts import TEMPLATE_CONTRACTS
from saga.agents.game_designer import _validate
from saga.agents.systems_architect import deterministic_blueprint
from saga.archetypes import (
    build_action_rpg_adapter,
    build_action_rpg_plan,
    load_pack,
    pack_for_template,
    validate_action_rpg_plan,
)
from saga.blueprint import validate_blueprint


def _design():
    return {
        "title": "Emberfall Warden",
        "genre": "top-down action RPG",
        "mechanic_template": "action_rpg",
        "hero_description": "a masked amber lantern knight viewed from above",
        "core_mechanics": [
            "explore three persistent rooms",
            "fight stalkers with frontal melee",
            "collect sparks and complete the hermit's quest",
            "defeat the forge warden",
        ],
        "story_premise": "A lantern knight relights a ruined heart-forge.",
        "theme_thread": "Every recovered spark restores a forgotten promise.",
        "win_condition": "Complete the hermit's quest and defeat the forge warden.",
        "lose_condition": "Run out of health.",
        "levels": [
            {
                "name": "The Ember Keep",
                "description": "Three connected forge rooms full of rust and old runes.",
                "outro_beat": "The forge answers the lantern with a living flame.",
                "intensity": 6,
                "pressure_notes": "Tougher pursuit and a faster second boss phase.",
            }
        ],
        "art_style": "high-contrast painterly pixel art",
        "audio_mood": "warm low strings and hammer percussion",
        "key_item": {"description": "a faceted golden forge spark", "role": "pickup"},
        "extra_sprites": [
            {"name": "rust_stalker", "description": "a red rust stalker viewed from above"},
            {"name": "ember_hermit", "description": "a violet forge hermit viewed from above"},
            {"name": "forge_warden", "description": "a massive iron forge guardian viewed from above"},
        ],
    }


def test_action_rpg_design_compiles_to_complete_multi_system_blueprint():
    design = _design()

    assert _validate(design, 1) == []
    blueprint = deterministic_blueprint(design)
    assert validate_blueprint(blueprint) == []
    kinds = {system["kind"] for system in blueprint["systems"]}
    assert {
        "movement",
        "combat",
        "enemy_ai",
        "inventory",
        "dialogue",
        "quest",
        "level_transition",
        "save_load",
        "boss",
        "objective",
    } <= kinds
    assert "Shift: dash after quest unlock" in blueprint["player"]["controls"]
    assert "quest_stage" in blueprint["save_state"]


def test_action_rpg_pack_manifest_and_plan_are_versioned_and_complete():
    pack = load_pack("action_rpg")
    plan = build_action_rpg_plan(_design(), 0)

    assert pack_for_template("action_rpg") == pack
    assert pack.version == 1
    assert pack.mechanic_template == "action_rpg"
    assert "three_room_persistence" in pack.capabilities
    assert "versioned_checkpoint_save" in pack.capabilities
    assert "two_phase_boss" in pack.capabilities
    assert "progression_profile.gd" in pack.required_files
    assert "action_rpg_level.gd" in pack.required_files
    assert validate_action_rpg_plan(plan) == []
    assert [room["id"] for room in plan["rooms"]] == [
        "hermit_court",
        "rust_vault",
        "heart_forge",
    ]
    assert sum(
        pickup["amount"]
        for room in plan["rooms"]
        for pickup in room.get("pickups", [])
        if pickup["kind"] == "sparks"
    ) == 10
    assert plan["rooms"][-1]["boss"]["phases"] == 2


def test_action_rpg_qa_save_is_isolated_from_the_player_profile():
    profile = (
        load_pack("action_rpg").root / "progression_profile.gd"
    ).read_text(encoding="utf-8")

    assert 'QA_SAVE_PATH := "user://saga_action_rpg_qa_save.json"' in profile
    assert '"--objective-probe" in arguments' in profile
    assert '"--action-rpg-playthrough" in arguments' in profile
    assert 'if "--action-rpg-playthrough" in OS.get_cmdline_user_args():' in profile
    assert 'return {"save": SAVE_PATH' in profile


def test_action_rpg_plan_validator_rejects_cosmetic_rpg_shell():
    plan = build_action_rpg_plan(_design(), 0)
    plan["rooms"] = plan["rooms"][:1]
    plan["quest_stages"] = ["collect_sparks"]

    errors = validate_action_rpg_plan(plan)

    assert "action RPG v1 requires exactly three connected rooms" in errors
    assert "the final room must contain the boss" in errors
    assert "quest must expose collect, return, forge-open and complete stages" in errors


def test_action_rpg_adapter_is_compact_versioned_and_uses_authored_assets():
    script = build_action_rpg_adapter(
        _design(),
        0,
        [
            "hero_sprite.png",
            "level_0_bg.png",
            "extra_rust_stalker.png",
            "extra_ember_hermit.png",
            "extra_forge_warden.png",
            "key_item.png",
        ],
    )

    assert len(script.splitlines()) < 12
    assert "action_rpg_level.gd" in script
    assert "extra_rust_stalker.png" in script
    assert "extra_ember_hermit.png" in script
    assert "extra_forge_warden.png" in script
    assert '\\"pack_version\\": 1' in script
    assert '\\"room_plan\\"' in script
    assert [
        description
        for description, pattern in TEMPLATE_CONTRACTS["action_rpg"]
        if not re.search(pattern, script)
    ] == []


def test_coder_scaffolds_action_rpg_without_model_call(tmp_path, monkeypatch):
    project = tmp_path / "project"
    hero = tmp_path / "hero_sprite.png"
    background = tmp_path / "level_0_bg.png"
    hero.write_bytes(b"not decoded during scaffolding")
    background.write_bytes(b"not decoded during scaffolding")
    monkeypatch.setattr(coder_module, "run_project_dir", lambda _state: project)
    monkeypatch.setattr(coder_module, "_is_remote", lambda: True)
    monkeypatch.setattr(
        coder_module,
        "_chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a deterministic archetype must not call the Coder model")
        ),
    )

    result = coder_module.coder(
        {
            "design_doc": _design(),
            "sprite_paths": [str(hero), str(background)],
            "bgm_path": None,
            "current_level": 0,
            "qa_errors": [],
            "tune_notes": [],
        }
    )

    assert result["coder_model"] == "archetype/action_rpg@1"
    assert (project / "Level_0.gd").is_file()
    assert (project / "archetypes" / "action_rpg" / "boss.gd").is_file()
    project_config = (project / "project.godot").read_text(encoding="utf-8")
    assert 'ActionRpgProfile="*res://archetypes/action_rpg/progression_profile.gd"' in project_config
    assert 'ActionRpgProbe="*res://action_rpg_probe.gd"' in project_config
    assert 'ActionRpgPlaythrough="*res://action_rpg_playthrough.gd"' in project_config


def test_action_rpg_input_playthrough_uses_only_player_controls():
    source = coder_module.ACTION_RPG_PLAYTHROUGH_GD

    assert "Input.action_press" in source
    assert "Input.action_release" in source
    assert "qa_" not in source.lower()
    assert "ACTION_RPG_PLAYTHROUGH" in source


def test_action_rpg_input_playthrough_parser_requires_every_observed_system(monkeypatch):
    output = (
        "[ACTION_RPG_PLAYTHROUGH] status=passed movement=true melee=true "
        "pickup=true inventory=true dialogue=true quest=true rooms=true "
        "checkpoint=true dash=true boss_phase=true win=true frames=2400 "
        "attacks=30 interactions=2 deaths=1 reason=none"
    )
    monkeypatch.setattr(
        qa_agent,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, ""),
    )

    result, errors, blocked = qa_agent._run_action_rpg_playthrough(
        "project", "res://Level_0.tscn"
    )

    assert errors == []
    assert blocked is False
    assert result["status"] == "passed"
    assert result["normal_input_only"] is True
    assert result["boss_phase_verified"] is True
    assert result["deaths"] == 1


def test_action_rpg_input_playthrough_parser_rejects_missing_transition(monkeypatch):
    output = (
        "[ACTION_RPG_PLAYTHROUGH] status=failed movement=true melee=true "
        "pickup=true inventory=true dialogue=true quest=true rooms=true "
        "checkpoint=true dash=false boss_phase=false win=false frames=12000 "
        "attacks=20 interactions=2 deaths=3 reason=timeout_boss"
    )
    monkeypatch.setattr(
        qa_agent,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, ""),
    )

    result, errors, blocked = qa_agent._run_action_rpg_playthrough(
        "project", "res://Level_0.tscn"
    )

    assert result["status"] == "failed"
    assert blocked is False
    assert any("dash" in error for error in errors)
    assert any("boss_phase" in error for error in errors)


def test_action_rpg_qa_parser_requires_every_system_transition(monkeypatch):
    output = "\n".join(
        [
            "[ACTION_RPG_METRICS] movement=true melee=true enemy_state=true pickup=true inventory=true dialogue=true quest=true room=true save=true loss=true restart=true boss_phase=true win=true",
            "[OBJECTIVE_METRICS] completion_seconds=0.2 progress_events=13 max_stall_frames=1 stuck=false restart=passed deaths=1",
            "[OBJECTIVE] status=passed template=action_rpg reason=none collected=13 total=13 remaining=0 frames=13",
        ]
    )
    monkeypatch.setattr(
        qa_agent,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, ""),
    )

    result, errors, blocked = qa_agent._run_objective_probe(
        "project", "res://Level_0.tscn", "action_rpg"
    )

    assert errors == []
    assert blocked is False
    assert result["completion_score"] == 100
    assert result["movement_verified"] is True
    assert result["save_reload_verified"] is True
    assert result["boss_phases_verified"] is True
    assert result["boss_win_verified"] is True


def test_action_rpg_art_contract_is_top_down_and_actor_free():
    background_prompt = next(
        request[0]
        for request in _asset_requests(_design())
        if request[1] == "level_0_bg"
    )

    assert "strict 2D top-down orthographic" in background_prompt
    assert "connected rooms" in background_prompt
    assert "no isometric angle" in background_prompt
    assert "no hero" in background_prompt
    assert "no boss" in background_prompt


def test_action_rpg_pack_failure_is_a_harness_block():
    assert qa_agent._has_harness_error(
        ["SCRIPT ERROR: Parse Error at res://archetypes/action_rpg/boss.gd:12"]
    )


def test_action_rpg_pickup_disables_monitoring_safely_after_collision_signal():
    source = (
        load_pack("action_rpg").root / "pickup.gd"
    ).read_text(encoding="utf-8")

    assert 'set_deferred("monitoring", false)' in source
    assert "\n\tmonitoring = false" not in source


def test_action_rpg_room_transitions_are_reachable_before_boundary_collisions():
    source = (
        load_pack("action_rpg").root / "action_rpg_level.gd"
    ).read_text(encoding="utf-8")

    assert "player.position.x >= 970.0" in source
    assert "player.position.x <= 54.0" in source
    assert "room_index == 2 and is_instance_valid(boss)" in source


def test_action_rpg_production_gate_requires_authored_role_art(tmp_path):
    (tmp_path / "Level_0.gd").write_text(
        'extends "res://archetypes/action_rpg/action_rpg_level.gd"',
        encoding="utf-8",
    )
    hero = tmp_path / "hero_sprite.png"
    background = tmp_path / "level_0_bg.png"
    hero.write_bytes(b"hero")
    background.write_bytes(b"background")
    result = qa_agent.qa_agent(
        {
            "godot_project_path": str(tmp_path),
            "design_doc": {
                "mechanic_template": "action_rpg",
                "levels": [{"name": "L1"}],
            },
            "sprite_paths": [str(hero), str(background)],
            "current_level": 0,
            "retry_count": 0,
        }
    )

    attempt = result["level_results"][0]["attempts"][-1]
    assert attempt["stage"] == "production_assets"
    error = " ".join(attempt["errors"])
    assert "stalker enemy sprite" in error
    assert "quest NPC sprite" in error
    assert "forge boss sprite" in error
