import json
import re
import subprocess

from saga.agents import coder as coder_module
from saga.agents import qa_agent
from saga.agents.coder_contracts import TEMPLATE_CONTRACTS
from saga.agents.game_designer import _validate
from saga.agents.systems_architect import deterministic_blueprint
from saga.archetypes import (
    RUN_AND_GUN_LAYOUTS,
    build_run_and_gun_encounter_plan,
    build_run_and_gun_adapter,
    load_pack,
    pack_for_template,
    scaffold_pack,
    validate_run_and_gun_encounter_plan,
)
from saga.blueprint import validate_blueprint


def _design():
    return {
        "title": "Ashline Courier",
        "genre": "side-view action platformer",
        "mechanic_template": "run_and_gun",
        "hero_description": "a bright courier in a cobalt pressure suit",
        "core_mechanics": ["run and jump", "fire pulse bolts", "defeat the commander"],
        "story_premise": "A courier crosses a siege line to reopen the dawn relay.",
        "theme_thread": "Every checkpoint restores another part of the relay route.",
        "win_condition": "Defeat the sector commander.",
        "lose_condition": "Run out of health.",
        "levels": [{
            "name": "The Broken Causeway",
            "description": "A long industrial causeway under drone fire.",
            "outro_beat": "The first relay wakes and throws a blue line toward dawn.",
            "intensity": 6,
            "pressure_notes": "More guards, a distant checkpoint, and a three-phase commander.",
        }],
        "art_style": "high-contrast industrial pixel art",
        "audio_mood": "urgent percussion and radio static",
        "key_item": {"description": "a cyan relay beacon", "role": "pickup"},
        "extra_sprites": [
            {"name": "enemy_guard", "description": "an angular red guard drone"},
            {"name": "sector_boss", "description": "a massive violet siege walker"},
        ],
    }


def test_run_and_gun_is_a_valid_design_and_multi_system_blueprint():
    design = _design()

    assert _validate(design, 1) == []
    blueprint = deterministic_blueprint(design)
    assert validate_blueprint(blueprint) == []
    kinds = {system["kind"] for system in blueprint["systems"]}
    assert {"movement", "combat", "enemy_ai", "checkpoint", "boss", "objective"} <= kinds
    assert blueprint["player"]["controls"] == [
        "left/right arrows: run",
        "up arrow: jump",
        "ui_accept: fire",
    ]


def test_pack_manifest_names_every_required_capability_file():
    pack = load_pack("run_and_gun")

    assert pack.version == 2
    assert pack.mechanic_template == "run_and_gun"
    assert "checkpoint_respawn" in pack.capabilities
    assert "multi_phase_boss" in pack.capabilities
    assert "encounter_layout_grammar" in pack.capabilities
    assert "hazard.gd" in pack.required_files
    assert "pickup.gd" in pack.required_files
    assert "run_and_gun_level.gd" in pack.required_files
    assert pack_for_template("collect") is None


def test_scaffolder_copies_only_versioned_pack_files(tmp_path):
    pack = scaffold_pack(tmp_path, "run_and_gun")
    destination = tmp_path / "archetypes" / "run_and_gun"

    assert pack is not None
    assert json.loads((destination / "manifest.json").read_text())["version"] == 2
    assert {path.name for path in destination.glob("*.gd")} == {
        path for path in pack.required_files
    }


def test_adapter_is_small_versioned_and_uses_authored_assets():
    script = build_run_and_gun_adapter(
        _design(),
        0,
        [
            "hero_sprite.png",
            "hero_walk.png",
            "level_0_bg.png",
            "extra_enemy_guard.png",
            "extra_sector_boss.png",
            "key_item.png",
        ],
    )

    assert len(script.splitlines()) < 12
    assert "run_and_gun_level.gd" in script
    assert "extra_enemy_guard.png" in script
    assert "extra_sector_boss.png" in script
    assert '\\"pack_version\\": 2' in script
    assert '\\"encounter_plan\\"' in script
    assert [
        description
        for description, pattern in TEMPLATE_CONTRACTS["run_and_gun"]
        if not re.search(pattern, script)
    ] == []


def test_coder_scaffolds_pack_without_a_model_call(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source = tmp_path / "hero_sprite.png"
    source.write_bytes(b"not decoded during scaffolding")
    monkeypatch.setattr(coder_module, "run_project_dir", lambda _state: project)
    monkeypatch.setattr(coder_module, "_is_remote", lambda: True)
    monkeypatch.setattr(
        coder_module,
        "_chat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a deterministic archetype must not call the Coder model")
        ),
    )

    result = coder_module.coder({
        "design_doc": _design(),
        "sprite_paths": [str(source)],
        "bgm_path": None,
        "current_level": 0,
        "qa_errors": [],
        "tune_notes": [],
    })

    assert result["coder_model"] == "archetype/run_and_gun@2"
    assert (project / "Level_0.gd").is_file()
    assert (project / "archetypes" / "run_and_gun" / "boss.gd").is_file()
    assert "capabilities:" in result["coder_prompt"]


def test_encounter_plan_is_deterministic_varied_and_structurally_valid():
    design = _design()
    first = build_run_and_gun_encounter_plan(design, 0)
    second = build_run_and_gun_encounter_plan(design, 0)
    alternate = build_run_and_gun_encounter_plan(
        {**design, "title": "Copper Moon Rebellion"}, 0
    )

    assert first == second
    assert first["layout_id"] in RUN_AND_GUN_LAYOUTS
    assert validate_run_and_gun_encounter_plan(first) == []
    assert len(first["platforms"]) >= 3
    assert len(first["encounter_beats"]) == 5
    assert len({item["role"] for item in first["enemy_spawns"]}) >= 2
    assert first["seed"] != alternate["seed"]
    assert (first["layout_id"], first["platforms"]) != (
        alternate["layout_id"], alternate["platforms"]
    )


def test_encounter_plan_validator_rejects_a_cosmetic_corridor():
    plan = build_run_and_gun_encounter_plan(_design(), 0)
    plan["platforms"] = []
    plan["hazards"] = []
    plan["enemy_spawns"] = [
        {"x": 500.0, "role": "scout"},
        {"x": 700.0, "role": "scout"},
        {"x": 900.0, "role": "scout"},
    ]

    errors = validate_run_and_gun_encounter_plan(plan)

    assert "at least three traversal platforms are required" in errors
    assert "at least one readable hazard is required" in errors
    assert "at least two enemy roles are required" in errors


def test_qa_parser_requires_all_run_and_gun_capabilities(monkeypatch):
    output = "\n".join([
        "[RUN_AND_GUN_METRICS] fire=true checkpoint=true lose=true restart=true enemy=true boss_damage=true win=true",
        "[RUN_AND_GUN_STRUCTURE] layout=switchbacks platforms=6 encounters=5 hazards=2 pickups=1 roles=3 valid=true",
        "[OBJECTIVE_METRICS] completion_seconds=0.2 progress_events=7 max_stall_frames=1 stuck=false restart=passed deaths=1",
        "[OBJECTIVE] status=passed template=run_and_gun reason=none collected=7 total=7 remaining=0 frames=12",
    ])
    monkeypatch.setattr(
        qa_agent,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, output, ""),
    )

    result, errors, blocked = qa_agent._run_objective_probe(
        "project", "res://Level_0.tscn", "run_and_gun"
    )

    assert errors == []
    assert blocked is False
    assert result["completion_score"] == 100
    assert result["checkpoint_verified"] is True
    assert result["boss_win_verified"] is True
    assert result["structure_verified"] is True
    assert result["layout_id"] == "switchbacks"
    assert result["enemy_role_count"] == 3


def test_pack_script_failure_is_a_harness_block_not_a_model_repair():
    assert qa_agent._has_harness_error([
        "SCRIPT ERROR: Parse Error at res://archetypes/run_and_gun/boss.gd:12"
    ])
