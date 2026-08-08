from pathlib import Path

import pytest

from saga.blueprint import (
    BLUEPRINT_VERSION,
    build_order,
    compile_build_plan,
    load_blueprint,
    validate_blueprint,
)
from saga.router import DEFAULT_ROUTE, LAGUNA, NEMOTRON, QWEN_LOCAL, candidates

EXAMPLE = Path(__file__).resolve().parent.parent / "blueprints" / "example_action_rpg.json"


def _bp():
    return {
        "blueprint_version": BLUEPRINT_VERSION,
        "title": "Test Game",
        "premise": "A tester tests.",
        "core_loop": ["move", "collect"],
        "win_condition": "collect everything",
        "lose_condition": "none",
        "player": {"controls": ["arrow keys: move"], "abilities": []},
        "systems": [
            {
                "id": "movement",
                "kind": "movement",
                "description": "walk around",
                "depends_on": [],
                "acceptance": ["arrow keys move the hero"],
            },
            {
                "id": "pickups",
                "kind": "pickup",
                "description": "collect things",
                "depends_on": ["movement"],
                "acceptance": ["walking over a pickup collects it"],
            },
        ],
    }


def test_example_blueprint_is_valid_and_orderable():
    bp = load_blueprint(EXAMPLE)
    order = build_order(bp["systems"])
    assert order[0] == "movement"
    assert order.index("quest") > order.index("dialogue")
    assert order.index("boss_fight") > order.index("quest")


def test_every_system_needs_acceptance_criteria():
    bp = _bp()
    bp["systems"][1]["acceptance"] = []
    assert any("acceptance" in problem for problem in validate_blueprint(bp))


@pytest.mark.parametrize("count", [0, 2, 13])
def test_blueprint_enforces_advertised_system_count(count):
    bp = _bp()
    prototype = bp["systems"][-1]
    while len(bp["systems"]) < count:
        index = len(bp["systems"])
        bp["systems"].append({
            **prototype,
            "id": f"system_{index}",
            "depends_on": [],
        })
    bp["systems"] = bp["systems"][:count]

    assert any("3-12" in problem for problem in validate_blueprint(bp))


def test_blueprint_accepts_minimum_system_count():
    bp = _bp()
    bp["systems"].append({
        "id": "hud",
        "kind": "hud",
        "description": "show progress",
        "depends_on": ["pickups"],
        "acceptance": ["the HUD shows collected pickups"],
    })

    assert validate_blueprint(bp) == []


def test_unknown_dependency_is_flagged():
    bp = _bp()
    bp["systems"][1]["depends_on"] = ["teleporter"]
    assert any("teleporter" in problem for problem in validate_blueprint(bp))


def test_dependency_cycle_is_a_contract_bug():
    systems = [
        {"id": "a", "kind": "movement", "description": "d", "depends_on": ["b"], "acceptance": ["x"]},
        {"id": "b", "kind": "hud", "description": "d", "depends_on": ["a"], "acceptance": ["x"]},
    ]
    with pytest.raises(ValueError, match="cycle"):
        build_order(systems)


def test_build_order_breaks_ties_by_declaration_order():
    systems = [
        {"id": "movement", "kind": "movement", "depends_on": []},
        {"id": "hud", "kind": "hud", "depends_on": []},
        {"id": "combat", "kind": "combat", "depends_on": ["movement", "hud"]},
    ]
    assert build_order(systems) == ["movement", "hud", "combat"]


def test_declared_save_state_requires_a_save_system():
    bp = _bp()
    bp["save_state"] = ["hero position"]
    assert any("save_load" in problem for problem in validate_blueprint(bp))


def test_router_reserves_nemotron_for_architecture_and_defaults_to_laguna():
    assert candidates("architecture")[0] == NEMOTRON
    assert candidates("movement")[0] == QWEN_LOCAL
    assert candidates("camera") == DEFAULT_ROUTE
    assert candidates("camera")[0] == LAGUNA


def test_router_overrides_replace_a_route_without_mutating_defaults():
    assert candidates("boss", {"boss": [QWEN_LOCAL]}) == [QWEN_LOCAL]
    assert candidates("boss")[0] == NEMOTRON


def test_compiled_plan_is_dependency_ordered_and_records_model_fallbacks():
    plan = compile_build_plan(_bp())

    assert [step["system_id"] for step in plan] == ["movement", "pickups"]
    assert plan[0]["recommended_model"] == QWEN_LOCAL
    assert plan[0]["fallback_models"]
    assert plan[1]["depends_on"] == ["movement"]


def test_blueprint_version_is_explicit_and_rejected_when_unknown():
    bp = _bp()
    bp["blueprint_version"] = 99

    assert any("blueprint_version" in problem for problem in validate_blueprint(bp))
