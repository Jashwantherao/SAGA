import copy
import json

import pytest

from saga.agents.composition_director import composition_director
import saga.graph as graph_module
from saga.game_spec import translate_legacy_design, validate_game_spec
from saga.graph import _route_after_qa, advance_level, build_graph


def _design(template: str = "collect", levels: int = 2) -> dict:
    return {
        "title": "Clockwork Crossing",
        "genre": "arcade adventure",
        "mechanic_template": template,
        "hero_description": "a bright brass mouse with a blue scarf",
        "core_mechanics": ["move", "complete the authored objective"],
        "story_premise": "A courier repairs a clockwork crossing.",
        "theme_thread": "Every repaired mechanism opens the path onward.",
        "win_condition": "Complete the final objective.",
        "lose_condition": "Lose all lives.",
        "levels": [
            {
                "name": f"Crossing {index + 1}",
                "description": "A readable brass-and-stone arena.",
                "outro_beat": "Another gear begins to turn.",
                "intensity": 4 + index,
                "pressure_notes": "Increase the template's authored pressure.",
            }
            for index in range(levels)
        ],
        "art_style": "high-contrast illustrated clockwork",
        "audio_mood": "urgent but hopeful",
        "key_item": {"description": "a radiant winding key", "role": "pickup"},
        "extra_sprites": [],
    }


def test_translates_resolves_and_persists_both_contracts(tmp_path):
    result = composition_director(
        {"run_dir": str(tmp_path), "design_doc": _design("collect")}
    )

    assert result["game_spec_status"] == "translated"
    assert result["game_spec_errors"] == []
    assert validate_game_spec(result["game_spec"]) == []
    assert result["assembly_hash"] == result["assembly_lock"]["assembly_hash"]
    assert result["assembly_lock"]["modes"][0]["components"][0]["id"] == "legacy.collect"
    assert json.loads((tmp_path / "game_spec.json").read_text(encoding="utf-8")) == result["game_spec"]
    assert json.loads(
        (tmp_path / "assembly.lock.json").read_text(encoding="utf-8")
    ) == result["assembly_lock"]


def test_supplied_game_spec_is_fixed_and_not_mutated(tmp_path):
    supplied = translate_legacy_design(_design("action_rpg", levels=1))
    original = copy.deepcopy(supplied)

    result = composition_director(
        {
            "run_dir": str(tmp_path),
            "design_doc": _design("action_rpg", levels=1),
            "game_spec": supplied,
        }
    )

    assert result["game_spec_status"] == "fixed"
    assert result["game_spec"] == original
    assert result["game_spec"] is not supplied
    assert supplied == original
    component_ids = {
        component["id"]
        for component in result["assembly_lock"]["modes"][0]["components"]
    }
    assert "combat.melee" in component_ids
    assert "boss.action_rpg" in component_ids


def test_supplied_legacy_spec_cannot_lock_a_different_game_than_coder_builds(tmp_path):
    supplied = translate_legacy_design(_design("action_rpg", levels=1))

    with pytest.raises(ValueError, match="does not match the DesignDoc"):
        composition_director(
            {
                "run_dir": str(tmp_path),
                "design_doc": _design("collect", levels=1),
                "game_spec": supplied,
            }
        )

    assert not (tmp_path / "assembly.lock.json").exists()


def test_supplied_action_rpg_spec_is_compiled_into_builder_content(tmp_path):
    design = _design("action_rpg", levels=1)
    supplied = translate_legacy_design(design)
    supplied["world"]["zones"][0]["description"] = "A different unbuilt world."
    supplied["world"]["zones"][0]["name"] = "The Player-Authored Vault"

    result = composition_director(
        {
            "run_dir": str(tmp_path),
            "design_doc": design,
            "game_spec": supplied,
        }
    )

    assert result["game_spec_status"] == "fixed_compiled"
    assert result["design_doc"]["levels"][0] == {
        "name": "The Player-Authored Vault",
        "description": "A different unbuilt world.",
        "outro_beat": supplied["world"]["zones"][0]["outro_beat"],
        "intensity": supplied["world"]["zones"][0]["intensity"],
        "pressure_notes": supplied["world"]["zones"][0]["pacing_notes"],
    }
    assert json.loads((tmp_path / "game_spec.json").read_text(encoding="utf-8")) == supplied


def test_custom_game_spec_stays_blocked_for_a_legacy_generated_pack(tmp_path):
    design = _design("collect", levels=1)
    supplied = translate_legacy_design(design)
    supplied["world"]["zones"][0]["description"] = "Content its builder cannot consume."

    with pytest.raises(ValueError, match="supported only by the Action-RPG"):
        composition_director(
            {"run_dir": str(tmp_path), "design_doc": design, "game_spec": supplied}
        )


def test_invalid_supplied_spec_fails_before_writing_misleading_artifacts(tmp_path):
    supplied = translate_legacy_design(_design(levels=1))
    supplied["modes"][0]["capabilities"] = []

    with pytest.raises(ValueError, match="supplied GameSpec is invalid"):
        composition_director(
            {
                "run_dir": str(tmp_path),
                "design_doc": _design(levels=1),
                "game_spec": supplied,
            }
        )

    assert not (tmp_path / "game_spec.json").exists()
    assert not (tmp_path / "assembly.lock.json").exists()


def test_graph_locks_composition_and_art_direction_before_asset_work():
    edges = {
        (edge.source, edge.target) for edge in build_graph().get_graph().edges
    }

    assert ("systems_architect", "composition_director") in edges
    assert ("composition_director", "art_director") in edges
    assert ("art_director", "asset_maker") in edges
    assert ("composition_director", "audio_agent") in edges
    assert ("systems_architect", "asset_maker") not in edges
    assert ("composition_director", "asset_maker") not in edges
    assert ("systems_architect", "audio_agent") not in edges


def test_coder_waits_for_both_asset_and_audio_production_branches(monkeypatch):
    calls = []
    original = graph_module.StateGraph.add_edge

    def recording_add_edge(self, start_key, end_key):
        calls.append((start_key, end_key))
        return original(self, start_key, end_key)

    monkeypatch.setattr(graph_module.StateGraph, "add_edge", recording_add_edge)
    build_graph()

    assert (["asset_maker", "audio_agent"], "coder") in calls
    assert ("asset_maker", "coder") not in calls
    assert ("audio_agent", "coder") not in calls


def test_terminal_qa_failure_does_not_enter_the_generic_retry_loop():
    assert _route_after_qa(
        {
            "qa_passed": False,
            "qa_terminal": True,
            "retry_count": 0,
            "ship_blocked": False,
        }
    ) == "done"


def test_advancing_a_level_clears_terminal_qa_state():
    result = advance_level({"current_level": 0, "qa_terminal": True})

    assert result["qa_terminal"] is False
