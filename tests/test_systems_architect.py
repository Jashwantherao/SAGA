import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from saga.blueprint import BLUEPRINT_VERSION, validate_blueprint
from saga.agents import systems_architect as architect_module
from saga.agents.systems_architect import deterministic_blueprint, systems_architect


def _design(template="dot_maze", levels=1):
    return {
        "title": "Test Catacomb",
        "genre": "arcade",
        "mechanic_template": template,
        "hero_description": "a bright clockwork mouse",
        "core_mechanics": ["move", "complete the objective"],
        "story_premise": "A mouse repairs a broken clock.",
        "theme_thread": "The maze is the clockwork.",
        "win_condition": "Complete the objective.",
        "lose_condition": "Lose all lives.",
        "levels": [
            {
                "name": f"Level {index + 1}",
                "description": "A readable test arena.",
                "outro_beat": "The clock moves again.",
                "intensity": 4 + index,
                "pressure_notes": "Increase authored pressure.",
            }
            for index in range(levels)
        ],
        "art_style": "high contrast",
        "audio_mood": "tense",
        "key_item": {"description": "a gold shard", "role": "pickup"},
        "extra_sprites": [],
    }


@pytest.mark.parametrize(
    "template",
    [
        "collect",
        "survive_hazards",
        "ordered_switches",
        "depletion",
        "survive_and_deplete",
        "maze_chase",
        "dot_maze",
        "herd_to_goal",
        "capture_zones",
    ],
)
def test_deterministic_fallback_is_valid_for_every_live_template(template):
    bp = deterministic_blueprint(_design(template))

    assert bp["blueprint_version"] == BLUEPRINT_VERSION
    assert validate_blueprint(bp) == []
    assert len(bp["systems"]) == 3


def test_architect_persists_fixed_blueprint_and_compiles_plan(tmp_path, monkeypatch):
    bp = deterministic_blueprint(_design("collect"))
    monkeypatch.setattr(
        architect_module,
        "settings",
        SimpleNamespace(architect_backend="nvidia", architect_model="nemotron-test"),
    )

    result = systems_architect(
        {"run_dir": str(tmp_path), "design_doc": _design("collect"), "blueprint": bp}
    )

    assert result["blueprint_status"] == "fixed"
    assert [step["system_id"] for step in result["blueprint_build_plan"]] == [
        "movement",
        "hud",
        "collection_objective",
    ]
    assert json.loads((tmp_path / "blueprint.json").read_text(encoding="utf-8")) == bp


def test_provider_failure_is_recorded_and_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(
        architect_module,
        "settings",
        SimpleNamespace(architect_backend="nvidia", architect_model="nemotron-test"),
    )
    monkeypatch.setattr(
        architect_module,
        "_generate_remote",
        lambda _design: (_ for _ in ()).throw(RuntimeError("endpoint unavailable")),
    )

    result = systems_architect({"run_dir": str(tmp_path), "design_doc": _design()})

    assert result["blueprint_status"] == "fallback"
    assert result["blueprint_model"] == "nemotron-test"
    assert "endpoint unavailable" in result["blueprint_errors"][0]
    assert validate_blueprint(result["blueprint"]) == []


def test_generated_blueprint_is_not_silently_canonicalized_when_supplied(tmp_path):
    bp = deterministic_blueprint(_design())
    bp["blueprint_version"] = 99

    with pytest.raises(ValueError, match="supplied blueprint is invalid"):
        systems_architect(
            {"run_dir": str(tmp_path), "design_doc": _design(), "blueprint": bp}
        )


def _with_save_load(bp):
    bp["save_state"] = ["lives"]
    bp["systems"].append(
        {
            "id": "save_load",
            "kind": "save_load",
            "description": "unrequested persistence",
            "depends_on": ["movement"],
            "acceptance": ["save lives"],
        }
    )
    return bp


def test_scope_firewall_strips_generated_out_of_scope_systems():
    bp = architect_module._canonicalize(_with_save_load(deterministic_blueprint(_design())), _design())

    assert "save_load" not in {system["kind"] for system in bp["systems"]}
    assert bp["save_state"] == []
    assert any("save_load" in note for note in bp["scope_notes"])


def _scaffolding_only(design):
    """What an over-ambitious architect leaves behind: the firewall keeps the
    movement/hud scaffolding and removes every RPG system, so nothing that
    implements the template's actual mechanic survives."""
    bp = deterministic_blueprint(design)
    bp["systems"] = [
        system
        for system in bp["systems"]
        if system["kind"] in {"movement", "camera", "hud"}
    ] or [
        {
            "id": "movement",
            "kind": "movement",
            "description": "The hero walks.",
            "depends_on": [],
            "acceptance": ["arrow keys move the hero"],
        }
    ]
    return bp


def test_firewall_leaving_only_scaffolding_is_rejected_not_validated_clean():
    """validate_blueprint is design-blind and accepts any non-empty systems
    list, so without a viability check a contract describing a game with no
    gameplay passes structurally."""
    design = _design("collect")
    stripped = architect_module._canonicalize(_scaffolding_only(design), design)

    assert validate_blueprint(stripped) == [], "structurally valid is the whole problem"

    problems = architect_module._blueprint_problems(stripped, design)
    assert len(problems) == 1
    assert "collect core loop" in problems[0]
    assert "pickup" in problems[0]


def test_a_blueprint_that_keeps_its_mechanic_stays_viable():
    design = _design("collect")
    bp = architect_module._canonicalize(deterministic_blueprint(design), design)

    assert architect_module._blueprint_problems(bp, design) == []


@pytest.mark.parametrize(
    "template",
    [
        "collect",
        "survive_hazards",
        "ordered_switches",
        "depletion",
        "survive_and_deplete",
        "maze_chase",
        "dot_maze",
        "herd_to_goal",
        "capture_zones",
    ],
)
def test_deterministic_fallback_stays_viable_for_every_template(template):
    """The fallback contract must never trip the check it is meant to survive."""
    design = _design(template)

    assert architect_module._viability_problems(deterministic_blueprint(design), design) == []


def test_supplied_complex_blueprint_is_not_held_to_arcade_mechanics(tmp_path, monkeypatch):
    """The firewall never runs on a human-reviewed contract, so nothing was
    silently removed and the viability check must not reject it for being
    outside the arcade templates."""
    example = (
        Path(__file__).resolve().parent.parent / "blueprints" / "example_action_rpg.json"
    )
    bp = json.loads(example.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        architect_module,
        "settings",
        SimpleNamespace(architect_backend="nvidia", architect_model="nemotron-test"),
    )

    result = systems_architect(
        {"run_dir": str(tmp_path), "design_doc": _design("collect"), "blueprint": bp}
    )

    assert result["blueprint"]["systems"], "supplied contract must survive intact"


def test_supplied_blueprint_keeps_out_of_scope_systems_with_advisory_note(
    tmp_path, monkeypatch
):
    bp = _with_save_load(deterministic_blueprint(_design()))
    monkeypatch.setattr(
        architect_module,
        "settings",
        SimpleNamespace(architect_backend="nvidia", architect_model="nemotron-test"),
    )

    result = systems_architect(
        {"run_dir": str(tmp_path), "design_doc": _design(), "blueprint": bp}
    )

    assert "save_load" in {system["kind"] for system in result["blueprint"]["systems"]}
    assert result["blueprint"]["save_state"] == ["lives"]
    assert any(
        "kept, unverified" in note for note in result["blueprint"]["scope_notes"]
    )


def test_supplied_complex_blueprint_survives_intact(tmp_path, monkeypatch):
    """The Emberfall Warden contract is the complex-game pilot; supplying it
    must never silently shrink it to the template scope."""
    example = (
        Path(__file__).resolve().parent.parent / "blueprints" / "example_action_rpg.json"
    )
    bp = json.loads(example.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        architect_module,
        "settings",
        SimpleNamespace(architect_backend="nvidia", architect_model="nemotron-test"),
    )

    result = systems_architect(
        {"run_dir": str(tmp_path), "design_doc": _design("collect"), "blueprint": bp}
    )

    assert len(result["blueprint"]["systems"]) == len(bp["systems"])
    assert {system["id"] for system in result["blueprint"]["systems"]} == {
        system["id"] for system in bp["systems"]
    }
