"""Game Designer agent — turns a one-line prompt into a structured game design doc.

Two backends share the same schema and system prompt:
- "local" (default): a local model via Ollama's structured outputs. The
  design task is heavily structured by now - template menu with selection
  guidance, per-template lever lists, intensity rules, a strict JSON schema
  - which is exactly the shape of problem a mid-size local model handles,
  and it makes the whole pipeline runnable end to end with zero cloud cost.
- "claude": the Anthropic API - the premium option for when the key is
  funded. Select with SAGA_DESIGNER_BACKEND=claude.
"""

import json
import os

from saga.state import GraphState

CLAUDE_MODEL = "claude-sonnet-5"
LOCAL_MODEL = os.environ.get(
    "SAGA_DESIGNER_MODEL", "hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_S"
)

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
                    "outro_beat": {"type": "string"},
                    "intensity": {"type": "integer", "minimum": 1, "maximum": 10},
                    "pressure_notes": {"type": "string"},
                },
                "required": ["name", "description", "outro_beat", "intensity", "pressure_notes"],
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
    "Given a one-line game idea, design a small, complete multi-level 2D Godot "
    "game.\n\n"
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
    "Each template's difficulty levers, for your per-level fields - never cite "
    "a lever your template lacks: survive_hazards: hazard speed and count, "
    "lives, survival time. depletion: drain rate, refill rate, zone count and "
    "spacing, survival time. survive_and_deplete: all of those plus drain ramp "
    "and zone fuel. maze_chase: patroller speed and route coverage, pickup "
    "placement depth, lives. collect: pickup count and how far apart they sit. "
    "ordered_switches: sequence length and switch spacing. herd_to_goal: flee "
    "speed and goal-zone size. capture_zones: patroller speed, zone count and "
    "spread.\n\n"
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
    "Design 3-5 levels as REAL stages: visually distinct backgrounds, a "
    "narrative arc from first to last, and three authored fields per level "
    "beyond name and description:\n"
    "- intensity (1 to 10): the level's overall pressure. Non-decreasing "
    "across the sequence; open at 3 or 4 and make the final level 8 or "
    "higher. The build system anchors the mechanic's reference numbers at "
    "intensity 4 and scales pressure roughly 15% per point, so treat these "
    "as literal settings, not mood words.\n"
    "- pressure_notes: one sentence naming which of your template's levers "
    "(from the list above) rise THIS level. The FINAL level's pressure_notes "
    "must also name one structural climax, not just larger numbers: hazard "
    "templates stage a second wave or force a final crossing through the "
    "hazards' path; resource templates make the last stretch nearly "
    "refill-less - zones sparse, distant, or almost spent; maze_chase puts "
    "the last pickup deep in a dead-end the patroller's route covers; "
    "collect and ordered_switches place the final objectives at the map's "
    "far extremes so the closing route is the longest and most exposed; "
    "herd_to_goal shrinks the goal and quickens the creature. The climax "
    "should take away something earlier levels let the player rely on.\n"
    "- outro_beat: 1-2 sentences of story shown full-screen after the level "
    "is won, before the next loads. Write what JUST happened and what it "
    "cost or revealed - never a recap of the premise, never numbers or "
    "mechanics words. The first beat sets what is at stake ahead; a middle "
    "beat complicates things or takes something away; the final level's "
    "beat IS the ending - resolve what the hero wanted in the premise, in "
    "the same emotional register as audio_mood. The player reads these one "
    "at a time on an otherwise empty screen: make each one earn it.\n\n"
    "Hard constraints: playable entirely with HELD arrow-key movement - never "
    "require a discrete button press to win. All interactions are touch-based "
    "(moving into things). One key_item icon, one hero sprite, one background "
    "per level. Losing must freeze play and update the on-screen label - never "
    "remove the player from the scene. Keep each level's scope achievable for "
    "~100 lines of GDScript."
)


def _validate(doc: dict) -> list[str]:
    """Structural checks a local model can plausibly get wrong; returned as a
    problem list so a corrective retry can quote them verbatim."""
    problems = []
    for key in DESIGN_DOC_SCHEMA["required"]:
        if not doc.get(key):
            problems.append(f"missing or empty field {key!r}")
    if doc.get("mechanic_template") not in MECHANIC_TEMPLATES:
        problems.append(f"mechanic_template must be one of {MECHANIC_TEMPLATES}")
    key_item = doc.get("key_item") or {}
    if key_item.get("role") not in KEY_ITEM_ROLES:
        problems.append(f"key_item.role must be one of {KEY_ITEM_ROLES}")
    if not key_item.get("description"):
        problems.append("key_item.description is required")
    levels = doc.get("levels") or []
    if not 3 <= len(levels) <= 5:
        problems.append(f"need 3-5 levels, got {len(levels)}")
    for i, lvl in enumerate(levels):
        for field in ("name", "description", "outro_beat", "pressure_notes"):
            if not lvl.get(field):
                problems.append(f"levels[{i}].{field} is required")
        if not isinstance(lvl.get("intensity"), int):
            problems.append(f"levels[{i}].intensity must be an integer 1-10")
    return problems


def _normalize(doc: dict) -> dict:
    """Safe harness-side fixups: clamp intensity into 1-10 and enforce the
    non-decreasing rule via a running max (a curve that dips is the exact
    noise this field exists to prevent)."""
    prev = 0
    for lvl in doc.get("levels") or []:
        value = max(1, min(10, int(lvl.get("intensity") or 1)))
        if value < prev:
            print(f"[Game Designer] intensity dip ({value} after {prev}) raised to {prev}")
            value = prev
        lvl["intensity"] = value
        prev = value
    return doc


def _design_claude(user_prompt: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": DESIGN_DOC_SCHEMA},
        },
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def _design_local(user_prompt: str) -> dict:
    import ollama

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    response = ollama.chat(model=LOCAL_MODEL, messages=messages, format=DESIGN_DOC_SCHEMA)
    doc = json.loads(response["message"]["content"])

    problems = _validate(doc)
    if problems:
        print(f"[Game Designer] Local doc invalid, one corrective retry: {problems}")
        messages.append({"role": "assistant", "content": json.dumps(doc)})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Your design doc has these problems - return the complete "
                    "corrected doc: " + "; ".join(problems)
                ),
            }
        )
        response = ollama.chat(model=LOCAL_MODEL, messages=messages, format=DESIGN_DOC_SCHEMA)
        doc = json.loads(response["message"]["content"])
        problems = _validate(doc)
        if problems:
            raise ValueError(f"Local designer produced an invalid design doc: {problems}")
    return doc


def game_designer(state: GraphState) -> GraphState:
    backend = os.environ.get("SAGA_DESIGNER_BACKEND", "local")
    if backend == "claude":
        design_doc = _design_claude(state["user_prompt"])
    else:
        design_doc = _design_local(state["user_prompt"])
    design_doc = _normalize(design_doc)

    print(
        f"[Game Designer/{backend}] Produced design doc: {design_doc['title']!r} "
        f"(template: {design_doc['mechanic_template']}, "
        f"{len(design_doc['levels'])} levels, "
        f"intensity {[lvl['intensity'] for lvl in design_doc['levels']]})"
    )
    return {"user_prompt": state["user_prompt"], "design_doc": design_doc}
