"""Structural contracts enforced on generated level scripts."""

import re


TEMPLATE_CONTRACTS = {
    "run_and_gun": [
        (
            "the versioned run-and-gun base level",
            r'extends\s+"res://archetypes/run_and_gun/run_and_gun_level\.gd"',
        ),
        ("the compact level-definition adapter", r"func\s+level_definition\s*\("),
        ("the archetype version pin", r'\\?"pack_version\\?"\s*:\s*4'),
        ("the validated encounter plan", r'\\?"encounter_plan\\?"\s*:'),
        ("the campaign progression contract", r'\\?"progression\\?"\s*:'),
        ("authored enemy pressure", r'\\?"enemy_count\\?"\s*:'),
        ("authored boss durability", r'\\?"boss_health\\?"\s*:'),
    ],
    "capture_zones": [
        ("the stable player handle required by objective QA", r"var\s+player(?:\s*:\s*Area2D)?\b"),
        ("the stable zone array required by objective QA", r"var\s+zones(?:\s*:\s*Array(?:\[Area2D\])?)?\b"),
        ("the stable patroller handle required by objective QA", r"var\s+patroller(?:\s*:\s*Area2D)?\b"),
        ("the per-zone capture progress required by objective QA", r"var\s+zone_progress\b"),
        ("the per-zone ownership state required by objective QA", r"var\s+zone_owner\b"),
        ("the player overlap state required by objective QA", r"var\s+player_in_zones\b"),
        ("the patroller overlap state required by objective QA", r"var\s+enemy_in_zones\b"),
        ("the capture threshold required by objective QA", r"var\s+capture_required\b"),
        ("the public capture radius required by objective QA", r"var\s+capture_radius\b"),
        ("the player capture rate required by objective QA", r"var\s+capture_rate\b"),
        ("the patroller decay rate required by objective QA", r"var\s+decay_rate\b"),
        ("the public patroller speed required by objective QA", r"var\s+patroller_speed\b"),
        ("the title/playing/won state required by objective QA", r"var\s+state\b"),
    ],
    "survive_and_deplete": [
        ("the stable player handle required by objective QA", r"var\s+player(?:\s*:\s*Area2D)?\b"),
        ("the stable refill-zone array required by objective QA", r"var\s+zones(?:\s*:\s*Array(?:\[Area2D\])?)?\b"),
        ("the stable hazard array required by objective QA", r"var\s+hazards(?:\s*:\s*Array(?:\[Area2D\])?)?\b"),
        ("the current zone-fuel array required by objective QA", r"var\s+zone_fuel\b"),
        ("the refill-overlap array required by objective QA", r"var\s+inside_zones\b"),
        ("the resource maximum required by objective QA", r"var\s+resource_max\b"),
        ("the current resource required by objective QA", r"var\s+resource\b"),
        ("the drain rate and ramp required by objective QA", r"var\s+drain_ramp\b"),
        ("the refill and fuel-burn rates required by objective QA", r"var\s+fuel_burn\b"),
        ("the hazard hit cost required by objective QA", r"var\s+hazard_hit_cost\b"),
        ("the hit cooldown required by objective QA", r"var\s+hit_cooldown\b"),
        ("the survival timer required by objective QA", r"var\s+time_left\b"),
        ("the title/playing/won/over state required by objective QA", r"var\s+state\b"),
    ],
    "depletion": [
        (
            "the stable player handle required by objective QA (`var player: Area2D`)",
            r"var\s+player(?:\s*:\s*Area2D)?\b",
        ),
        (
            "the stable refill-zone array required by objective QA (`var refill_zones`)",
            r"var\s+refill_zones(?:\s*:\s*Array(?:\[Area2D\])?)?\b",
        ),
        ("the resource maximum required by objective QA", r"var\s+resource_max\b"),
        ("the current resource required by objective QA", r"var\s+resource\b"),
        ("the drain rate required by objective QA", r"var\s+drain_rate\b"),
        ("the refill rate required by objective QA", r"var\s+refill_rate\b"),
        ("the refill overlap counter required by objective QA", r"var\s+zones_inside\b"),
        ("the survival duration required by objective QA", r"var\s+survival_time\b"),
        ("the current survival timer required by objective QA", r"var\s+time_left\b"),
        (
            "the title/playing/won/over state required by objective QA",
            r"var\s+state\b",
        ),
    ],
    "survive_hazards": [
        (
            "the stable player handle required by objective QA (`var player: Area2D`)",
            r"var\s+player(?:\s*:\s*Area2D)?\b",
        ),
        (
            "the stable hazard array required by objective QA (`var hazards`)",
            r"var\s+hazards(?:\s*:\s*Array(?:\[Area2D\])?)?\b",
        ),
        ("the starting life count required by objective QA", r"var\s+starting_lives\b"),
        ("the current lives counter required by objective QA", r"var\s+lives\b"),
        ("the survival duration required by objective QA", r"var\s+survival_time\b"),
        ("the current survival timer required by objective QA", r"var\s+time_left\b"),
        (
            "the public hit cooldown required by objective QA (`var hit_cooldown`)",
            r"var\s+hit_cooldown\b",
        ),
        (
            "the title/playing/won/over state required by objective QA",
            r"var\s+state\b",
        ),
    ],
    "ordered_switches": [
        (
            "the stable player handle required by objective QA (`var player: Area2D`)",
            r"var\s+player(?:\s*:\s*Area2D)?\b",
        ),
        (
            "the stable switch array required by objective QA (`var switches`)",
            r"var\s+switches(?:\s*:\s*Array(?:\[Area2D\])?)?\b",
        ),
        (
            "the ordered switch-index array required by objective QA (`var switch_order`)",
            r"var\s+switch_order(?:\s*:\s*Array(?:\[int\])?)?\b",
        ),
        (
            "the public progress counter required by objective QA (`var progress`)",
            r"var\s+progress(?:\s*:\s*int)?\b",
        ),
        (
            "the wrong-order reset counter required by objective QA (`var reset_count`)",
            r"var\s+reset_count(?:\s*:\s*int)?\b",
        ),
        (
            "the title/playing/won/over state required by objective QA",
            r"var\s+state\b",
        ),
    ],
    "dot_maze": [
        ("the Rect2 wall array and axis-separated wall collision", r"Rect2\("),
        (
            "the stable player handle required by objective QA (`var player: Area2D`)",
            r"var\s+player(?:\s*:\s*Area2D)?\b",
        ),
        (
            "the stable wall array required by objective QA (`walls` or `wall_rects`)",
            r"var\s+(?:walls|wall_rects)\b",
        ),
        (
            "the total_dots counter required by objective QA",
            r"var\s+total_dots\b",
        ),
        (
            "the title/playing/won/over state required by objective QA",
            r"var\s+state\b",
        ),
        (
            "ghost movement (patrol via move_toward plus a hunter moving toward the player)",
            r"move_toward",
        ),
        (
            "the ghost-touch handler connected via player.area_entered",
            r"player\.area_entered\.connect",
        ),
    ],
    "maze_chase": [
        ("the Rect2 wall array and axis-separated wall collision", r"Rect2\("),
        (
            "the stable player handle required by objective QA (`var player: Area2D`)",
            r"var\s+player(?:\s*:\s*Area2D)?\b",
        ),
        (
            "the stable wall array required by objective QA (`walls`, `wall_rects`, or `active_wall_rects`)",
            r"var\s+(?:walls|wall_rects|active_wall_rects)\b",
        ),
        (
            "the pickup total required by objective QA (`total_gems` or `total_pickups`)",
            r"var\s+(?:total_gems|total_pickups)\b",
        ),
        (
            "the title/playing/won/over state required by objective QA",
            r"var\s+state\b",
        ),
        (
            "the stable patroller handle required by objective QA (`var patroller: Area2D`)",
            r"var\s+patroller(?:\s*:\s*Area2D)?\b",
        ),
        (
            "the patroller-touch handler connected via player.area_entered",
            r"player\.area_entered\.connect",
        ),
    ],
    "herd_to_goal": [
        ("the stable player handle required by objective QA", r"var\s+player(?:\s*:\s*Area2D)?\b"),
        ("the stable creature array required by objective QA", r"var\s+creatures(?:\s*:\s*Array(?:\[Area2D\])?)?\b"),
        ("the permanent settled-state array required by objective QA", r"var\s+creature_settled\b"),
        ("the stable goal-zone handle required by objective QA", r"var\s+goal(?:\s*:\s*Area2D)?\b"),
        ("the panic radius that keeps distant creatures still", r"var\s+panic_radius\b"),
        ("the public goal radius required by objective QA", r"var\s+goal_radius\b"),
        ("the player speed required for herding balance", r"var\s+speed\b"),
        ("the creature flee speed required for objective QA", r"var\s+flee_speed\b"),
        ("the title/playing/won state required by objective QA", r"var\s+state\b"),
    ],
}

UNIVERSAL_CONTRACTS = [
    (
        "hero idle/walk pose registration via Anim.set_poses",
        r"Anim\.set_poses\(",
    ),
    (
        "per-frame character animation via the Anim autoload - call "
        "Anim.walk(sprite, is_moving, direction.x) each frame for the player "
        "and anything that walks, or Anim.hover(sprite) for anything that "
        "floats, so the sprite is not a static image sliding around",
        r"Anim\.(walk|hover)\(",
    ),
]


def _call_arguments(script: str, call_name: str) -> list[list[str]]:
    """Return top-level argument lists for calls, tolerating nested expressions."""
    calls: list[list[str]] = []
    pattern = re.compile(rf"{re.escape(call_name)}\s*\(")
    for match in pattern.finditer(script):
        start = match.end()
        depth = 1
        quote = ""
        escaped = False
        arguments: list[str] = []
        argument_start = start
        for index in range(start, len(script)):
            character = script[index]
            if quote:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    quote = ""
                continue
            if character in {'"', "'"}:
                quote = character
            elif character in "([{":
                depth += 1
            elif character in ")]}":
                depth -= 1
                if depth == 0:
                    arguments.append(script[argument_start:index].strip())
                    calls.append(arguments if arguments != [""] else [])
                    break
            elif character == "," and depth == 1:
                arguments.append(script[argument_start:index].strip())
                argument_start = index + 1
    return calls


def animation_call_violations(script: str) -> list[str]:
    """Catch Anim calls that exist textually but cannot match the harness API."""
    violations = []
    for arguments in _call_arguments(script, "Anim.walk"):
        if len(arguments) != 3:
            violations.append(
                "Anim.walk must receive exactly three arguments: "
                "Anim.walk(sprite, is_moving_bool, direction_x_float)"
            )
        elif arguments[1].strip().lower() in {
            "direction", "input_dir", "input_vector", "motion",
            "move_dir", "move_vector", "velocity",
        }:
            violations.append(
                "Anim.walk argument 2 must be a bool, not a Vector2; use "
                "velocity.length() > 0.0 (or equivalent)"
            )
    return list(dict.fromkeys(violations))

def _numeric_var(gdscript: str, name: str) -> float | None:
    match = re.search(
        rf"(?:@export\s+)?var\s+{name}\s*(?::\s*float\s*)?[:=]?=\s*(-?\d+(?:\.\d+)?)",
        gdscript,
    )
    return float(match.group(1)) if match else None


# The objective probes refuse to solve a level whose numbers make the mechanic
# impossible, but they report only a reason code - a real run spent all six
# retries on "invalid_herd_balance" without ever being told which numbers were
# wrong. Checking the same relationships statically turns that into one
# actionable message before a Godot process is spawned.
HERD_FLEE_SPEED_RATIO = 0.6


def balance_violations(gdscript: str, template: str) -> list[str]:
    """Numeric preconditions the deterministic objective probe will enforce."""
    violations = []
    if template == "herd_to_goal":
        speed = _numeric_var(gdscript, "speed")
        flee_speed = _numeric_var(gdscript, "flee_speed")
        if speed and flee_speed and flee_speed >= speed * HERD_FLEE_SPEED_RATIO:
            violations.append(
                f"flee_speed ({flee_speed:g}) must stay below "
                f"{HERD_FLEE_SPEED_RATIO:g} x speed ({speed:g}), i.e. under "
                f"{speed * HERD_FLEE_SPEED_RATIO:g} - creatures that flee nearly as "
                "fast as the player can never be herded, and objective QA rejects "
                "the level as invalid_herd_balance"
            )
    return violations


FORBIDDEN_PATTERNS = [
    (
        "the script declares a local variable that shadows a harness autoload "
        "(Game, Sfx, Music, Ambience). These are engine globals - call them "
        "directly as Game.level_complete() and Sfx.play(...) with no null "
        "checks and no local declaration, or they silently do nothing",
        r"var\s+(?:Game|Sfx|Music|Ambience|Screenshot|Interlude|Victory)\b",
    ),
    (
        "Game.level_complete() is wrapped in a null check, which means it may "
        "never run and the game can never advance a level. Call it directly",
        r"if\s+Game\s*!=\s*null",
    ),
]

# Godot 3 names a model reaches for by reflex, especially a small local one
# falling back on training data that predates Godot 4. The engine reports them
# only as "Could not find base class X" or a failed identifier lookup at load
# time - a full Coder+QA retry spent to learn something a regex knows, and a
# message that never names the replacement, so the model can spiral on it. A
# real run burned all six retries on `extends KinematicBody2D`.
#
# Every pattern must leave the Godot 4 spelling alone: \b between "Sprite" and
# "2D" does not exist, so \bSprite\b cannot match inside Sprite2D. The
# false-positive test asserts that against the worked examples.
GODOT3_RENAMES = [
    (r"\bKinematicBody2D\b", "KinematicBody2D", "CharacterBody2D"),
    (r"\bKinematicBody\b", "KinematicBody", "CharacterBody3D"),
    (r"\bSprite\b", "Sprite", "Sprite2D"),
    (r"\bAnimatedSprite\b", "AnimatedSprite", "AnimatedSprite2D"),
    (r"\bSpatial\b", "Spatial", "Node3D"),
    (r"\bYSort\b", "YSort", "a Node2D with y_sort_enabled = true"),
    (r"\bParticles2D\b", "Particles2D", "GPUParticles2D"),
    (r"\bCollisionShape\b", "CollisionShape", "CollisionShape2D"),
    (
        r"\bPool(?:String|Int|Real|Byte|Vector2|Vector3|Color)Array\b",
        "a PoolXArray type",
        "the matching PackedXArray (PackedStringArray, PackedInt32Array, ...)",
    ),
    (r"(?<![@\w])export\s+var\b", "bare 'export var'", "@export var"),
    (r"(?<![@\w])onready\s+var\b", "bare 'onready var'", "@onready var"),
    (r"\byield\s*\(", "yield(...)", "await"),
    (r"\.instance\(\)", ".instance()", ".instantiate()"),
    (r"\brand_range\b", "rand_range", "randf_range"),
    (r"\.empty\(\)", ".empty()", ".is_empty()"),
    (r"\bOS\s*\.\s*get_ticks_msec\b", "OS.get_ticks_msec", "Time.get_ticks_msec"),
]

FORBIDDEN_PATTERNS += [
    (
        f"the script uses {old}, which does not exist in Godot 4 - use {new} "
        "instead, everywhere it appears (extends clause, type hint, "
        "constructor, or 'is' check)",
        pattern,
    )
    for pattern, old, new in GODOT3_RENAMES
]

FORBIDDEN_PATTERNS += [
    (
        "move_and_slide() takes no arguments in Godot 4 - assign the velocity "
        "property first, then call move_and_slide() with an empty argument list",
        r"move_and_slide\s*\(\s*[^)\s]",
    ),
    (
        "the script uses Godot 3's connect(\"signal\", target, \"method\") "
        "signature, which no longer exists - connect a Callable instead, as "
        "signal_name.connect(_on_signal)",
        r"\.connect\(\s*\"",
    ),
]
