"""Coder agent - generates a minimal Godot 4 project via a local Ollama model.

The harness writes the deterministic boilerplate itself (project.godot, a bare
Main.tscn scene, the Screenshot and Sfx autoloads, and the synthesized SFX
WAVs) since hand-authoring correct .tscn/resource plumbing is a poor fit for
an LLM. The model's only job is to write Main.gd - the actual gameplay logic
- given the design doc and the list of already-generated asset filenames.

The design doc's mechanic_template selects both a template-specific
requirements paragraph appended to the system prompt and the closest worked
few-shot example. Showing a small local model a complete example of the
structure it is asked to produce is its single biggest reliability lever, so
each template maps to whichever of the five authored examples is
structurally nearest. Every few-shot demonstrates the shared "juice" idioms:
a title -> playing -> over state machine (with headless auto-start so QA
still exercises gameplay), Sfx autoload calls, and a CPUParticles2D ambient
effect.
"""

import os
import re
import shutil
from pathlib import Path

import ollama

from saga.sfx import write_default_sfx
from saga.state import GraphState

MODEL = os.environ.get("SAGA_CODER_MODEL", "qwen2.5-coder:14b")
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output" / "godot_project"

PROJECT_GODOT_TEMPLATE = """config_version=5

[application]
config/name="{title}"
run/main_scene="res://Main.tscn"
config/features=PackedStringArray("4.7")

[autoload]
Screenshot="*res://screenshot.gd"
Sfx="*res://sfx.gd"
Ambience="*res://ambience.gd"

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
        img.save_png("res://screenshot.png")
"""

# Harness-owned ambient particles: presentation boilerplate the 14B model
# reliably gets wrong when asked to write it (it invents CPUParticles2D
# properties), so it lives here with the other harness-owned polish. Skipped
# headlessly - no visual value, and dummy-renderer particles leak RIDs.
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


def _build_main_tscn(bgm_filename: str | None) -> str:
    """Bgm autoplay is wired here by the harness, not left to the LLM - the
    filename is already known before the template is filled in, same "harness
    owns the boilerplate, LLM owns gameplay" split as the rest of the scene."""
    if not bgm_filename:
        return """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://Main.gd" id="1"]

[node name="Main" type="Node2D"]
script = ExtResource("1")
"""
    return f"""[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://Main.gd" id="1"]
[ext_resource type="AudioStream" path="res://assets/{bgm_filename}" id="2"]

[node name="Main" type="Node2D"]
script = ExtResource("1")

[node name="BGM" type="AudioStreamPlayer" parent="."]
stream = ExtResource("2")
autoplay = true
"""


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
    "condition exactly. Structure play as three states in a `state` "
    "variable: 'title' (show the game title and 'Press Enter to start'; "
    "ui_accept starts), 'playing', and 'over' (show the result and 'Press "
    "Enter to restart'; ui_accept calls get_tree().reload_current_scene()). "
    "At the end of _ready, if DisplayServer.get_name() == \"headless\", set "
    "state straight to 'playing' so automated QA exercises real gameplay. "
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
    "exist crashes QA. When a template needs a second object appearance "
    "(hazard, patroller, frost, drone), reuse the key_item sprite tinted "
    "via modulate and scaled, exactly as the example does - there is no "
    "separate image for it. Put every gameplay-tuning number - speeds, "
    "rates, durations, counts, radii - in a named variable at the top of "
    "the script so a human playtester can retune it later. Respond with "
    "ONLY a single ```gdscript fenced code block, no explanation before or "
    "after it."
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
        "positions; touching them in the correct order advances progress "
        "(tint activated switches via modulate and play the pickup sound), "
        "touching one out of order resets progress and the tints (play the "
        "hit sound); show progress in the label; win when the full sequence "
        "is completed."
    ),
    "survive_hazards": (
        "Structure for this game: place several hazard Area2Ds that move "
        "every frame along deterministic paths (straight lines that bounce "
        "off the viewport edges by flipping the direction component); the "
        "player starts with a few lives and loses one on each hazard touch; "
        "a survival timer counts down in _process; show time and lives in "
        "the label; win when the timer reaches zero, lose when lives reach "
        "zero."
    ),
    "depletion": (
        "Structure for this game: a resource value drains every frame in "
        "_process; standing inside refill zone Area2Ds restores it instead "
        "(track overlap by connecting area_entered and area_exited on the "
        "player and counting zones inside); clamp the resource to 0-100; a "
        "timer counts down; show resource and time in the label; win when "
        "the timer reaches zero with the resource above zero, lose the "
        "moment the resource hits zero."
    ),
    "herd_to_goal": (
        "Structure for this game: one creature Area2D flees the player every "
        "frame (move it along the vector pointing away from the player, "
        "scaled by speed and delta, clamped inside the viewport); one goal "
        "zone Area2D at a fixed position; connect the goal's area_entered "
        "and win when the entering area is the creature; show guidance in "
        "the label."
    ),
    "capture_zones": (
        "Structure for this game: place several zone-marker Area2Ds; "
        "touching one claims it (tint it via modulate and set a flag); one "
        "patroller Area2D moves between fixed waypoints every frame and "
        "un-claims any zone it touches (reset tint and flag); show the "
        "claimed count in the label; win when all zones are claimed at the "
        "same time."
    ),
    "survive_and_deplete": (
        "Structure for this game: combine depletion with roaming hazards. A "
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
}

# --- Few-shot worked examples ------------------------------------------------
# Five authored examples; every template maps to the structurally nearest one.
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
    "Levels:\n"
    "- Rooftop Dash: a sunlit row of rooftops with scattered coins\n"
    "Available image assets: hero_sprite.png, key_item.png, level_0_bg.png\n"
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

    if DisplayServer.get_name() == "headless":
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
        state = "over"
        Sfx.play("win")
        status_label.text = "All coins collected - you win!  Press Enter to restart"

func _process(delta):
    if state == "title":
        status_label.text = "COIN RUSH - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
            status_label.text = "Coins: 0 / %d" % total_coins
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

SURVIVE_EXAMPLE_USER = (
    "Title: Meteor Vigil\n"
    "Genre: arcade survival\n"
    "Mechanic template: survive_hazards\n"
    "Core mechanics: dodge falling meteors, survive until dawn\n"
    "Story premise: A lone stargazer weaves between falling meteors until sunrise.\n"
    "Win condition: survive for 30 seconds\n"
    "Lose condition: lose all 3 lives\n"
    "Key item: a blazing meteor fragment (role: hazard)\n"
    "Levels:\n"
    "- Night Ridge: a dark ridgeline under a meteor shower\n"
    "Available image assets: hero_sprite.png, key_item.png, level_0_bg.png\n"
)

SURVIVE_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 240.0
var hazard_speed = 180.0
var starting_lives = 3
var survival_time = 30.0
var lives = starting_lives
var time_left = survival_time
var state = "title"
var player: Area2D
var status_label: Label
var hazards = []
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
    var player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_hit)
    add_child(player)

    var starts = [Vector2(150, 100), Vector2(850, 200), Vector2(500, 480)]
    var dirs = [Vector2(1, 0.5), Vector2(-1, 0.3), Vector2(0.7, -1)]
    for i in starts.size():
        _spawn_hazard(starts[i], dirs[i])

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless":
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
    if state != "playing":
        return
    lives -= 1
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
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    time_left -= delta
    if time_left <= 0.0:
        state = "over"
        Sfx.play("win")
        status_label.text = "Dawn breaks - you survived!  Press Enter to restart"
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
    player.position += velocity.normalized() * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))

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
    "Levels:\n"
    "- The Long Walk: a fog-bound rampart dotted with braziers\n"
    "Available image assets: hero_sprite.png, key_item.png, level_0_bg.png\n"
)

DEPLETION_EXAMPLE_RESPONSE = """```gdscript
extends Node2D

@export var speed = 240.0
var drain_rate = 8.0
var refill_rate = 15.0
var survival_time = 30.0
var light = 100.0
var time_left = survival_time
var zones_inside = 0
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
    player.area_entered.connect(_on_player_area_entered)
    player.area_exited.connect(_on_player_area_exited)
    add_child(player)

    var zone_positions = [Vector2(220, 300), Vector2(512, 150), Vector2(820, 420)]
    for pos in zone_positions:
        _spawn_zone(pos)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    status_label = Label.new()
    status_label.position = Vector2(20, 20)
    canvas.add_child(status_label)

    if DisplayServer.get_name() == "headless":
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
    if state == "over":
        if Input.is_action_just_pressed("ui_accept"):
            get_tree().reload_current_scene()
        return

    if zones_inside > 0:
        light += refill_rate * delta
    else:
        light -= drain_rate * delta
    light = clamp(light, 0.0, 100.0)
    time_left -= delta

    if light <= 0.0:
        state = "over"
        Sfx.play("lose")
        status_label.text = "The lantern gutters out...  Press Enter to restart"
        return
    if time_left <= 0.0:
        state = "over"
        Sfx.play("win")
        status_label.text = "Dawn comes - the light held!  Press Enter to restart"
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

    status_label.text = "Light: %d%%   Time: %ds" % [int(light), int(ceil(time_left))]
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
    "Levels:\n"
    "- The Core Floor: a dim reactor hall lit by scattered charging pads\n"
    "Available image assets: hero_sprite.png, key_item.png, level_0_bg.png\n"
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

var power = 100.0
var time_left = survival_time
var elapsed = 0.0
var hit_cooldown = 0.0
var state = "title"
var player: Area2D
var status_label: Label
var zones = []
var zone_fuel = []
var zone_sprites = []
var inside_zones = []
var hazards = []
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
    var player_sprite = Sprite2D.new()
    player_sprite.texture = load("res://assets/hero_sprite.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 18.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    player.area_entered.connect(_on_player_touched)
    add_child(player)

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

    if DisplayServer.get_name() == "headless":
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
        power -= hazard_hit_cost
        hit_cooldown = hit_cooldown_time
        player.modulate = Color(1.0, 0.45, 0.45)
        Sfx.play("hit")

func _process(delta):
    if state == "title":
        status_label.text = "REACTOR DIVE - Press Enter to start"
        if Input.is_action_just_pressed("ui_accept"):
            state = "playing"
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
        power += refill_rate * delta
    else:
        power -= (drain_rate + elapsed * drain_ramp) * delta
    power = clamp(power, 0.0, 100.0)

    if power <= 0.0:
        state = "over"
        Sfx.play("lose")
        status_label.text = "Systems dark. The reactor wins...  Press Enter to restart"
        return
    if time_left <= 0.0:
        state = "over"
        Sfx.play("win")
        status_label.text = "Rescue arrives - you held on!  Press Enter to restart"
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
    player.position += velocity.normalized() * speed * delta
    player.position = player.position.clamp(Vector2.ZERO, Vector2(1024, 576))

    var pads_left = 0
    for f in zone_fuel:
        if f > 0.0:
            pads_left += 1
    status_label.text = "Power: %d%%   Time: %ds   Pads: %d" % [int(power), int(ceil(time_left)), pads_left]
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
    "Levels:\n"
    "- The Vault: dim steel corridors lined with deposit boxes\n"
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

    if DisplayServer.get_name() == "headless":
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
        state = "over"
        Sfx.play("win")
        status_label.text = "The vault is empty - clean getaway!  Press Enter to restart"

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

FEW_SHOTS = {
    "collect": (COLLECT_EXAMPLE_USER, COLLECT_EXAMPLE_RESPONSE),
    "survive_hazards": (SURVIVE_EXAMPLE_USER, SURVIVE_EXAMPLE_RESPONSE),
    "depletion": (DEPLETION_EXAMPLE_USER, DEPLETION_EXAMPLE_RESPONSE),
    "survive_and_deplete": (HYBRID_EXAMPLE_USER, HYBRID_EXAMPLE_RESPONSE),
    "maze_chase": (MAZE_EXAMPLE_USER, MAZE_EXAMPLE_RESPONSE),
}

# Structurally nearest authored example per template: ordered_switches shares
# collect's touch-static-objects-and-track-progress shape, herd_to_goal shares
# survive_hazards' per-frame moving-Area2D vector math, capture_zones shares
# depletion's continuous state changes plus a mover.
TEMPLATE_TO_FEW_SHOT = {
    "collect": "collect",
    "ordered_switches": "collect",
    "survive_hazards": "survive_hazards",
    "herd_to_goal": "survive_hazards",
    "depletion": "depletion",
    "capture_zones": "depletion",
    "survive_and_deplete": "survive_and_deplete",
    "maze_chase": "maze_chase",
}

FIX_SYSTEM_PROMPT = (
    "You are the Coder agent in an automated game studio. Godot's QA check just "
    "ran your previous GDScript and found errors. Fix the specific errors "
    "listed - do not rewrite the script from scratch or change unrelated "
    "behavior. Preserve the existing mechanic, status-label, "
    "title/playing/over state machine, Sfx calls, and win/lose logic as-is "
    "unless one of them is itself the cause of an error. No custom InputMap "
    "actions are defined in this project, so only use Godot's built-in "
    "default input actions (ui_up, ui_down, ui_left, ui_right, and ui_accept "
    "for start/restart only) - never invent a new action name. Respond with "
    "ONLY a single ```gdscript fenced code block containing the complete "
    "corrected script, no explanation before or after it."
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


def _extract_gdscript(text: str) -> str:
    match = re.search(r"```gdscript\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fall back to a generic fenced block if the model didn't tag it
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    raise ValueError("Coder agent response did not contain a fenced code block")


def coder(state: GraphState) -> GraphState:
    design_doc = state["design_doc"]
    sprite_paths = state.get("sprite_paths") or []
    bgm_path = state.get("bgm_path")

    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    assets_dir = PROJECT_DIR / "assets"
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

    template = design_doc.get("mechanic_template") or "collect"
    example_user, example_response = FEW_SHOTS[TEMPLATE_TO_FEW_SHOT.get(template, "collect")]

    qa_errors = state.get("qa_errors") or []
    tune_notes = state.get("tune_notes") or []

    # The fix/tune paths need the real asset list too: without it the model
    # cannot recover from an invented-filename error (it has no way to know
    # which files exist) and tends to flail into fallback code instead.
    assets_line = f"Available image assets (use these EXACT filenames): {', '.join(asset_filenames)}\n"

    if qa_errors:
        previous_script = (PROJECT_DIR / "Main.gd").read_text(encoding="utf-8")
        errors_desc = "\n".join(f"- {e}" for e in qa_errors)
        user_prompt = (
            f"Previous Main.gd:\n```gdscript\n{previous_script}\n```\n\n"
            f"{assets_line}"
            f"Godot reported these errors:\n{errors_desc}\n"
        )
        system_prompt = FIX_SYSTEM_PROMPT
    elif tune_notes:
        previous_script = (PROJECT_DIR / "Main.gd").read_text(encoding="utf-8")
        notes_desc = "\n".join(f"- {n}" for n in tune_notes)
        user_prompt = (
            f"Previous Main.gd:\n```gdscript\n{previous_script}\n```\n\n"
            f"{assets_line}"
            f"Apply these tuning changes:\n{notes_desc}\n"
        )
        system_prompt = TUNE_SYSTEM_PROMPT
    else:
        key_item = design_doc["key_item"]
        levels_desc = "\n".join(f"- {lvl['name']}: {lvl['description']}" for lvl in design_doc["levels"])
        user_prompt = (
            f"Title: {design_doc['title']}\n"
            f"Genre: {design_doc['genre']}\n"
            f"Mechanic template: {template}\n"
            f"Core mechanics: {', '.join(design_doc['core_mechanics'])}\n"
            f"Story premise: {design_doc['story_premise']}\n"
            f"Win condition: {design_doc['win_condition']}\n"
            f"Lose condition: {design_doc['lose_condition']}\n"
            f"Key item: {key_item['description']} (role: {key_item['role']})\n"
            f"Levels:\n{levels_desc}\n"
            f"Available image assets: {', '.join(asset_filenames)}\n"
        )
        requirements = TEMPLATE_REQUIREMENTS.get(template, TEMPLATE_REQUIREMENTS["collect"])
        system_prompt = f"{SYSTEM_PROMPT_BASE} {requirements}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": example_user},
        {"role": "assistant", "content": example_response},
        {"role": "user", "content": user_prompt},
    ]
    response = ollama.chat(model=MODEL, messages=messages)
    try:
        gdscript = _extract_gdscript(response["message"]["content"])
    except ValueError:
        # Local models occasionally drop the fence under long prompts; one
        # retry recovers nearly all of these without failing the whole run.
        print("[Coder] Response had no code fence, retrying once")
        response = ollama.chat(model=MODEL, messages=messages)
        gdscript = _extract_gdscript(response["message"]["content"])

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
        retry_response = ollama.chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": FIX_SYSTEM_PROMPT},
                {"role": "user", "content": example_user},
                {"role": "assistant", "content": example_response},
                {
                    "role": "user",
                    "content": (
                        f"Previous Main.gd:\n```gdscript\n{gdscript}\n```\n\n"
                        f"{assets_line}"
                        f"These errors must be fixed by using only the exact "
                        f"filenames listed above:\n{errors_desc}\n"
                    ),
                },
            ],
        )
        gdscript = _extract_gdscript(retry_response["message"]["content"])

    (PROJECT_DIR / "project.godot").write_text(
        PROJECT_GODOT_TEMPLATE.format(title=design_doc["title"]), encoding="utf-8"
    )
    (PROJECT_DIR / "screenshot.gd").write_text(SCREENSHOT_GD, encoding="utf-8")
    (PROJECT_DIR / "sfx.gd").write_text(SFX_GD, encoding="utf-8")
    (PROJECT_DIR / "ambience.gd").write_text(AMBIENCE_GD, encoding="utf-8")
    (PROJECT_DIR / "Main.tscn").write_text(_build_main_tscn(bgm_filename), encoding="utf-8")
    (PROJECT_DIR / "Main.gd").write_text(gdscript, encoding="utf-8")

    action = "Fixed" if qa_errors else ("Tuned" if tune_notes else "Generated")
    print(f"[Coder] {action} Godot project ({template}, model={MODEL}) -> {PROJECT_DIR}")
    # tune_notes are consumed by this pass; clear them so a subsequent QA
    # retry takes the fix path against the already-tuned script.
    return {"godot_project_path": str(PROJECT_DIR), "tune_notes": None}
