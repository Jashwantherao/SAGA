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
from saga.experience import repair_action_rpg_candidate, score_action_rpg_candidate
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
    assert pack.version == 4
    assert pack.mechanic_template == "action_rpg"
    assert "variable_world_persistence" in pack.capabilities
    assert "four_persona_experience_critics" in pack.capabilities
    assert "bounded_content_repair" in pack.capabilities
    assert "versioned_checkpoint_save" in pack.capabilities
    assert "two_phase_boss" in pack.capabilities
    assert "progression_profile.gd" in pack.required_files
    assert "action_rpg_level.gd" in pack.required_files
    assert validate_action_rpg_plan(plan) == []
    assert 4 <= len(plan["rooms"]) <= 6
    assert plan["rooms"][0]["id"] == "hermit_court"
    assert plan["rooms"][1]["id"] == "rust_vault"
    assert plan["rooms"][-1]["id"] == "heart_forge"
    assert sum(
        pickup["amount"]
        for room in plan["rooms"]
        for pickup in room.get("pickups", [])
        if pickup["kind"] == "sparks"
    ) == 10
    assert plan["rooms"][-1]["boss"]["phases"] == 2
    assert plan["schema_version"] == 3
    assert plan["compiler"]["id"] == "encounter_progression"
    assert plan["experience_search"]["candidates_evaluated"] == 24
    assert plan["experience_search"]["score"] >= 78
    assert len({
        enemy["role"]
        for room in plan["rooms"]
        for enemy in room.get("enemies", [])
    }) >= 3
    assert len({room["layout_id"] for room in plan["rooms"]}) >= 4
    assert all(
        verdict["passed"]
        for verdict in plan["experience_search"]["personas"].values()
    )
    assert plan["experience_search"]["telemetry"]["room_count"] == len(plan["rooms"])
    assert any(
        pickup["kind"] == "health"
        for room in plan["rooms"][:-1]
        for pickup in room.get("pickups", [])
    )


def test_action_rpg_v3_runtime_contains_production_feedback_contract():
    root = load_pack("action_rpg").root
    level = (root / "action_rpg_level.gd").read_text(encoding="utf-8")
    player = (root / "player_controller.gd").read_text(encoding="utf-8")
    enemy = (root / "enemy.gd").read_text(encoding="utf-8")

    assert 'player.set_authored_visual(_asset("hero"), _asset("hero_walk")' in level
    assert 'str(child.name) == "FallbackVisual"' in level
    assert 'Sfx.play("win")' in level
    assert "CPUParticles2D.new()" in level
    assert "walk_texture" in player
    assert "attack_animation_left" in player
    assert "_spawn_dash_echo" in player
    assert 'state = "attack_telegraph"' in enemy
    assert "windup_left" in enemy


def test_action_rpg_experience_search_is_repeatable_but_not_a_fixed_game():
    first = build_action_rpg_plan(_design(), 0)
    repeated = build_action_rpg_plan(_design(), 0)
    alternate_design = _design()
    alternate_design["title"] = "Moonlit Archive"
    alternate_design["story_premise"] = "A cartographer maps a library that rearranges itself."
    alternate = build_action_rpg_plan(alternate_design, 0)

    assert first == repeated
    assert first["experience_search"]["selected_signature"] != alternate["experience_search"]["selected_signature"]
    assert score_action_rpg_candidate(first)["passed"] is True


def test_candidate_studio_repairs_only_failed_experience_evidence():
    plan = build_action_rpg_plan(_design(), 0)
    for room in plan["rooms"]:
        room["pickups"] = [
            pickup
            for pickup in room.get("pickups", [])
            if pickup.get("kind") not in {"health"}
            and not str(pickup.get("id") or "").startswith("optional_relic_")
        ]
    before = score_action_rpg_candidate(plan)

    repaired, ledger = repair_action_rpg_candidate(plan, before)
    after = score_action_rpg_candidate(repaired)

    assert before["passed"] is False
    assert {edit["owner"] for edit in ledger} <= {"progression", "encounter", "world"}
    assert any(
        str(pickup.get("id") or "").startswith("optional_relic_")
        for room in repaired["rooms"]
        for pickup in room.get("pickups", [])
    )
    assert after["score"] >= before["score"]


def test_action_rpg_quality_gate_rejects_role_and_layout_monotony():
    plan = build_action_rpg_plan(_design(), 0)
    for room in plan["rooms"]:
        room["layout_id"] = "same_box"
        for enemy in room.get("enemies", []):
            enemy["role"] = "stalker"

    errors = validate_action_rpg_plan(plan)

    assert "action RPG encounters require at least three enemy roles" in errors
    assert "action RPG journey requires at least four spatial layouts" in errors
    assert "action RPG experience score is below the playable quality floor" in errors


def test_action_rpg_qa_save_is_isolated_from_the_player_profile():
    profile = (
        load_pack("action_rpg").root / "progression_profile.gd"
    ).read_text(encoding="utf-8")

    assert 'QA_SAVE_PATH := "user://saga_action_rpg_qa_save.json"' in profile
    assert '"--objective-probe" in arguments' in profile
    assert '"--action-rpg-playthrough" in arguments' in profile
    assert '"--presentation-capture" in arguments' in profile
    assert 'if "--action-rpg-playthrough" in OS.get_cmdline_user_args() or "--presentation-capture" in OS.get_cmdline_user_args():' in profile
    assert 'return {"save": SAVE_PATH' in profile


def test_action_rpg_plan_validator_rejects_cosmetic_rpg_shell():
    plan = build_action_rpg_plan(_design(), 0)
    plan["rooms"] = plan["rooms"][:1]
    plan["quest_stages"] = ["collect_sparks"]

    errors = validate_action_rpg_plan(plan)

    assert "action RPG v4 requires four to six connected rooms" in errors
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
    assert '\\"pack_version\\": 4' in script
    assert '\\"room_plan\\"' in script
    assert [
        description
        for description, pattern in TEMPLATE_CONTRACTS["action_rpg"]
        if not re.search(pattern, script)
    ] == []


def test_action_rpg_adapter_binds_authored_actor_roles_instead_of_fallback_shapes():
    script = build_action_rpg_adapter(
        _design(),
        0,
        [
            "hero_sprite.png",
            "level_0_bg.png",
            "extra_thorn_sentinel.png",
            "extra_thorn_skirmisher.png",
            "extra_root_archivist.png",
            "extra_glass_stag_boss.png",
            "key_item.png",
        ],
    )

    assert '\\"npc\\": \\"res://assets/extra_root_archivist.png\\"' in script
    assert '\\"enemy_sentinel\\": \\"res://assets/extra_thorn_sentinel.png\\"' in script
    assert '\\"enemy_skirmisher\\": \\"res://assets/extra_thorn_skirmisher.png\\"' in script
    assert "extra_glass_stag_boss.png" in script


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

    assert result["coder_model"] == "archetype/action_rpg@4"
    assert result["content_plan"]["experience_search"]["personas"]["explorer"]["passed"] is True
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
    assert '_pickup_target(level, "entry_sparks"' in source
    assert 'player.call("test_move"' in source


def test_action_rpg_input_playthrough_parser_requires_every_observed_system(monkeypatch):
    output = (
        "[ACTION_RPG_PLAYTHROUGH] status=passed movement=true melee=true "
        "pickup=true inventory=true dialogue=true quest=true rooms=true "
        "rooms_visited=5 rooms_total=5 "
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
    assert result["rooms_visited"] == result["rooms_total"] == 5
    assert result["deaths"] == 1


def test_action_rpg_input_playthrough_parser_rejects_missing_transition(monkeypatch):
    output = (
        "[ACTION_RPG_PLAYTHROUGH] status=failed movement=true melee=true "
        "pickup=true inventory=true dialogue=true quest=true rooms=true "
        "rooms_visited=4 rooms_total=5 "
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
    assert "room_index == _last_room_index() and is_instance_valid(boss)" in source
    assert "target >= _room_count()" in source


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
