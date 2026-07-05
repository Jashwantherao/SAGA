"""Coder agent - generates a minimal Godot 4 project via a local Ollama model.

The harness writes the deterministic boilerplate itself (project.godot, a bare
Main.tscn scene) since hand-authoring correct .tscn resource syntax is a poor
fit for an LLM with no QA loop yet to catch mistakes. The model's only job is
to write Main.gd - the actual gameplay logic - given the design doc and the
list of already-generated asset filenames it can load.
"""

import re
import shutil
from pathlib import Path

import ollama

from saga.state import GraphState

MODEL = "qwen2.5-coder:14b"
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output" / "godot_project"

PROJECT_GODOT_TEMPLATE = """config_version=5

[application]
config/name="{title}"
run/main_scene="res://Main.tscn"
config/features=PackedStringArray("4.7")

[display]
window/size/viewport_width=1024
window/size/viewport_height=576
window/stretch/mode="canvas_items"

[rendering]
renderer/rendering_method="gl_compatibility"
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

SYSTEM_PROMPT = (
    "You are the Coder agent in an automated game studio. You write GDScript "
    "(Godot 4) attached to a single Node2D root node. The game window is a "
    "fixed 1024x576 viewport - keep all world positions (player, pickups) "
    "within that range. Image asset filenames tell you their role: a file "
    "starting with 'level_' is a level background, sized exactly 1024x576 to "
    "match the viewport - load it into a Sprite2D, set `centered = false` "
    "and `position = Vector2.ZERO` so it fills the screen edge-to-edge from "
    "the top-left corner (Sprite2D is centered by default, which would only "
    "show a quarter of it). A file starting with 'collectible' is the "
    "pickup icon, sized 128x128 - small enough to use at its native size "
    "with no extra scaling. Any other image asset is the hero/player "
    "sprite. Build a complete small game, not just movement: a controllable "
    "sprite, one or more collectible pickups placed as Area2D nodes with a "
    "CollisionShape2D child, collected via the area_entered signal (make the "
    "player an Area2D too, so two Area2Ds overlapping is what fires the "
    "signal - do not rely on physics bodies). Track a score, show it in a "
    "Label on a CanvasLayer, and check a win condition once every pickup is "
    "collected (e.g. update the label to announce a win). Use the level "
    "descriptions for pacing/flavor if helpful. Load image assets with "
    "load(\"res://assets/<filename>\") and Texture2D/Sprite2D nodes created "
    "in code. Do not attempt to load or play audio yourself - background "
    "music is handled separately. No custom InputMap actions are defined in "
    "this project, so only use Godot's built-in default input actions "
    "(ui_up, ui_down, ui_left, ui_right, ui_accept, ui_select, ui_cancel) - "
    "never invent a new action name. Respond with ONLY a single ```gdscript "
    "fenced code block, no explanation before or after it."
)

EXAMPLE_USER_PROMPT = (
    "Title: Coin Rush\n"
    "Genre: arcade platformer\n"
    "Core mechanics: run and jump, collect coins, win when all coins are collected\n"
    "Story premise: A courier sprints across rooftops collecting scattered coins.\n"
    "Levels:\n"
    "- Rooftop Dash: a sunlit row of rooftops with scattered coins\n"
    "Available image assets: courier.png, collectible.png, level_0_bg.png\n"
)

# A worked example demonstrating the patterns the model gets wrong most often
# without one: creating nodes dynamically (never $NodeName / get_node() on a
# node that isn't actually in Main.tscn, since the scene is bare), only using
# Godot's built-in input actions (no custom InputMap exists), collecting
# pickups via Area2D-to-Area2D overlap (both player and pickup are Area2D
# with a CollisionShape2D - avoids physics-body/collision-layer setup), a
# real score + win condition rather than an uncalled stub function, and
# filling the fixed 1024x576 viewport with the background instead of leaving
# it centered at the origin (which only shows one quarter of it).
EXAMPLE_ASSISTANT_RESPONSE = """```gdscript
extends Node2D

@export var speed = 220.0
var score = 0
var total_coins = 0
var player: Area2D
var score_label: Label

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
    player_sprite.texture = load("res://assets/courier.png")
    player.add_child(player_sprite)
    var player_shape = CollisionShape2D.new()
    var player_circle = CircleShape2D.new()
    player_circle.radius = 20.0
    player_shape.shape = player_circle
    player.add_child(player_shape)
    add_child(player)

    var coin_positions = [Vector2(250, 300), Vector2(400, 200), Vector2(550, 350)]
    total_coins = coin_positions.size()
    for pos in coin_positions:
        _spawn_coin(pos)

    var canvas = CanvasLayer.new()
    add_child(canvas)
    score_label = Label.new()
    score_label.position = Vector2(20, 20)
    score_label.text = "Coins: 0 / %d" % total_coins
    canvas.add_child(score_label)

func _spawn_coin(pos: Vector2):
    var coin = Area2D.new()
    coin.position = pos
    var sprite = Sprite2D.new()
    sprite.texture = load("res://assets/collectible.png")
    coin.add_child(sprite)
    var shape = CollisionShape2D.new()
    var circle = CircleShape2D.new()
    circle.radius = 16.0
    shape.shape = circle
    coin.add_child(shape)
    coin.area_entered.connect(_on_coin_area_entered.bind(coin))
    add_child(coin)

func _on_coin_area_entered(area: Area2D, coin: Area2D):
    if area != player:
        return
    coin.queue_free()
    score += 1
    score_label.text = "Coins: %d / %d" % [score, total_coins]
    if score >= total_coins:
        score_label.text += "  -  You win!"

func _process(delta):
    var velocity = Vector2.ZERO
    if Input.is_action_pressed("ui_right"):
        velocity.x += 1.0
    if Input.is_action_pressed("ui_left"):
        velocity.x -= 1.0
    if Input.is_action_just_pressed("ui_accept"):
        velocity.y -= 1.0

    player.position += velocity.normalized() * speed * delta
```"""

FIX_SYSTEM_PROMPT = (
    "You are the Coder agent in an automated game studio. Godot's QA check just "
    "ran your previous GDScript and found errors. Fix the specific errors "
    "listed - do not rewrite the script from scratch or change unrelated "
    "behavior. Preserve the existing collectible/score/win-condition logic "
    "as-is unless it is itself the cause of an error. No custom InputMap "
    "actions are defined in this project, so only use Godot's built-in "
    "default input actions (ui_up, ui_down, ui_left, ui_right, ui_accept, "
    "ui_select, ui_cancel) - never invent a new action name. Respond with "
    "ONLY a single ```gdscript fenced code block containing the complete "
    "corrected script, no explanation before or after it."
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

    qa_errors = state.get("qa_errors") or []

    if qa_errors:
        previous_script = (PROJECT_DIR / "Main.gd").read_text(encoding="utf-8")
        errors_desc = "\n".join(f"- {e}" for e in qa_errors)
        user_prompt = (
            f"Previous Main.gd:\n```gdscript\n{previous_script}\n```\n\n"
            f"Godot reported these errors:\n{errors_desc}\n"
        )
        system_prompt = FIX_SYSTEM_PROMPT
    else:
        levels_desc = "\n".join(f"- {lvl['name']}: {lvl['description']}" for lvl in design_doc["levels"])
        user_prompt = (
            f"Title: {design_doc['title']}\n"
            f"Genre: {design_doc['genre']}\n"
            f"Core mechanics: {', '.join(design_doc['core_mechanics'])}\n"
            f"Story premise: {design_doc['story_premise']}\n"
            f"Levels:\n{levels_desc}\n"
            f"Available image assets: {', '.join(asset_filenames)}\n"
        )
        system_prompt = SYSTEM_PROMPT

    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": EXAMPLE_USER_PROMPT},
            {"role": "assistant", "content": EXAMPLE_ASSISTANT_RESPONSE},
            {"role": "user", "content": user_prompt},
        ],
    )
    gdscript = _extract_gdscript(response["message"]["content"])

    (PROJECT_DIR / "project.godot").write_text(
        PROJECT_GODOT_TEMPLATE.format(title=design_doc["title"]), encoding="utf-8"
    )
    (PROJECT_DIR / "Main.tscn").write_text(_build_main_tscn(bgm_filename), encoding="utf-8")
    (PROJECT_DIR / "Main.gd").write_text(gdscript, encoding="utf-8")

    action = "Fixed" if qa_errors else "Generated"
    print(f"[Coder] {action} Godot project -> {PROJECT_DIR}")
    return {"godot_project_path": str(PROJECT_DIR)}
