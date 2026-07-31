import pytest

from saga.safety import (
    UnsafeGeneratedCodeError,
    assert_safe_gdscript,
    scan_generated_gdscript,
)


def test_allows_scene_code_and_exact_asset_loads():
    script = """
extends Node2D
var hero_texture = load("res://assets/hero_sprite.png")

func _process(delta):
    position.x += 100.0 * delta
"""
    assert scan_generated_gdscript(script) == []


@pytest.mark.parametrize(
    "line",
    [
        'OS.execute("powershell", [])',
        'FileAccess.open("user://save.dat", FileAccess.WRITE)',
        'var request = HTTPRequest.new()',
        'var config = load("res://project.godot")',
        'JavaScriptBridge.eval("alert(1)")',
    ],
)
def test_blocks_host_capabilities(line):
    with pytest.raises(UnsafeGeneratedCodeError):
        assert_safe_gdscript(f"extends Node2D\nfunc _ready():\n    {line}\n")


def test_ignores_forbidden_names_inside_comments():
    assert scan_generated_gdscript("# Never call OS.execute or FileAccess\nextends Node2D") == []
