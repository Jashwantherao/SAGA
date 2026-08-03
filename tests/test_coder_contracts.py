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


def _godot3_violations(source):
    from saga.agents.coder_contracts import FORBIDDEN_PATTERNS

    return [desc for desc, pattern in FORBIDDEN_PATTERNS if re.search(pattern, source)]


def test_godot3_base_class_is_caught_before_a_godot_spawn():
    """A real run burned all six retries on `extends KinematicBody2D`: Godot
    reports it only as "Could not find base class", which never names the
    replacement, so the model spiralled instead of repairing."""
    violations = _godot3_violations("extends KinematicBody2D\n")

    assert len(violations) == 1
    assert "CharacterBody2D" in violations[0]


def test_the_worked_examples_trip_no_godot3_rule():
    """The few-shot responses are known-good Godot 4. Any match here is a
    false positive that would reject correct code on every single run."""
    from saga.agents import coder

    sources = {
        name: getattr(coder, name)
        for name in dir(coder)
        if name.endswith(("EXAMPLE_RESPONSE", "_GD"))
    }
    offenders = {
        name: _godot3_violations(source)
        for name, source in sources.items()
        if isinstance(source, str) and _godot3_violations(source)
    }

    assert sources, "expected worked examples to check against"
    assert offenders == {}


def test_godot4_spellings_are_not_mistaken_for_their_godot3_ancestors():
    """The \b in \bSprite\b cannot fire inside Sprite2D - that boundary is
    what makes a rename table safe to run over every candidate."""
    clean = (
        "extends CharacterBody2D\n"
        "@export var speed := 200.0\n"
        "@onready var art: Sprite2D = $Sprite2D\n"
        "var shape := $CollisionShape2D\n"
        "var puff := $GPUParticles2D\n"
        "var names := PackedStringArray()\n"
        "func _physics_process(_d):\n"
        "\tvelocity = Vector2.ZERO\n"
        "\tmove_and_slide()\n"
        "\tbody_entered.connect(_on_body_entered)\n"
        "\tvar n = preload('res://x.tscn').instantiate()\n"
        "\tif names.is_empty():\n"
        "\t\tprint(Time.get_ticks_msec(), randf_range(0.0, 1.0))\n"
    )

    assert _godot3_violations(clean) == []


def test_godot3_api_calls_are_named_with_their_replacement():
    for source, expected in [
        ("move_and_slide(velocity)", "no arguments"),
        ('button.connect("pressed", self, "_on_pressed")', "Callable"),
        ("export var speed = 5", "@export var"),
        ("onready var hero = $Hero", "@onready var"),
        ("yield(get_tree(), 'idle_frame')", "await"),
        ("var n = scene.instance()", ".instantiate()"),
    ]:
        violations = _godot3_violations(source)
        assert violations, f"{source!r} should be rejected"
        assert any(expected in item for item in violations), f"{source!r} -> {violations}"


def test_unherdable_speed_balance_is_caught_before_the_probe_runs():
    """A real 3-level run spent all six retries on invalid_herd_balance. The
    probe enforces flee_speed < 0.6 x speed but reports only a reason code, and
    the prompt said merely "well below", so nothing ever named the threshold."""
    from saga.agents.coder_contracts import balance_violations

    violations = balance_violations(
        "@export var speed = 240.0\nvar flee_speed = 200.0\n", "herd_to_goal"
    )

    assert len(violations) == 1
    assert "200" in violations[0] and "144" in violations[0]


def test_a_balanced_herd_passes():
    from saga.agents.coder_contracts import balance_violations

    assert balance_violations(
        "@export var speed = 240.0\nvar flee_speed = 90.0\n", "herd_to_goal"
    ) == []


def test_the_herd_worked_example_satisfies_the_rule_it_teaches():
    """The few-shot is the model's template for these numbers; if it tripped
    the check, every herd game would start from a rejected example."""
    from saga.agents.coder import HERD_EXAMPLE_RESPONSE
    from saga.agents.coder_contracts import balance_violations

    assert balance_violations(HERD_EXAMPLE_RESPONSE, "herd_to_goal") == []


def test_balance_rules_apply_only_to_their_own_template():
    from saga.agents.coder_contracts import balance_violations

    unbalanced = "@export var speed = 240.0\nvar flee_speed = 200.0\n"

    assert balance_violations(unbalanced, "collect") == []


def test_probe_rejection_names_the_threshold_it_enforced():
    from saga.agents.qa_agent import PROBE_REASON_HINTS

    assert "0.6" in PROBE_REASON_HINTS["invalid_herd_balance"]
    assert "greater than drain_rate" in PROBE_REASON_HINTS["invalid_depletion_settings"]
