from pathlib import Path

import re

from saga.agents.coder import (
    CAPTURE_EXAMPLE_RESPONSE,
    CAPTURE_PROBE_GD,
    DEPLETION_EXAMPLE_RESPONSE,
    DEPLETION_PROBE_GD,
    HYBRID_EXAMPLE_RESPONSE,
    HYBRID_PROBE_GD,
    HERD_EXAMPLE_RESPONSE,
    HERD_PROBE_GD,
    OBJECTIVE_PROBE_GD,
    ORDERED_SWITCHES_EXAMPLE_RESPONSE,
    PROJECT_GODOT_TEMPLATE,
    SURVIVAL_PROBE_GD,
    SURVIVE_EXAMPLE_RESPONSE,
    SWITCH_PROBE_GD,
    _final_candidate_errors,
)
from saga.agents.coder_backend import extract_gdscript
from saga.agents.coder_contracts import (
    TEMPLATE_CONTRACTS,
    animation_call_violations,
)


def test_maze_chase_contract_exposes_objective_qa_adapters():
    descriptions = " ".join(
        description for description, _pattern in TEMPLATE_CONTRACTS["maze_chase"]
    )

    assert "stable player handle" in descriptions
    assert "stable wall array" in descriptions
    assert "pickup total" in descriptions
    assert "state" in descriptions
    assert "stable patroller handle" in descriptions


def test_animation_contract_rejects_walk_call_with_vector_as_second_argument_only():
    script = "Anim.walk(player_sprite, velocity)"

    violations = animation_call_violations(script)

    assert violations == [
        "Anim.walk must receive exactly three arguments: "
        "Anim.walk(sprite, is_moving_bool, direction_x_float)"
    ]


def test_animation_contract_accepts_nested_boolean_and_direction_arguments():
    script = "Anim.walk(player_sprite, direction.length() > 0.0, direction.x)"

    assert animation_call_violations(script) == []


def test_animation_contract_rejects_vector_as_boolean_even_with_three_arguments():
    script = "Anim.walk(player_sprite, velocity, velocity.x)"

    assert animation_call_violations(script) == [
        "Anim.walk argument 2 must be a bool, not a Vector2; use "
        "velocity.length() > 0.0 (or equivalent)"
    ]


def test_final_candidate_recheck_catches_bad_repair_after_correction_round():
    script = """
extends Node2D
func _process(_delta):
    Anim.set_poses(sprite, idle, walking)
    Anim.walk(sprite, velocity)
    load("res://assets/invented.png")
"""

    errors = _final_candidate_errors(
        script,
        template="unknown",
        valid_assets={"hero_sprite.png", "hero_walk.png"},
    )

    assert any("exactly three arguments" in error for error in errors)
    assert "Asset does not exist: res://assets/invented.png" in errors


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


def test_capture_example_satisfies_qa_contract_and_installs_probe():
    script = extract_gdscript(CAPTURE_EXAMPLE_RESPONSE)
    missing = [
        description
        for description, pattern in TEMPLATE_CONTRACTS["capture_zones"]
        if not re.search(pattern, script)
    ]

    assert missing == []
    assert 'CaptureProbe="*res://capture_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert '"capture_zones"' in OBJECTIVE_PROBE_GD
    assert "contest_did_not_decay" in CAPTURE_PROBE_GD
    assert "ownership_did_not_reset" in CAPTURE_PROBE_GD
    assert "all_owned_did_not_win" in CAPTURE_PROBE_GD


def test_herd_example_satisfies_qa_contract_and_installs_probe():
    script = extract_gdscript(HERD_EXAMPLE_RESPONSE)
    missing = [
        description
        for description, pattern in TEMPLATE_CONTRACTS["herd_to_goal"]
        if not re.search(pattern, script)
    ]

    assert missing == []
    assert 'HerdProbe="*res://herd_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert '"herd_to_goal"' in OBJECTIVE_PROBE_GD
    assert "creature_moved_outside_panic_radius" in HERD_PROBE_GD
    assert "creature_did_not_flee_toward_goal" in HERD_PROBE_GD
    assert "settled_creature_moved" in HERD_PROBE_GD
    assert "all_settled_did_not_win" in HERD_PROBE_GD


def _reject(previous_evidence, errors):
    from saga.agents.coder import _rejected_repair_result

    return _rejected_repair_result(
        project_dir=Path("."),
        model="m",
        original_goal=list(previous_evidence),
        errors=list(errors),
    )["repair_validation_errors"]


def test_repeated_repair_rejections_do_not_nest_their_own_evidence():
    """A rejected repair feeds its evidence back as the next attempt's goal.
    Re-wrapping it verbatim nested one prefix per retry and repeated the same
    parse errors a dozen times, growing the prompt fastest exactly when the
    model was already failing to hold it."""
    errors = ['Parse Error: Could not find base class "KinematicBody2D".']

    evidence = _reject(["Original goal from QA"], errors)
    for _ in range(5):
        evidence = _reject(evidence, errors)

    assert not any("Original repair goal: Original repair goal:" in item for item in evidence)
    assert len(evidence) == len(set(evidence)), "no duplicated lines"
    assert len(evidence) <= 8


def test_rejection_still_reports_the_goal_and_the_validation_failure():
    evidence = _reject(["player must move with the arrow keys"], ["unbalanced indent"])

    assert "Candidate validation: unbalanced indent" in evidence
    assert "Original repair goal: player must move with the arrow keys" in evidence


def test_a_goal_restating_this_rejection_is_not_echoed_back():
    errors = ["unbalanced indent"]
    first = _reject(["fix the indent"], errors)
    second = _reject(first, errors)

    assert second.count("Candidate validation: unbalanced indent") == 1
