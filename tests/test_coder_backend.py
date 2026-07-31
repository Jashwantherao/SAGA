from saga.agents.coder_backend import extract_gdscript
from saga.agents.coder import ANIM_GD, AUTOPLAY_GD, OBJECTIVE_PROBE_GD, PROJECT_GODOT_TEMPLATE


def test_extracts_tagged_gdscript():
    assert extract_gdscript("```gdscript\nextends Node2D\n```") == "extends Node2D"


def test_falls_back_to_generic_code_fence():
    assert extract_gdscript("```\nextends Node2D\n```") == "extends Node2D"


def test_generated_projects_install_the_objective_probe_autoload():
    assert 'ObjectiveProbe="*res://objective_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert "--objective-template=" in OBJECTIVE_PROBE_GD
    assert "template=%s" in OBJECTIVE_PROBE_GD
    assert "total_gems" in OBJECTIVE_PROBE_GD
    assert "patroller" in OBJECTIVE_PROBE_GD
    assert "_placement_preflight" in OBJECTIVE_PROBE_GD
    assert "unreachable_pickup" in OBJECTIVE_PROBE_GD


def test_autoplay_quit_stays_inside_report_function():
    lines = AUTOPLAY_GD.splitlines()
    quit_line = next(line for line in lines if "get_tree().quit()" in line)

    assert quit_line.startswith("\t")


def test_walk_animation_matches_left_facing_generated_art():
    assert "faces screen-left" in ANIM_GD
    assert "sprite.flip_h = dir_x > 0.0" in ANIM_GD
