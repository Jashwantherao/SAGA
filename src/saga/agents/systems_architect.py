"""Systems Architect - convert a creative design into a buildable contract.

The design doc deliberately leaves implementation open. This node closes that
gap before expensive asset and code work begins: it asks the benchmark winner
for an ordered set of systems with concrete acceptance criteria, validates the
answer, compiles model recommendations, and persists the result. Provider
failure never sinks a production; a deterministic template-aware blueprint is
the explicit, recorded fallback.
"""

import copy
import json
import re
from pathlib import Path

from saga.blueprint import (
    BLUEPRINT_VERSION,
    SYSTEM_KINDS,
    compile_build_plan,
    validate_blueprint,
)
from saga.config import settings
from saga.state import GraphState


BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {
        "blueprint_version": {"type": "integer", "enum": [BLUEPRINT_VERSION]},
        "title": {"type": "string"},
        "premise": {"type": "string"},
        "core_loop": {"type": "array", "items": {"type": "string"}},
        "win_condition": {"type": "string"},
        "lose_condition": {"type": "string"},
        "player": {
            "type": "object",
            "properties": {
                "controls": {"type": "array", "items": {"type": "string"}},
                "abilities": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["controls", "abilities"],
            "additionalProperties": False,
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "ai_states": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "description", "ai_states"],
                "additionalProperties": False,
            },
        },
        "save_state": {"type": "array", "items": {"type": "string"}},
        "scope_notes": {"type": "array", "items": {"type": "string"}},
        "systems": {
            "type": "array",
            "minItems": 3,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string", "enum": SYSTEM_KINDS},
                    "description": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "acceptance": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "kind", "description", "depends_on", "acceptance"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "blueprint_version",
        "title",
        "premise",
        "core_loop",
        "win_condition",
        "lose_condition",
        "player",
        "entities",
        "save_state",
        "systems",
    ],
    "additionalProperties": False,
}


SYSTEM_PROMPT = f"""You are the Systems Architect in an automated Godot game studio.
Turn the supplied game design into a small, coherent implementation contract.
The Coder and QA agents will treat every acceptance criterion as mandatory.

Rules:
- Preserve the supplied premise, win condition, lose condition and scope.
- Declare systems in dependency order. A depends_on id must appear earlier.
- Use lowercase slug ids. Use only these system kinds: {SYSTEM_KINDS}.
- Write 3-8 systems for an arcade game; add systems only when the design needs them.
- Acceptance criteria must be observable and testable, with exact state changes.
- Include movement and HUD. Represent the selected mechanic as its own system.
- Classic templates use held arrow movement and touch interactions. run_and_gun
  deliberately adds up-to-jump, ui_accept-to-fire and Tab weapon cycling; do not invent other actions.
- Do not prescribe visual assets as gameplay systems.
- Return only one JSON object matching the supplied schema.
"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    return json.loads(text)


def _canonicalize(bp: dict, design: dict, *, firewall: bool = True) -> dict:
    """Harness-owned facts cannot drift during architectural elaboration.

    The scope firewall applies only to model-generated blueprints. A supplied
    blueprint was reviewed by a human, so its out-of-scope systems are kept
    and annotated instead of removed (see _annotate_out_of_scope)."""
    result = copy.deepcopy(bp)
    result["blueprint_version"] = BLUEPRINT_VERSION
    result["title"] = design["title"]
    result["premise"] = design["story_premise"]
    result["win_condition"] = design["win_condition"]
    result["lose_condition"] = design["lose_condition"]
    result.setdefault("entities", [])
    result.setdefault("save_state", [])
    if firewall:
        _apply_scope_firewall(result, design)
    else:
        _annotate_out_of_scope(result, design)
    return result


TEMPLATE_SYSTEM_KINDS = {
    "collect": {"pickup", "objective"},
    "survive_hazards": {"hazard", "enemy_ai", "objective"},
    "ordered_switches": {"switch", "objective"},
    "depletion": {"resource", "zone_control", "objective"},
    "survive_and_deplete": {"resource", "hazard", "enemy_ai", "zone_control", "objective"},
    "maze_chase": {"maze", "pickup", "hazard", "enemy_ai", "objective"},
    "dot_maze": {"maze", "pickup", "hazard", "enemy_ai", "objective"},
    "run_and_gun": {"combat", "enemy_ai", "checkpoint", "boss", "progression", "save_load", "objective"},
    "action_rpg": {"combat", "enemy_ai", "inventory", "dialogue", "quest", "level_transition", "boss", "save_load", "objective"},
    "herd_to_goal": {"herding", "objective"},
    "capture_zones": {"zone_control", "hazard", "enemy_ai", "objective"},
}


def _allowed_kinds(design: dict) -> set[str]:
    """System kinds the current template Coder and probes can actually verify."""
    template = design.get("mechanic_template") or "collect"
    allowed = {"movement", "camera", "hud"} | TEMPLATE_SYSTEM_KINDS.get(
        template, {"objective"}
    )
    if len(design.get("levels") or []) > 1:
        allowed.add("level_transition")
    return allowed


def _viability_problems(bp: dict, design: dict) -> list[str]:
    """Reject a blueprint the firewall stripped down past the core loop.

    validate_blueprint is design-blind: it accepts any non-empty systems list,
    so an architect that answers a collect template with movement, hud and
    four out-of-scope RPG systems leaves a contract that validates clean and
    describes a game with no gameplay in it. The firewall runs before
    validation, so nothing else notices. Scaffolding kinds (movement, camera,
    hud, level_transition) cannot satisfy this on their own - at least one
    system must implement the template's own mechanic.
    """
    template = design.get("mechanic_template") or "collect"
    mechanic_kinds = TEMPLATE_SYSTEM_KINDS.get(template, {"objective"})
    kinds = {system.get("kind") for system in bp.get("systems") or []}
    if kinds & mechanic_kinds:
        return []
    return [
        f"no system implements the {template} core loop: expected at least one "
        f"of {sorted(mechanic_kinds)}, got {sorted(kind for kind in kinds if kind)}"
    ]


def _blueprint_problems(bp: dict, design: dict) -> list[str]:
    """Structural validity plus core-loop viability, for the generated paths
    where the scope firewall can silently remove the mechanic."""
    return validate_blueprint(bp) + _viability_problems(bp, design)


def _annotate_out_of_scope(bp: dict, design: dict) -> None:
    """A supplied, human-reviewed blueprint keeps every system it declares.

    Out-of-scope systems are recorded as advisories instead of being removed:
    their acceptance criteria reach the Coder as guidance, but no deterministic
    probe verifies them yet, and the builder ledger's qa_confirmed flag stays
    the source of truth for what was actually proven.
    """
    allowed = _allowed_kinds(design)
    outside = [
        f"{system.get('id')} ({system.get('kind')})"
        for system in bp.get("systems") or []
        if system.get("kind") not in allowed
    ]
    if not outside:
        return
    note = (
        "Supplied systems outside the verified "
        f"{design.get('mechanic_template') or 'collect'} probe scope "
        f"(kept, unverified until per-system probes exist): {', '.join(outside)}"
    )
    notes = list(bp.get("scope_notes") or [])
    notes.append(note)
    bp["scope_notes"] = list(dict.fromkeys(notes))
    print(f"[Systems Architect] {note}")


def _apply_scope_firewall(bp: dict, design: dict) -> None:
    """Prevent an architect from turning a compact template into scope creep.

    The current Coder and deterministic probes implement one of the nine
    arcade templates. Quests, inventory and dialogue still belong to the
    future complex-game pipeline; run_and_gun is the explicit exception for
    its verified campaign progression and save contract.
    """
    template = design.get("mechanic_template") or "collect"
    allowed = _allowed_kinds(design)

    systems = list(bp.get("systems") or [])
    removed = [system for system in systems if system.get("kind") not in allowed]
    kept = [system for system in systems if system.get("kind") in allowed]
    kept_ids = {system.get("id") for system in kept}
    for system in kept:
        system["depends_on"] = [
            dependency
            for dependency in (system.get("depends_on") or [])
            if dependency in kept_ids
        ]
    bp["systems"] = kept

    notes = list(bp.get("scope_notes") or [])
    if removed:
        summary = ", ".join(
            f"{system.get('id')} ({system.get('kind')})" for system in removed
        )
        note = f"Removed systems outside the {template} production scope: {summary}"
        notes.append(note)
        print(f"[Systems Architect] Scope firewall: {note}")
    if not any(system.get("kind") == "save_load" for system in kept):
        if bp.get("save_state"):
            notes.append("Removed save_state because this production has no save_load system")
        bp["save_state"] = []
    if notes:
        bp["scope_notes"] = list(dict.fromkeys(notes))
    else:
        bp.pop("scope_notes", None)


def _system(
    sid: str,
    kind: str,
    description: str,
    depends_on: list[str],
    acceptance: list[str],
) -> dict:
    return {
        "id": sid,
        "kind": kind,
        "description": description,
        "depends_on": depends_on,
        "acceptance": acceptance,
    }


def deterministic_blueprint(design: dict) -> dict:
    """Template-aware safety net used when the architect service is offline."""
    template = design.get("mechanic_template") or "collect"
    run_and_gun = template == "run_and_gun"
    action_rpg = template == "action_rpg"
    systems = [
        _system(
            "movement",
            "movement",
            (
                "Responsive side-view running and jumping with gravity and solid platforms."
                if run_and_gun
                else "Responsive four-directional player movement constrained to the playfield."
            ),
            [],
            (
                [
                    "Holding left or right accelerates the hero horizontally",
                    "Pressing up while grounded produces exactly one jump",
                    "Gravity returns the hero to solid platforms without falling through them",
                ]
                if run_and_gun
                else [
                    "Holding an arrow key moves the hero in that direction every frame",
                    "Releasing all arrows stops player-controlled movement",
                    "The hero cannot leave the visible playfield",
                ]
            ),
        ),
        _system(
            "hud",
            "hud",
            "A readable HUD exposes objective progress and the current play state.",
            ["movement"],
            [
                "The HUD shows objective progress during active play",
                "HUD values update in the same frame as their gameplay state",
                "Win and loss states display an unambiguous message",
            ],
        ),
    ]

    mechanic_specs = {
        "collect": (
            "collection_objective",
            "pickup",
            "Touch-based collectibles with truthful remaining-count and completion state.",
            [
                "Touching a collectible removes exactly that collectible",
                "Progress increments exactly once per collectible",
                "Collecting the final item triggers the declared win condition",
            ],
        ),
        "survive_hazards": (
            "hazard_survival",
            "hazard",
            "Moving hazards, damage, lives, survival timer, loss and clean restart.",
            [
                "Hazard contact applies exactly one bounded damage event",
                "Reaching zero lives triggers loss and freezes active play",
                "Surviving the full timer triggers the declared win condition",
            ],
        ),
        "ordered_switches": (
            "ordered_switches",
            "switch",
            "Touch switches accept only the authored sequence and expose progress.",
            [
                "Touching the next correct switch advances the sequence exactly once",
                "An incorrect switch visibly resets or rejects progress",
                "Completing the full sequence triggers the declared win condition",
            ],
        ),
        "depletion": (
            "resource_loop",
            "resource",
            "A continuously draining resource with touch-based refill zones.",
            [
                "The resource decreases continuously outside refill zones",
                "Entering a refill zone increases the resource without exceeding its maximum",
                "An empty resource triggers loss and surviving the timer triggers win",
            ],
        ),
        "survive_and_deplete": (
            "survival_resource_loop",
            "resource",
            "Ramping resource drain, finite refill fuel and damaging roaming hazards.",
            [
                "Drain rate increases over the authored survival interval",
                "Refill zones restore resource while consuming finite zone fuel",
                "Hazards cause damage, empty resource loses, and the timer can still be won",
            ],
        ),
        "maze_chase": (
            "maze_chase",
            "maze",
            "A connected wall maze with pickups and an active patroller.",
            [
                "Every required pickup is reachable from the player start",
                "Walls block both the player and patroller consistently",
                "Collecting all pickups wins while patroller contact costs a life",
            ],
        ),
        "dot_maze": (
            "dot_maze",
            "maze",
            "A connected dense maze with dots, ghosts, lives and power reversal.",
            [
                "Every dot is reachable and collectible exactly once",
                "Ghost contact costs one life unless a power state is active",
                "Power pickup state expires deterministically and all dots collected triggers win",
            ],
        ),
        "run_and_gun": (
            "ranged_combat",
            "combat",
            "Three collectible projectile weapons with distinct patterns, health, damage and defeat.",
            [
                "Pulse, spread and launcher weapons emit observably different projectile patterns",
                "Weapon pickups add finite-ammo loadouts and Tab cycles acquired weapons",
                "Player projectiles damage enemies without damaging the player",
                "Enemy attacks reduce health and zero health enters the loss state",
            ],
        ),
        "action_rpg": (
            "melee_combat",
            "combat",
            "Short frontal-arc melee with health, hit cooldown, stagger and clean loss.",
            [
                "A Z-key swing damages every enemy in the frontal arc exactly once",
                "Enemy contact reduces hero health once per invulnerability window",
                "Zero hero health enters loss and checkpoint restart restores a playable hero",
            ],
        ),
        "herd_to_goal": (
            "herding_objective",
            "herding",
            "A touch-pressure creature flees the hero and can enter a goal zone.",
            [
                "The creature moves away when the hero enters its flee radius",
                "The creature remains inside the playfield",
                "The creature entering the goal triggers the declared win condition",
            ],
        ),
        "capture_zones": (
            "zone_control",
            "zone_control",
            "Touch-captured zones with contest, decay and truthful ownership.",
            [
                "Player presence advances capture and records player ownership",
                "Contested or abandoned zones follow the declared decay rule",
                "Owning every required zone triggers the declared win condition",
            ],
        ),
    }
    sid, kind, description, acceptance = mechanic_specs.get(
        template, mechanic_specs["collect"]
    )
    systems.append(_system(sid, kind, description, ["movement", "hud"], acceptance))

    completion_system_id = sid
    if run_and_gun:
        systems.extend(
            [
                _system(
                    "enemy_behaviour",
                    "enemy_ai",
                    "Five enemy roles create bounded patrol, armor, ranged, turret and flying pressure inside threat-budgeted waves.",
                    ["movement", "ranged_combat"],
                    [
                        "Scout, bruiser, hunter, turret and flyer roles expose distinct movement or attack behavior",
                        "Triggered arena waves never exceed their declared threat budget",
                        "Defeated enemies stop dealing damage and increment progress once",
                    ],
                ),
                _system(
                    "checkpoint_respawn",
                    "checkpoint",
                    "Touching a checkpoint changes the clean respawn position.",
                    ["movement", "hud"],
                    [
                        "A checkpoint activates exactly once on player contact",
                        "A loss can restart with full health at the last checkpoint",
                        "Restart restores the pulse loadout and rebuilds an active wave without losing its arena contract",
                    ],
                ),
                _system(
                    "boss_encounter",
                    "boss",
                    "A durable ranged boss escalates from one-shot to three-shot and five-shot attack patterns.",
                    ["ranged_combat", "enemy_behaviour"],
                    [
                        "Boss health decreases from player projectile damage",
                        "Crossing health thresholds changes the boss phase and projectile pattern",
                        "Zero boss health disables combat and emits one defeat event",
                    ],
                ),
                _system(
                    "campaign_progression",
                    "progression",
                    "Boss rewards fund one of three persistent upgrade tracks through a versioned campaign profile.",
                    ["checkpoint_respawn", "boss_encounter"],
                    [
                        "A boss reward is granted at most once for its level id",
                        "Firepower, mobility or vitality purchases deduct the declared cost and change player capability",
                        "The versioned profile survives level transition and reload",
                        "Malformed save data falls back to a valid default profile",
                    ],
                ),
                _system(
                    "sector_objective",
                    "objective",
                    "Defeating the boss completes the sector after ordinary combat and checkpoint play.",
                    ["campaign_progression"],
                    [
                        "The HUD reports health, checkpoint, enemy and boss state",
                        "The level cannot win while the boss remains alive",
                        "Boss defeat sets won and advances through the authored level flow exactly once",
                    ],
                ),
            ]
        )
        completion_system_id = "sector_objective"
    elif action_rpg:
        systems.extend(
            [
                _system(
                    "stalker_behaviour", "enemy_ai",
                    "Enemies patrol, chase, attack and enter a non-damaging stagger state.",
                    ["movement", "melee_combat"],
                    [
                        "An enemy outside detection follows its patrol",
                        "An enemy inside detection chases and attacks only in range",
                        "A melee hit causes a 0.5 second stagger before normal behavior resumes",
                    ],
                ),
                _system(
                    "inventory", "inventory",
                    "Spark currency and gear pickups persist in a readable C-key panel.",
                    ["hud"],
                    [
                        "A pickup changes inventory exactly once",
                        "The inventory panel lists exact item and spark counts",
                        "Spending sparks cannot make the balance negative",
                    ],
                ),
                _system(
                    "hermit_dialogue", "dialogue",
                    "X-key NPC dialogue advances one line at a time and locks movement.",
                    ["movement"],
                    [
                        "Interaction in range opens named dialogue",
                        "Each X press advances exactly one line",
                        "Closing the final line restores hero movement",
                    ],
                ),
                _system(
                    "forge_quest", "quest",
                    "Ten sparks handed to the hermit unlock dash and the forge room.",
                    ["inventory", "hermit_dialogue"],
                    [
                        "The quest cannot complete before ten sparks are held",
                        "Turn-in deducts exactly ten sparks and advances the quest once",
                        "Completion unlocks dash and opens the sealed room",
                    ],
                ),
                _system(
                    "persistent_rooms", "level_transition",
                    "Three connected rooms retain defeated enemies and collected pickups.",
                    ["stalker_behaviour", "inventory", "forge_quest"],
                    [
                        "Room exits place the hero at the matching entrance",
                        "The forge room rejects entry until the quest opens it",
                        "Cleared enemies and collected pickups do not respawn on revisit",
                    ],
                ),
                _system(
                    "checkpoint_profile", "save_load",
                    "A versioned atomic checkpoint preserves room, hero, inventory and quest state.",
                    ["persistent_rooms"],
                    [
                        "Checkpoint data includes every declared RPG state field",
                        "Reload restores room, health, inventory and quest without duplication",
                        "Malformed or incompatible data falls back to a valid profile",
                    ],
                ),
                _system(
                    "forge_warden", "boss",
                    "A telegraphed forge boss becomes enraged below half health.",
                    ["melee_combat", "forge_quest", "persistent_rooms"],
                    [
                        "Every slam visibly telegraphs before damage",
                        "Crossing half health enters a faster second phase",
                        "Defeat advances the quest to complete and triggers the win flow",
                    ],
                ),
                _system(
                    "heart_forge_objective", "objective",
                    "The game wins only after quest completion, forge entry and boss defeat.",
                    ["checkpoint_profile", "forge_warden"],
                    [
                        "All exploration, inventory, dialogue and quest transitions are probe-visible",
                        "The boss cannot be reached before the forge quest opens the room",
                        "Boss defeat sets won exactly once",
                    ],
                ),
            ]
        )
        completion_system_id = "heart_forge_objective"

    if len(design.get("levels") or []) > 1:
        systems.append(
            _system(
                "level_flow",
                "level_transition",
                "Advance only after a verified win and preserve the authored level order.",
                [completion_system_id],
                [
                    "A level win shows its authored outro before advancing",
                    "Advancing loads exactly the next authored level",
                    "The final level win reaches the victory screen",
                ],
            )
        )

    return {
        "blueprint_version": BLUEPRINT_VERSION,
        "title": design["title"],
        "premise": design["story_premise"],
        "core_loop": list(design.get("core_mechanics") or []),
        "win_condition": design["win_condition"],
        "lose_condition": design["lose_condition"],
        "player": {
            "controls": (
                ["left/right arrows: run", "up arrow: jump", "ui_accept: fire", "Tab: cycle acquired weapons"]
                if run_and_gun
                else (
                    ["held arrows: move", "Z: melee", "X: interact and advance dialogue", "C: inventory", "Shift: dash after quest unlock"]
                    if action_rpg
                    else ["held arrow keys: move in four directions"]
                )
            ),
            "abilities": (
                ["run", "jump", "collect and switch weapons", "fire projectiles", "activate checkpoints", "purchase persistent upgrades"]
                if run_and_gun
                else (
                    ["explore rooms", "swing lantern", "collect gear", "talk", "complete quests", "unlock dash", "save at room checkpoints"]
                    if action_rpg
                    else ["touch-based interaction with gameplay objects"]
                )
            ),
        },
        "entities": (
            [
                {"name": "rust_stalker", "description": "Patrol/chase/stagger melee enemy", "ai_states": ["patrol", "chase", "attack", "staggered"]},
                {"name": "ember_hermit", "description": "Quest NPC and spark trader", "ai_states": ["idle", "talking"]},
                {"name": "forge_warden", "description": "Two-phase telegraphed boss", "ai_states": ["idle", "slam_telegraph", "slam", "enraged", "defeated"]},
            ]
            if action_rpg else []
        ),
        "save_state": (
            ["room_index", "hero_position", "hero_hp", "sparks", "items", "quest_stage", "dash_unlocked", "boss_defeated", "collected_pickups", "cleared_enemies"]
            if action_rpg else []
        ),
        "systems": systems,
    }


def _generate_remote(design: dict) -> dict:
    from saga.llm import chat

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
            + "\nJSON schema:\n"
            + json.dumps(BLUEPRINT_SCHEMA, indent=2),
        },
        {"role": "user", "content": json.dumps(design, indent=2)},
    ]
    # NVIDIA's compatible surface is reliable at plain JSON prompting but
    # model support for response_format varies. Do not turn a transport
    # feature mismatch into a silent deterministic fallback.
    structured_mode = settings.architect_backend != "nvidia"
    raw = chat(
        messages,
        model=settings.architect_model,
        json_mode=structured_mode,
        max_tokens=8000,
        base_url=settings.architect_base_url,
        key_env=settings.architect_key_env,
        timeout=settings.architect_timeout,
        temperature=0.2,
    )
    bp = _canonicalize(_parse_json(raw), design)
    problems = _blueprint_problems(bp, design)
    if problems:
        print(f"[Systems Architect] Invalid blueprint, one corrective retry: {problems}")
        messages += [
            {"role": "assistant", "content": json.dumps(bp)},
            {
                "role": "user",
                "content": "Return the complete corrected blueprint. Problems: "
                + "; ".join(problems),
            },
        ]
        raw = chat(
            messages,
            model=settings.architect_model,
            json_mode=structured_mode,
            max_tokens=8000,
            base_url=settings.architect_base_url,
            key_env=settings.architect_key_env,
            timeout=settings.architect_timeout,
            temperature=0.1,
        )
        bp = _canonicalize(_parse_json(raw), design)
        problems = _blueprint_problems(bp, design)
        if problems:
            raise ValueError(f"architect produced an invalid blueprint: {problems}")
    return bp


def _generate_local(design: dict) -> dict:
    import ollama

    response = ollama.chat(
        model=settings.architect_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(design, indent=2)},
        ],
        format=BLUEPRINT_SCHEMA,
        options={"num_ctx": 16384, "num_predict": 8000, "temperature": 0.2},
    )
    bp = _canonicalize(_parse_json(response["message"]["content"]), design)
    problems = _blueprint_problems(bp, design)
    if problems:
        raise ValueError(f"local architect produced an invalid blueprint: {problems}")
    return bp


def _write_blueprint(state: GraphState, bp: dict) -> Path:
    path = Path(state["run_dir"]) / "blueprint.json"
    path.write_text(json.dumps(bp, indent=2), encoding="utf-8")
    return path


def systems_architect(state: GraphState) -> GraphState:
    design = state["design_doc"]
    supplied = state.get("blueprint")
    errors: list[str] = []
    model: str | None = None

    if supplied:
        supplied_problems = validate_blueprint(supplied)
        if supplied_problems:
            raise ValueError(f"supplied blueprint is invalid: {supplied_problems}")
        bp = _canonicalize(copy.deepcopy(supplied), design, firewall=False)
        problems = validate_blueprint(bp)
        if problems:
            raise ValueError(f"supplied blueprint is invalid: {problems}")
        status = "fixed"
    elif settings.architect_backend in {"off", "deterministic"}:
        bp = deterministic_blueprint(design)
        status = "deterministic"
    else:
        model = settings.architect_model
        try:
            if settings.architect_backend == "local":
                bp = _generate_local(design)
            else:
                # nvidia/openai/remote all use the configured compatible URL.
                bp = _generate_remote(design)
            status = "generated"
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors.append(message[:1000])
            print(
                f"[Systems Architect] Model unavailable ({message}); "
                "using deterministic contract"
            )
            bp = deterministic_blueprint(design)
            status = "fallback"

    # A supplied blueprint keeps every system it declares - the firewall never
    # ran on it - so only the generated paths can have lost their core loop to
    # scope filtering. Holding a human-reviewed complex-game contract to the
    # arcade templates' mechanic kinds would reject it for being ambitious.
    problems = validate_blueprint(bp) if supplied else _blueprint_problems(bp, design)
    if problems:
        raise ValueError(f"Systems Architect produced an invalid fallback: {problems}")
    plan = compile_build_plan(bp)
    path = _write_blueprint(state, bp)
    print(
        f"[Systems Architect/{status}] {len(plan)} systems, "
        f"build order {[step['system_id'] for step in plan]} -> {path}"
    )
    return {
        "blueprint": bp,
        "blueprint_status": status,
        "blueprint_model": model,
        "blueprint_errors": errors,
        "blueprint_build_plan": plan,
    }
