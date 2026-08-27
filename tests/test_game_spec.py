import copy
import json

import pytest

from saga.agents.game_designer import MECHANIC_TEMPLATES
from saga.game_spec import (
    CONDITION_OPERATORS,
    EFFECT_OPERATORS,
    GAME_SPEC_SCHEMA,
    GAME_SPEC_VERSION,
    LEGACY_TEMPLATE_CAPABILITIES,
    game_spec_from_legacy_design,
    translate_legacy_design,
    validate_condition_ast,
    validate_effect_ast,
    validate_game_spec,
)


def _design(template: str = "collect", *, levels: int = 2, lose: str = "none") -> dict:
    return {
        "title": "Lantern Atlas",
        "genre": "luminous adventure",
        "mechanic_template": template,
        "hero_description": "a bright ivory cartographer with a cobalt lantern",
        "core_mechanics": ["move", "read the world", "complete the objective"],
        "story_premise": "A cartographer restores paths erased by a living storm.",
        "theme_thread": "Every completed route redraws a piece of the lost atlas.",
        "win_condition": "Restore the final path.",
        "lose_condition": lose,
        "levels": [
            {
                "name": f"Lost Route {index + 1}",
                "description": f"A distinct storm-buried region {index + 1}.",
                "outro_beat": "A road returns to the atlas.",
                "intensity": 4 + index,
                "pressure_notes": "Increase the selected template's primary pressure.",
            }
            for index in range(levels)
        ],
        "art_style": "high-contrast painterly pixel art",
        "audio_mood": "restless strings resolving into warm synths",
        "key_item": {"description": "a glass compass seed", "role": "pickup"},
        "extra_sprites": [
            {"name": "storm_warden", "description": "a tall indigo route guardian"},
            {"name": "atlas_gate", "description": "an illuminated folding gate"},
        ],
    }


def _all_keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def test_schema_is_json_serializable_and_explicitly_versioned():
    rendered = json.dumps(GAME_SPEC_SCHEMA)

    assert "SAGA GameSpec v2" in rendered
    assert GAME_SPEC_SCHEMA["properties"]["game_spec_version"] == {
        "const": GAME_SPEC_VERSION
    }
    assert "condition" in GAME_SPEC_SCHEMA["$defs"]
    assert "effect" in GAME_SPEC_SCHEMA["$defs"]


def test_legacy_profile_table_covers_every_current_designer_template():
    assert set(LEGACY_TEMPLATE_CAPABILITIES) == set(MECHANIC_TEMPLATES)
    assert all(LEGACY_TEMPLATE_CAPABILITIES[template] for template in MECHANIC_TEMPLATES)


@pytest.mark.parametrize("template", MECHANIC_TEMPLATES)
def test_every_legacy_template_translates_to_a_valid_data_only_spec(template):
    design = _design(template)
    original = copy.deepcopy(design)

    spec = game_spec_from_legacy_design(design)

    assert design == original, "translation must not mutate the creative brief"
    assert spec["game_spec_version"] == 2
    assert spec["legacy"]["mechanic_template"] == template
    assert spec["capabilities"] == list(LEGACY_TEMPLATE_CAPABILITIES[template])
    assert spec["modes"][0]["capabilities"] == [
        {"id": capability, "version": 1}
        for capability in spec["capabilities"]
    ]
    assert spec["modes"][0]["spatial_model"] == (
        "side_view_2d" if template == "run_and_gun" else "top_down_2d"
    )
    assert validate_game_spec(spec) == []
    assert {"script", "gdscript", "code", "expression"}.isdisjoint(_all_keys(spec))


def test_legacy_translation_builds_an_ordered_campaign_and_restricted_rules():
    spec = translate_legacy_design(_design("action_rpg", levels=3, lose="Hero hp reaches 0."))

    assert [zone["id"] for zone in spec["world"]["zones"]] == [
        "level_0",
        "level_1",
        "level_2",
    ]
    assert [(edge["from"], edge["to"]) for edge in spec["world"]["edges"]] == [
        ("level_0", "level_1"),
        ("level_1", "level_2"),
    ]
    assert spec["world"]["zones"][0]["on_complete"] == [
        {"op": "set_flag", "fact": "level_0_complete", "value": True},
        {"op": "unlock_edge", "edge": "level_0_to_1"},
    ]
    assert spec["rules"]["win"]["when"]["fact"] == "level_2_complete"
    assert spec["rules"]["lose"]["when"] == {
        "op": "flag",
        "fact": "game_lost",
        "equals": True,
    }


def test_a_no_loss_legacy_game_uses_the_explicit_never_condition():
    spec = game_spec_from_legacy_design(_design("ordered_switches", levels=1))

    assert spec["rules"]["lose"] == {"description": "none", "when": {"op": "never"}}
    assert "game_lost" not in {fact["id"] for fact in spec["state"]["facts"]}


def test_unknown_or_incomplete_legacy_design_fails_before_translation():
    design = _design()
    design["mechanic_template"] = "freeform_gdscript"
    with pytest.raises(ValueError, match="unsupported legacy mechanic_template"):
        game_spec_from_legacy_design(design)

    design = _design()
    design["levels"] = []
    with pytest.raises(ValueError, match="at least one level"):
        game_spec_from_legacy_design(design)


def test_nested_condition_ast_accepts_only_declared_typed_references():
    condition = {
        "op": "all",
        "conditions": [
            {"op": "flag", "fact": "forge_open", "equals": True},
            {
                "op": "any",
                "conditions": [
                    {"op": "counter_gte", "fact": "sparks", "value": 10},
                    {"op": "owns_item", "item": "ember_key", "count": 1},
                ],
            },
            {"op": "not", "condition": {"op": "party_has_tag", "tag": "cursed"}},
        ],
    }

    assert validate_condition_ast(
        condition,
        fact_types={"forge_open": "bool", "sparks": "int"},
        item_ids={"ember_key"},
        party_tags={"cursed"},
    ) == []


@pytest.mark.parametrize(
    "condition, expected",
    [
        ({"op": "eval", "code": "OS.execute('anything')"}, "code are forbidden"),
        ({"op": "flag", "fact": "ready", "equals": True, "code": "pass"}, "unsupported field"),
        ({"op": "all", "conditions": []}, "non-empty list"),
        ({"op": "owns_item", "item": "key", "count": 0}, "positive integer"),
        ({"op": "not"}, ".condition is required"),
    ],
)
def test_condition_ast_rejects_code_ambiguity_and_invalid_shapes(condition, expected):
    assert any(expected in problem for problem in validate_condition_ast(condition))


def test_condition_ast_reports_unknown_and_wrongly_typed_references():
    unknown = validate_condition_ast(
        {"op": "counter_gte", "fact": "missing", "value": 2},
        fact_types={"quest_done": "bool"},
    )
    wrong_type = validate_condition_ast(
        {"op": "counter_gte", "fact": "quest_done", "value": 2},
        fact_types={"quest_done": "bool"},
    )

    assert any("unknown state fact" in problem for problem in unknown)
    assert any("must have type 'int'" in problem for problem in wrong_type)


@pytest.mark.parametrize(
    "effect",
    [
        {"op": "set_flag", "fact": "quest_done", "value": True},
        {"op": "add_counter", "fact": "sparks", "amount": -10},
        {"op": "grant_item", "item": "dash_charm", "count": 1},
        {"op": "unlock_edge", "edge": "court_to_forge"},
    ],
)
def test_effect_ast_accepts_each_bounded_mutation(effect):
    assert validate_effect_ast(
        effect,
        fact_types={"quest_done": "bool", "sparks": "int"},
        item_ids={"dash_charm"},
        edge_ids={"court_to_forge"},
    ) == []


def test_effect_ast_rejects_arbitrary_calls_zero_delta_and_dangling_refs():
    assert set(EFFECT_OPERATORS) == {
        "set_flag",
        "add_counter",
        "grant_item",
        "unlock_edge",
    }
    arbitrary = validate_effect_ast({"op": "call", "method": "queue_free"})
    zero = validate_effect_ast(
        {"op": "add_counter", "fact": "sparks", "amount": 0},
        fact_types={"sparks": "int"},
    )
    dangling = validate_effect_ast(
        {"op": "unlock_edge", "edge": "missing_edge"}, edge_ids={"known_edge"}
    )

    assert any("code are forbidden" in problem for problem in arbitrary)
    assert any("non-zero integer" in problem for problem in zero)
    assert any("unknown world edge" in problem for problem in dangling)


def test_game_spec_validation_catches_mode_state_content_and_world_reference_errors():
    spec = game_spec_from_legacy_design(_design("collect"))
    spec["modes"][0]["capabilities"].append(
        {"id": "combat.unprovisioned", "version": 1}
    )
    spec["rules"]["win"]["when"]["fact"] = "missing_fact"
    spec["world"]["zones"][0]["on_complete"].append(
        {"op": "grant_item", "item": "missing_item", "count": 1}
    )
    spec["world"]["zones"].append(
        {
            "id": "island",
            "name": "Island",
            "description": "A disconnected test zone.",
            "intensity": 3,
            "pacing_notes": "No route reaches it.",
            "outro_beat": "Nothing happens.",
            "on_complete": [],
        }
    )

    problems = validate_game_spec(spec)

    assert any("undeclared capability 'combat.unprovisioned'" in item for item in problems)
    assert any("unknown state fact 'missing_fact'" in item for item in problems)
    assert any("unknown item 'missing_item'" in item for item in problems)
    assert any("zones unreachable" in item and "island" in item for item in problems)


def test_state_fact_types_and_bounds_are_enforced():
    spec = game_spec_from_legacy_design(_design(levels=1))
    spec["state"]["facts"].extend(
        [
            {"id": "sparks", "namespace": "legacy.collect", "type": "int", "initial": 11, "minimum": 0, "maximum": 10},
            {
                "id": "quest_stage",
                "namespace": "legacy.collect",
                "type": "string",
                "initial": "missing",
                "allowed_values": ["collect", "complete"],
            },
        ]
    )

    problems = validate_game_spec(spec)

    assert any("state.facts[1]" in problem and "above maximum" in problem for problem in problems)
    assert any("state.facts[2]" in problem and "allowed_values" in problem for problem in problems)


def test_all_condition_operators_are_schema_backed():
    rendered = json.dumps(GAME_SPEC_SCHEMA["$defs"]["condition"])

    assert set(CONDITION_OPERATORS) == {
        "always",
        "never",
        "all",
        "any",
        "not",
        "flag",
        "counter_gte",
        "owns_item",
        "party_has_tag",
    }
    assert all(operator in rendered for operator in CONDITION_OPERATORS)


def test_statically_closed_world_gate_does_not_count_as_reachable():
    spec = game_spec_from_legacy_design(_design(levels=2))
    spec["world"]["edges"][0]["gate"] = {"op": "never"}

    problems = validate_game_spec(spec)

    assert any("zones unreachable" in problem and "level_1" in problem for problem in problems)


def test_statically_impossible_win_contract_is_rejected():
    spec = game_spec_from_legacy_design(_design(levels=1))
    spec["rules"]["win"]["when"] = {
        "op": "all",
        "conditions": [{"op": "always"}, {"op": "never"}],
    }

    assert "rules.win.when is statically impossible" in validate_game_spec(spec)
