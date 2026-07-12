"""Game Designer agent — turns a one-line prompt into a structured game design doc."""

import json

import anthropic

from saga.state import GraphState

MODEL = "claude-sonnet-5"

MECHANIC_TEMPLATES = [
    "collect",
    "survive_hazards",
    "ordered_switches",
    "depletion",
    "herd_to_goal",
    "capture_zones",
    "survive_and_deplete",
    "maze_chase",
]

KEY_ITEM_ROLES = ["pickup", "hazard", "switch", "creature", "zone_marker"]

DESIGN_DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "genre": {"type": "string"},
        "mechanic_template": {"type": "string", "enum": MECHANIC_TEMPLATES},
        "hero_description": {"type": "string"},
        "core_mechanics": {"type": "array", "items": {"type": "string"}},
        "story_premise": {"type": "string"},
        "theme_thread": {"type": "string"},
        "win_condition": {"type": "string"},
        "lose_condition": {"type": "string"},
        "levels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
        "art_style": {"type": "string"},
        "audio_mood": {"type": "string"},
        "key_item": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "role": {"type": "string", "enum": KEY_ITEM_ROLES},
            },
            "required": ["description", "role"],
            "additionalProperties": False,
        },
    },
    "required": [
        "title",
        "genre",
        "mechanic_template",
        "hero_description",
        "core_mechanics",
        "story_premise",
        "theme_thread",
        "win_condition",
        "lose_condition",
        "levels",
        "art_style",
        "audio_mood",
        "key_item",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are the Game Designer agent in an automated indie-game studio pipeline. "
    "Given a one-line game idea, design a small, complete 2D Godot game.\n\n"
    "First, choose the mechanic_template whose fantasy best matches the idea - do "
    "NOT default to 'collect': survive_and_deplete (a draining resource, refill "
    "zones with finite fuel, AND roaming hazards - the richest option; prefer it "
    "whenever the fantasy supports both a fading resource and an active threat), "
    "maze_chase (navigate walled corridors collecting items while dodging a "
    "patroller - prefer it when the fantasy is about tight spaces, stealth, or "
    "labyrinths), survive_hazards (outlast moving dangers), ordered_switches "
    "(activate triggers in sequence), depletion (a resource drains unless "
    "replenished), herd_to_goal (corner a fleeing creature), capture_zones "
    "(claim regions while a patroller un-claims them), or collect (gather "
    "items) only when gathering genuinely is the idea's core fantasy.\n\n"
    "The mechanic must EMBODY the premise, not decorate it: state in theme_thread "
    "how the mechanic is the story ('the fading warmth IS the depleting "
    "resource'). Choose art_style and audio_mood to match the mechanic's "
    "emotional register - tense and driving for survival, contemplative for "
    "puzzles - not generic genre descriptors. Give exactly one win_condition and "
    "one lose_condition (write 'none' if losing is impossible). The key_item is "
    "the one generated icon asset; describe it concretely and visually, and give "
    "it the role the mechanic needs (pickup, hazard, switch, creature, or "
    "zone_marker). The hero_description drives the hero sprite generation: make "
    "it concrete, characterful, and HIGH CONTRAST against the level's palette - "
    "a dark hero on a dark background disappears.\n\n"
    "Hard constraints: single-scene game, playable entirely with HELD arrow-key "
    "movement - never require a discrete button press to win. All interactions "
    "are touch-based (moving into things). One key_item icon, one hero sprite, "
    "one background per level (3-5 levels as pacing variations, not new scenes). "
    "Losing must freeze play and update the on-screen label - never remove the "
    "player from the scene. Keep scope achievable for ~100 lines of GDScript."
)


def game_designer(state: GraphState) -> GraphState:
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": DESIGN_DOC_SCHEMA},
        },
        messages=[{"role": "user", "content": state["user_prompt"]}],
    )

    text = next(block.text for block in response.content if block.type == "text")
    design_doc = json.loads(text)

    print(
        f"[Game Designer] Produced design doc: {design_doc['title']!r} "
        f"(template: {design_doc['mechanic_template']})"
    )
    return {"user_prompt": state["user_prompt"], "design_doc": design_doc}
