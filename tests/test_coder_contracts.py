import re

from saga.agents.coder import (
    ORDERED_SWITCHES_EXAMPLE_RESPONSE,
    PROJECT_GODOT_TEMPLATE,
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
