"""Coder agent - generates a minimal Godot 4 project via a local Ollama model.

The harness writes the deterministic boilerplate itself (project.godot, a bare
Main.tscn scene, the Screenshot and Sfx autoloads, and the synthesized SFX
WAVs) since hand-authoring correct .tscn/resource plumbing is a poor fit for
an LLM. The model's only job is to write one Level_N.gd gameplay script
- given the design doc and the list of already-generated asset filenames.

The design doc's mechanic_template selects both a template-specific
requirements paragraph appended to the system prompt and the closest worked
few-shot example. Showing a small local model a complete example of the
structure it is asked to produce is its single biggest reliability lever, so
each template maps to whichever of the seven authored examples is
structurally nearest. Every few-shot demonstrates the shared "juice" idioms:
a title -> playing -> over state machine (with headless auto-start so QA
still exercises gameplay), Sfx autoload calls, and a CPUParticles2D ambient
effect.
"""

import re
import shutil
from pathlib import Path

from saga.agents.coder_backend import (
    MODEL,
    REMOTE_MODEL,
    TEMPLATE_MODEL_OVERRIDES,
    chat as _chat,
    extract_gdscript as _extract_gdscript,
    is_remote as _is_remote,
    routed_chat as _routed_chat,
    stop_gpu_services as _stop_gpu_services,
)
from saga.agents.coder_contracts import (
    FORBIDDEN_PATTERNS,
    TEMPLATE_CONTRACTS,
    UNIVERSAL_CONTRACTS,
    animation_call_violations,
)
from saga.config import settings
from saga.repair_gate import recover_interrupted_repair, validate_and_promote_repair
from saga.safety import assert_safe_gdscript, scan_generated_gdscript
from saga.sfx import write_default_sfx
from saga.state import GraphState
from saga.workspace import project_dir as run_project_dir

PROJECT_GODOT_TEMPLATE = """config_version=5

[application]
config/name="{title}"
run/main_scene="res://Level_0.tscn"
config/features=PackedStringArray("4.7")

[autoload]
Screenshot="*res://screenshot.gd"
Sfx="*res://sfx.gd"
Ambience="*res://ambience.gd"
Anim="*res://anim.gd"
Autoplay="*res://autoplay.gd"
ObjectiveProbe="*res://objective_probe.gd"
SwitchProbe="*res://switch_probe.gd"
SurvivalProbe="*res://survival_probe.gd"
DepletionProbe="*res://depletion_probe.gd"
HybridProbe="*res://hybrid_probe.gd"
CaptureProbe="*res://capture_probe.gd"
HerdProbe="*res://herd_probe.gd"
Music="*res://music.gd"
Game="*res://game.gd"

[display]
window/size/viewport_width=1024
window/size/viewport_height=576
window/stretch/mode="canvas_items"

[rendering]
renderer/rendering_method="gl_compatibility"
"""

# Harness-owned QA helper: saves one frame so a human (or the vision model)
# can check the build's look without launching it. It also injects a brief
# ui_accept press so the game's title screen dismisses and the screenshot
# captures actual gameplay. Must no-op headlessly or its save errors would
# trip the QA error patterns (headless gameplay coverage comes from the
# few-shots' own headless auto-start instead).
SCREENSHOT_GD = """extends Node

var frame = 0

func _process(_delta):
    if DisplayServer.get_name() == "headless":
        return
    frame += 1
    if frame == 5:
        Input.action_press("ui_accept")
    if frame == 8:
        Input.action_release("ui_accept")
    if frame == 60:
        var img = get_viewport().get_texture().get_image()
        var scene_name = "scene"
        if get_tree().current_scene != null:
            scene_name = str(get_tree().current_scene.name)
        img.save_png("res://screenshot_%s.png" % scene_name)
"""

def _gd_string(text: str) -> str:
    """Escape arbitrary text into a GDScript double-quoted string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


# Harness-owned level flow: the generated level scripts only ever call
# Game.level_complete() once on a win; the interlude (narrative beat),
# advancing, the victory screen, and restarting are deterministic harness
# code, not LLM output.
def _build_game_gd(level_count: int, beats: list[str]) -> str:
    scenes = ", ".join(f'"res://Level_{i}.tscn"' for i in range(level_count))
    beats_gd = ", ".join(_gd_string(b) for b in beats)
    return f"""extends Node

var level = 0
var level_scenes = [{scenes}]
var level_beats = [{beats_gd}]

func current_beat() -> String:
    if level < level_beats.size():
        return level_beats[level]
    return ""

func level_complete():
    await get_tree().create_timer(1.5).timeout
    get_tree().change_scene_to_file("res://Interlude.tscn")

func advance():
    level += 1
    if level < level_scenes.size():
        get_tree().change_scene_to_file(level_scenes[level])
    else:
        get_tree().change_scene_to_file("res://Victory.tscn")

func restart():
    level = 0
    get_tree().change_scene_to_file(level_scenes[0])
"""


# The between-level narrative beat: the just-won level's outro_beat on an
# otherwise empty screen. Enter continues; it also auto-continues so a
# headless QA run that happens to win a level never stalls here.
INTERLUDE_GD = """extends Node2D

var elapsed = 0.0

func _ready():
    var canvas = CanvasLayer.new()
    add_child(canvas)
    var beat = Label.new()
    beat.position = Vector2(162, 230)
    beat.size = Vector2(700, 130)
    beat.autowrap_mode = TextServer.AUTOWRAP_WORD
    beat.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    beat.text = Game.current_beat()
    canvas.add_child(beat)
    var hint = Label.new()
    hint.position = Vector2(162, 400)
    hint.size = Vector2(700, 40)
    hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
    hint.text = "Press Enter to continue"
    canvas.add_child(hint)

func _process(delta):
    elapsed += delta
    var auto_continue = 10.0
    if DisplayServer.get_name() == "headless":
        auto_continue = 0.5
    if Input.is_action_just_pressed("ui_accept") or elapsed > auto_continue:
        Game.advance()
"""

INTERLUDE_TSCN = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://interlude.gd" id="1"]

[node name="Interlude" type="Node2D"]
script = ExtResource("1")
"""


# Music lives in an autoload so it survives scene changes between levels
# (and loops, which the old per-scene autoplay player never did).
def _build_music_gd(bgm_filename: str | None) -> str:
    if not bgm_filename:
        return "extends Node\n"
    return f"""extends Node

func _ready():
    var player = AudioStreamPlayer.new()
    player.stream = load("res://assets/{bgm_filename}")
    add_child(player)
    player.finished.connect(player.play)
    player.play()
"""


VICTORY_GD = """extends Node2D

func _ready():
    var canvas = CanvasLayer.new()
    add_child(canvas)
    var label = Label.new()
    label.position = Vector2(320, 270)
    label.text = "VICTORY - every level complete!  Press Enter to play again"
    canvas.add_child(label)

func _process(_delta):
    if Input.is_action_just_pressed("ui_accept"):
        Game.restart()
"""

VICTORY_TSCN = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://victory.gd" id="1"]

[node name="Victory" type="Node2D"]
script = ExtResource("1")
"""

# Harness-owned ambient particles: presentation boilerplate the 14B model
# reliably gets wrong when asked to write it (it invents CPUParticles2D
# properties), so it lives here with the other harness-owned polish. Skipped
# headlessly - no visual value, and dummy-renderer particles leak RIDs.
# Harness-owned character animation. Generated sprites are single static PNGs -
# there is no sprite sheet and no frame-based animation anywhere in the
# pipeline - so a hero has always been a still image sliding around, which is
# what makes these builds read as mock-ups rather than games. Procedural motion
# closes most of that gap for free: a sprite that bobs while walking, leans
# into its direction, squashes on impact and breathes when idle is perceived as
# animated even though it is one frame.
#
# It lives in the harness rather than the Coder's prompt for the same reason
# Sfx does: it must be identical in every game, cannot be silently simplified
# away, and is pure boilerplate the model would otherwise reinvent badly.
#
# Every helper animates a Sprite2D CHILD, never the Area2D that owns gameplay
# position - the offsets are local, so bobbing cannot fight collision.
ANIM_GD = """extends Node

const BOB_HEIGHT := 3.0
const BOB_SPEED := 9.0
const LEAN_DEGREES := 5.0
const IDLE_AMOUNT := 0.03
const IDLE_SPEED := 2.2
const LEG_SWING := 0.11

# Actual leg movement, without a second drawn frame. Image generation can hold
# a character consistent across poses but cannot control where its legs are -
# asking for two consecutive walk frames reliably returns two standing poses -
# so a stepping gait cannot be drawn. It can be deformed instead: shear the
# lower part of the sprite sideways on a sine wave, with the left and right
# halves in opposite phase, and the near and far legs scissor past each other
# the way they do in a walk. Displacement ramps from zero at the hip to full at
# the feet so the body stays put while the legs swing under it.
const LEG_SHADER := "
shader_type canvas_item;
uniform float phase = 0.0;
uniform float amount = 0.0;
uniform float leg_line = 0.55;

void fragment() {
\tvec2 uv = UV;
\tif (uv.y > leg_line) {
\t\tfloat depth = (uv.y - leg_line) / (1.0 - leg_line);
\t\t// Front and back must travel in opposite directions to scissor, but a
\t\t// hard split at the midline shears the two halves apart and tears a gap
\t\t// down the body at any useful amplitude. A sine across the width crosses
\t\t// zero at the middle instead, so the halves oppose each other and the
\t\t// sprite stays continuous.
\t\tfloat side = sin((uv.x - 0.5) * 3.14159);
\t\tuv.x += sin(phase) * amount * depth * side;
\t}
\t// A shifted sample can fall outside the sprite; the art is alpha-cropped
\t// tight to its edges, so clamping there would smear the outermost column
\t// of pixels into a streak instead of letting the leg end.
\tif (uv.x < 0.0 || uv.x > 1.0) {
\t\tCOLOR = vec4(0.0);
\t} else {
\t\tCOLOR = texture(TEXTURE, uv);
\t}
}
"

# Phase is derived from the clock rather than stored, so callers stay
# stateless. The per-instance offset stops a row of identical creatures
# bobbing in lockstep, which reads as one object instead of several.
func _phase(node: Node2D, speed: float) -> float:
\treturn Time.get_ticks_msec() / 1000.0 * speed + float(node.get_instance_id() % 97) * 0.13

func _base(sprite: Node2D) -> Vector2:
\tif not sprite.has_meta("anim_base"):
\t\tsprite.set_meta("anim_base", sprite.scale)
\treturn sprite.get_meta("anim_base")

# Register a resting and a walking image for a character. walk() then swaps
# between them, which is what makes a sprite look like it stands up to move
# and settles when it stops - procedural bobbing alone cannot change a pose.
# Optional: a character with no walk pose simply keeps its single texture.
func set_poses(sprite: Sprite2D, idle_texture: Texture2D, walk_texture: Texture2D) -> void:
\tif not is_instance_valid(sprite):
\t\treturn
\tsprite.set_meta("pose_idle", idle_texture)
\tsprite.set_meta("pose_walk", walk_texture)

func _legs(sprite: Node2D, phase: float, amount: float) -> void:
\tif not (sprite is CanvasItem):
\t\treturn
\tvar mat: ShaderMaterial = sprite.material as ShaderMaterial
\tif mat == null:
\t\tvar shader := Shader.new()
\t\tshader.code = LEG_SHADER
\t\tmat = ShaderMaterial.new()
\t\tmat.shader = shader
\t\tsprite.material = mat
\tmat.set_shader_parameter("phase", phase)
\tmat.set_shader_parameter("amount", amount)

func _set_pose(sprite: Node2D, moving: bool) -> void:
\tif not (sprite is Sprite2D) or not sprite.has_meta("pose_walk"):
\t\treturn
\tvar wanted: Texture2D = sprite.get_meta("pose_walk") if moving else sprite.get_meta("pose_idle")
\tif wanted != null and sprite.texture != wanted:
\t\tsprite.texture = wanted

# Hero assets have one explicit orientation contract: their native texture
# faces screen-left. Pass the movement direction and mirror only for rightward
# motion. Vertical movement preserves the most recent horizontal facing.
func walk(sprite: Node2D, moving: bool, dir_x: float = 0.0) -> void:
\tif not is_instance_valid(sprite):
\t\treturn
\tvar base: Vector2 = _base(sprite)
\tif dir_x != 0.0 and sprite is Sprite2D:
\t\tsprite.flip_h = dir_x > 0.0
\t_set_pose(sprite, moving)
\tif moving:
\t\tvar p := _phase(sprite, BOB_SPEED)
\t\t# The body bounces at twice the stride rate - one rise per step, two per
\t\t# full cycle - which is what couples the bob to the legs instead of
\t\t# leaving them as two unrelated wobbles.
\t\tsprite.position.y = -abs(sin(p)) * BOB_HEIGHT
\t\tsprite.rotation_degrees = sin(p * 0.5) * LEAN_DEGREES
\t\tsprite.scale = Vector2(base.x * (1.0 + abs(sin(p)) * 0.04), base.y * (1.0 - abs(sin(p)) * 0.04))
\t\t_legs(sprite, p * 0.5, LEG_SWING)
\telse:
\t\tvar q := _phase(sprite, IDLE_SPEED)
\t\tsprite.position.y = 0.0
\t\tsprite.rotation_degrees = 0.0
\t\tsprite.scale = Vector2(base.x * (1.0 - sin(q) * IDLE_AMOUNT), base.y * (1.0 + sin(q) * IDLE_AMOUNT))
\t\t_legs(sprite, 0.0, 0.0)

# Call every frame for anything that hovers, drifts or swims.
func hover(sprite: Node2D, amount: float = 4.0, speed: float = 2.0) -> void:
\tif not is_instance_valid(sprite):
\t\treturn
\tvar base: Vector2 = _base(sprite)
\tvar p := _phase(sprite, speed)
\tsprite.position.y = sin(p) * amount
\tsprite.scale = Vector2(base.x * (1.0 + sin(p) * 0.05), base.y * (1.0 - sin(p) * 0.05))

# One-shot punch for a pickup, a spawn, or a landing.
func pop(sprite: Node2D, strength: float = 0.35) -> void:
\tif not is_instance_valid(sprite):
\t\treturn
\tvar base: Vector2 = _base(sprite)
\tvar tween := sprite.create_tween()
\ttween.tween_property(sprite, "scale", base * (1.0 + strength), 0.08)
\ttween.tween_property(sprite, "scale", base, 0.16).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)

# One-shot squash for an impact - wide and short, then recover.
func squash(sprite: Node2D, strength: float = 0.3) -> void:
\tif not is_instance_valid(sprite):
\t\treturn
\tvar base: Vector2 = _base(sprite)
\tvar tween := sprite.create_tween()
\ttween.tween_property(sprite, "scale", Vector2(base.x * (1.0 + strength), base.y * (1.0 - strength)), 0.06)
\ttween.tween_property(sprite, "scale", base, 0.18).set_trans(Tween.TRANS_ELASTIC).set_ease(Tween.EASE_OUT)

# Damage feedback: flash a colour and return to normal.
func flash(sprite: Node2D, color: Color = Color(1, 0.4, 0.4)) -> void:
\tif not is_instance_valid(sprite):
\t\treturn
\tvar tween := sprite.create_tween()
\ttween.tween_property(sprite, "modulate", color, 0.05)
\ttween.tween_property(sprite, "modulate", Color(1, 1, 1), 0.25)
"""

# Harness-owned autoplay probe. QA has only ever proved a script does not
# crash, which says nothing about whether the game responds to a player at all
# - a level whose hero cannot move, or whose objective can never change, runs
# perfectly and reports PASSED. Godot can press its own keys via
# Input.action_press, so the harness can hold the arrow keys down and watch
# what happens.
#
# Two signals, both template-agnostic. Something in the scene must MOVE when a
# direction is held, and the status Label - which every template is already
# required to show game state in - must eventually say something different.
# A game failing either is inert regardless of what it was trying to be.
#
# Deliberately not a win condition: reaching an objective needs skill this
# cannot fake, so absence of progress here is not evidence of an unwinnable
# game. It catches the floor, not the ceiling.
AUTOPLAY_GD = """extends Node

const SETTLE_FRAMES := 20
const BASELINE_FRAMES := 40
const HOLD_FRAMES := 45
const DIRECTIONS := ["ui_right", "ui_down", "ui_left", "ui_up"]

var _frame := 0
var _leg := -1
var _held := ""
var _labels := {}
var _previous := {}
var _idle_motion := 0.0
var _input_motion := 0.0
var _active := false

func _ready() -> void:
	_active = "--autoplay" in OS.get_cmdline_user_args()
	if _active:
		process_priority = 500

func _collect(node: Node, labels: Array, movers: Array) -> void:
	if node is Label:
		labels.append(node)
	elif node is Node2D and not (node is Sprite2D):
		# Sprite2D is excluded on purpose: the Anim autoload writes a bob and a
		# lean into every animated sprite's local position every frame, so
		# measuring sprites measures the animation rather than the game.
		movers.append(node)
	for child in node.get_children():
		_collect(child, labels, movers)

func _accumulate(movers: Array) -> float:
	var total := 0.0
	for m in movers:
		var id: int = m.get_instance_id()
		var here: Vector2 = m.global_position
		if _previous.has(id):
			total += _previous[id].distance_to(here)
		_previous[id] = here
	return total

func _process(_delta: float) -> void:
	if not _active:
		return
	var root: Node = get_tree().current_scene
	if root == null:
		return
	var labels: Array = []
	var movers: Array = []
	_collect(root, labels, movers)
	for l in labels:
		_labels[l.text] = true

	_frame += 1
	if _frame < SETTLE_FRAMES:
		_accumulate(movers)
		return
	if _frame == SETTLE_FRAMES:
		Input.action_press("ui_accept")
		_accumulate(movers)
		return
	if _frame == SETTLE_FRAMES + 1:
		Input.action_release("ui_accept")
		_accumulate(movers)
		return

	# Baseline first, with nothing held. Hazards patrol, creatures drift and
	# tweens run during this window exactly as they do later, so whatever the
	# game does on its own is measured before any key is touched.
	if _frame < SETTLE_FRAMES + BASELINE_FRAMES:
		_idle_motion += _accumulate(movers)
		return

	_input_motion += _accumulate(movers)
	var leg: int = (_frame - SETTLE_FRAMES - BASELINE_FRAMES) / HOLD_FRAMES
	if leg != _leg:
		if _held != "":
			Input.action_release(_held)
		_leg = leg
		if _leg >= DIRECTIONS.size():
			_report()
			return
		_held = DIRECTIONS[_leg]
		Input.action_press(_held)

func _report() -> void:
	_active = false
	if _held != "":
		Input.action_release(_held)
	# Per-frame rates, since the two windows are different lengths.
	var idle_rate := _idle_motion / float(BASELINE_FRAMES)
	var input_rate := _input_motion / float(HOLD_FRAMES * DIRECTIONS.size())
	print("[AUTOPLAY] idle_rate=%.3f input_rate=%.3f label_states=%d" % [idle_rate, input_rate, _labels.size()])
	get_tree().quit()
"""

# Harness-owned objective solver for deterministic collectible mechanics.
# Generic autoplay proves that input moves the game; this probe separately
# proves that every spawned pickup is spatially reachable and that collecting
# all of them drives the generated script into its real `won` state. It covers
# ordinary collect levels as well as maze_chase and dot_maze.
# Ghost collisions are disabled so this is a logic/reachability test rather
# than a skill or difficulty benchmark (the balance pass covers enemy speed).
OBJECTIVE_PROBE_GD = """extends Node

const GRID := 16.0
const GRID_WIDTH := 64
const GRID_HEIGHT := 36
const START_DELAY_FRAMES := 10
const MAX_FRAMES := 12000

var _active := false
var _template := "dot_maze"
var _frame := 0
var _root: Node
var _player: Area2D
var _walls: Array = []
var _ignored_ids := {}
var _path: Array[Vector2] = []
var _target: Area2D
var _exit: Area2D
var _phase := "pickups"
var _arrival_frame := -1
var _initial_total := 0
var _detail_areas: Array = []
var _last_remaining := -1
var _last_progress_frame := 0
var _progress_events := 0
var _max_stall_frames := 0
var _stuck := false
var _deaths := 0

func _ready() -> void:
	var arguments := OS.get_cmdline_user_args()
	_active = "--objective-probe" in arguments
	for argument in arguments:
		if argument.begins_with("--objective-template="):
			_template = argument.trim_prefix("--objective-template=")
	_active = _active and _template not in ["ordered_switches", "survive_hazards", "depletion", "survive_and_deplete", "capture_zones", "herd_to_goal"]
	if _active:
		process_priority = 600

func _has_property(object: Object, property_name: String) -> bool:
	for property in object.get_property_list():
		if str(property.get("name", "")) == property_name:
			return true
	return false

func _read_property(object: Object, names: Array, fallback = null):
	for property_name in names:
		if _has_property(object, property_name):
			return object.get(property_name)
	return fallback

func _collect_areas(node: Node, areas: Array) -> void:
	for child in node.get_children():
		if child is Area2D:
			areas.append(child)
		_collect_areas(child, areas)

func _looks_like_exit(area: Area2D) -> bool:
	if "exit" in str(area.name).to_lower():
		return true
	for connection in area.area_entered.get_connections():
		var callback = connection.get("callable")
		if callback is Callable and "exit" in str(callback.get_method()).to_lower():
			return true
	return false

func _find_exit() -> Area2D:
	var explicit = _read_property(
		_root, ["exit_door", "exit_door_area", "exit_area"], null
	)
	if explicit is Area2D:
		return explicit
	var areas: Array = []
	_collect_areas(_root, areas)
	for area in areas:
		if _looks_like_exit(area):
			return area
	return null

func _remaining_pickups() -> Array:
	if _root == null or not is_instance_valid(_root):
		return []
	var areas: Array = []
	_collect_areas(_root, areas)
	var pickups: Array = []
	for area in areas:
		if area == _player:
			continue
		if _ignored_ids.has(area.get_instance_id()):
			continue
		if not area.is_queued_for_deletion():
			pickups.append(area)
	return pickups

func _cell(position: Vector2) -> Vector2i:
	return Vector2i(
		clampi(int(floor(position.x / GRID)), 0, GRID_WIDTH - 1),
		clampi(int(floor(position.y / GRID)), 0, GRID_HEIGHT - 1)
	)

func _center(cell: Vector2i) -> Vector2:
	return Vector2(cell) * GRID + Vector2.ONE * (GRID * 0.5)

func _blocked(cell: Vector2i) -> bool:
	if cell.x < 0 or cell.x >= GRID_WIDTH or cell.y < 0 or cell.y >= GRID_HEIGHT:
		return true
	var half_size = float(_read_property(_root, ["player_half_size", "player_half"], 14.0))
	var center := _center(cell)
	var player_rect := Rect2(center - Vector2.ONE * half_size, Vector2.ONE * half_size * 2.0)
	for wall in _walls:
		if typeof(wall) == TYPE_RECT2 and player_rect.intersects(wall):
			return true
	return false

func _flood(start: Vector2i) -> Dictionary:
	var queue: Array[Vector2i] = [start]
	var head := 0
	var came_from := {start: start}
	var distance := {start: 0}
	var directions: Array[Vector2i] = [
		Vector2i.RIGHT, Vector2i.DOWN, Vector2i.LEFT, Vector2i.UP
	]
	while head < queue.size():
		var current := queue[head]
		head += 1
		for direction: Vector2i in directions:
			var next_cell: Vector2i = current + direction
			if came_from.has(next_cell) or _blocked(next_cell):
				continue
			came_from[next_cell] = current
			distance[next_cell] = int(distance[current]) + 1
			queue.append(next_cell)
	return {"came_from": came_from, "distance": distance}

func _placement_preflight() -> bool:
	var start := _cell(_player.global_position)
	if _blocked(start):
		_fail("player_spawn_blocked")
		return false
	var flood := _flood(start)
	var distance: Dictionary = flood.distance
	_detail_areas = []
	for pickup in _remaining_pickups():
		if not distance.has(_cell(pickup.global_position)):
			_detail_areas.append(pickup)
	if not _detail_areas.is_empty():
		_fail("unreachable_pickup")
		return false
	return true

func _plan_path() -> bool:
	var pickups := _remaining_pickups()
	if pickups.is_empty():
		_path = []
		_target = null
		return true

	var start := _cell(_player.global_position)
	if _blocked(start):
		_fail("player_spawn_blocked")
		return false
	var flood := _flood(start)
	var came_from: Dictionary = flood.came_from
	var distance: Dictionary = flood.distance

	var best_pickup: Area2D
	var best_cell := Vector2i.ZERO
	var best_distance := 1 << 30
	for pickup in pickups:
		var pickup_cell := _cell(pickup.global_position)
		if distance.has(pickup_cell) and int(distance[pickup_cell]) < best_distance:
			best_pickup = pickup
			best_cell = pickup_cell
			best_distance = int(distance[pickup_cell])
	if best_pickup == null:
		_fail("unreachable_pickup")
		return false

	var cells: Array[Vector2i] = []
	var cursor := best_cell
	while cursor != start:
		cells.push_front(cursor)
		cursor = came_from[cursor]
	_path = []
	for cell in cells:
		_path.append(_center(cell))
	# Finish at the exact Area2D position so Godot's real overlap signal fires.
	_path.append(best_pickup.global_position)
	_target = best_pickup
	_arrival_frame = -1
	return true

func _plan_exit() -> bool:
	if _exit == null or not is_instance_valid(_exit):
		_fail("exit_disappeared")
		return false
	var raw_walls = _read_property(
		_root, ["wall_rects", "walls", "active_wall_rects"], []
	)
	if typeof(raw_walls) == TYPE_ARRAY:
		_walls = raw_walls
	var start := _cell(_player.global_position)
	if _blocked(start):
		_fail("player_blocked_after_unlock")
		return false
	var flood := _flood(start)
	var came_from: Dictionary = flood.came_from
	var distance: Dictionary = flood.distance
	var exit_cell := _cell(_exit.global_position)
	if not distance.has(exit_cell):
		_detail_areas = [_exit]
		_fail("unreachable_exit")
		return false
	var cells: Array[Vector2i] = []
	var cursor := exit_cell
	while cursor != start:
		cells.push_front(cursor)
		cursor = came_from[cursor]
	_path = []
	for cell in cells:
		_path.append(_center(cell))
	_path.append(_exit.global_position)
	_target = _exit
	_phase = "exit"
	_arrival_frame = -1
	return true

func _ignore_area(candidate) -> void:
	if candidate is Area2D:
		_ignored_ids[candidate.get_instance_id()] = true
		candidate.collision_layer = 0
		candidate.collision_mask = 0
		candidate.monitoring = false
		candidate.monitorable = false

func _ignore_areas(candidate) -> void:
	if typeof(candidate) == TYPE_ARRAY:
		for area in candidate:
			_ignore_area(area)

func _initialize() -> bool:
	_root = get_tree().current_scene
	if _root == null:
		return false
	var candidate = _read_property(_root, ["player"])
	if not (candidate is Area2D):
		_fail("missing_player_interface")
		return false
	_player = candidate
	var raw_walls = _read_property(_root, ["wall_rects", "walls", "active_wall_rects"], [])
	if typeof(raw_walls) != TYPE_ARRAY:
		_fail("missing_wall_interface")
		return false
	_walls = raw_walls

	_ignore_areas(_read_property(_root, ["ghosts"], []))
	_ignore_areas(_read_property(_root, ["patrollers"], []))
	_ignore_area(_read_property(_root, ["patroller", "hunter"], null))
	_exit = _find_exit()
	if _exit != null:
		_ignored_ids[_exit.get_instance_id()] = true

	var pickups := _remaining_pickups()
	_initial_total = int(_read_property(
		_root, ["total_dots", "total_gems", "total_pickups"], pickups.size()
	))
	if _initial_total <= 0 or pickups.is_empty():
		_fail("no_pickups")
		return false
	_last_remaining = pickups.size()
	_last_progress_frame = _frame
	if not _placement_preflight():
		return false
	return _plan_path()

func _state() -> String:
	return str(_read_property(_root, ["state"], "unknown"))

func _physics_process(_delta: float) -> void:
	if not _active:
		return
	_frame += 1
	if _frame < START_DELAY_FRAMES:
		return
	if _root == null:
		if not _initialize():
			return
	_track_progress()

	if get_tree().current_scene != _root or _state() == "won":
		_pass()
		return
	if _state() == "over":
		_fail("lose_state")
		return
	if _frame >= MAX_FRAMES:
		_fail("timeout")
		return

	if _target == null or not is_instance_valid(_target) or _target.is_queued_for_deletion():
		if _phase == "exit":
			_fail("exit_disappeared")
			return
		if not _plan_path():
			return
		if _target == null:
			# Every pickup has disappeared; allow its signal one physics frame to
			# update state to won before deciding that completion logic is broken.
			if _state() == "won":
				_pass()
			elif _exit != null:
				_plan_exit()
			elif _frame % 30 == 0:
				_fail("win_state_not_reached")
			return

	if not _path.is_empty():
		var waypoint := _path[0]
		_player.global_position = _player.global_position.move_toward(waypoint, GRID * 0.75)
		if _player.global_position.distance_to(waypoint) < 1.0:
			_path.pop_front()
	elif _phase == "exit":
		if _arrival_frame < 0:
			_arrival_frame = _frame
		elif _frame - _arrival_frame >= 30:
			_fail("exit_did_not_win")
	else:
		# Reaching a pickup is not enough: its real Area2D signal must remove it
		# and advance progress. Fail early instead of laundering a dead pickup
		# interaction into a generic 200-second timeout.
		if _arrival_frame < 0:
			_arrival_frame = _frame
		elif _frame - _arrival_frame >= 60:
			_detail_areas = [_target]
			_fail("pickup_did_not_collect")

func _track_progress() -> void:
	if _root == null:
		return
	var remaining := _remaining_pickups().size()
	if _last_remaining < 0:
		_last_remaining = remaining
		_last_progress_frame = _frame
		return
	if remaining < _last_remaining:
		_progress_events += _last_remaining - remaining
		_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)
		_last_progress_frame = _frame
	_last_remaining = remaining
	_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)

func _counts() -> Dictionary:
	var remaining := _remaining_pickups().size() if _root != null else 0
	return {
		"remaining": remaining,
		"collected": maxi(0, _initial_total - remaining),
		"total": _initial_total,
	}

func _pass() -> void:
	if not _active:
		return
	_active = false
	_track_progress()
	var counts := _counts()
	_print_metrics()
	print("[OBJECTIVE] status=passed template=%s reason=none collected=%d total=%d remaining=%d frames=%d" % [_template, counts.collected, counts.total, counts.remaining, _frame])
	get_tree().quit()

func _fail(reason: String) -> void:
	if not _active:
		return
	_active = false
	_stuck = reason in ["timeout", "pickup_did_not_collect", "unreachable_pickup", "unreachable_exit"]
	_track_progress()
	var counts := _counts()
	var reported_areas := _detail_areas if not _detail_areas.is_empty() else _remaining_pickups()
	for area in reported_areas.slice(0, 12):
		print("[OBJECTIVE_DETAIL] node=%s position=(%.1f,%.1f) ignored=%s" % [area.name, area.global_position.x, area.global_position.y, str(_ignored_ids.has(area.get_instance_id()))])
	if reported_areas.size() > 12:
		print("[OBJECTIVE_DETAIL] omitted=%d" % (reported_areas.size() - 12))
	_print_metrics()
	print("[OBJECTIVE] status=failed template=%s reason=%s collected=%d total=%d remaining=%d frames=%d" % [_template, reason, counts.collected, counts.total, counts.remaining, _frame])
	get_tree().quit()

func _print_metrics() -> void:
	var restart_status := "not_applicable" if _template == "collect" else "not_tested"
	print("[OBJECTIVE_METRICS] completion_seconds=%.3f progress_events=%d max_stall_frames=%d stuck=%s restart=%s deaths=%d" % [float(_frame) / 60.0, _progress_events, _max_stall_frames, str(_stuck), restart_status, _deaths])
"""

# Ordered-switch QA runs two real interaction passes. It first activates one
# correct switch and then an intentionally wrong one, requiring the generated
# reset counter and progress to reset. It reloads the scene and completes the
# authored order from a clean state, requiring the actual `won` transition.
SWITCH_PROBE_GD = """extends Node

const MAX_FRAMES := 3600
const INTERACTION_TIMEOUT := 90
const MOVE_STEP := 14.0
const RETREAT_POSITION := Vector2(512, 288)

var _active := false
var _frame := 0
var _root: Node
var _player: Area2D
var _switches: Array[Area2D] = []
var _order: Array[int] = []
var _phase := "wrong_first"
var _target: Area2D
var _target_index := -1
var _arrival_frame := -1
var _phase_start_frame := 0
var _wrong_reset_baseline := 0
var _wrong_order_verified := false
var _reload_verified := false
var _reload_frame := -1
var _old_root_id := 0
var _correct_step := 0
var _activations := 0
var _progress_events := 0
var _max_stall_frames := 0
var _last_progress_frame := 0
var _stuck := false

func _ready() -> void:
	var template := ""
	var arguments := OS.get_cmdline_user_args()
	for argument in arguments:
		if argument.begins_with("--objective-template="):
			template = argument.trim_prefix("--objective-template=")
	_active = "--objective-probe" in arguments and template == "ordered_switches"
	if _active:
		process_priority = 610

func _has_property(object: Object, property_name: String) -> bool:
	for property in object.get_property_list():
		if str(property.get("name", "")) == property_name:
			return true
	return false

func _read_property(object: Object, property_name: String, fallback = null):
	if _has_property(object, property_name):
		return object.get(property_name)
	return fallback

func _state() -> String:
	return str(_read_property(_root, "state", "unknown")) if _root != null else "unknown"

func _progress() -> int:
	return int(_read_property(_root, "progress", -1)) if _root != null else -1

func _reset_count() -> int:
	return int(_read_property(_root, "reset_count", -1)) if _root != null else -1

func _initialize_root() -> bool:
	_root = get_tree().current_scene
	if _root == null:
		return false
	var player_candidate = _read_property(_root, "player", null)
	if not (player_candidate is Area2D):
		_fail("missing_player_interface")
		return false
	_player = player_candidate
	var raw_switches = _read_property(_root, "switches", null)
	var raw_order = _read_property(_root, "switch_order", null)
	if typeof(raw_switches) != TYPE_ARRAY or typeof(raw_order) != TYPE_ARRAY:
		_fail("missing_switch_interface")
		return false
	_switches = []
	for candidate in raw_switches:
		if not (candidate is Area2D):
			_fail("invalid_switch_interface")
			return false
		_switches.append(candidate)
	_order = []
	for value in raw_order:
		_order.append(int(value))
	if _switches.size() < 2 or _order.size() != _switches.size():
		_fail("invalid_switch_order")
		return false
	var seen := {}
	for index in _order:
		if index < 0 or index >= _switches.size() or seen.has(index):
			_fail("invalid_switch_order")
			return false
		seen[index] = true
	if _progress() != 0 or _reset_count() < 0:
		_fail("dirty_switch_state")
		return false
	return true

func _set_target(index: int) -> void:
	_target_index = index
	_target = _switches[index]
	_arrival_frame = -1
	_phase_start_frame = _frame

func _move_to_target() -> void:
	if _target == null or not is_instance_valid(_target):
		_fail("switch_disappeared")
		return
	_player.global_position = _player.global_position.move_toward(
		_target.global_position, MOVE_STEP
	)
	if _player.global_position.distance_to(_target.global_position) < 1.0 and _arrival_frame < 0:
		_arrival_frame = _frame

func _mark_progress() -> void:
	_progress_events += 1
	_activations += 1
	_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)
	_last_progress_frame = _frame

func _wrong_index() -> int:
	# Re-touching the first switch is guaranteed to be wrong at step two and
	# works even for the minimum two-switch sequence.
	return _order[0]

func _physics_process(_delta: float) -> void:
	if not _active:
		return
	_frame += 1
	_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)
	if _frame >= MAX_FRAMES:
		_fail("timeout")
		return

	if _phase == "await_reload":
		var scene := get_tree().current_scene
		if scene != null and scene.get_instance_id() != _old_root_id:
			_reload_verified = true
			if not _initialize_root():
				return
			_phase = "correct"
			_correct_step = 0
			_set_target(_order[0])
		elif _frame - _reload_frame > 180:
			_fail("reload_failed")
		return

	if _root == null:
		if not _initialize_root():
			return
		_last_progress_frame = _frame
		_set_target(_order[0])

	if get_tree().current_scene != _root:
		if _phase == "correct" and _correct_step >= _order.size() - 1:
			_correct_step = _order.size()
			_pass()
		else:
			_fail("unexpected_scene_change")
		return
	if _state() == "over":
		_fail("lose_state")
		return

	if _phase == "wrong_first":
		_move_to_target()
		if _progress() == 1:
			_mark_progress()
			_wrong_reset_baseline = _reset_count()
			_phase = "retreat"
			_target = null
			_phase_start_frame = _frame
		elif _arrival_frame >= 0 and _frame - _arrival_frame > INTERACTION_TIMEOUT:
			_fail("switch_did_not_advance")
	elif _phase == "retreat":
		_player.global_position = _player.global_position.move_toward(
			RETREAT_POSITION, MOVE_STEP
		)
		if _player.global_position.distance_to(RETREAT_POSITION) < 1.0:
			_phase = "wrong_reset"
			_set_target(_wrong_index())
	elif _phase == "wrong_reset":
		_move_to_target()
		if _reset_count() > _wrong_reset_baseline and _progress() == 0:
			_wrong_order_verified = true
			_mark_progress()
			_old_root_id = _root.get_instance_id()
			_phase = "await_reload"
			_reload_frame = _frame
			var reload_error := get_tree().reload_current_scene()
			if reload_error != OK:
				_fail("reload_failed")
		elif _state() == "won" or _progress() > 1:
			_fail("wrong_order_accepted")
		elif _arrival_frame >= 0 and _frame - _arrival_frame > INTERACTION_TIMEOUT:
			_fail("wrong_order_did_not_reset")
	elif _phase == "correct":
		_move_to_target()
		if _progress() > _correct_step:
			_correct_step = _progress()
			_mark_progress()
			if _correct_step < _order.size():
				_set_target(_order[_correct_step])
			elif _state() == "won":
				_pass()
		elif _arrival_frame >= 0 and _frame - _arrival_frame > INTERACTION_TIMEOUT:
			if _correct_step >= _order.size() and _state() != "won":
				_fail("win_state_not_reached")
			else:
				_fail("switch_did_not_advance")

func _print_metrics() -> void:
	print("[OBJECTIVE_METRICS] completion_seconds=%.3f progress_events=%d max_stall_frames=%d stuck=%s restart=%s deaths=0" % [float(_frame) / 60.0, _progress_events, _max_stall_frames, str(_stuck), "passed" if _reload_verified else "failed"])
	print("[SWITCH_METRICS] sequence_length=%d activations=%d wrong_order_reset=%s clean_reload=%s correct_progress=%d" % [_order.size(), _activations, str(_wrong_order_verified), str(_reload_verified), _correct_step])

func _pass() -> void:
	if not _active:
		return
	_active = false
	_print_metrics()
	print("[OBJECTIVE] status=passed template=ordered_switches reason=none collected=%d total=%d remaining=%d frames=%d" % [_correct_step, _order.size(), maxi(0, _order.size() - _correct_step), _frame])
	get_tree().quit()

func _fail(reason: String) -> void:
	if not _active:
		return
	_active = false
	_stuck = reason in ["timeout", "switch_did_not_advance", "wrong_order_did_not_reset", "switch_disappeared"]
	if _target != null and is_instance_valid(_target):
		print("[OBJECTIVE_DETAIL] node=%s position=(%.1f,%.1f) ignored=false" % [_target.name, _target.global_position.x, _target.global_position.y])
	_print_metrics()
	print("[OBJECTIVE] status=failed template=ordered_switches reason=%s collected=%d total=%d remaining=%d frames=%d" % [reason, _correct_step, _order.size(), maxi(0, _order.size() - _correct_step), _frame])
	get_tree().quit()
"""

# Survival QA proves both terminal paths instead of merely waiting for a
# label. It deals real Area2D collision damage until the generated lose state,
# presses the actual restart input, validates fresh state, then shortens only
# the public timer and requires the generated win transition.
SURVIVAL_PROBE_GD = """extends Node

const MAX_FRAMES := 1800
const INTERACTION_TIMEOUT := 120
const MOVE_STEP := 18.0

var _active := false
var _frame := 0
var _root: Node
var _player: Area2D
var _hazards: Array[Area2D] = []
var _target: Area2D
var _phase := "first_hit"
var _phase_start_frame := 0
var _arrival_frame := -1
var _lives_before_hit := 0
var _starting_lives := 0
var _damage_events := 0
var _milestones := 0
var _progress_events := 0
var _max_stall_frames := 0
var _last_progress_frame := 0
var _single_hit_exact := false
var _lose_verified := false
var _restart_verified := false
var _timer_win_verified := false
var _old_root_id := 0
var _restart_frame := -1
var _retreat_position := Vector2.ZERO
var _retreat_clear_frames := 0
var _stuck := false

func _ready() -> void:
	var template := ""
	var arguments := OS.get_cmdline_user_args()
	for argument in arguments:
		if argument.begins_with("--objective-template="):
			template = argument.trim_prefix("--objective-template=")
	_active = "--objective-probe" in arguments and template == "survive_hazards"
	if _active:
		process_priority = 620

func _has_property(object: Object, property_name: String) -> bool:
	for property in object.get_property_list():
		if str(property.get("name", "")) == property_name:
			return true
	return false

func _read_property(object: Object, property_name: String, fallback = null):
	if _has_property(object, property_name):
		return object.get(property_name)
	return fallback

func _state() -> String:
	return str(_read_property(_root, "state", "unknown")) if _root != null else "unknown"

func _lives() -> int:
	return int(_read_property(_root, "lives", -1)) if _root != null else -1

func _initialize_root(after_restart: bool = false) -> bool:
	_root = get_tree().current_scene
	if _root == null:
		return false
	var player_candidate = _read_property(_root, "player", null)
	var raw_hazards = _read_property(_root, "hazards", null)
	if not (player_candidate is Area2D):
		_fail("missing_player_interface")
		return false
	if typeof(raw_hazards) != TYPE_ARRAY:
		_fail("missing_hazard_interface")
		return false
	_player = player_candidate
	_hazards = []
	for candidate in raw_hazards:
		if not (candidate is Area2D):
			_fail("invalid_hazard_interface")
			return false
		_hazards.append(candidate)
	if _hazards.is_empty():
		_fail("no_hazards")
		return false
	var reported_starting := int(_read_property(_root, "starting_lives", -1))
	var survival_time := float(_read_property(_root, "survival_time", -1.0))
	if reported_starting < 2 or survival_time <= 0.0:
		_fail("invalid_survival_settings")
		return false
	if not _has_property(_root, "hit_cooldown") or not _has_property(_root, "time_left"):
		_fail("missing_survival_interface")
		return false
	if not after_restart:
		_starting_lives = reported_starting
	elif reported_starting != _starting_lives:
		_fail("restart_changed_lives")
		return false
	if _lives() != _starting_lives or _state() != "playing":
		_fail("dirty_survival_state")
		return false
	_root.set("time_left", maxf(survival_time, 60.0))
	_target = _hazards[0]
	return true

func _mark_milestone() -> void:
	_milestones += 1
	_progress_events += 1
	_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)
	_last_progress_frame = _frame

func _begin_hit() -> void:
	_lives_before_hit = _lives()
	_root.set("hit_cooldown", 0.0)
	_arrival_frame = -1
	_phase_start_frame = _frame

func _force_hit() -> void:
	if _target == null or not is_instance_valid(_target):
		_fail("hazard_disappeared")
		return
	_player.global_position = _player.global_position.move_toward(
		_target.global_position, MOVE_STEP
	)
	if _player.global_position.distance_to(_target.global_position) < 1.0 and _arrival_frame < 0:
		_arrival_frame = _frame

func _begin_retreat() -> void:
	var hazard_position := _target.global_position
	_retreat_position = Vector2(
		900.0 if hazard_position.x < 512.0 else 100.0,
		500.0 if hazard_position.y < 288.0 else 76.0
	)
	_retreat_clear_frames = 0
	_phase = "retreat"
	_phase_start_frame = _frame

func _process_hit(first_hit: bool) -> void:
	_force_hit()
	var current_lives := _lives()
	if current_lives < _lives_before_hit - 1:
		_fail("excessive_collision_damage")
		return
	if current_lives == _lives_before_hit - 1:
		_damage_events += 1
		if first_hit:
			_single_hit_exact = true
			_mark_milestone()
		if current_lives <= 0:
			if _state() != "over":
				_fail("lose_state_not_reached")
				return
			_lose_verified = true
			_mark_milestone()
			_old_root_id = _root.get_instance_id()
			_phase = "await_restart"
			_restart_frame = _frame
			Input.action_press("ui_accept")
		else:
			_begin_retreat()
	elif _arrival_frame >= 0 and _frame - _arrival_frame > INTERACTION_TIMEOUT:
		_fail("collision_did_not_damage")

func _disable_hazards() -> void:
	for hazard in _hazards:
		hazard.collision_layer = 0
		hazard.collision_mask = 0
		hazard.monitoring = false
		hazard.monitorable = false

func _physics_process(_delta: float) -> void:
	if not _active:
		return
	_frame += 1
	_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)
	if _frame >= MAX_FRAMES:
		_fail("timeout")
		return

	if _phase == "await_restart":
		if _frame > _restart_frame:
			Input.action_release("ui_accept")
		var scene := get_tree().current_scene
		if scene != null and scene.get_instance_id() != _old_root_id:
			if not _initialize_root(true):
				return
			_restart_verified = true
			_mark_milestone()
			_disable_hazards()
			_root.set("time_left", 0.05)
			_phase = "timer_win"
			_phase_start_frame = _frame
		elif _frame - _restart_frame > INTERACTION_TIMEOUT:
			_fail("restart_failed")
		return

	if _root == null:
		if not _initialize_root():
			return
		_last_progress_frame = _frame
		_begin_hit()

	if get_tree().current_scene != _root:
		if _phase == "timer_win":
			_timer_win_verified = true
			_mark_milestone()
			_pass()
		else:
			_fail("unexpected_scene_change")
		return

	if _phase == "first_hit":
		_process_hit(true)
	elif _phase == "retreat":
		_player.global_position = _player.global_position.move_toward(
			_retreat_position, MOVE_STEP
		)
		if _player.global_position.distance_to(_target.global_position) > 90.0:
			_retreat_clear_frames += 1
		else:
			_retreat_clear_frames = 0
		if _retreat_clear_frames >= 3:
			_phase = "lose_hit"
			_begin_hit()
		elif _frame - _phase_start_frame > INTERACTION_TIMEOUT:
			_fail("could_not_leave_hazard")
	elif _phase == "lose_hit":
		_process_hit(false)
	elif _phase == "timer_win":
		if _state() == "won":
			_timer_win_verified = true
			_mark_milestone()
			_pass()
		elif _state() == "over":
			_fail("lose_after_clean_restart")
		elif _frame - _phase_start_frame > INTERACTION_TIMEOUT:
			_fail("timer_win_not_reached")

func _print_metrics() -> void:
	print("[OBJECTIVE_METRICS] completion_seconds=%.3f progress_events=%d max_stall_frames=%d stuck=%s restart=%s deaths=%d" % [float(_frame) / 60.0, _progress_events, _max_stall_frames, str(_stuck), "passed" if _restart_verified else "failed", 1 if _lose_verified else 0])
	print("[SURVIVAL_METRICS] starting_lives=%d damage_events=%d single_hit_exact=%s lose_verified=%s clean_restart=%s timer_win=%s" % [_starting_lives, _damage_events, str(_single_hit_exact), str(_lose_verified), str(_restart_verified), str(_timer_win_verified)])

func _pass() -> void:
	if not _active:
		return
	_active = false
	Input.action_release("ui_accept")
	_print_metrics()
	print("[OBJECTIVE] status=passed template=survive_hazards reason=none collected=%d total=4 remaining=%d frames=%d" % [_milestones, maxi(0, 4 - _milestones), _frame])
	get_tree().quit()

func _fail(reason: String) -> void:
	if not _active:
		return
	_active = false
	Input.action_release("ui_accept")
	_stuck = reason in ["timeout", "collision_did_not_damage", "could_not_leave_hazard", "restart_failed", "timer_win_not_reached"]
	if _target != null and is_instance_valid(_target):
		print("[OBJECTIVE_DETAIL] node=%s position=(%.1f,%.1f) ignored=false" % [_target.name, _target.global_position.x, _target.global_position.y])
	_print_metrics()
	print("[OBJECTIVE] status=failed template=survive_hazards reason=%s collected=%d total=4 remaining=%d frames=%d" % [reason, _milestones, maxi(0, 4 - _milestones), _frame])
	get_tree().quit()
"""

# Depletion QA exercises live overlap-driven resource behavior. It observes
# drain outside all zones, moves the real player inside a real refill Area2D,
# forces resource exhaustion and restart, then accelerates only the public
# timer and requires the generated win path.
DEPLETION_PROBE_GD = """extends Node

const MAX_FRAMES := 1800
const PHASE_TIMEOUT := 180
const MOVE_STEP := 20.0
const CHANGE_EPSILON := 0.2

var _active := false
var _frame := 0
var _root: Node
var _player: Area2D
var _zones: Array[Area2D] = []
var _target_zone: Area2D
var _phase := "initial_outside"
var _phase_start_frame := 0
var _settled_frames := 0
var _resource_max := 0.0
var _baseline := 0.0
var _drained_amount := 0.0
var _refilled_amount := 0.0
var _drain_verified := false
var _refill_verified := false
var _lose_verified := false
var _restart_verified := false
var _timer_win_verified := false
var _milestones := 0
var _progress_events := 0
var _max_stall_frames := 0
var _last_progress_frame := 0
var _old_root_id := 0
var _restart_frame := -1
var _outside_position := Vector2.ZERO
var _stuck := false

func _ready() -> void:
	var template := ""
	var arguments := OS.get_cmdline_user_args()
	for argument in arguments:
		if argument.begins_with("--objective-template="):
			template = argument.trim_prefix("--objective-template=")
	_active = "--objective-probe" in arguments and template == "depletion"
	if _active:
		process_priority = 630

func _has_property(object: Object, property_name: String) -> bool:
	for property in object.get_property_list():
		if str(property.get("name", "")) == property_name:
			return true
	return false

func _read_property(object: Object, property_name: String, fallback = null):
	if _has_property(object, property_name):
		return object.get(property_name)
	return fallback

func _state() -> String:
	return str(_read_property(_root, "state", "unknown")) if _root != null else "unknown"

func _resource() -> float:
	return float(_read_property(_root, "resource", -1.0)) if _root != null else -1.0

func _zones_inside() -> int:
	return int(_read_property(_root, "zones_inside", -1)) if _root != null else -1

func _initialize_root(after_restart: bool = false) -> bool:
	_root = get_tree().current_scene
	if _root == null:
		return false
	var player_candidate = _read_property(_root, "player", null)
	var raw_zones = _read_property(_root, "refill_zones", null)
	if not (player_candidate is Area2D):
		_fail("missing_player_interface")
		return false
	if typeof(raw_zones) != TYPE_ARRAY:
		_fail("missing_refill_zone_interface")
		return false
	_player = player_candidate
	_zones = []
	for candidate in raw_zones:
		if not (candidate is Area2D):
			_fail("invalid_refill_zone_interface")
			return false
		_zones.append(candidate)
	if _zones.is_empty():
		_fail("no_refill_zones")
		return false
	for property_name in ["resource_max", "resource", "drain_rate", "refill_rate", "zones_inside", "survival_time", "time_left"]:
		if not _has_property(_root, property_name):
			_fail("missing_depletion_interface")
			return false
	var reported_max := float(_read_property(_root, "resource_max", -1.0))
	var drain_rate := float(_read_property(_root, "drain_rate", -1.0))
	var refill_rate := float(_read_property(_root, "refill_rate", -1.0))
	var survival_time := float(_read_property(_root, "survival_time", -1.0))
	if reported_max <= 0.0 or drain_rate <= 0.0 or refill_rate <= drain_rate or survival_time <= 0.0:
		_fail("invalid_depletion_settings")
		return false
	if not after_restart:
		_resource_max = reported_max
	elif absf(reported_max - _resource_max) > 0.01:
		_fail("restart_changed_resource_max")
		return false
	if _resource() < _resource_max * 0.9 or _state() != "playing":
		_fail("dirty_depletion_state")
		return false
	_root.set("time_left", maxf(survival_time, 60.0))
	_target_zone = _zones[0]
	_outside_position = _find_outside_position()
	return true

func _find_outside_position() -> Vector2:
	var candidates := [
		Vector2(32, 32), Vector2(992, 32),
		Vector2(32, 544), Vector2(992, 544),
	]
	var best: Vector2 = candidates[0]
	var best_clearance := -1.0
	for candidate: Vector2 in candidates:
		var clearance := 1.0e20
		for zone in _zones:
			clearance = minf(clearance, candidate.distance_to(zone.global_position))
		if clearance > best_clearance:
			best = candidate
			best_clearance = clearance
	return best

func _mark_milestone() -> void:
	_milestones += 1
	_progress_events += 1
	_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)
	_last_progress_frame = _frame

func _begin_phase(name: String) -> void:
	_phase = name
	_phase_start_frame = _frame
	_settled_frames = 0

func _place_outside() -> void:
	_player.global_position = _outside_position

func _move_to_zone() -> void:
	if _target_zone == null or not is_instance_valid(_target_zone):
		_fail("refill_zone_disappeared")
		return
	_player.global_position = _player.global_position.move_toward(
		_target_zone.global_position, MOVE_STEP
	)

func _physics_process(_delta: float) -> void:
	if not _active:
		return
	_frame += 1
	_max_stall_frames = maxi(_max_stall_frames, _frame - _last_progress_frame)
	if _frame >= MAX_FRAMES:
		_fail("timeout")
		return

	if _phase == "await_restart":
		if _frame > _restart_frame:
			Input.action_release("ui_accept")
		var scene := get_tree().current_scene
		if scene != null and scene.get_instance_id() != _old_root_id:
			if not _initialize_root(true):
				return
			_restart_verified = true
			_mark_milestone()
			_root.set("resource", _resource_max)
			_root.set("time_left", 0.05)
			_begin_phase("timer_win")
		elif _frame - _restart_frame > PHASE_TIMEOUT:
			_fail("restart_failed")
		return

	if _root == null:
		if not _initialize_root():
			return
		_last_progress_frame = _frame
		_place_outside()
		_begin_phase("initial_outside")

	if get_tree().current_scene != _root:
		if _phase == "timer_win":
			_timer_win_verified = true
			_mark_milestone()
			_pass()
		else:
			_fail("unexpected_scene_change")
		return

	if _phase == "initial_outside":
		_place_outside()
		if _zones_inside() == 0:
			_settled_frames += 1
		else:
			_settled_frames = 0
		if _settled_frames >= 5:
			_baseline = _resource()
			_begin_phase("drain")
	elif _phase == "drain":
		var change := _baseline - _resource()
		if change >= CHANGE_EPSILON:
			_drained_amount = change
			_drain_verified = true
			_mark_milestone()
			_root.set("resource", _resource_max * 0.5)
			_begin_phase("seek_refill")
		elif _resource() > _baseline + 0.01:
			_fail("resource_increased_outside_zone")
		elif _frame - _phase_start_frame > PHASE_TIMEOUT:
			_fail("resource_did_not_drain")
	elif _phase == "seek_refill":
		_move_to_zone()
		if _zones_inside() > 0:
			_baseline = _resource()
			_begin_phase("refill")
		elif _frame - _phase_start_frame > PHASE_TIMEOUT:
			_fail("refill_zone_not_entered")
	elif _phase == "refill":
		var change := _resource() - _baseline
		if change >= CHANGE_EPSILON:
			_refilled_amount = change
			_refill_verified = true
			_mark_milestone()
			_place_outside()
			_begin_phase("loss_outside")
		elif _frame - _phase_start_frame > PHASE_TIMEOUT:
			_fail("resource_did_not_refill")
	elif _phase == "loss_outside":
		_place_outside()
		if _zones_inside() == 0:
			_settled_frames += 1
		else:
			_settled_frames = 0
		if _settled_frames >= 5:
			_root.set("resource", 0.01)
			_begin_phase("resource_loss")
		elif _frame - _phase_start_frame > PHASE_TIMEOUT:
			_fail("could_not_leave_refill_zone")
	elif _phase == "resource_loss":
		if _state() == "over":
			_lose_verified = true
			_mark_milestone()
			_old_root_id = _root.get_instance_id()
			_restart_frame = _frame
			_phase = "await_restart"
			Input.action_press("ui_accept")
		elif _state() == "won":
			_fail("won_with_empty_resource")
		elif _frame - _phase_start_frame > PHASE_TIMEOUT:
			_fail("empty_resource_did_not_lose")
	elif _phase == "timer_win":
		if _state() == "won":
			_timer_win_verified = true
			_mark_milestone()
			_pass()
		elif _state() == "over":
			_fail("lost_with_full_resource")
		elif _frame - _phase_start_frame > PHASE_TIMEOUT:
			_fail("timer_win_not_reached")

func _print_metrics() -> void:
	print("[OBJECTIVE_METRICS] completion_seconds=%.3f progress_events=%d max_stall_frames=%d stuck=%s restart=%s deaths=%d" % [float(_frame) / 60.0, _progress_events, _max_stall_frames, str(_stuck), "passed" if _restart_verified else "failed", 1 if _lose_verified else 0])
	print("[DEPLETION_METRICS] resource_max=%.3f drained_amount=%.3f refilled_amount=%.3f drain_verified=%s refill_verified=%s lose_verified=%s clean_restart=%s timer_win=%s" % [_resource_max, _drained_amount, _refilled_amount, str(_drain_verified), str(_refill_verified), str(_lose_verified), str(_restart_verified), str(_timer_win_verified)])

func _pass() -> void:
	if not _active:
		return
	_active = false
	Input.action_release("ui_accept")
	_print_metrics()
	print("[OBJECTIVE] status=passed template=depletion reason=none collected=%d total=5 remaining=%d frames=%d" % [_milestones, maxi(0, 5 - _milestones), _frame])
	get_tree().quit()

func _fail(reason: String) -> void:
	if not _active:
		return
	_active = false
	Input.action_release("ui_accept")
	_stuck = reason in ["timeout", "resource_did_not_drain", "refill_zone_not_entered", "resource_did_not_refill", "could_not_leave_refill_zone", "empty_resource_did_not_lose", "restart_failed", "timer_win_not_reached"]
	if _target_zone != null and is_instance_valid(_target_zone):
		print("[OBJECTIVE_DETAIL] node=%s position=(%.1f,%.1f) ignored=false" % [_target_zone.name, _target_zone.global_position.x, _target_zone.global_position.y])
	_print_metrics()
	print("[OBJECTIVE] status=failed template=depletion reason=%s collected=%d total=5 remaining=%d frames=%d" % [reason, _milestones, maxi(0, 5 - _milestones), _frame])
	get_tree().quit()
"""

HYBRID_PROBE_GD = """extends Node

const MAX_FRAMES := 1800
const TIMEOUT := 180
const MOVE_STEP := 22.0
var _active := false
var _frame := 0
var _root: Node
var _player: Area2D
var _zones: Array[Area2D] = []
var _hazards: Array[Area2D] = []
var _phase := "outside"
var _phase_frame := 0
var _baseline := 0.0
var _fuel_baseline := 0.0
var _drain_first := 0.0
var _drain_second := 0.0
var _refill_amount := 0.0
var _fuel_used := 0.0
var _hazard_damage := 0.0
var _ramp_ok := false
var _refill_ok := false
var _fuel_ok := false
var _hazard_ok := false
var _lose_ok := false
var _restart_ok := false
var _win_ok := false
var _milestones := 0
var _max_stall := 0
var _last_progress := 0
var _old_root_id := 0
var _restart_frame := 0
var _resource_max := 0.0
var _outside := Vector2(32, 32)
var _stuck := false

func _ready():
	var template := ""
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--objective-template="):
			template = argument.trim_prefix("--objective-template=")
	_active = "--objective-probe" in OS.get_cmdline_user_args() and template == "survive_and_deplete"
	if _active: process_priority = 640

func _has(o: Object, name: String) -> bool:
	for p in o.get_property_list():
		if str(p.get("name", "")) == name: return true
	return false

func _root_value(name: String, fallback = null):
	return _root.get(name) if _root != null and _has(_root, name) else fallback

func _state() -> String: return str(_root_value("state", "unknown"))
func _resource() -> float: return float(_root_value("resource", -1.0))

func _initialize_root(after_restart := false) -> bool:
	_root = get_tree().current_scene
	if _root == null: return false
	var p = _root_value("player")
	var zs = _root_value("zones")
	var hs = _root_value("hazards")
	for name in ["resource_max", "resource", "drain_rate", "drain_ramp", "refill_rate", "fuel_burn", "hazard_hit_cost", "hit_cooldown", "time_left", "survival_time", "zone_fuel", "inside_zones"]:
		if not _has(_root, name): _fail("missing_hybrid_interface"); return false
	if not (p is Area2D) or typeof(zs) != TYPE_ARRAY or typeof(hs) != TYPE_ARRAY:
		_fail("missing_hybrid_nodes"); return false
	_player = p; _zones = []; _hazards = []
	for z in zs:
		if not (z is Area2D): _fail("invalid_zone_interface"); return false
		_zones.append(z)
	for h in hs:
		if not (h is Area2D): _fail("invalid_hazard_interface"); return false
		_hazards.append(h)
	if _zones.is_empty() or _hazards.is_empty(): _fail("missing_hybrid_objects"); return false
	var mx := float(_root_value("resource_max", -1.0))
	if not after_restart: _resource_max = mx
	if mx <= 0 or absf(mx - _resource_max) > 0.01 or _resource() < mx * 0.9 or _state() != "playing":
		_fail("dirty_hybrid_state"); return false
	_root.set("time_left", maxf(float(_root_value("survival_time", 60.0)), 60.0))
	_outside = Vector2(992, 32)
	return true

func _mark():
	_milestones += 1
	_max_stall = maxi(_max_stall, _frame - _last_progress)
	_last_progress = _frame

func _begin(name: String): _phase = name; _phase_frame = _frame

func _physics_process(_delta):
	if not _active: return
	_frame += 1; _max_stall = maxi(_max_stall, _frame - _last_progress)
	if _frame >= MAX_FRAMES: _fail("timeout"); return
	if _phase == "restart":
		if _frame > _restart_frame: Input.action_release("ui_accept")
		var scene := get_tree().current_scene
		if scene != null and scene.get_instance_id() != _old_root_id:
			if not _initialize_root(true): return
			_restart_ok = true; _mark(); _root.set("resource", _resource_max); _root.set("time_left", 0.05)
			for h in _hazards: h.collision_layer = 0; h.collision_mask = 0; h.monitoring = false
			_begin("win")
		elif _frame - _restart_frame > TIMEOUT: _fail("restart_failed")
		return
	if _root == null:
		if not _initialize_root(): return
		_last_progress = _frame; _player.global_position = _outside; _begin("outside")
	if get_tree().current_scene != _root:
		if _phase == "win": _win_ok = true; _mark(); _pass()
		else: _fail("unexpected_scene_change")
		return
	if _phase == "outside":
		_player.global_position = _outside
		if _frame - _phase_frame == 5: _baseline = _resource()
		elif _frame - _phase_frame == 95: _drain_first = _baseline - _resource(); _baseline = _resource()
		elif _frame - _phase_frame == 185:
			_drain_second = _baseline - _resource()
			if _drain_first <= 0 or _drain_second <= _drain_first: _fail("drain_ramp_not_observed"); return
			_ramp_ok = true; _mark(); _root.set("resource", _resource_max * 0.5); _begin("seek_zone")
	elif _phase == "seek_zone":
		_player.global_position = _player.global_position.move_toward(_zones[0].global_position, MOVE_STEP)
		var inside = _root_value("inside_zones", [])
		if typeof(inside) == TYPE_ARRAY and inside.size() > 0 and inside[0]:
			_baseline = _resource(); var fuel = _root_value("zone_fuel", []); _fuel_baseline = float(fuel[0]); _begin("refill")
		elif _frame - _phase_frame > TIMEOUT: _fail("zone_not_entered")
	elif _phase == "refill":
		var fuel = _root_value("zone_fuel", [])
		_refill_amount = _resource() - _baseline; _fuel_used = _fuel_baseline - float(fuel[0])
		if _refill_amount > 0.2 and _fuel_used > 0.2:
			_refill_ok = true; _fuel_ok = true; _mark(); _mark(); _player.global_position = _outside
			_root.set("resource", _resource_max * 0.8); _root.set("hit_cooldown", 0.0); _baseline = _resource(); _begin("hazard")
		elif _frame - _phase_frame > TIMEOUT: _fail("refill_or_fuel_failed")
	elif _phase == "hazard":
		_player.global_position = _player.global_position.move_toward(_hazards[0].global_position, MOVE_STEP)
		_hazard_damage = _baseline - _resource()
		if _hazard_damage >= float(_root_value("hazard_hit_cost", 1.0)) * 0.8:
			_hazard_ok = true; _mark(); _player.global_position = _outside; _root.set("resource", 0.01); _begin("lose")
		elif _frame - _phase_frame > TIMEOUT: _fail("hazard_did_not_damage")
	elif _phase == "lose":
		if _state() == "over":
			_lose_ok = true; _mark(); _old_root_id = _root.get_instance_id(); _restart_frame = _frame; _phase = "restart"; Input.action_press("ui_accept")
		elif _frame - _phase_frame > TIMEOUT: _fail("empty_resource_did_not_lose")
	elif _phase == "win":
		if _state() == "won": _win_ok = true; _mark(); _pass()
		elif _frame - _phase_frame > TIMEOUT: _fail("timer_win_not_reached")

func _metrics():
	print("[OBJECTIVE_METRICS] completion_seconds=%.3f progress_events=%d max_stall_frames=%d stuck=%s restart=%s deaths=%d" % [float(_frame)/60.0, _milestones, _max_stall, str(_stuck), "passed" if _restart_ok else "failed", 1 if _lose_ok else 0])
	print("[HYBRID_METRICS] drain_first=%.3f drain_second=%.3f refill=%.3f fuel_used=%.3f hazard_damage=%.3f ramp=%s refill_ok=%s fuel_ok=%s hazard_ok=%s lose=%s restart_ok=%s timer_win=%s" % [_drain_first, _drain_second, _refill_amount, _fuel_used, _hazard_damage, str(_ramp_ok), str(_refill_ok), str(_fuel_ok), str(_hazard_ok), str(_lose_ok), str(_restart_ok), str(_win_ok)])

func _pass():
	if not _active: return
	_active = false; Input.action_release("ui_accept"); _metrics()
	print("[OBJECTIVE] status=passed template=survive_and_deplete reason=none collected=%d total=7 remaining=%d frames=%d" % [_milestones, maxi(0, 7-_milestones), _frame]); get_tree().quit()

func _fail(reason: String):
	if not _active: return
	_active = false; Input.action_release("ui_accept"); _stuck = true; _metrics()
	print("[OBJECTIVE] status=failed template=survive_and_deplete reason=%s collected=%d total=7 remaining=%d frames=%d" % [reason, _milestones, maxi(0, 7-_milestones), _frame]); get_tree().quit()
"""

CAPTURE_PROBE_GD = """extends Node

const MAX_FRAMES := 1800
const PHASE_TIMEOUT := 300
var _active := false
var _frame := 0
var _root: Node
var _player: Area2D
var _patroller: Area2D
var _zones: Array[Area2D] = []
var _outside := Vector2(32, 32)
var _phase := "initialize"
var _phase_frame := 0
var _capture_baseline := 0.0
var _capture_gain := 0.0
var _contest_baseline := 0.0
var _decay_amount := 0.0
var _target_zone := 0
var _capture_ok := false
var _contest_ok := false
var _ownership_ok := false
var _win_ok := false
var _milestones := 0
var _last_progress := 0
var _max_stall := 0
var _stuck := false

func _ready():
	var template := ""
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--objective-template="):
			template = argument.trim_prefix("--objective-template=")
	_active = "--objective-probe" in OS.get_cmdline_user_args() and template == "capture_zones"
	if _active: process_priority = 650

func _has(object: Object, name: String) -> bool:
	for property in object.get_property_list():
		if str(property.get("name", "")) == name: return true
	return false

func _root_value(name: String, fallback = null):
	return _root.get(name) if _root != null and _has(_root, name) else fallback

func _choose_outside() -> Vector2:
	var best := Vector2(32, 32)
	var best_distance := -1.0
	for candidate in [Vector2(32, 32), Vector2(992, 32), Vector2(32, 544), Vector2(992, 544)]:
		var nearest := 1000000.0
		for zone in _zones: nearest = minf(nearest, candidate.distance_to(zone.global_position))
		if nearest > best_distance: best = candidate; best_distance = nearest
	return best

func _initialize_root() -> bool:
	_root = get_tree().current_scene
	if _root == null: return false
	for name in ["player", "zones", "patroller", "zone_progress", "zone_owner", "player_in_zones", "enemy_in_zones", "capture_required", "capture_radius", "capture_rate", "decay_rate", "patroller_speed", "state"]:
		if not _has(_root, name): _fail("missing_capture_interface"); return false
	var player = _root_value("player")
	var patroller = _root_value("patroller")
	var zones = _root_value("zones", [])
	var progress = _root_value("zone_progress", [])
	var owners = _root_value("zone_owner", [])
	var player_inside = _root_value("player_in_zones", [])
	var enemy_inside = _root_value("enemy_in_zones", [])
	if not (player is Area2D) or not (patroller is Area2D) or typeof(zones) != TYPE_ARRAY:
		_fail("invalid_capture_nodes"); return false
	if zones.size() < 2 or progress.size() != zones.size() or owners.size() != zones.size() or player_inside.size() != zones.size() or enemy_inside.size() != zones.size():
		_fail("invalid_capture_arrays"); return false
	_player = player; _patroller = patroller; _zones = []
	for zone in zones:
		if not (zone is Area2D): _fail("invalid_capture_zone"); return false
		_zones.append(zone)
	if float(_root_value("capture_required", 0.0)) <= 0.0 or float(_root_value("capture_radius", 0.0)) <= 0.0 or float(_root_value("capture_rate", 0.0)) <= 0.0 or float(_root_value("decay_rate", 0.0)) <= 0.0:
		_fail("invalid_capture_rates"); return false
	if str(_root_value("state", "unknown")) != "playing": _fail("dirty_capture_state"); return false
	for i in owners.size():
		if int(owners[i]) != 0 or float(progress[i]) > 0.01: _fail("dirty_capture_ownership"); return false
	_root.set("patroller_speed", 0.0)
	_outside = _choose_outside()
	_player.global_position = _outside; _patroller.global_position = _outside
	_begin("settle")
	return true

func _progress(index: int) -> float:
	var values = _root_value("zone_progress", [])
	return float(values[index]) if index >= 0 and index < values.size() else -1.0

func _owner(index: int) -> int:
	var values = _root_value("zone_owner", [])
	return int(values[index]) if index >= 0 and index < values.size() else -99

func _mark():
	_milestones += 1
	_max_stall = maxi(_max_stall, _frame - _last_progress)
	_last_progress = _frame

func _begin(name: String):
	_phase = name; _phase_frame = _frame

func _physics_process(_delta):
	if not _active: return
	_frame += 1; _max_stall = maxi(_max_stall, _frame - _last_progress)
	if _frame >= MAX_FRAMES: _fail("timeout"); return
	if _root == null:
		if not _initialize_root(): return
	if get_tree().current_scene != _root: _fail("unexpected_scene_change"); return
	if _phase == "settle":
		_player.global_position = _outside; _patroller.global_position = _outside
		if _frame - _phase_frame >= 5:
			_capture_baseline = _progress(0); _begin("capture")
	elif _phase == "capture":
		_player.global_position = _zones[0].global_position; _patroller.global_position = _outside
		_capture_gain = _progress(0) - _capture_baseline
		if _owner(0) == 1 and _capture_gain > 0.1:
			_capture_ok = true; _mark(); _contest_baseline = _progress(0); _begin("contest")
		elif _frame - _phase_frame > PHASE_TIMEOUT: _fail("zone_did_not_capture")
	elif _phase == "contest":
		_player.global_position = _zones[0].global_position + Vector2(30, 0); _patroller.global_position = _zones[0].global_position - Vector2(30, 0)
		_decay_amount = _contest_baseline - _progress(0)
		if _decay_amount > 0.1:
			_contest_ok = true; _mark(); _begin("ownership_reset")
		elif _frame - _phase_frame > PHASE_TIMEOUT: _fail("contest_did_not_decay")
	elif _phase == "ownership_reset":
		_player.global_position = _outside; _patroller.global_position = _zones[0].global_position
		_decay_amount = _contest_baseline - _progress(0)
		if _owner(0) == 0 and _progress(0) <= 0.01:
			_ownership_ok = true; _mark(); _patroller.global_position = _outside; _target_zone = 0; _begin("capture_all")
		elif _frame - _phase_frame > PHASE_TIMEOUT: _fail("ownership_did_not_reset")
	elif _phase == "capture_all":
		_patroller.global_position = _outside
		if _target_zone < _zones.size():
			_player.global_position = _zones[_target_zone].global_position
			if _owner(_target_zone) == 1:
				_target_zone += 1; _phase_frame = _frame
			elif _frame - _phase_frame > PHASE_TIMEOUT: _fail("zone_did_not_recapture")
		else:
			_player.global_position = _outside; _begin("win")
	elif _phase == "win":
		_patroller.global_position = _outside
		if str(_root_value("state", "unknown")) == "won":
			_win_ok = true; _mark(); _pass()
		elif _frame - _phase_frame > PHASE_TIMEOUT: _fail("all_owned_did_not_win")

func _metrics():
	var owned := 0
	for owner in _root_value("zone_owner", []):
		if int(owner) == 1: owned += 1
	print("[OBJECTIVE_METRICS] completion_seconds=%.3f progress_events=%d max_stall_frames=%d stuck=%s restart=not_applicable deaths=0" % [float(_frame) / 60.0, _milestones, _max_stall, str(_stuck)])
	print("[CAPTURE_METRICS] capture_gain=%.3f decay=%.3f owned=%d zones=%d capture=%s contest=%s ownership=%s win=%s" % [_capture_gain, _decay_amount, owned, _zones.size(), str(_capture_ok), str(_contest_ok), str(_ownership_ok), str(_win_ok)])
	print("[CAPTURE_OVERLAP] player=%s enemy=%s" % [str(_root_value("player_in_zones", [])), str(_root_value("enemy_in_zones", []))])

func _pass():
	if not _active: return
	_active = false; _metrics()
	print("[OBJECTIVE] status=passed template=capture_zones reason=none collected=%d total=4 remaining=%d frames=%d" % [_milestones, maxi(0, 4 - _milestones), _frame]); get_tree().quit()

func _fail(reason: String):
	if not _active: return
	_active = false; _stuck = true; _metrics()
	print("[OBJECTIVE] status=failed template=capture_zones reason=%s collected=%d total=4 remaining=%d frames=%d" % [reason, _milestones, maxi(0, 4 - _milestones), _frame]); get_tree().quit()
"""

HERD_PROBE_GD = """extends Node

const MAX_FRAMES := 3600
const TARGET_TIMEOUT := 720
const STILL_FRAMES := 30
var _active := false
var _frame := 0
var _root: Node
var _player: Area2D
var _goal: Area2D
var _creatures: Array[Area2D] = []
var _safe_spot := Vector2(32, 32)
var _phase := "initialize"
var _phase_frame := 0
var _baseline_position := Vector2.ZERO
var _settled_position := Vector2.ZERO
var _start_goal_distance := 0.0
var _still_drift := 0.0
var _flee_distance := 0.0
var _goal_gain := 0.0
var _target_creature := 0
var _still_ok := false
var _flee_ok := false
var _settle_ok := false
var _persistent_ok := false
var _win_ok := false
var _milestones := 0
var _last_progress := 0
var _max_stall := 0
var _stuck := false

func _ready():
	var template := ""
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--objective-template="):
			template = argument.trim_prefix("--objective-template=")
	_active = "--objective-probe" in OS.get_cmdline_user_args() and template == "herd_to_goal"
	if _active: process_priority = 660

func _has(object: Object, name: String) -> bool:
	for property in object.get_property_list():
		if str(property.get("name", "")) == name: return true
	return false

func _root_value(name: String, fallback = null):
	return _root.get(name) if _root != null and _has(_root, name) else fallback

func _is_settled(index: int) -> bool:
	var values = _root_value("creature_settled", [])
	return bool(values[index]) if index >= 0 and index < values.size() else false

func _choose_safe_spot() -> Vector2:
	var best := Vector2(32, 32)
	var best_distance := -1.0
	for candidate in [Vector2(32, 32), Vector2(992, 32), Vector2(32, 544), Vector2(992, 544)]:
		var distance: float = candidate.distance_to(_creatures[0].global_position)
		if distance > best_distance: best = candidate; best_distance = distance
	return best

func _initialize_root() -> bool:
	_root = get_tree().current_scene
	if _root == null: return false
	for name in ["player", "creatures", "creature_settled", "goal", "panic_radius", "goal_radius", "speed", "flee_speed", "state"]:
		if not _has(_root, name): _fail("missing_herd_interface"); return false
	var player = _root_value("player")
	var goal = _root_value("goal")
	var creatures = _root_value("creatures", [])
	var settled = _root_value("creature_settled", [])
	if not (player is Area2D) or not (goal is Area2D) or typeof(creatures) != TYPE_ARRAY:
		_fail("invalid_herd_nodes"); return false
	if creatures.is_empty() or settled.size() != creatures.size(): _fail("invalid_herd_arrays"); return false
	_player = player; _goal = goal; _creatures = []
	for creature in creatures:
		if not (creature is Area2D): _fail("invalid_herd_creature"); return false
		_creatures.append(creature)
	for value in settled:
		if bool(value): _fail("dirty_herd_settlement"); return false
	var panic := float(_root_value("panic_radius", 0.0))
	var goal_radius := float(_root_value("goal_radius", 0.0))
	var player_speed := float(_root_value("speed", 0.0))
	var flee_speed := float(_root_value("flee_speed", 0.0))
	if panic <= 0.0 or goal_radius <= 0.0 or flee_speed <= 0.0 or player_speed <= 0.0 or flee_speed >= player_speed * 0.6:
		_fail("invalid_herd_balance"); return false
	if str(_root_value("state", "unknown")) != "playing": _fail("dirty_herd_state"); return false
	_safe_spot = _choose_safe_spot()
	if _safe_spot.distance_to(_creatures[0].global_position) <= panic + 10.0: _fail("no_calm_approach_space"); return false
	_player.global_position = _safe_spot; _begin("settle")
	return true

func _mark():
	_milestones += 1
	_max_stall = maxi(_max_stall, _frame - _last_progress)
	_last_progress = _frame

func _begin(name: String):
	_phase = name; _phase_frame = _frame

func _place_behind(index: int):
	var creature := _creatures[index]
	var toward_goal := creature.global_position.direction_to(_goal.global_position)
	if toward_goal.length_squared() < 0.01: toward_goal = Vector2.RIGHT
	var follow_distance := minf(float(_root_value("panic_radius", 100.0)) * 0.45, 45.0)
	_player.global_position = creature.global_position - toward_goal * follow_distance

func _physics_process(_delta):
	if not _active: return
	_frame += 1; _max_stall = maxi(_max_stall, _frame - _last_progress)
	if _frame >= MAX_FRAMES: _fail("timeout"); return
	if _root == null:
		if not _initialize_root(): return
	if get_tree().current_scene != _root: _fail("unexpected_scene_change"); return
	if _phase == "settle":
		_player.global_position = _safe_spot
		if _frame - _phase_frame >= 5:
			_baseline_position = _creatures[0].global_position; _begin("still")
	elif _phase == "still":
		_player.global_position = _safe_spot
		_still_drift = _baseline_position.distance_to(_creatures[0].global_position)
		if _frame - _phase_frame >= STILL_FRAMES:
			if _still_drift > 0.5: _fail("creature_moved_outside_panic_radius"); return
			_still_ok = true; _mark(); _baseline_position = _creatures[0].global_position
			_start_goal_distance = _baseline_position.distance_to(_goal.global_position); _begin("flee")
	elif _phase == "flee":
		_place_behind(0)
		_flee_distance = _baseline_position.distance_to(_creatures[0].global_position)
		_goal_gain = _start_goal_distance - _creatures[0].global_position.distance_to(_goal.global_position)
		if _flee_distance > 2.0 and _goal_gain > 1.0:
			_flee_ok = true; _mark(); _begin("settle_first")
		elif _frame - _phase_frame > TARGET_TIMEOUT: _fail("creature_did_not_flee_toward_goal")
	elif _phase == "settle_first":
		_place_behind(0)
		_goal_gain = _start_goal_distance - _creatures[0].global_position.distance_to(_goal.global_position)
		if _is_settled(0):
			_settle_ok = true; _mark(); _settled_position = _creatures[0].global_position; _begin("persistent")
		elif _frame - _phase_frame > TARGET_TIMEOUT: _fail("creature_did_not_settle")
	elif _phase == "persistent":
		_player.global_position = _settled_position + Vector2(10, 0)
		if not _is_settled(0): _fail("settled_flag_was_lost"); return
		if _frame - _phase_frame >= STILL_FRAMES:
			if _settled_position.distance_to(_creatures[0].global_position) > 0.5: _fail("settled_creature_moved"); return
			_persistent_ok = true; _mark(); _target_creature = 1; _begin("herd_all")
	elif _phase == "herd_all":
		while _target_creature < _creatures.size() and _is_settled(_target_creature):
			_target_creature += 1; _phase_frame = _frame
		if _target_creature < _creatures.size():
			_place_behind(_target_creature)
			if _frame - _phase_frame > TARGET_TIMEOUT: _fail("remaining_creature_did_not_settle")
		else:
			_player.global_position = _safe_spot; _begin("win")
	elif _phase == "win":
		if str(_root_value("state", "unknown")) == "won":
			_win_ok = true; _mark(); _pass()
		elif _frame - _phase_frame > TARGET_TIMEOUT: _fail("all_settled_did_not_win")

func _metrics():
	var settled_count := 0
	for value in _root_value("creature_settled", []):
		if bool(value): settled_count += 1
	print("[OBJECTIVE_METRICS] completion_seconds=%.3f progress_events=%d max_stall_frames=%d stuck=%s restart=not_applicable deaths=0" % [float(_frame) / 60.0, _milestones, _max_stall, str(_stuck)])
	print("[HERD_METRICS] still_drift=%.3f flee_distance=%.3f goal_gain=%.3f settled=%d creatures=%d still=%s flee=%s settle=%s persistent=%s win=%s" % [_still_drift, _flee_distance, _goal_gain, settled_count, _creatures.size(), str(_still_ok), str(_flee_ok), str(_settle_ok), str(_persistent_ok), str(_win_ok)])

func _pass():
	if not _active: return
	_active = false; _metrics()
	print("[OBJECTIVE] status=passed template=herd_to_goal reason=none collected=%d total=5 remaining=%d frames=%d" % [_milestones, maxi(0, 5 - _milestones), _frame]); get_tree().quit()

func _fail(reason: String):
	if not _active: return
	_active = false; _stuck = true; _metrics()
	print("[OBJECTIVE] status=failed template=herd_to_goal reason=%s collected=%d total=5 remaining=%d frames=%d" % [reason, _milestones, maxi(0, 5 - _milestones), _frame]); get_tree().quit()
"""

AMBIENCE_GD = """extends Node

func _ready():
    if DisplayServer.get_name() == "headless":
        return
    var particles = CPUParticles2D.new()
    particles.amount = 45
    particles.lifetime = 7.0
    particles.preprocess = 7.0
    particles.position = Vector2(512, -10)
    particles.emission_shape = CPUParticles2D.EMISSION_SHAPE_RECTANGLE
    particles.emission_rect_extents = Vector2(520, 8)
    particles.direction = Vector2(0, 1)
    particles.gravity = Vector2(0, 12)
    particles.initial_velocity_min = 12.0
    particles.initial_velocity_max = 32.0
    particles.scale_amount_min = 1.0
    particles.scale_amount_max = 2.2
    particles.color = Color(1, 1, 1, 0.4)
    particles.z_index = 10
    add_child(particles)
"""

# Harness-owned SFX autoload: loads the four synthesized cues written by
# saga.sfx and exposes Sfx.play(name). The LLM only ever calls play().
SFX_GD = """extends Node

var players = {}

func _ready():
    for sfx_name in ["pickup", "hit", "win", "lose"]:
        var player = AudioStreamPlayer.new()
        player.stream = load("res://assets/sfx_%s.wav" % sfx_name)
        add_child(player)
        players[sfx_name] = player

func play(sfx_name: String):
    if players.has(sfx_name):
        players[sfx_name].play()
"""


def _build_level_tscn(index: int) -> str:
    """Per-level scene boilerplate: a bare Node2D with the level's script.
    BGM moved to the Music autoload so it persists across level changes."""
    return f"""[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://Level_{index}.gd" id="1"]

[node name="Level{index}" type="Node2D"]
script = ExtResource("1")
"""


# Godot 3 -> 4 renames the models reach for most. Every one of these was
# observed live: a zero-shot platformer burned its entire retry budget on
# Camera2D alone, repairing one property per pass (current, then
# smoothing_enabled, then limit_smoothing_enabled) because each round only
# surfaced the next error. Listing them up front turned a 3-retry convergence
# into 1. Models trained largely on Godot 3 material reproduce the old names
# confidently, and QA can only report them one at a time.
GODOT4_API_NOTES = (
    "Godot 4 API notes - your training data may predate these renames, and "
    "getting them wrong is the single most common failure here. There is no "
    "class named `Sprite` - Godot 4 renamed it `Sprite2D` (or `Sprite3D` in "
    "3D); every sprite node, type hint, and `is` check must say Sprite2D. "
    "Camera2D uses "
    "`enabled` (not `current`) and `position_smoothing_enabled` / "
    "`position_smoothing_speed` (not `smoothing_enabled` / `smoothing_speed`); "
    "there is no `limit_smoothing_enabled`, and make_current() works only once "
    "the node is inside the tree. Build tweens with create_tween() - "
    "Tween.new() and interpolate_property() are gone; repeat with "
    "set_loops() rather than a `loop` property, and never start a tween "
    "without adding at least one tweener. `yield` is gone; use "
    "`await`. Signals connect and emit as `sig.connect(callable)` and "
    "`sig.emit(...)`. Renamed: instance() -> instantiate(), .empty() -> "
    ".is_empty(), rand_range -> randf_range, OS.get_ticks_msec() -> "
    "Time.get_ticks_msec(). Set label text size with "
    "label.add_theme_font_size_override(\"font_size\", n). A physics body must "
    "be inside the tree before move_and_slide() or any body_test_motion() "
    "call. Parse JSON with JSON.parse_string(text), which returns the value "
    "or null. Do not invent geometry helpers on built-in types - Rect2 has "
    "has_point/intersects/merge/expand/grow and no get_closest_point(); clamp "
    "a position with Vector2.clamp() or by clamping each axis. "
)

def _asset_manifest(filenames: list[str], design_doc: dict) -> str:
    """List the available images with what each one actually depicts.

    A bare filename list tells the model a file exists but not what is in it,
    so a purpose-built sprite goes unused and the object gets drawn as a plain
    ColorRect instead - which is what missing art looks like on screen. The
    role prefixes are the same ones SYSTEM_PROMPT_BASE describes.
    """
    extras = {s["name"]: s["description"] for s in (design_doc.get("extra_sprites") or [])}
    key_item = design_doc.get("key_item") or {}

    lines = []
    for name in filenames:
        if name.startswith("level_"):
            note = "this level's background, exactly 1024x576"
        elif name.startswith("key_item"):
            note = f"{key_item.get('description', 'the key item')} (role: {key_item.get('role', 'pickup')}), 128x128 with transparency"
        elif name.startswith("hero_walk"):
            note = (
                "the SAME hero in a walking pose - register it with "
                "Anim.set_poses(hero_sprite, <resting texture>, <this texture>) so the "
                "hero stands up to move and settles when still. Do not create a "
                "second sprite for it"
            )
        elif name.startswith("extra_"):
            # Stable files are extra_<slug>.png; the regex also accepts older
            # ComfyUI-numbered files collected before run isolation.
            slug = re.sub(r"_\d+_?$", "", name.rsplit(".", 1)[0][len("extra_"):])
            note = f"{extras.get(slug, slug.replace('_', ' '))}, 128x128 with transparency"
        else:
            note = f"{design_doc.get('hero_description', 'the player character')} - the player, 128x128 with transparency"
        lines.append(f"- {name}: {note}")
    return "\n".join(lines)


SYSTEM_PROMPT_BASE = (
    "You are the Coder agent in an automated game studio. You write GDScript "
    "(Godot 4) attached to a single Node2D root node. The game window is a "
    "fixed 1024x576 viewport - keep all world positions within that range. "
    "Image asset filenames tell you their role: a file starting with 'level_' "
    "is a level background, sized exactly 1024x576 - load it into a Sprite2D, "
    "set `centered = false` and `position = Vector2.ZERO` so it fills the "
    "screen edge-to-edge (Sprite2D is centered by default, which would only "
    "show a quarter of it). A file starting with 'key_item' is the key item "
    "icon, sized 128x128, usable at native size - its gameplay role is given "
    "in the design brief. Any other image asset is the hero/player sprite. "
    "All gameplay interactions are touch-based: the player is an Area2D with "
    "a CollisionShape2D child, and every interactive object (pickup, hazard, "
    "switch, creature, zone) is also an Area2D with a CollisionShape2D child, "
    "detected via the area_entered (and area_exited where needed) signals - "
    "never use physics bodies. Show the game state in a Label on a "
    "CanvasLayer, and implement the design brief's win condition and lose "
    "condition exactly. Your script controls ONE level of a multi-level "
    "game - the design brief names your level and its position, so scale "
    "difficulty numbers up for later levels. Structure play as four states "
    "in a `state` variable: 'title' (show the game title and 'Press Enter "
    "to start'; ui_accept starts), 'playing', 'won' (on winning the level: "
    "set state to 'won', play the win sound, set the label to a "
    "level-complete message, and call Game.level_complete() exactly once - "
    "the harness's Game autoload advances to the next level or the victory "
    "screen), and 'over' (on losing: show the result and 'Press Enter to "
    "restart'; ui_accept calls get_tree().reload_current_scene() to retry "
    "the level). At the end of _ready, if DisplayServer.get_name() == "
    "\"headless\" or Game.level > 0, set state straight to 'playing' - QA "
    "runs headlessly and the title card belongs on the first level only. "
    "ui_accept may ONLY start or restart the game - never use it inside "
    "gameplay, and never require any discrete button press to win; the core "
    "loop must be playable with HELD movement keys alone. No custom InputMap "
    "actions are defined, so only use Godot's built-in default input actions "
    "(ui_up, ui_down, ui_left, ui_right for movement, ui_accept only for "
    "start/restart) - never invent a new action name. An Sfx autoload "
    "exists: call Sfx.play(\"pickup\"), Sfx.play(\"hit\"), Sfx.play(\"win\"), "
    "or Sfx.play(\"lose\") at the matching gameplay moments - do not load or "
    "play any other audio; background music is handled separately. Ambient "
    "particles are also handled separately by the harness - never create "
    "CPUParticles2D yourself. The scene starts bare, so create every "
    "node in code and never use $NodeName or get_node() for nodes you did "
    "not create. Load image assets with load(\"res://assets/<filename>\") "
    "using ONLY filenames from the 'Available image assets' list, copied "
    "verbatim - never invent a filename; a load() of a file that does not "
    "exist crashes QA. The asset list says what each image depicts: use the "
    "one that matches the object you are creating - a sprite named for a wall, "
    "an enemy or a platform exists precisely so that object is drawn with it. "
    "Never draw a game object as a plain ColorRect or an untextured rectangle "
    "while a matching sprite is listed. Only when nothing in the list fits "
    "should you fall back to reusing the key_item sprite tinted via modulate "
    "and scaled, as the example does. "
    "Generated level scripts run on the host, so never use FileAccess, "
    "DirAccess, ResourceSaver, OS process/shell/environment methods, networking "
    "classes, native extensions, user://, file://, or web URLs. Resource loads "
    "are limited to the exact res://assets/* paths listed in the brief. "
    "Put every gameplay-tuning number - speeds, "
    "rates, durations, counts, radii - in a named variable at the top of "
    "the script so a human playtester can retune it later. An Anim autoload "
    "provides the character animation, and you must use it. When a hero_walk "
    "asset is listed, call Anim.set_poses(hero_sprite, <hero resting texture>, "
    "<hero_walk texture>) once in _ready - both are images of the same "
    "character, and Anim swaps between them so the hero visibly stands up to "
    "move and settles again when it stops. Never build a second sprite node "
    "for the walking pose. "
    "Keep a reference to each character's Sprite2D child (the sprite, never "
    "the Area2D that owns its position - Anim writes local offsets that would "
    "otherwise fight collision). Every frame, call Anim.walk(sprite, "
    "is_moving, direction.x) for the player and for anything that walks, "
    "passing whether it moved this frame and its horizontal direction so it "
    "bobs, leans and faces the right way; call Anim.hover(sprite) instead for "
    "anything that floats, drifts or swims. On events, call Anim.pop(sprite) "
    "when something is collected, rescued or spawned, Anim.squash(sprite) on "
    "an impact or landing, and Anim.flash(sprite) when the player takes "
    "damage. Do not write your own scale, rotation or modulate tweens for "
    "these - Anim owns them. "
    + GODOT4_API_NOTES +
    "Respond with ONLY a single ```gdscript fenced code block, no explanation "
    "before or after it."
)

TEMPLATE_REQUIREMENTS = {
    "collect": (
        "Structure for this game: place several pickup Area2Ds at hardcoded "
        "positions; on player touch, queue_free the pickup, play the pickup "
        "sound, and increment a score shown in the label; win when every "
        "pickup is collected."
    ),
    "ordered_switches": (
        "Structure for this game: place several switch Area2Ds at hardcoded "
        "positions and expose them in `var switches: Array[Area2D]`; expose "
        "their required zero-based indices in `var switch_order: Array[int]`, "
        "the current step in `var progress: int`, and increment public "
        "`var reset_count: int` every time a wrong switch resets the puzzle. "
        "Touching them in the correct order advances progress "
        "(tint activated switches via modulate and play the pickup sound), "
        "touching one out of order resets progress and the tints (play the "
        "hit sound); show progress in the label; win when the full sequence "
        "is completed."
    ),
    "survive_hazards": (
        "Structure for this game: place several hazard Area2Ds that move "
        "and expose them in `var hazards: Array[Area2D]`; expose public "
        "`starting_lives`, `lives`, `survival_time`, `time_left`, and "
        "`hit_cooldown` variables for deterministic gameplay QA. "
        "every frame along deterministic paths (straight lines that bounce "
        "off the viewport edges by flipping the direction component); the "
        "player starts with a few lives and loses one on each hazard touch; "
        "a survival timer counts down in _process; show time and lives in "
        "the label; win when the timer reaches zero, lose when lives reach "
        "zero."
    ),
    "depletion": (
        "Structure for this game: expose `resource_max`, `resource`, "
        "`drain_rate`, `refill_rate`, `survival_time`, `time_left`, and "
        "`zones_inside` variables plus `var refill_zones: Array[Area2D]` for "
        "deterministic gameplay QA. The resource drains every frame in "
        "_process; standing inside refill zone Area2Ds restores it instead "
        "(track overlap by connecting area_entered and area_exited on the "
        "player and counting zones inside); clamp the resource to 0-100; a "
        "timer counts down; show resource and time in the label; win when "
        "the timer reaches zero with the resource above zero, lose the "
        "moment the resource hits zero."
    ),
    "herd_to_goal": (
        "Structure for this game: expose public `player`, `creatures`, "
        "`creature_settled`, `goal`, `panic_radius`, `goal_radius`, `speed`, "
        "`flee_speed`, and `state` adapters for deterministic gameplay QA. "
        "Use several creature Area2Ds and one goal Area2D at a fixed position. "
        "Herding only works if the creatures hold "
        "still while you line up a push, so a creature flees ONLY when the "
        "player is within a named panic_radius variable - beyond that radius "
        "it does not move at all. Inside the radius it moves along the vector "
        "pointing away from the player, scaled by speed and delta, clamped "
        "inside the viewport; flee speed must stay well below the player's "
        "speed or it can never be caught up with. A creature whose position "
        "is inside goal_radius SETTLES permanently: set creature_settled[index], "
        "stop it fleeing for the rest of the level no matter how close the "
        "player comes, and play the pickup sound once. Track the settled "
        "count in the label and win when every creature has settled - never "
        "require them to be inside the zone simultaneously, because a "
        "creature that can still flee will simply wander back out."
    ),
    "capture_zones": (
        "Structure for this game: expose public `player`, `zones`, `patroller`, "
        "`zone_progress`, `zone_owner`, `player_in_zones`, `enemy_in_zones`, "
        "`capture_required`, `capture_radius`, `capture_rate`, `decay_rate`, and `patroller_speed` "
        "adapters for deterministic gameplay QA. Place at least two zone-marker "
        "Area2Ds. Update both overlap arrays every frame from the real Area2D "
        "positions and capture_radius. While only the player overlaps a zone, increase its progress; "
        "when progress reaches capture_required, set zone_owner[index] to 1. "
        "While the patroller overlaps, or both actors contest the zone, decrease "
        "progress; when it reaches zero, reset ownership to 0. Tint every zone "
        "from its actual owner/progress, show the owned count in the label, and "
        "win only when every zone_owner entry is 1 at the same time."
    ),
    "survive_and_deplete": (
        "Structure for this game: combine depletion with roaming hazards. "
        "Expose public `resource_max`, `resource`, `drain_rate`, `drain_ramp`, "
        "`refill_rate`, `fuel_burn`, `hazard_hit_cost`, `hit_cooldown`, "
        "`time_left`, `zones`, `zone_fuel`, `inside_zones`, and `hazards` "
        "adapters for deterministic gameplay QA. A "
        "resource drains every frame, and the drain accelerates as time "
        "passes (a ramp variable). Refill zone Area2Ds restore the resource, "
        "but each zone has finite fuel that burns while it is used - when a "
        "zone's fuel runs out, dim its sprite via modulate and stop it "
        "refilling. Roaming hazard Area2Ds bounce off the viewport edges "
        "every frame; build them from the key_item sprite tinted via "
        "modulate and scaled down so they read as a different object. "
        "Touching a hazard costs a chunk of the resource, plays the hit "
        "sound, and starts a brief hit-cooldown during which the player "
        "flashes red and cannot be hit again. Win when the timer reaches "
        "zero, lose the moment the resource hits zero. Show resource, time, "
        "and remaining active zones in the label."
    ),
    "maze_chase": (
        "Structure for this game: walled corridors. Define the walls as an "
        "array of Rect2 values (including border walls around the viewport) "
        "and draw each as a ColorRect matching its rect. Move the player "
        "with axis-separated collision: try the x move and the y move "
        "separately, and only apply each if the player's rect does not "
        "intersect any wall rect. Place pickup Area2Ds in the corridors "
        "(play the pickup sound and count them on touch); one patroller "
        "hazard Area2D moves between fixed waypoints every frame (build it "
        "from the key_item sprite tinted via modulate); touching the "
        "patroller costs a life, plays the hit sound, and starts a brief "
        "hit-cooldown with a red flash. Win when every pickup is collected, "
        "lose when lives reach zero."
    ),
    "dot_maze": (
        "Structure for this game: a dense corridor maze in the classic "
        "chase-and-chomp style. Walls are an array of Rect2 values (border "
        "walls plus rows of inner blocks leaving open corridors), each drawn "
        "as a ColorRect; the player moves with axis-separated collision "
        "against them. Spawn many small dots along the corridors with nested "
        "for-loops over position arrays (key_item sprite scaled small), plus "
        "a few large power pickups at the corners (key_item scaled bigger, "
        "tinted gold). Three ghost Area2Ds built from the key_item sprite "
        "tinted distinct colors: two patrol fixed waypoint rectangles via "
        "move_toward, one hunts by moving directly toward the player every "
        "frame. Eating a power pickup starts a power timer: all ghosts tint "
        "blue, flee away from the player at reduced speed, and touching one "
        "eats it - play the pickup sound and teleport it back to its home "
        "position, no longer frightened. When the timer expires ghosts "
        "return to normal. Touching a normal ghost costs a life, plays the "
        "hit sound, respawns the player at their start position, and starts "
        "a brief hit-cooldown. Win when every dot and power pickup is "
        "eaten; lose when lives reach zero. Show dots remaining, lives, and "
        "a POWER indicator while the timer runs. Reproduce EVERY system the "
        "worked example demonstrates - the walls, both ghost movement "
        "styles, the power mode, and the ghost-touch handler; never stub a "
        "function with pass or drop a system 'for simplicity'. A missing "
        "system is a failed level even if the script runs."
    ),
}

# --- Few-shot worked examples ------------------------------------------------
# Seven authored examples; every template maps to the structurally nearest one.
# Each demonstrates the invariants: nodes created in code (bare scene), held
# built-in input actions only, Area2D-to-Area2D detection, background filling
# the viewport, a status Label on a CanvasLayer, named tuning variables, the
# title/playing/over state machine with headless auto-start, Sfx calls, and
# explicit win/lose states that freeze play without freeing live nodes.
# (Ambient particles are deliberately NOT here - they are harness-owned via
# the Ambience autoload, since the 14B model invents CPUParticles2D API
# when asked to write particle config itself.)

COLLECT_EXAMPLE_USER = (
    "Title: Coin Rush\n"
    "Genre: arcade collector\n"
    "Mechanic template: collect\n"
    "Core mechanics: run around, collect coins\n"
    "Story premise: A courier sprints across rooftops collecting scattered coins.\n"
    "Win condition: collect all the coins\n"
    "Lose condition: none\n"
    "Key item: a gleaming gold coin (role: pickup)\n"
    "This is level 1 of 1: Rooftop Dash: a sunlit row of rooftops with scattered coins\n"
    "Available image assets: hero_sprite.png, hero_walk.png, key_item.png, level_0_bg.png\n"
)

COLLECT_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 220.0
var score = 0
var total_coins = 0
var state = "title"
var player: Area2D
var status_label: Label

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    player = Area2D.new()
    player.position = Vector2(100, 300)
    var player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    add_child(player)

    var coin_positions = [Vector2(300, 300), Vector2(520, 180), Vector2(760, 400)]
    total_coins = coin_positions.size()
    for pos in coin_positions:
        _spawn_coin(pos)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_coin(pos: Vector2):
    var coin = Area2D.new()
    coin.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    coin.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 16.0
    shape.shape = circle
    coin.add_child(shape)
    coin.area_entered.connect(_on_coin_area_entered.bind(coin))
    add_child(coin)

func _on_coin_area_entered(area: Area2D, coin: Area2D):
    if state != "playing" or area != player:
        return
    coin.queue_free()
    score += 1
    Sfx.play("pickup")
    status_label.text = "Coins: %d / %d" % [score, total_coins]
    if score >= total_coins:
        state = "won"
        Sfx.play("win")
        status_label.text = "All coins collected - level complete!"
        Game.level_complete()

func _process(delta):
    if state == "title":
        status_label.text = "COIN RUSH - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
            status_label.text = "Coins: 0 / %d" % total_coins
        return
    if state == "won":
        return
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    player.position += velocity.normalized() * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))
```"""

ORDERED_SWITCHES_EXAMPLE_USER = (
    "Title: Signal Path\n"
    "Genre: sequence puzzle\n"
    "Mechanic template: ordered_switches\n"
    "Core mechanics: move around, activate beacons in order\n"
    "Story premise: A scout restores a silent relay network.\n"
    "Win condition: activate every beacon in the shown order\n"
    "Lose condition: none\n"
    "Key item: a glowing numbered relay beacon (role: switch)\n"
    "This is level 1 of 1: Relay Court: four beacons surround an old transmitter\n"
    "Available image assets: hero_sprite.png, hero_walk.png, key_item.png, level_0_bg.png\n"
)

ORDERED_SWITCHES_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 220.0
var state = "title"
var player: Area2D
var player_sprite: Sprite2D
var switches: Array[Area2D] = []
var switch_order: Array[int] = [2, 0, 3, 1]
var progress: int = 0
var reset_count: int = 0
var status_label: Label

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    player = Area2D.new()
    player.position = Vector2(512, 288)
    player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    add_child(player)
    Anim.set_poses(
        player_sprite,
        load("res://assets/hero_sprite.png"),
        load("res://assets/hero_walk.png"),
    )

    var positions = [
        Vector2(180, 150), Vector2(844, 150),
        Vector2(180, 430), Vector2(844, 430),
    ]
    for index in positions.size():
        _spawn_switch(positions[index], index)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"
        _update_label()

func _spawn_switch(pos: Vector2, index: int):
    var switch = Area2D.new()
    switch.name = "Switch%d" % index
    switch.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    switch.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 22.0
    shape.shape = circle
    switch.add_child(shape)
    switch.area_entered.connect(_on_switch_area_entered.bind(index))
    add_child(switch)
    switches.append(switch)

func _on_switch_area_entered(area: Area2D, index: int):
    if state != "playing" or area != player:
        return
    if index == switch_order[progress]:
        switches[index].modulate = Color(0.35, 1.0, 0.45)
        progress += 1
        Sfx.play("pickup")
        if progress >= switch_order.size():
            state = "won"
            status_label.text = "Relay restored - level complete!"
            Sfx.play("win")
            Game.level_complete()
            return
    else:
        progress = 0
        reset_count += 1
        for switch in switches:
            switch.modulate = Color.WHITE
        Sfx.play("hit")
    _update_label()

func _update_label():
    status_label.text = "Sequence: %d / %d" % [progress, switch_order.size()]

func _process(delta):
    if state == "title":
        status_label.text = "SIGNAL PATH - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
            _update_label()
        return
    if state == "won":
        return
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var direction = velocity.normalized()
    player.position += direction * speed * delta
    player.position = player.position.clamp(Vector2(30, 30), Vector2(994, 546))
    Anim.walk(player_sprite, direction.length() > 0.0, direction.x)
```"""

SURVIVE_EXAMPLE_USER = (
    "Title: Meteor Vigil\n"
    "Genre: arcade survival\n"
    "Mechanic template: survive_hazards\n"
    "Core mechanics: dodge falling meteors, survive until dawn\n"
    "Story premise: A lone stargazer weaves between falling meteors until sunrise.\n"
    "Win condition: survive for 30 seconds\n"
    "Lose condition: lose all 3 lives\n"
    "Key item: a blazing meteor fragment (role: hazard)\n"
    "This is level 1 of 1: Night Ridge: a dark ridgeline under a meteor shower\n"
    "Available image assets: hero_sprite.png, hero_walk.png, key_item.png, level_0_bg.png\n"
)

SURVIVE_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 240.0
var hazard_speed = 180.0
var starting_lives = 3
var survival_time = 30.0
var lives = starting_lives
var time_left = survival_time
var hit_cooldown = 0.0
var state = "title"
var player: Area2D
var player_sprite: Sprite2D
var status_label: Label
var hazards: Array[Area2D] = []
var hazard_dirs = []

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    player = Area2D.new()
    player.position = Vector2(512, 288)
    player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_hit)
    add_child(player)
    Anim.set_poses(
        player_sprite,
        load("res://assets/hero_sprite.png"),
        load("res://assets/hero_walk.png"),
    )

    var starts = [Vector2(150, 100), Vector2(850, 200), Vector2(500, 480)]
    var dirs = [Vector2(1, 0.5), Vector2(-1, 0.3), Vector2(0.7, -1)]
    for i in starts.size():
        _spawn_hazard(starts[i], dirs[i])

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_hazard(pos: Vector2, dir: Vector2):
    var hazard = Area2D.new()
    hazard.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    hazard.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 16.0
    shape.shape = circle
    hazard.add_child(shape)
    add_child(hazard)
    hazards.append(hazard)
    hazard_dirs.append(dir.normalized())

func _on_player_hit(area: Area2D):
    if state != "playing" or hit_cooldown > 0.0:
        return
    lives -= 1
    hit_cooldown = 0.35
    Sfx.play("hit")
    if lives <= 0:
        state = "over"
        Sfx.play("lose")
        status_label.text = "The vigil is lost...  Press Enter to restart"

func _process(delta):
    if state == "title":
        status_label.text = "METEOR VIGIL - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
        return
    if state == "won":
        return
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    hit_cooldown = maxf(0.0, hit_cooldown - delta)

    time_left -= delta
    if time_left <= 0.0:
        state = "won"
        Sfx.play("win")
        status_label.text = "Dawn breaks - level complete!"
        Game.level_complete()
        return

    for i in hazards.size():
        var hazard = hazards[i]
        hazard.position += hazard_dirs[i] * hazard_speed * delta
        var dir = hazard_dirs[i]
        if hazard.position.x < 0.0 or hazard.position.x > 1024.0:
            dir.x = -dir.x
        if hazard.position.y < 0.0 or hazard.position.y > 576.0:
            dir.y = -dir.y
        hazard_dirs[i] = dir

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var direction = velocity.normalized()
    player.position += direction * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))
    Anim.walk(player_sprite, direction.length() > 0.0, direction.x)

    status_label.text = "Survive: %ds   Lives: %d" % [int(ceil(time_left)), lives]
```"""

DEPLETION_EXAMPLE_USER = (
    "Title: Last Lantern\n"
    "Genre: survival puzzle\n"
    "Mechanic template: depletion\n"
    "Core mechanics: keep the lantern lit, move between braziers\n"
    "Story premise: A night watchman keeps his failing lantern alive by borrowing flame from braziers.\n"
    "Win condition: keep the lantern lit for 30 seconds\n"
    "Lose condition: the lantern's light reaches zero\n"
    "Key item: a crackling stone brazier (role: zone_marker)\n"
    "This is level 1 of 1: The Long Walk: a fog-bound rampart dotted with braziers\n"
    "Available image assets: hero_sprite.png, hero_walk.png, key_item.png, level_0_bg.png\n"
)

DEPLETION_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 240.0
var drain_rate = 8.0
var refill_rate = 15.0
var survival_time = 30.0
var resource_max = 100.0
var resource = resource_max
var time_left = survival_time
var zones_inside = 0
var state = "title"
var player: Area2D
var player_sprite: Sprite2D
var refill_zones: Array[Area2D] = []
var status_label: Label

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    player = Area2D.new()
    player.position = Vector2(100, 300)
    player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_area_entered)
    player.area_exited.connect(_on_player_area_exited)
    add_child(player)
    Anim.set_poses(
        player_sprite,
        load("res://assets/hero_sprite.png"),
        load("res://assets/hero_walk.png"),
    )

    var zone_positions = [Vector2(220, 300), Vector2(512, 150), Vector2(820, 420)]
    for pos in zone_positions:
        _spawn_zone(pos)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_zone(pos: Vector2):
    var zone = Area2D.new()
    zone.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    zone.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 70.0
    shape.shape = circle
    zone.add_child(shape)
    add_child(zone)
    refill_zones.append(zone)

func _on_player_area_entered(area: Area2D):
    zones_inside += 1

func _on_player_area_exited(area: Area2D):
    zones_inside -= 1

func _process(delta):
    if state == "title":
        status_label.text = "LAST LANTERN - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
        return
    if state == "won":
        return
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    if zones_inside > 0:
        resource += refill_rate * delta
    else:
        resource -= drain_rate * delta
    resource = clamp(resource, 0.0, resource_max)
    time_left -= delta

    if resource <= 0.0:
        state = "over"
        Sfx.play("lose")
        status_label.text = "The lantern gutters out...  Press Enter to restart"
        return
    if time_left <= 0.0:
        state = "won"
        Sfx.play("win")
        status_label.text = "Dawn comes - level complete!"
        Game.level_complete()
        return

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var direction = velocity.normalized()
    player.position += direction * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))
    Anim.walk(player_sprite, direction.length() > 0.0, direction.x)

    status_label.text = "Light: %d%%   Time: %ds" % [int(resource), int(ceil(time_left))]
```"""

HERD_EXAMPLE_USER = (
    "Title: Mooncalf Crossing\n"
    "Genre: herding puzzle\n"
    "Mechanic template: herd_to_goal\n"
    "Core mechanics: approach skittish creatures from behind and guide them into a sanctuary\n"
    "Story premise: A keeper must guide three mooncalves home before dawn.\n"
    "Win condition: settle every creature in the sanctuary\n"
    "Lose condition: none\n"
    "Key item: a glowing mooncalf (role: creature)\n"
    "This is level 1 of 1: Quiet Pasture: an open field with a sanctuary at the east edge\n"
    "Available image assets: hero_sprite.png, hero_walk.png, key_item.png, level_0_bg.png\n"
)

HERD_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 240.0
var flee_speed = 90.0
var panic_radius = 115.0
var goal_radius = 72.0
var state = "title"
var player: Area2D
var player_sprite: Sprite2D
var creatures: Array[Area2D] = []
var creature_sprites: Array[Sprite2D] = []
var creature_settled: Array[bool] = []
var goal: Area2D
var status_label: Label

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    player = Area2D.new()
    player.position = Vector2(100, 300)
    player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    add_child(player)
    Anim.set_poses(player_sprite, load("res://assets/hero_sprite.png"), load("res://assets/hero_walk.png"))

    goal = Area2D.new()
    goal.position = Vector2(850, 300)
    var goal_sprite = Sprite2D.new()
    goal_sprite.texture = load("res://assets/key_item.png")
    goal_sprite.modulate = Color(0.35, 1.0, 0.5, 0.65)
    goal_sprite.scale = Vector2(1.35, 1.35)
    goal.add_child(goal_sprite)
    var goal_shape = CollisionShape2D.new()
    var goal_circle = CircleShape2D.new()
    goal_circle.radius = goal_radius
    goal_shape.shape = goal_circle
    goal.add_child(goal_shape)
    add_child(goal)

    for pos in [Vector2(280, 170), Vector2(380, 330), Vector2(250, 470)]:
        _spawn_creature(pos)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_creature(pos: Vector2):
    var creature = Area2D.new()
    creature.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    sprite.scale = Vector2(0.65, 0.65)
    creature.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 22.0
    shape.shape = circle
    creature.add_child(shape)
    add_child(creature)
    creatures.append(creature)
    creature_sprites.append(sprite)
    creature_settled.append(false)

func _process(delta):
    if state == "title":
        status_label.text = "MOONCALF CROSSING - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
        return
    if state == "won":
        return

    for i in creatures.size():
        var creature = creatures[i]
        if creature_settled[i]:
            Anim.hover(creature_sprites[i])
            continue
        if creature.global_position.distance_to(goal.global_position) <= goal_radius:
            creature_settled[i] = true
            creature_sprites[i].modulate = Color(0.55, 1.0, 0.65)
            Sfx.play("pickup")
            continue
        if creature.global_position.distance_to(player.global_position) < panic_radius:
            var flee_direction = (creature.global_position - player.global_position).normalized()
            creature.position += flee_direction * flee_speed * delta
            creature.position = creature.position.clamp(Vector2(24, 24), Vector2(1000, 552))
            Anim.walk(creature_sprites[i], true, flee_direction.x)
        else:
            Anim.walk(creature_sprites[i], false, 0.0)

    var settled_count = creature_settled.count(true)
    if settled_count == creatures.size():
        state = "won"
        Sfx.play("win")
        status_label.text = "The herd is safe - level complete!"
        Game.level_complete()
        return

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var direction = velocity.normalized()
    player.position += direction * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))
    Anim.walk(player_sprite, direction.length() > 0.0, direction.x)
    status_label.text = "Mooncalves safe: %d/%d" % [settled_count, creatures.size()]
```"""

CAPTURE_EXAMPLE_USER = (
    "Title: Signal Dominion\n"
    "Genre: territory arcade\n"
    "Mechanic template: capture_zones\n"
    "Core mechanics: hold signal zones while a patrol drone erases control\n"
    "Story premise: A courier must retune every relay before the security drone undoes the work.\n"
    "Win condition: own every relay at the same time\n"
    "Lose condition: none\n"
    "Key item: a luminous signal relay (role: zone_marker)\n"
    "This is level 1 of 1: Relay Floor: a broad control room with three exposed relays\n"
    "Available image assets: hero_sprite.png, hero_walk.png, key_item.png, level_0_bg.png\n"
)

CAPTURE_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 240.0
var capture_required = 1.0
var capture_radius = 70.0
var capture_rate = 1.2
var decay_rate = 0.8
var patroller_speed = 115.0
var state = "title"
var player: Area2D
var player_sprite: Sprite2D
var zones: Array[Area2D] = []
var zone_sprites: Array[Sprite2D] = []
var zone_progress: Array[float] = []
var zone_owner: Array[int] = []
var player_in_zones: Array[bool] = []
var enemy_in_zones: Array[bool] = []
var patroller: Area2D
var patroller_sprite: Sprite2D
var waypoints = [Vector2(120, 100), Vector2(900, 100), Vector2(900, 500), Vector2(120, 500)]
var waypoint_index = 1
var status_label: Label

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    player = Area2D.new()
    player.position = Vector2(512, 300)
    player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_entered)
    player.area_exited.connect(_on_player_exited)
    add_child(player)
    Anim.set_poses(player_sprite, load("res://assets/hero_sprite.png"), load("res://assets/hero_walk.png"))

    for pos in [Vector2(210, 180), Vector2(512, 420), Vector2(820, 190)]:
        _spawn_zone(pos)

    patroller = Area2D.new()
    patroller.position = waypoints[0]
    patroller_sprite = Sprite2D.new()
    patroller_sprite.texture = load("res://assets/key_item.png")
    patroller_sprite.modulate = Color(1.0, 0.3, 0.3)
    patroller_sprite.scale = Vector2(0.55, 0.55)
    patroller.add_child(patroller_sprite)
    var patrol_shape = CollisionShape2D.new()
    var patrol_circle = CircleShape2D.new()
    patrol_circle.radius = 24.0
    patrol_shape.shape = patrol_circle
    patroller.add_child(patrol_shape)
    patroller.area_entered.connect(_on_patroller_entered)
    patroller.area_exited.connect(_on_patroller_exited)
    add_child(patroller)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_zone(pos: Vector2):
    var zone = Area2D.new()
    zone.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    sprite.modulate = Color(0.45, 0.5, 0.65)
    zone.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 55.0
    shape.shape = circle
    zone.add_child(shape)
    add_child(zone)
    zones.append(zone)
    zone_sprites.append(sprite)
    zone_progress.append(0.0)
    zone_owner.append(0)
    player_in_zones.append(false)
    enemy_in_zones.append(false)

func _zone_index(area: Area2D) -> int:
    return zones.find(area)

func _on_player_entered(area: Area2D):
    var index = _zone_index(area)
    if index >= 0:
        player_in_zones[index] = true

func _on_player_exited(area: Area2D):
    var index = _zone_index(area)
    if index >= 0:
        player_in_zones[index] = false

func _on_patroller_entered(area: Area2D):
    var index = _zone_index(area)
    if index >= 0:
        enemy_in_zones[index] = true

func _on_patroller_exited(area: Area2D):
    var index = _zone_index(area)
    if index >= 0:
        enemy_in_zones[index] = false

func _update_zone(index: int, delta: float):
    if player_in_zones[index] and not enemy_in_zones[index]:
        zone_progress[index] += capture_rate * delta
    elif enemy_in_zones[index]:
        zone_progress[index] -= decay_rate * delta
    zone_progress[index] = clamp(zone_progress[index], 0.0, capture_required)
    if zone_progress[index] >= capture_required:
        if zone_owner[index] != 1:
            Sfx.play("pickup")
        zone_owner[index] = 1
    elif zone_progress[index] <= 0.0:
        zone_owner[index] = 0
    var ratio = zone_progress[index] / capture_required
    zone_sprites[index].modulate = Color(0.35 + ratio * 0.25, 0.5 + ratio * 0.5, 0.65 - ratio * 0.35)

func _process(delta):
    if state == "title":
        status_label.text = "SIGNAL DOMINION - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
        return
    if state == "won":
        return

    var target: Vector2 = waypoints[waypoint_index]
    patroller.position = patroller.position.move_toward(target, patroller_speed * delta)
    if patroller.position.distance_to(target) < 5.0:
        waypoint_index = (waypoint_index + 1) % waypoints.size()
    Anim.hover(patroller_sprite)

    for i in zones.size():
        player_in_zones[i] = player.global_position.distance_to(zones[i].global_position) <= capture_radius
        enemy_in_zones[i] = patroller.global_position.distance_to(zones[i].global_position) <= capture_radius
        _update_zone(i, delta)

    var owned = zone_owner.count(1)
    if owned == zones.size():
        state = "won"
        Sfx.play("win")
        status_label.text = "All relays synchronized - level complete!"
        Game.level_complete()
        return

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var direction = velocity.normalized()
    player.position += direction * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))
    Anim.walk(player_sprite, direction.length() > 0.0, direction.x)
    status_label.text = "Relays: %d/%d" % [owned, zones.size()]
```"""

HYBRID_EXAMPLE_USER = (
    "Title: Reactor Dive\n"
    "Genre: tense survival\n"
    "Mechanic template: survive_and_deplete\n"
    "Core mechanics: power drains faster over time, charging pads have finite charge, dodge security drones\n"
    "Story premise: A maintenance robot must keep its power alive in a failing reactor until rescue arrives.\n"
    "Win condition: survive for 60 seconds\n"
    "Lose condition: power reaches zero\n"
    "Key item: a glowing charging pad (role: zone_marker)\n"
    "This is level 1 of 1: The Core Floor: a dim reactor hall lit by scattered charging pads\n"
    "Available image assets: hero_sprite.png, hero_walk.png, key_item.png, level_0_bg.png\n"
)

HYBRID_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 240.0
var drain_rate = 5.0
var drain_ramp = 0.08
var refill_rate = 18.0
var fuel_burn = 12.0
var zone_fuel_max = 40.0
var hazard_speed = 140.0
var hazard_hit_cost = 15.0
var hit_cooldown_time = 1.2
var survival_time = 60.0
var resource_max = 100.0

var resource = resource_max
var time_left = survival_time
var elapsed = 0.0
var hit_cooldown = 0.0
var state = "title"
var player: Area2D
var player_sprite: Sprite2D
var status_label: Label
var zones: Array[Area2D] = []
var zone_fuel = []
var zone_sprites = []
var inside_zones = []
var hazards: Array[Area2D] = []
var hazard_dirs = []

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    player = Area2D.new()
    player.position = Vector2(512, 300)
    player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 18.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_touched)
    add_child(player)
    Anim.set_poses(player_sprite, load("res://assets/hero_sprite.png"), load("res://assets/hero_walk.png"))

    var zone_positions = [Vector2(160, 420), Vector2(512, 470), Vector2(870, 400)]
    for i in zone_positions.size():
        _spawn_zone(i, zone_positions[i])

    var hazard_starts = [Vector2(200, 150), Vector2(800, 250)]
    var hazard_headings = [Vector2(1, 0.6), Vector2(-1, 0.4)]
    for i in hazard_starts.size():
        _spawn_hazard(hazard_starts[i], hazard_headings[i])

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_zone(index: int, pos: Vector2):
    var zone = Area2D.new()
    zone.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    zone.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 65.0
    shape.shape = circle
    zone.add_child(shape)
    zone.area_entered.connect(_on_zone_entered.bind(index))
    zone.area_exited.connect(_on_zone_exited.bind(index))
    add_child(zone)
    zones.append(zone)
    zone_fuel.append(zone_fuel_max)
    zone_sprites.append(sprite)
    inside_zones.append(false)

func _spawn_hazard(pos: Vector2, heading: Vector2):
    var hazard = Area2D.new()
    hazard.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    sprite.modulate = Color(0.5, 0.7, 1.4)
    sprite.scale = Vector2(0.7, 0.7)
    hazard.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 14.0
    shape.shape = circle
    hazard.add_child(shape)
    add_child(hazard)
    hazards.append(hazard)
    hazard_dirs.append(heading.normalized())

func _on_zone_entered(area: Area2D, index: int):
    if area == player:
        inside_zones[index] = true
        if zone_fuel[index] > 0.0:
            Sfx.play("pickup")

func _on_zone_exited(area: Area2D, index: int):
    if area == player:
        inside_zones[index] = false

func _on_player_touched(area: Area2D):
    if state != "playing" or hit_cooldown > 0.0:
        return
    if area in hazards:
        resource -= hazard_hit_cost
        hit_cooldown = hit_cooldown_time
        player.modulate = Color(1.0, 0.45, 0.45)
        Sfx.play("hit")

func _process(delta):
    if state == "title":
        status_label.text = "REACTOR DIVE - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
        return
    if state == "won":
        return
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    elapsed += delta
    time_left -= delta

    if hit_cooldown > 0.0:
        hit_cooldown -= delta
        if hit_cooldown <= 0.0:
            player.modulate = Color(1, 1, 1)

    var refilling = false
    for i in zones.size():
        if inside_zones[i] and zone_fuel[i] > 0.0:
            refilling = true
            zone_fuel[i] -= fuel_burn * delta
            if zone_fuel[i] <= 0.0:
                zone_fuel[i] = 0.0
                zone_sprites[i].modulate = Color(0.35, 0.35, 0.45)

    if refilling:
        resource += refill_rate * delta
    else:
        resource -= (drain_rate + elapsed * drain_ramp) * delta
    resource = clamp(resource, 0.0, resource_max)

    if resource <= 0.0:
        state = "over"
        Sfx.play("lose")
        status_label.text = "Systems dark. The reactor wins...  Press Enter to restart"
        return
    if time_left <= 0.0:
        state = "won"
        Sfx.play("win")
        status_label.text = "Rescue arrives - level complete!"
        Game.level_complete()
        return

    for i in hazards.size():
        var hazard = hazards[i]
        hazard.position += hazard_dirs[i] * hazard_speed * delta
        var dir = hazard_dirs[i]
        if hazard.position.x < 0.0 or hazard.position.x > 1024.0:
            dir.x = -dir.x
        if hazard.position.y < 0.0 or hazard.position.y > 576.0:
            dir.y = -dir.y
        hazard_dirs[i] = dir

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var direction = velocity.normalized()
    player.position += direction * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))
    Anim.walk(player_sprite, direction.length() > 0.0, direction.x)

    var pads_left = 0
    for f in zone_fuel:
        if f > 0.0:
            pads_left += 1
    status_label.text = "Power: %d%%   Time: %ds   Pads: %d" % [int(resource), int(ceil(time_left)), pads_left]
```"""

MAZE_EXAMPLE_USER = (
    "Title: Vault Runner\n"
    "Genre: maze arcade\n"
    "Mechanic template: maze_chase\n"
    "Core mechanics: navigate the vault corridors, grab every gem, dodge the patrolling guard light\n"
    "Story premise: A cat burglar slips through a bank vault's corridors lifting gems while the guard light sweeps its rounds.\n"
    "Win condition: collect all 4 gems\n"
    "Lose condition: lose all 3 lives\n"
    "Key item: a sparkling cut gem (role: pickup)\n"
    "This is level 1 of 1: The Vault: dim steel corridors lined with deposit boxes\n"
    "Available image assets: hero_sprite.png, key_item.png, level_0_bg.png\n"
)

MAZE_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 220.0
var patroller_speed = 120.0
var starting_lives = 3
var hit_cooldown_time = 1.2
var player_half_size = 14.0

var lives = starting_lives
var score = 0
var total_gems = 0
var hit_cooldown = 0.0
var state = "title"
var player: Area2D
var status_label: Label
var walls = []
var patroller: Area2D
var patrol_points = [Vector2(320, 80), Vector2(320, 500), Vector2(560, 500), Vector2(560, 80)]
var patrol_index = 0

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    walls = [
        Rect2(0, 0, 1024, 24), Rect2(0, 552, 1024, 24),
        Rect2(0, 0, 24, 576), Rect2(1000, 0, 24, 576),
        Rect2(200, 120, 24, 340), Rect2(420, 0, 24, 300),
        Rect2(640, 260, 24, 316), Rect2(820, 0, 24, 220),
    ]
    for r in walls:
        var wall_rect = ColorRect.new()
        wall_rect.position = r.position
        wall_rect.size = r.size
        wall_rect.color = Color(0.14, 0.16, 0.24, 0.92)
        add_child(wall_rect)

    player = Area2D.new()
    player.position = Vector2(100, 300)
    var player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = player_half_size
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_touched)
    add_child(player)

    var gem_positions = [Vector2(320, 300), Vector2(530, 100), Vector2(730, 480), Vector2(920, 300)]
    total_gems = gem_positions.size()
    for pos in gem_positions:
        _spawn_gem(pos)

    patroller = Area2D.new()
    patroller.position = patrol_points[0]
    var patroller_sprite = Sprite2D.new()
    patroller_sprite.texture = load("res://assets/key_item.png")
    patroller_sprite.modulate = Color(1.3, 0.5, 0.5)
    patroller_sprite.scale = Vector2(0.6, 0.6)
    patroller.add_child(patroller_sprite)
    var patroller_shape = CollisionShape2D.new()
    var patroller_circle = CircleShape2D.new()
    patroller_circle.radius = 14.0
    patroller_shape.shape = patroller_circle
    patroller.add_child(patroller_shape)
    add_child(patroller)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_gem(pos: Vector2):
    var gem = Area2D.new()
    gem.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    sprite.scale = Vector2(0.5, 0.5)
    gem.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 12.0
    shape.shape = circle
    gem.add_child(shape)
    gem.area_entered.connect(_on_gem_area_entered.bind(gem))
    add_child(gem)

func _on_gem_area_entered(area: Area2D, gem: Area2D):
    if state != "playing" or area != player:
        return
    gem.queue_free()
    score += 1
    Sfx.play("pickup")
    if score >= total_gems:
        state = "won"
        Sfx.play("win")
        status_label.text = "The vault is empty - level complete!"
        Game.level_complete()

func _on_player_touched(area: Area2D):
    if state != "playing" or hit_cooldown > 0.0:
        return
    if area == patroller:
        lives -= 1
        hit_cooldown = hit_cooldown_time
        player.modulate = Color(1.0, 0.45, 0.45)
        Sfx.play("hit")
        if lives <= 0:
            state = "over"
            Sfx.play("lose")
            status_label.text = "Caught by the guard light...  Press Enter to restart"

func _hits_wall(pos: Vector2) -> bool:
    var half = Vector2(player_half_size, player_half_size)
    var player_rect = Rect2(pos - half, half * 2.0)
    for w in walls:
        if player_rect.intersects(w):
            return true
    return false

func _process(delta):
    if state == "title":
        status_label.text = "VAULT RUNNER - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
        return
    if state == "won":
        return
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    if hit_cooldown > 0.0:
        hit_cooldown -= delta
        if hit_cooldown <= 0.0:
            player.modulate = Color(1, 1, 1)

    var target = patrol_points[patrol_index]
    patroller.position = patroller.position.move_toward(target, patroller_speed * delta)
    if patroller.position.distance_to(target) < 2.0:
        patrol_index = (patrol_index + 1) % patrol_points.size()

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var motion = velocity.normalized() * speed * delta

    var new_x = player.position + Vector2(motion.x, 0)
    if not _hits_wall(new_x):
        player.position = new_x
    var new_y = player.position + Vector2(0, motion.y)
    if not _hits_wall(new_y):
        player.position = new_y

    status_label.text = "Gems: %d / %d   Lives: %d" % [score, total_gems, lives]
```"""

DOT_MAZE_EXAMPLE_USER = (
    "Title: Glutton Grove\n"
    "Genre: arcade chase\n"
    "Mechanic template: dot_maze\n"
    "Core mechanics: eat every glow-berry in the hedge maze, dodge the garden wardens, golden berries turn the tables\n"
    "Story premise: A round little glutton sneaks into a hedge-maze garden to eat every glow-berry while the wardens make their rounds.\n"
    "Win condition: eat every berry in the maze\n"
    "Lose condition: lose all 3 lives\n"
    "Key item: a plump glowing berry (role: pickup)\n"
    "This is level 1 of 1: The Hedge Rounds: a moonlit garden maze of tall hedges\n"
    "Available image assets: hero_sprite.png, key_item.png, level_0_bg.png\n"
)

DOT_MAZE_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 200.0
var patrol_speed = 110.0
var hunter_speed = 90.0
var frightened_speed = 65.0
var power_duration = 6.0
var starting_lives = 3
var hit_cooldown_time = 1.2
var player_half_size = 14.0

var lives = starting_lives
var score = 0
var total_dots = 0
var power_left = 0.0
var hit_cooldown = 0.0
var state = "title"
var player: Area2D
var player_spawn = Vector2(512, 490)
var status_label: Label
var walls = []
var ghosts = []
var ghost_sprites = []
var ghost_tints = []
var ghost_home = []
var ghost_routes = []
var ghost_route_index = []
var ghost_frightened = []
var pellet_positions = [Vector2(75, 70), Vector2(950, 70), Vector2(75, 490), Vector2(950, 490)]

func _ready():
    var background = Sprite2D.new()
    background.texture = load("res://assets/level_0_bg.png")
    background.centered = false
    background.position = Vector2.ZERO
    background.z_index = -1
    add_child(background)

    walls = [
        Rect2(0, 0, 1024, 20), Rect2(0, 556, 1024, 20),
        Rect2(0, 0, 20, 576), Rect2(1004, 0, 20, 576),
    ]
    for row_y in [110, 250, 390]:
        for block_x in [130, 350, 560, 780]:
            walls.append(Rect2(block_x, row_y, 120, 60))
    for r in walls:
        var wall_rect = ColorRect.new()
        wall_rect.position = r.position
        wall_rect.size = r.size
        wall_rect.color = Color(0.12, 0.2, 0.14, 0.92)
        add_child(wall_rect)

    player = Area2D.new()
    player.position = player_spawn
    var player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = player_half_size
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_touched)
    add_child(player)

    for y in [70, 210, 350, 490]:
        for x in [75, 160, 300, 410, 515, 620, 730, 840, 950]:
            if Vector2(x, y) in pellet_positions:
                continue
            _spawn_dot(Vector2(x, y), false)
    for x in [75, 300, 515, 730, 950]:
        for y in [140, 280, 420]:
            _spawn_dot(Vector2(x, y), false)
    for pos in pellet_positions:
        _spawn_dot(pos, true)

    _spawn_ghost(Vector2(75, 70), Color(1.4, 0.5, 0.5), [Vector2(300, 70), Vector2(300, 490), Vector2(75, 490), Vector2(75, 70)])
    _spawn_ghost(Vector2(950, 70), Color(1.3, 0.6, 1.3), [Vector2(730, 70), Vector2(950, 70), Vector2(950, 490), Vector2(730, 490)])
    _spawn_ghost(Vector2(515, 280), Color(0.6, 1.3, 0.7), [])

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless" or Game.level > 0:
        state = "playing"

func _spawn_dot(pos: Vector2, is_pellet: bool):
    var dot = Area2D.new()
    dot.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    if is_pellet:
        sprite.scale = Vector2(0.45, 0.45)
        sprite.modulate = Color(1.4, 1.2, 0.5)
    else:
        sprite.scale = Vector2(0.18, 0.18)
    dot.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 10.0
    shape.shape = circle
    dot.add_child(shape)
    dot.area_entered.connect(_on_dot_entered.bind(dot, is_pellet))
    add_child(dot)
    total_dots += 1

func _spawn_ghost(pos: Vector2, tint: Color, route: Array):
    var ghost = Area2D.new()
    ghost.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/key_item.png")
    sprite.modulate = tint
    sprite.scale = Vector2(0.55, 0.55)
    ghost.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 14.0
    shape.shape = circle
    ghost.add_child(shape)
    add_child(ghost)
    ghosts.append(ghost)
    ghost_sprites.append(sprite)
    ghost_tints.append(tint)
    ghost_home.append(pos)
    ghost_routes.append(route)
    ghost_route_index.append(0)
    ghost_frightened.append(false)

func _on_dot_entered(area: Area2D, dot: Area2D, is_pellet: bool):
    if state != "playing" or area != player:
        return
    dot.queue_free()
    score += 1
    Sfx.play("pickup")
    if is_pellet:
        power_left = power_duration
        for i in ghosts.size():
            ghost_frightened[i] = true
    if score >= total_dots:
        state = "won"
        Sfx.play("win")
        status_label.text = "The grove is picked clean - level complete!"
        Game.level_complete()

func _on_player_touched(area: Area2D):
    if state != "playing":
        return
    var gi = ghosts.find(area)
    if gi == -1:
        return
    if ghost_frightened[gi]:
        Sfx.play("pickup")
        ghosts[gi].position = ghost_home[gi]
        ghost_frightened[gi] = false
        return
    if hit_cooldown > 0.0:
        return
    lives -= 1
    hit_cooldown = hit_cooldown_time
    player.modulate = Color(1.0, 0.45, 0.45)
    player.position = player_spawn
    Sfx.play("hit")
    if lives <= 0:
        state = "over"
        Sfx.play("lose")
        status_label.text = "The wardens caught the glutton...  Press Enter to restart"

func _hits_wall(pos: Vector2) -> bool:
    var half = Vector2(player_half_size, player_half_size)
    var player_rect = Rect2(pos - half, half * 2.0)
    for w in walls:
        if player_rect.intersects(w):
            return true
    return false

func _process(delta):
    if state == "title":
        status_label.text = "GLUTTON GROVE - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
        return
    if state == "won":
        return
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    if hit_cooldown > 0.0:
        hit_cooldown -= delta
        if hit_cooldown <= 0.0:
            player.modulate = Color(1, 1, 1)

    if power_left > 0.0:
        power_left -= delta
        if power_left <= 0.0:
            for i in ghosts.size():
                ghost_frightened[i] = false

    for i in ghosts.size():
        var ghost = ghosts[i]
        if ghost_frightened[i]:
            ghost_sprites[i].modulate = Color(0.5, 0.6, 1.4)
            var away = (ghost.position - player.position).normalized()
            ghost.position += away * frightened_speed * delta
            ghost.position = ghost.position.clamp(Vector2(40, 40), Vector2(984, 536))
        else:
            ghost_sprites[i].modulate = ghost_tints[i]
            if ghost_routes[i].size() > 0:
                var target = ghost_routes[i][ghost_route_index[i]]
                ghost.position = ghost.position.move_toward(target, patrol_speed * delta)
                if ghost.position.distance_to(target) < 2.0:
                    ghost_route_index[i] = (ghost_route_index[i] + 1) % ghost_routes[i].size()
            else:
                var toward = (player.position - ghost.position).normalized()
                ghost.position += toward * hunter_speed * delta

    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_pressed("ui_down"):
        velocity.y += 1.0
    if Input.is_action_pressed("ui_up"):
        velocity.y -= 1.0
    var motion = velocity.normalized() * speed * delta

    var new_x = player.position + Vector2(motion.x, 0)
    if not _hits_wall(new_x):
        player.position = new_x
    var new_y = player.position + Vector2(0, motion.y)
    if not _hits_wall(new_y):
        player.position = new_y

    var power_note = ""
    if power_left > 0.0:
        power_note = "   POWER %ds!" % int(ceil(power_left))
    status_label.text = "Berries: %d / %d   Lives: %d%s" % [score, total_dots, lives, power_note]
```"""

FEW_SHOTS = {
    "collect": (COLLECT_EXAMPLE_USER, COLLECT_EXAMPLE_RESPONSE),
    "ordered_switches": (
        ORDERED_SWITCHES_EXAMPLE_USER,
        ORDERED_SWITCHES_EXAMPLE_RESPONSE,
    ),
    "survive_hazards": (SURVIVE_EXAMPLE_USER, SURVIVE_EXAMPLE_RESPONSE),
    "depletion": (DEPLETION_EXAMPLE_USER, DEPLETION_EXAMPLE_RESPONSE),
    "herd_to_goal": (HERD_EXAMPLE_USER, HERD_EXAMPLE_RESPONSE),
    "capture_zones": (CAPTURE_EXAMPLE_USER, CAPTURE_EXAMPLE_RESPONSE),
    "survive_and_deplete": (HYBRID_EXAMPLE_USER, HYBRID_EXAMPLE_RESPONSE),
    "maze_chase": (MAZE_EXAMPLE_USER, MAZE_EXAMPLE_RESPONSE),
    "dot_maze": (DOT_MAZE_EXAMPLE_USER, DOT_MAZE_EXAMPLE_RESPONSE),
}

# Template-specific phrasing for the intensity anchor: which direction each
# family's pressure moves. Written in the few-shots' own tuning-variable
# vocabulary so the model has a literal target, and family-aware because
# some levers invert (longer survival time is HARDER in survival templates).
INTENSITY_LEVERS = {
    "collect": "more pickups, placed farther apart",
    "ordered_switches": "a longer sequence with switches spaced farther apart",
    "survive_hazards": "faster and more hazards and a longer survival time; keep lives at 3",
    "depletion": "higher drain, stingier refill, fewer or farther-apart zones",
    "survive_and_deplete": (
        "higher drain and drain ramp, faster and more hazards, less zone fuel, "
        "zones spaced farther apart"
    ),
    "herd_to_goal": (
        "a larger panic_radius (creatures bolt sooner, so you must approach "
        "more carefully), more creatures, and a smaller goal zone - raise "
        "flee speed only slightly and never to within 60% of the player's "
        "speed, or the creatures simply cannot be herded at all"
    ),
    "capture_zones": "a faster patroller and zones spread farther apart",
    "maze_chase": "a faster patroller covering more of the route, pickups placed deeper",
    "dot_maze": (
        "faster ghosts (especially the hunter), shorter power duration, more "
        "dots; keep lives at 3"
    ),
}

# Structurally nearest authored example per template. Ordered switches has a
# dedicated example because autonomous QA requires stable sequence/reset
# adapters. Herd and capture zones now have dedicated examples for their
# permanent-settlement and ownership QA interfaces.
TEMPLATE_TO_FEW_SHOT = {
    "collect": "collect",
    "ordered_switches": "ordered_switches",
    "survive_hazards": "survive_hazards",
    "herd_to_goal": "herd_to_goal",
    "depletion": "depletion",
    "capture_zones": "capture_zones",
    "survive_and_deplete": "survive_and_deplete",
    "maze_chase": "maze_chase",
    "dot_maze": "dot_maze",
}

FIX_SYSTEM_PROMPT = (
    "You are the Coder agent in an automated game studio. Godot's QA check just "
    "ran your previous GDScript and found errors. Fix the specific errors "
    "listed - do not rewrite the script from scratch or change unrelated "
    "behavior. Preserve the existing mechanic, status-label, "
    "title/playing/over state machine, Sfx calls, and win/lose logic as-is "
    "unless one of them is itself the cause of an error. If an error says a "
    "method expected N arguments but was called with N+1, the signal was "
    "connected with .bind(...) - the handler must accept the extra bound "
    "argument (e.g. func _on_zone_entered(area: Area2D, index: int)), "
    "exactly as the worked example does. No custom InputMap actions are "
    "defined in this project, so only use Godot's built-in default input "
    "actions (ui_up, ui_down, ui_left, ui_right, and ui_accept for "
    "start/restart only) - never invent a new action name. "
    + GODOT4_API_NOTES +
    "Respond with ONLY a single ```gdscript fenced code block containing the "
    "complete corrected script, no explanation before or after it."
)

TUNE_SYSTEM_PROMPT = (
    "You are the Coder agent in an automated game studio. A human playtester "
    "reviewed the current build and a feedback interpreter produced specific "
    "tuning changes to apply to your previous GDScript. Apply exactly the "
    "listed changes - do not rewrite the script from scratch or change any "
    "unrelated behavior. Preserve the existing mechanic, status-label, "
    "title/playing/over state machine, Sfx calls, and win/lose logic. No "
    "custom InputMap actions are defined in this project, so only use "
    "Godot's built-in default input actions (ui_up, ui_down, ui_left, "
    "ui_right, and ui_accept for start/restart only) - never invent a new "
    "action name. Respond with ONLY a single ```gdscript fenced code block "
    "containing the complete updated script, no explanation before or after "
    "it."
)


def _contract_violations(gdscript: str, template: str) -> list[str]:
    contract = (TEMPLATE_CONTRACTS.get(template) or []) + UNIVERSAL_CONTRACTS
    violations = [desc for desc, pattern in contract if not re.search(pattern, gdscript)]
    violations += animation_call_violations(gdscript)
    violations += [desc for desc, pattern in FORBIDDEN_PATTERNS if re.search(pattern, gdscript)]
    return list(dict.fromkeys(violations))


def _final_candidate_errors(
    gdscript: str,
    *,
    template: str,
    valid_assets: set[str],
) -> list[str]:
    """Recheck corrected output before it is allowed to replace a script."""
    errors = [f"Contract: {violation}" for violation in _contract_violations(gdscript, template)]
    bad_refs = sorted(
        {match for match in re.findall(r'res://assets/([^"\']+)', gdscript) if match not in valid_assets}
    )
    errors += [f"Asset does not exist: res://assets/{reference}" for reference in bad_refs]
    errors += [finding.message() for finding in scan_generated_gdscript(gdscript)]
    return errors


def _rejected_repair_result(
    *,
    project_dir: Path,
    model: str,
    original_goal: list[str],
    errors: list[str],
) -> GraphState:
    evidence = [
        "Repair candidate rejected before promotion; the previous gameplay script was preserved."
    ]
    evidence += [f"Candidate validation: {error}" for error in errors]
    evidence += [f"Original repair goal: {goal}" for goal in original_goal]
    print(f"[Coder] Repair candidate rejected; previous script restored: {errors}")
    return {
        "godot_project_path": str(project_dir),
        "tune_notes": None,
        "coder_model": model,
        "repair_rejected": True,
        "repair_validation_errors": evidence,
    }


def _blueprint_contract(state: GraphState) -> str:
    """Compact architect handoff appended to fresh, repair and tune prompts."""
    blueprint = state.get("blueprint") or {}
    if not blueprint:
        return ""
    systems = {item.get("id"): item for item in blueprint.get("systems") or []}
    ordered_ids = [
        step.get("system_id") for step in state.get("blueprint_build_plan") or []
    ]
    if not ordered_ids:
        ordered_ids = list(systems)

    lines = [
        "SYSTEMS ARCHITECT CONTRACT (mandatory; preserve it during repairs):",
        "Core loop: " + " -> ".join(blueprint.get("core_loop") or []),
    ]
    for system_id in ordered_ids:
        system = systems.get(system_id)
        if not system:
            continue
        deps = ", ".join(system.get("depends_on") or []) or "none"
        lines.append(
            f"- {system_id} [{system.get('kind')}], after: {deps}: "
            f"{system.get('description', '')}"
        )
        lines.extend(f"  ACCEPT: {criterion}" for criterion in system.get("acceptance") or [])
    return "\n".join(lines) + "\n"


# Mechanics whose deterministic solver can answer "does this still complete?"
# during a build, not just at the end of one. Kept in sync with the QA Agent's
# objective-probe gate; a template outside it simply gets no behavioral gate.
PROBED_TEMPLATES = {
    "collect",
    "ordered_switches",
    "survive_hazards",
    "depletion",
    "survive_and_deplete",
    "capture_zones",
    "herd_to_goal",
    "dot_maze",
    "maze_chase",
}


def _objective_probe_for(project_dir, level_index: int, template: str):
    """Bind the QA Agent's objective solver to this level, or None when the
    template has no deterministic completion probe."""
    if template not in PROBED_TEMPLATES:
        return None
    from saga.agents.qa_agent import _run_objective_probe

    def run_probe():
        return _run_objective_probe(
            str(project_dir), f"res://Level_{level_index}.tscn", template
        )

    return run_probe


def coder(state: GraphState) -> GraphState:
    design_doc = state["design_doc"]
    sprite_paths = state.get("sprite_paths") or []
    bgm_path = state.get("bgm_path")
    current_level = state.get("current_level") or 0
    levels = design_doc["levels"]
    total_levels = len(levels)
    project_dir = run_project_dir(state)

    project_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = project_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    asset_filenames = []
    for src in sprite_paths:
        src_path = Path(src)
        shutil.copy(src_path, assets_dir / src_path.name)
        asset_filenames.append(src_path.name)
    bgm_filename = None
    if bgm_path:
        src_path = Path(bgm_path)
        shutil.copy(src_path, assets_dir / src_path.name)
        bgm_filename = src_path.name

    # Harness-owned SFX: synthesized deterministically, loaded by the Sfx
    # autoload, called by the generated script.
    write_default_sfx(assets_dir)

    if current_level == 0 and not _is_remote():
        _stop_gpu_services()

    # This level's script sees only ITS background in the asset list -
    # listing all N backgrounds invites the model to pick the wrong one.
    bg_files = [f for f in asset_filenames if f.startswith("level_")]
    level_bg = next(
        (f for f in bg_files if f.startswith(f"level_{current_level}_")),
        bg_files[0] if bg_files else None,
    )
    listed_assets = [f for f in asset_filenames if not f.startswith("level_")]
    if level_bg:
        listed_assets.append(level_bg)
    assets_manifest = _asset_manifest(listed_assets, design_doc)

    template = design_doc.get("mechanic_template") or "collect"
    example_user, example_response = FEW_SHOTS[TEMPLATE_TO_FEW_SHOT.get(template, "collect")]

    script_file = project_dir / f"Level_{current_level}.gd"
    qa_errors = state.get("qa_errors") or []
    tune_notes = state.get("tune_notes") or []
    is_repair = bool(qa_errors or tune_notes)
    if is_repair and recover_interrupted_repair(script_file):
        print(f"[Coder] Recovered interrupted repair checkpoint for level {current_level + 1}")

    # Fix-vs-fresh is no longer decided here: the Studio Director triages
    # every QA failure and clears qa_errors when it wants a fresh generation
    # (its deterministic fallback reproduces the escalation that used to be
    # hardcoded at this spot).

    # The fix/tune paths need the real asset list too: without it the model
    # cannot recover from an invented-filename error (it has no way to know
    # which files exist) and tends to flail into fallback code instead.
    assets_line = f"Available image assets (use these EXACT filenames):\n{assets_manifest}\n"
    blueprint_contract = _blueprint_contract(state)

    if qa_errors:
        previous_script = script_file.read_text(encoding="utf-8")
        errors_desc = "\n".join(f"- {e}" for e in qa_errors)
        user_prompt = (
            f"Previous script:\n```gdscript\n{previous_script}\n```\n\n"
            f"{assets_line}"
            f"{blueprint_contract}"
            f"Godot reported these errors:\n{errors_desc}\n"
        )
        system_prompt = FIX_SYSTEM_PROMPT
    elif tune_notes:
        previous_script = script_file.read_text(encoding="utf-8")
        notes_desc = "\n".join(f"- {n}" for n in tune_notes)
        user_prompt = (
            f"Previous script:\n```gdscript\n{previous_script}\n```\n\n"
            f"{assets_line}"
            f"{blueprint_contract}"
            f"Apply these tuning changes:\n{notes_desc}\n"
        )
        system_prompt = TUNE_SYSTEM_PROMPT
    else:
        key_item = design_doc["key_item"]
        level = levels[current_level]
        intensity = level.get("intensity")
        if intensity:
            levers = INTENSITY_LEVERS.get(template, INTENSITY_LEVERS["collect"])
            difficulty_line = (
                f"Difficulty intensity: {intensity}/10 (non-negotiable). The worked "
                f"example's numbers are intensity 4/10 - scale pressure roughly 15% "
                f"per point of difference via: {levers}. "
                f"Apply specifically: {level.get('pressure_notes', '')}\n"
            )
        else:
            difficulty_line = (
                f"Difficulty: scale for level {current_level + 1} of {total_levels} - "
                f"later levels get faster hazards, more of them, and tighter margins.\n"
            )
        user_prompt = (
            f"Title: {design_doc['title']}\n"
            f"Genre: {design_doc['genre']}\n"
            f"Mechanic template: {template}\n"
            f"Core mechanics: {', '.join(design_doc['core_mechanics'])}\n"
            f"Story premise: {design_doc['story_premise']}\n"
            f"Win condition (per level): {design_doc['win_condition']}\n"
            f"Lose condition: {design_doc['lose_condition']}\n"
            f"Key item: {key_item['description']} (role: {key_item['role']})\n"
            f"This is level {current_level + 1} of {total_levels}: "
            f"{level['name']}: {level['description']}\n"
            f"{difficulty_line}"
            f"{blueprint_contract}"
            f"Available image assets (use these EXACT filenames):\n{assets_manifest}\n"
        )
        requirements = TEMPLATE_REQUIREMENTS.get(template, TEMPLATE_REQUIREMENTS["collect"])
        system_prompt = f"{SYSTEM_PROMPT_BASE} {requirements}"

    # Per-template routing is a local-model workaround (small models drop
    # declarations on long few-shots); a hosted model handles every template.
    model = REMOTE_MODEL if _is_remote() else TEMPLATE_MODEL_OVERRIDES.get(template, MODEL)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": example_user},
        {"role": "assistant", "content": example_response},
        {"role": "user", "content": user_prompt},
    ]
    try:
        gdscript = _extract_gdscript(_chat(messages, model))
    except ValueError:
        # Models occasionally drop the fence under long prompts; one retry
        # recovers nearly all of these without failing the whole run.
        print("[Coder] Response had no code fence, retrying once")
        gdscript = _extract_gdscript(_chat(messages, model))

    # Pre-flight: catch invented asset filenames before wasting a Godot run.
    # One bounded self-correction round-trip; anything still wrong after
    # that falls through to the real QA loop.
    valid_assets = set(asset_filenames) | {f"sfx_{n}.wav" for n in ("pickup", "hit", "win", "lose")}
    if bgm_filename:
        valid_assets.add(bgm_filename)
    bad_refs = sorted(
        {m for m in re.findall(r'res://assets/([^"\']+)', gdscript) if m not in valid_assets}
    )
    if bad_refs:
        print(f"[Coder] Invented asset reference(s) {bad_refs}, requesting one correction")
        errors_desc = "\n".join(
            f"- load(\"res://assets/{ref}\") refers to a file that does not exist" for ref in bad_refs
        )
        gdscript = _extract_gdscript(
            _chat(
                [
                    {"role": "system", "content": FIX_SYSTEM_PROMPT},
                    {"role": "user", "content": example_user},
                    {"role": "assistant", "content": example_response},
                    {
                        "role": "user",
                        "content": (
                            f"Previous script:\n```gdscript\n{gdscript}\n```\n\n"
                            f"{assets_line}"
                            f"These errors must be fixed by using only the exact "
                            f"filenames listed above:\n{errors_desc}\n"
                        ),
                    },
                ],
                model,
            )
        )

    # Pre-flight: catch silently-simplified-away systems (contract check).
    # One bounded correction round-trip, same shape as the filename check.
    violations = _contract_violations(gdscript, template)
    if violations and not tune_notes:
        print(f"[Coder] Contract violation(s), requesting one correction: {violations}")
        errors_desc = "\n".join(
            f"- the script is missing a required system: {desc} - reproduce it "
            f"exactly as the worked example demonstrates" for desc in violations
        )
        gdscript = _extract_gdscript(
            _chat(
                [
                    {"role": "system", "content": FIX_SYSTEM_PROMPT},
                    {"role": "user", "content": example_user},
                    {"role": "assistant", "content": example_response},
                    {
                        "role": "user",
                        "content": (
                            f"Previous script:\n```gdscript\n{gdscript}\n```\n\n"
                            f"{assets_line}"
                            f"These problems must be fixed:\n{errors_desc}\n"
                        ),
                    },
                ],
                model,
            )
        )

    # Security pre-flight: model output is untrusted code that QA will execute.
    # Give the Coder one chance to remove unnecessary host capabilities, then
    # fail closed if any survive.
    safety_findings = scan_generated_gdscript(gdscript)
    if safety_findings:
        print(
            f"[Coder] Unsafe generated API use, requesting one correction: "
            f"{[finding.message() for finding in safety_findings]}"
        )
        errors_desc = "\n".join(f"- {finding.message()}" for finding in safety_findings)
        gdscript = _extract_gdscript(
            _chat(
                [
                    {"role": "system", "content": FIX_SYSTEM_PROMPT},
                    {"role": "user", "content": example_user},
                    {"role": "assistant", "content": example_response},
                    {
                        "role": "user",
                        "content": (
                            f"Previous script:\n```gdscript\n{gdscript}\n```\n\n"
                            f"{assets_line}"
                            "Remove every forbidden host capability below. The level "
                            "needs only scene, input, animation, and exact res://assets/ "
                            f"loads:\n{errors_desc}\n"
                        ),
                    },
                ],
                model,
            )
        )
    final_errors = _final_candidate_errors(
        gdscript,
        template=template,
        valid_assets=valid_assets,
    )
    if final_errors and is_repair:
        return _rejected_repair_result(
            project_dir=project_dir,
            model=model,
            original_goal=list(qa_errors or tune_notes),
            errors=final_errors,
        )
    assert_safe_gdscript(gdscript)

    (project_dir / "project.godot").write_text(
        PROJECT_GODOT_TEMPLATE.format(title=design_doc["title"]), encoding="utf-8"
    )
    (project_dir / "screenshot.gd").write_text(SCREENSHOT_GD, encoding="utf-8")
    (project_dir / "sfx.gd").write_text(SFX_GD, encoding="utf-8")
    (project_dir / "ambience.gd").write_text(AMBIENCE_GD, encoding="utf-8")
    (project_dir / "anim.gd").write_text(ANIM_GD, encoding="utf-8")
    (project_dir / "autoplay.gd").write_text(AUTOPLAY_GD, encoding="utf-8")
    (project_dir / "objective_probe.gd").write_text(OBJECTIVE_PROBE_GD, encoding="utf-8")
    (project_dir / "switch_probe.gd").write_text(SWITCH_PROBE_GD, encoding="utf-8")
    (project_dir / "survival_probe.gd").write_text(SURVIVAL_PROBE_GD, encoding="utf-8")
    (project_dir / "depletion_probe.gd").write_text(DEPLETION_PROBE_GD, encoding="utf-8")
    (project_dir / "hybrid_probe.gd").write_text(HYBRID_PROBE_GD, encoding="utf-8")
    (project_dir / "capture_probe.gd").write_text(CAPTURE_PROBE_GD, encoding="utf-8")
    (project_dir / "herd_probe.gd").write_text(HERD_PROBE_GD, encoding="utf-8")
    beats = [lvl.get("outro_beat", "") for lvl in levels]
    (project_dir / "music.gd").write_text(_build_music_gd(bgm_filename), encoding="utf-8")
    (project_dir / "game.gd").write_text(_build_game_gd(total_levels, beats), encoding="utf-8")
    (project_dir / "interlude.gd").write_text(INTERLUDE_GD, encoding="utf-8")
    (project_dir / "Interlude.tscn").write_text(INTERLUDE_TSCN, encoding="utf-8")
    (project_dir / "victory.gd").write_text(VICTORY_GD, encoding="utf-8")
    (project_dir / "Victory.tscn").write_text(VICTORY_TSCN, encoding="utf-8")
    (project_dir / f"Level_{current_level}.tscn").write_text(
        _build_level_tscn(current_level), encoding="utf-8"
    )
    if is_repair:
        validation = validate_and_promote_repair(
            script_file,
            gdscript,
            project_dir=project_dir,
            scene=f"res://Level_{current_level}.tscn",
        )
        if not validation.passed:
            return _rejected_repair_result(
                project_dir=project_dir,
                model=model,
                original_goal=list(qa_errors or tune_notes),
                errors=validation.errors,
            )
        print(f"[Coder] Repair gate passed for level {current_level + 1}; candidate promoted")
    else:
        script_file.write_text(gdscript, encoding="utf-8")

    system_build_results = None
    if not is_repair and settings.incremental_build and state.get("blueprint"):
        from saga.protected_builder import protected_incremental_build

        print(
            f"[Protected Builder] Quality mode enabled; refining up to "
            f"{settings.incremental_max_systems} blueprint systems"
        )
        system_build_results = protected_incremental_build(
            script_file=script_file,
            project_dir=project_dir,
            scene=f"res://Level_{current_level}.tscn",
            level_index=current_level,
            blueprint=state["blueprint"],
            build_plan=state.get("blueprint_build_plan") or [],
            model=model,
            chat=_chat,
            route_chat=lambda messages, preferred: _routed_chat(messages, preferred, model),
            extract_gdscript=_extract_gdscript,
            candidate_errors=lambda candidate: _final_candidate_errors(
                candidate,
                template=template,
                valid_assets=valid_assets,
            ),
            existing_results=state.get("system_build_results") or [],
            max_systems=settings.incremental_max_systems,
            max_attempts=settings.incremental_max_attempts,
            probe=_objective_probe_for(project_dir, current_level, template),
        )

    action = "Fixed" if qa_errors else ("Tuned" if tune_notes else "Generated")
    print(
        f"[Coder] {action} level {current_level + 1}/{total_levels} "
        f"({template}, model={model}) -> {project_dir}"
    )
    # tune_notes are consumed by this pass; clear them so a subsequent QA
    # retry takes the fix path against the already-tuned script.
    result = {
        "godot_project_path": str(project_dir),
        "tune_notes": None,
        "coder_model": model,
        "repair_rejected": False,
        "repair_validation_errors": [],
    }
    if not qa_errors and not tune_notes:
        # Only a fresh generation carries the design brief. Fix/tune passes
        # omit the key entirely rather than setting None, so the original
        # brief survives in state - a level that passes after two repairs
        # is still a valid (brief -> working script) training pair.
        result["coder_prompt"] = user_prompt
    if system_build_results is not None:
        result["system_build_results"] = system_build_results
    return result
