"""Game Designer agent — turns a one-line prompt into a structured game design doc.

Three backends share the same schema and system prompt, selected with
SAGA_DESIGNER_BACKEND:
- "local" (default): a local model via Ollama's structured outputs. The
  design task is heavily structured by now - template menu with selection
  guidance, per-template lever lists, intensity rules, a strict JSON schema
  - which is exactly the shape of problem a mid-size local model handles,
  and it makes the whole pipeline runnable end to end with zero cloud cost.
- "deepseek": a hosted OpenAI-compatible model (see saga.llm). Fractions of
  a cent per game, and it sidesteps the local model's habit of truncating
  long design docs.
- "claude": the Anthropic API - the premium option.

The hosted path gets JSON mode rather than schema-constrained decoding, so
the schema is spelled out in the prompt and _validate() enforces it after
the fact - which is what that validator was built for.
"""

import copy
import json
import re

from saga.config import settings
from saga.state import GraphState

CLAUDE_MODEL = "claude-sonnet-5"
LOCAL_MODEL = settings.designer_model
REMOTE_MODEL = settings.designer_remote_model

MECHANIC_TEMPLATES = [
    "collect",
    "survive_hazards",
    "ordered_switches",
    "depletion",
    "herd_to_goal",
    "capture_zones",
    "survive_and_deplete",
    "maze_chase",
    "dot_maze",
    "run_and_gun",
    "action_rpg",
]

KEY_ITEM_ROLES = ["pickup", "hazard", "switch", "creature", "zone_marker"]

# Every extra sprite is another image generation, so the count is capped to
# keep the art phase bounded. Four covers the usual shortfall - a platform, an
# enemy, a wall, a goal - without doubling the run time.
MAX_EXTRA_SPRITES = 4

# The name becomes a filename prefix, so it has to survive a round trip through
# the filesystem and the Coder's asset list.
EXTRA_SPRITE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")

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
        "extra_sprites": {
            "type": "array",
            "maxItems": MAX_EXTRA_SPRITES,
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
        "extra_sprites",
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
    "dot_maze (eat every dot in a dense maze while ghosts patrol and one hunts "
    "you, with rare power pickups that briefly turn the tables - prefer it for "
    "classic chase-and-chomp arcade fantasies), run_and_gun (a side-view action "
    "game built around jumping, three collectible weapons, mixed-role combat waves, checkpoints, persistent between-level upgrades and a "
    "multi-phase boss - prefer it for commando, blaster, siege or action-platform "
    "fantasies), action_rpg (a top-down exploration and melee-combat game with "
    "inventory, NPC dialogue, a spark-funded quest, persistent rooms, checkpoint "
    "save/load and a two-phase boss - prefer it for quests, dungeons, villages, "
    "loot, character growth or role-playing fantasies), maze_chase (navigate walled "
    "corridors collecting items while dodging a "
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
    "placement depth, lives. dot_maze: ghost speeds (patrollers and hunter), "
    "power-pickup duration, dot count, lives. run_and_gun: threat budget, enemy "
    "role mix, weapon-cache placement, player health, checkpoint spacing, upgrade rewards and boss phases. "
    "action_rpg: enemy health and pursuit, spark placement, quest cost, room order, "
    "checkpoint spacing and boss attack cadence. "
    "collect: pickup count and how "
    "far apart they sit. "
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
    "herd_to_goal shrinks the goal and quickens the creature; run_and_gun "
    "introduces the boss arena after the last checkpoint and escalates its phases; "
    "action_rpg seals the final room behind the completed quest and escalates the "
    "forge boss into its second phase. The climax "
    "should take away something earlier levels let the player rely on.\n"
    "- outro_beat: 1-2 sentences of story shown full-screen after the level "
    "is won, before the next loads. Write what JUST happened and what it "
    "cost or revealed - never a recap of the premise, never numbers or "
    "mechanics words. The first beat sets what is at stake ahead; a middle "
    "beat complicates things or takes something away; the final level's "
    "beat IS the ending - resolve what the hero wanted in the premise, in "
    "the same emotional register as audio_mood. The player reads these one "
    "at a time on an otherwise empty screen: make each one earn it.\n\n"
    "Hard constraints: every classic mechanic template is playable entirely with "
    "HELD arrow-key movement and touch interactions. Packed action templates are explicit "
    "exceptions: run_and_gun uses left/right movement, up to jump, ui_accept to fire, "
    "and Tab to cycle weapons; action_rpg uses arrows to move, Z for melee, X for "
    "interaction/dialogue, C for inventory, and Shift for the quest-unlocked dash. "
    "Losing must freeze play and update the on-screen "
    "label - never remove the player from the scene. Keep each level's scope "
    "achievable for a compact game-specific adapter; reusable archetype code owns "
    "movement, weapon patterns, role-specific AI, combat waves, checkpoints and bosses. "
    "For run_and_gun, use extra_sprites for visually distinct scout/bruiser/flyer "
    "enemies and the boss whenever the four-slot art budget allows. For action_rpg, "
    "prioritize the stalker enemy, quest NPC, forge boss and one gear pickup.\n\n"
    "Art the game needs: a hero sprite and one background per level are always "
    f"generated, plus the key_item icon. Use extra_sprites to ask for up to "
    f"{MAX_EXTRA_SPRITES} MORE things this specific game needs drawn - the "
    "enemy that chases, the platform that is stood on, the wall, the door, the "
    "goal. Anything you do not ask for does not exist, and the Coder will have "
    "to draw it as a plain coloured rectangle, which looks like missing art. "
    "Name each one lowercase with underscores after what it IS (wall, "
    "patrol_drone, exit_door) and describe it as concretely as the hero. Ask "
    "only for things that appear on screen as their own object; do not "
    "re-request the hero, the key_item, or a background."
)


def _level_system_prompt(level_count: int | None) -> str:
    if level_count is None:
        return SYSTEM_PROMPT
    return (
        SYSTEM_PROMPT
        + f"\n\nRUN OVERRIDE: Design exactly {level_count} level"
        + ("" if level_count == 1 else "s")
        + ". This exact count overrides the normal 3-5 level instruction. "
        "For a one-level game, make that level a complete compact arc with a "
        "clear setup, climax, and resolved ending; use intensity 4-6."
    )


def _validate(doc: dict, level_count: int | None = None) -> list[str]:
    """Structural checks a local model can plausibly get wrong; returned as a
    problem list so a corrective retry can quote them verbatim."""
    problems = []
    for key in DESIGN_DOC_SCHEMA["required"]:
        # extra_sprites is legitimately empty for a game that needs no extra
        # art, so absence is checked separately from emptiness.
        if key == "extra_sprites":
            if not isinstance(doc.get(key), list):
                problems.append("extra_sprites must be a list (use [] if none are needed)")
            continue
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
    if level_count is not None and len(levels) != level_count:
        unit = "level" if level_count == 1 else "levels"
        problems.append(f"need exactly {level_count} {unit}, got {len(levels)}")
    elif level_count is None and not 3 <= len(levels) <= 5:
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

    # Sprite names become filename prefixes, so repair what is repairable
    # rather than rejecting a good doc over "Patrol Drone" vs "patrol_drone".
    # Reserved prefixes would collide with the hero/key_item/background naming
    # the Coder keys its roles off, and duplicates would overwrite each other.
    # The cap applies to sprites that survive filtering, so junk entries cost
    # the game art it could otherwise have had.
    cleaned, seen = [], set()
    for sprite in doc.get("extra_sprites") or []:
        if len(cleaned) >= MAX_EXTRA_SPRITES:
            break
        if not isinstance(sprite, dict) or not sprite.get("description"):
            continue
        raw = str(sprite.get("name", "")).strip().lower().replace(" ", "_")
        name = re.sub(r"[^a-z0-9_]", "", raw)[:24].strip("_")
        if not EXTRA_SPRITE_NAME_RE.match(name):
            print(f"[Game Designer] dropping extra sprite with unusable name {sprite.get('name')!r}")
            continue
        if name in ("hero", "key_item", "level", "background", "bg"):
            print(f"[Game Designer] dropping extra sprite {name!r} - reserved name")
            continue
        if name in seen:
            print(f"[Game Designer] dropping duplicate extra sprite {name!r}")
            continue
        seen.add(name)
        cleaned.append({"name": name, "description": sprite["description"]})
    doc["extra_sprites"] = cleaned
    return doc


def _parse_json_lenient(text: str) -> dict:
    """A truncated response is a raised context/prediction budget the model
    still overran, or a model that ignores it - either way it's cheaper to
    salvage the doc than to discard a mostly-good generation. Closes any
    unterminated string and unbalanced brackets before parsing."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[Game Designer] JSON truncated ({e}), attempting salvage")
        stack = []
        in_string = False
        escaped = False
        for ch in text:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        salvaged = text + ('"' if in_string else "") + "".join(reversed(stack))
        return json.loads(salvaged)


def _design_claude(user_prompt: str, level_count: int | None = None) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=_level_system_prompt(level_count),
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": DESIGN_DOC_SCHEMA},
        },
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def _design_remote(user_prompt: str, level_count: int | None = None) -> dict:
    """Hosted OpenAI-compatible backend (DeepSeek by default).

    JSON mode guarantees valid JSON but not schema conformance, so the schema
    goes in the prompt and _validate() checks the result - the same
    corrective-retry path the local backend uses.
    """
    from saga.llm import chat

    schema_note = (
        "Respond with a single JSON object matching this schema exactly - no "
        "prose, no markdown fence:\n" + json.dumps(DESIGN_DOC_SCHEMA, indent=2)
    )
    messages = [
        {
            "role": "system",
            "content": _level_system_prompt(level_count) + "\n\n" + schema_note,
        },
        {"role": "user", "content": user_prompt},
    ]
    doc = _parse_json_lenient(
        chat(
            messages,
            model=REMOTE_MODEL,
            json_mode=True,
            timeout=settings.designer_timeout,
        )
    )

    problems = _validate(doc, level_count)
    if problems:
        print(f"[Game Designer] Remote doc invalid, one corrective retry: {problems}")
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
        doc = _parse_json_lenient(
            chat(
                messages,
                model=REMOTE_MODEL,
                json_mode=True,
                timeout=settings.designer_timeout,
            )
        )
        problems = _validate(doc, level_count)
        if problems:
            raise ValueError(f"Remote designer produced an invalid design doc: {problems}")
    return doc


def _design_local(user_prompt: str, level_count: int | None = None) -> dict:
    import ollama

    # A 3-5 level design doc with several string fields per level easily
    # exceeds Ollama's small default context/output window - Ollama truncates
    # silently rather than erroring, so under-provisioning here reads as a
    # JSON parse failure with no clue as to the real cause.
    options = {"num_ctx": 8192, "num_predict": 4096}

    messages = [
        {"role": "system", "content": _level_system_prompt(level_count)},
        {"role": "user", "content": user_prompt},
    ]
    response = ollama.chat(model=LOCAL_MODEL, messages=messages, format=DESIGN_DOC_SCHEMA, options=options)
    doc = _parse_json_lenient(response["message"]["content"])

    problems = _validate(doc, level_count)
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
        response = ollama.chat(model=LOCAL_MODEL, messages=messages, format=DESIGN_DOC_SCHEMA, options=options)
        doc = _parse_json_lenient(response["message"]["content"])
        problems = _validate(doc, level_count)
        if problems:
            raise ValueError(f"Local designer produced an invalid design doc: {problems}")
    return doc


def game_designer(state: GraphState) -> GraphState:
    backend = settings.designer_backend
    level_count = state.get("requested_levels")
    supplied = state.get("design_doc")
    if supplied:
        design_doc = _normalize(copy.deepcopy(supplied))
        problems = _validate(design_doc, level_count)
        if problems:
            raise ValueError(f"Supplied design doc is invalid: {problems}")
        backend = "fixed"
    elif backend == "claude":
        design_doc = _design_claude(state["user_prompt"], level_count)
    elif backend in ("deepseek", "openai", "remote"):
        design_doc = _design_remote(state["user_prompt"], level_count)
    else:
        design_doc = _design_local(state["user_prompt"], level_count)
    if not supplied:
        design_doc = _normalize(design_doc)

    print(
        f"[Game Designer/{backend}] Produced design doc: {design_doc['title']!r} "
        f"(template: {design_doc['mechanic_template']}, "
        f"{len(design_doc['levels'])} levels, "
        f"intensity {[lvl['intensity'] for lvl in design_doc['levels']]})"
    )
    return {"user_prompt": state["user_prompt"], "design_doc": design_doc}
