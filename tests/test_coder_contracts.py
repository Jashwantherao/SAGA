import re

from saga.agents.coder import (
    DEPLETION_EXAMPLE_RESPONSE,
    DEPLETION_PROBE_GD,
    HYBRID_EXAMPLE_RESPONSE,
    HYBRID_PROBE_GD,
    ORDERED_SWITCHES_EXAMPLE_RESPONSE,
    PROJECT_GODOT_TEMPLATE,
    SURVIVAL_PROBE_GD,
    SURVIVE_EXAMPLE_RESPONSE,
    SWITCH_PROBE_GD,
)
from saga.agents.coder_backend import extract_gdscript
from saga.agents.coder_contracts import TEMPLATE_CONTRACTS


def test_maze_chase_contract_exposes_objective_qa_adapters():
    descriptions = " ".join(
        description for description, _pattern in TEMPLATE_CONTRACTS["maze_chase"]
    )

    assert "stable player handle" in descriptions
    assert "stable wall array" in descriptions
    assert "pickup total" in descriptions
    assert "state" in descriptions
    assert "stable patroller handle" in descriptions


def test_ordered_switch_contract_exposes_sequence_qa_adapters():
    descriptions = " ".join(
        description for description, _pattern in TEMPLATE_CONTRACTS["ordered_switches"]
    )

    assert "stable player handle" in descriptions
    assert "stable switch array" in descriptions
    assert "ordered switch-index array" in descriptions
    assert "progress counter" in descriptions
    assert "reset counter" in descriptions
    assert "state" in descriptions


def test_ordered_switch_example_satisfies_qa_contract_and_installs_probe():
    script = extract_gdscript(ORDERED_SWITCHES_EXAMPLE_RESPONSE)
    missing = [
        description
        for description, pattern in TEMPLATE_CONTRACTS["ordered_switches"]
        if not re.search(pattern, script)
    ]

    assert missing == []
    assert 'SwitchProbe="*res://switch_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert "wrong_order_did_not_reset" in SWITCH_PROBE_GD
    assert "reload_current_scene" in SWITCH_PROBE_GD


def test_survival_example_satisfies_qa_contract_and_installs_probe():
    script = extract_gdscript(SURVIVE_EXAMPLE_RESPONSE)
    missing = [
        description
        for description, pattern in TEMPLATE_CONTRACTS["survive_hazards"]
        if not re.search(pattern, script)
    ]

    assert missing == []
    assert 'SurvivalProbe="*res://survival_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert "collision_did_not_damage" in SURVIVAL_PROBE_GD
    assert 'Input.action_press("ui_accept")' in SURVIVAL_PROBE_GD
    assert 'set("time_left", 0.05)' in SURVIVAL_PROBE_GD


def test_depletion_example_satisfies_qa_contract_and_installs_probe():
    script = extract_gdscript(DEPLETION_EXAMPLE_RESPONSE)
    missing = [
        description
        for description, pattern in TEMPLATE_CONTRACTS["depletion"]
        if not re.search(pattern, script)
    ]

    assert missing == []
    assert 'DepletionProbe="*res://depletion_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert "resource_did_not_drain" in DEPLETION_PROBE_GD
    assert "resource_did_not_refill" in DEPLETION_PROBE_GD
    assert 'Input.action_press("ui_accept")' in DEPLETION_PROBE_GD


def test_hybrid_example_satisfies_qa_contract_and_installs_probe():
    script = extract_gdscript(HYBRID_EXAMPLE_RESPONSE)
    missing = [d for d, pattern in TEMPLATE_CONTRACTS["survive_and_deplete"] if not re.search(pattern, script)]
    assert missing == []
    assert 'HybridProbe="*res://hybrid_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert "drain_ramp_not_observed" in HYBRID_PROBE_GD
    assert "hazard_did_not_damage" in HYBRID_PROBE_GD
