"""Structural contracts enforced on generated level scripts."""


TEMPLATE_CONTRACTS = {
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
        (
            "the panic radius that keeps creatures still until the player is close",
            r"panic_radius",
        ),
        (
            "the settled flag that stops a creature fleeing once it reaches the goal",
            r"settled",
        ),
    ],
}

UNIVERSAL_CONTRACTS = [
    (
        "per-frame character animation via the Anim autoload - call "
        "Anim.walk(sprite, is_moving, direction.x) each frame for the player "
        "and anything that walks, or Anim.hover(sprite) for anything that "
        "floats, so the sprite is not a static image sliding around",
        r"Anim\.(walk|hover)\(",
    ),
]

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
    (
        "the script uses 'Sprite', which does not exist in Godot 4 - it was "
        "renamed Sprite2D (or Sprite3D in 3D). Replace every use, as a type "
        "hint, constructor, or 'is' check, with Sprite2D",
        r"\bSprite\b",
    ),
]
