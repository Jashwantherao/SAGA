"""Experience-first content search for deterministic archetype runtimes.

The stable Godot packs own mechanics.  This module owns a different concern:
choosing *what the player experiences* inside those mechanics.  It deliberately
generates several bounded candidates and scores them before a plan reaches the
runtime; a language model is not allowed to replace this executable quality
gate with prose.
"""

from __future__ import annotations

import hashlib
import json
import random
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from saga import corpus


TOKEN_RE = re.compile(r"[a-z][a-z0-9_]{2,}")
STOP_WORDS = {
    "and", "are", "for", "from", "game", "godot", "level", "must", "the",
    "this", "use", "with", "your",
}
LEGACY_REQUIRED_FIELDS = {
    "recorded_at", "template", "model", "level_index", "retry_count",
    "first_try", "prompt", "completion",
}
DEFAULT_MIN_SIMILARITY = 0.20
DEFAULT_MAX_COMPLETION_CHARS = 8_000


@dataclass(frozen=True)
class VerifiedExperience:
    template: str
    model: str | None
    first_try: bool
    retry_count: int
    similarity: float
    completion: str
    verification_source: str


def _tokens(text: str) -> set[str]:
    return {
        token for token in TOKEN_RE.findall(text.lower())
        if token not in STOP_WORDS
    }


def _verification_source(record: dict) -> str | None:
    verification = record.get("verification")
    if isinstance(verification, dict):
        return "qa_gates" if verification.get("status") == "passed" else None
    if "qa_verified" in record:
        return "qa_verified" if record.get("qa_verified") is True else None
    if LEGACY_REQUIRED_FIELDS <= set(record):
        return "legacy_post_qa_corpus"
    return None


def retrieve_verified_experiences(
    *,
    template: str,
    query: str,
    limit: int = 1,
    corpus_path: str | Path | None = None,
    require_first_pass: bool = False,
    min_similarity: float = 0.0,
    max_completion_chars: int | None = None,
) -> list[VerifiedExperience]:
    """Return relevant complete scripts from the same mechanic template."""
    path = Path(corpus_path) if corpus_path is not None else corpus.CORPUS_PATH
    if limit <= 0 or not path.is_file():
        return []
    query_tokens = _tokens(query)
    candidates: list[tuple[tuple, int, VerifiedExperience]] = []
    seen_hashes: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for index, line in enumerate(lines):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        source = _verification_source(record)
        completion = record.get("completion")
        if (
            source is None
            or record.get("template") != template
            or not isinstance(completion, str)
            or not completion.strip()
        ):
            continue
        completion = completion.strip()
        prompt_tokens = _tokens(str(record.get("prompt") or ""))
        similarity = (
            len(query_tokens & prompt_tokens) / len(query_tokens)
            if query_tokens else 0.0
        )
        try:
            retry_count = max(0, int(record.get("retry_count") or 0))
        except (TypeError, ValueError):
            continue
        digest = hashlib.sha256(completion.encode("utf-8")).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        first_try = bool(record.get("first_try")) and retry_count == 0
        if require_first_pass and not first_try:
            continue
        if similarity < min_similarity:
            continue
        if max_completion_chars is not None and len(completion) > max_completion_chars:
            continue
        item = VerifiedExperience(
            template=template,
            model=record.get("model"),
            first_try=first_try,
            retry_count=retry_count,
            similarity=similarity,
            completion=completion,
            verification_source=source,
        )
        rank = (similarity, first_try, -retry_count, index)
        candidates.append((rank, index, item))
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    return [candidate[2] for candidate in candidates[:limit]]


def experience_context(
    *,
    template: str,
    query: str,
    limit: int = 1,
    max_chars: int = 12_000,
    corpus_path: str | Path | None = None,
) -> str:
    """Render complete verified examples within a strict character budget."""
    if max_chars <= 0:
        return ""
    blocks = []
    used = 0
    for item in retrieve_verified_experiences(
        template=template,
        query=query,
        limit=limit,
        corpus_path=corpus_path,
        require_first_pass=True,
        min_similarity=DEFAULT_MIN_SIMILARITY,
        max_completion_chars=min(max_chars, DEFAULT_MAX_COMPLETION_CHARS),
    ):
        quality = "first-pass" if item.first_try else f"repaired in {item.retry_count} retries"
        block = (
            "VERIFIED EXPERIENCE MEMORY (QA-passed reference only):\n"
            f"Mechanic: {item.template}; quality: {quality}; model: {item.model or 'unknown'}; "
            f"evidence: {item.verification_source}.\n"
            "Reuse structural gameplay patterns only. Do not copy its premise, "
            "asset filenames, labels, or balancing numbers. The current brief below "
            "is authoritative.\n"
            f"```gdscript\n{item.completion}\n```\n"
        )
        if used + len(block) > max_chars:
            continue
        blocks.append(block)
        used += len(block)
    return "\n".join(blocks)


ACTION_RPG_ROLE_COSTS = {
    "stalker": 2,
    "skirmisher": 2,
    "sentinel": 3,
    "bruiser": 4,
}

ACTION_RPG_LAYOUTS: dict[str, list[dict[str, Any]]] = {
    "broken_ring": [
        {"position": [390, 212], "size": [106, 42], "style": "ember_slab"},
        {"position": [640, 386], "size": [118, 46], "style": "ember_slab"},
        {"position": [780, 180], "size": [62, 62], "style": "rune_pillar"},
    ],
    "lantern_lanes": [
        {"position": [344, 190], "size": [72, 132], "style": "moon_pillar"},
        {"position": [620, 392], "size": [72, 128], "style": "moon_pillar"},
        {"position": [790, 230], "size": [96, 42], "style": "moon_slab"},
    ],
    "split_shrine": [
        {"position": [430, 170], "size": [128, 42], "style": "verdant_slab"},
        {"position": [430, 418], "size": [128, 42], "style": "verdant_slab"},
        {"position": [720, 292], "size": [72, 116], "style": "verdant_pillar"},
    ],
    "forge_teeth": [
        {"position": [338, 214], "size": [66, 88], "style": "iron_tooth"},
        {"position": [535, 366], "size": [66, 88], "style": "iron_tooth"},
        {"position": [735, 214], "size": [66, 88], "style": "iron_tooth"},
    ],
    "open_arena": [
        {"position": [410, 176], "size": [74, 46], "style": "boss_pillar"},
        {"position": [410, 410], "size": [74, 46], "style": "boss_pillar"},
    ],
    "sunken_crossing": [
        {"position": [315, 292], "size": [78, 166], "style": "flooded_pillar"},
        {"position": [610, 178], "size": [142, 42], "style": "flooded_slab"},
        {"position": [735, 412], "size": [118, 42], "style": "flooded_slab"},
    ],
    "hollow_spiral": [
        {"position": [365, 188], "size": [96, 44], "style": "crypt_slab"},
        {"position": [545, 290], "size": [72, 116], "style": "crypt_pillar"},
        {"position": [735, 398], "size": [104, 44], "style": "crypt_slab"},
    ],
}

ACTION_RPG_THEMES = (
    "ember_ruins",
    "moon_archive",
    "verdant_foundry",
    "storm_crypt",
    "sunken_sanctum",
    "glass_wilds",
)


def evaluate_objective_personas(template: str, objective: dict[str, Any]) -> dict[str, Any]:
    """Normalize deterministic objective evidence into four player viewpoints.

    Classic packs do not yet expose editable ContentIR, but their real solver
    telemetry can still reveal whether a completed level serves different play
    styles.  These verdicts are evidence only; they never turn a failed solver
    into a pass.
    """
    completed = (
        str(objective.get("status") or "") == "passed"
        and int(objective.get("remaining") or 0) == 0
        and not bool(objective.get("stuck"))
    )
    progress = int(objective.get("progress_events") or objective.get("collected") or 0)
    total = int(objective.get("total") or 0)
    restart = str(objective.get("restart_status") or "not_applicable")
    deaths = int(objective.get("deaths") or 0)
    completion = float(objective.get("completion_seconds") or 0.0)
    limits = {
        "collect": 60.0, "ordered_switches": 60.0, "survive_hazards": 30.0,
        "depletion": 30.0, "survive_and_deplete": 30.0,
        "capture_zones": 30.0, "herd_to_goal": 60.0,
    }
    ceiling = limits.get(template, max(30.0, completion * 1.25))
    explorer_signals = {
        "collect": int(objective.get("collected") or 0),
        "ordered_switches": int(objective.get("sequence_length") or 0),
        "capture_zones": int(objective.get("total_zones") or 0),
        "herd_to_goal": int(objective.get("total_creatures") or 0),
    }
    explored = explorer_signals.get(template, progress)
    personas = {
        "achiever": {
            "passed": completed and progress >= total,
            "progress_events": progress,
            "required_events": total,
        },
        "explorer": {
            "passed": completed and explored > 0,
            "distinct_objective_signals": explored,
        },
        "survivor": {
            "passed": completed and deaths <= 1 and restart in {"passed", "not_applicable"},
            "deaths": deaths,
            "restart": restart,
        },
        "speedrunner": {
            "passed": completed and completion <= ceiling,
            "completion_seconds": completion,
            "quality_ceiling_seconds": ceiling,
        },
    }
    return {
        "personas": personas,
        "telemetry": {
            "completion_seconds": completion,
            "progress_events": progress,
            "max_stall_frames": int(objective.get("max_stall_frames") or 0),
            "deaths": deaths,
            "stuck": bool(objective.get("stuck")),
        },
        "passed": all(item["passed"] for item in personas.values()),
    }


def _seed_for(design_doc: dict, level_index: int) -> str:
    levels = design_doc.get("levels") or [{}]
    level = levels[min(level_index, len(levels) - 1)]
    identity = "|".join(
        (
            str(design_doc.get("title") or "Action RPG"),
            str(design_doc.get("story_premise") or ""),
            str(design_doc.get("theme_thread") or ""),
            str(level.get("name") or f"Level {level_index + 1}"),
            str(level.get("description") or ""),
            str(level_index),
        )
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


ACTION_RPG_NARRATIVE_FIELDS = (
    "quest_title", "currency_name", "quest_giver_name", "boss_name", "enemy_name",
    "relic_name", "ability_name", "collect_objective", "return_objective",
    "boss_objective", "victory_text",
)


def _clean_narrative_text(value: Any, fallback: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = "".join(character for character in text if character.isprintable())
    text = text or fallback
    if len(text) <= limit:
        return text
    shortened = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[: max(1, limit - 1)]).strip() + "…"


def _role_display_name(design_doc: dict, role: str, fallback: str) -> str:
    for sprite in design_doc.get("extra_sprites") or []:
        raw = str(sprite.get("name") or "")
        if role not in raw:
            continue
        words = [
            word for word in raw.split("_")
            if word not in {role, "extra", "sprite", "character", "gear"}
        ]
        if words:
            display = " ".join(words).title()
            if role == "relic" and "relic" not in display.casefold():
                display += " Relic"
            return display
    return fallback


def _currency_name(design_doc: dict, identity: str) -> str:
    key_item = design_doc.get("key_item") or {}
    if key_item.get("name"):
        return _clean_narrative_text(key_item["name"], f"{identity} Relics", 36)
    description = str(key_item.get("description") or "").lower()
    if "shard" in description:
        return "Lens Shards" if "lens" in description else f"{identity} Shards"
    if "spark" in description:
        words = re.findall(r"[a-z]+", description)
        spark_index = words.index("spark") if "spark" in words else -1
        prefix = words[spark_index - 1].title() if spark_index > 0 else identity
        return f"{prefix} Sparks"
    if "fragment" in description:
        return f"{identity} Fragments"
    return f"{identity} Relics"


def compile_action_rpg_narrative(
    design_doc: dict, level_index: int, room_count: int
) -> dict[str, Any]:
    """Compile authored identity into bounded, runtime-safe player-facing text.

    New designs provide the explicit narrative object. Older fixed benchmark
    documents are upgraded from their title, level, key item, sprites and ending
    instead of falling back to the old Ember Hermit shell.
    """
    supplied = design_doc.get("narrative") or {}
    levels = design_doc.get("levels") or [{}]
    level = levels[min(level_index, len(levels) - 1)]
    title = _clean_narrative_text(design_doc.get("title"), "Untitled Oath", 54)
    title_words = [
        word for word in re.findall(r"[A-Za-z0-9]+", title)
        if word.lower() not in {"the", "a", "an", "of"}
    ]
    identity = (title_words[0] if title_words else "Lost").title()
    currency = _clean_narrative_text(
        supplied.get("currency_name"), _currency_name(design_doc, identity), 36
    )
    quest_giver = _clean_narrative_text(
        supplied.get("quest_giver_name"),
        _role_display_name(design_doc, "npc", f"{identity} Keeper"), 42,
    )
    boss_name = _clean_narrative_text(
        supplied.get("boss_name"),
        _role_display_name(design_doc, "boss", f"{identity} Guardian"), 42,
    )
    enemy_name = _clean_narrative_text(
        supplied.get("enemy_name"),
        _role_display_name(design_doc, "enemy", f"{identity} Wraith"), 42,
    )
    relic_name = _clean_narrative_text(
        supplied.get("relic_name"),
        _role_display_name(design_doc, "relic", f"{identity} Wayfinder"), 42,
    )
    ability_name = _clean_narrative_text(
        supplied.get("ability_name"), f"{identity} Step", 36
    )
    level_name = _clean_narrative_text(level.get("name"), f"{identity} Reach", 54)
    fallback_rooms = [
        f"{identity} Threshold", f"{identity} Archive", f"{identity} Crossing",
        f"{identity} Reliquary", f"{identity} Sanctum", f"{boss_name}'s Domain",
    ]
    room_names = [
        _clean_narrative_text(name, fallback_rooms[index], 54)
        for index, name in enumerate((supplied.get("room_names") or [])[:6])
    ]
    for index in range(len(room_names), 6):
        room_names.append(fallback_rooms[index])
    if len({name.casefold() for name in room_names}) != len(room_names):
        room_names = fallback_rooms
    quest_cost = 10
    fallback_dialogue = [
        f"The way through {level_name} has gone dark.",
        f"Recover {quest_cost} {currency} and I can open the final passage.",
        f"Take the {ability_name}. It will carry you to {boss_name}.",
    ]
    supplied_dialogue = supplied.get("dialogue_lines") or []
    dialogue_lines = [
        _clean_narrative_text(
            supplied_dialogue[index] if index < len(supplied_dialogue) else "",
            fallback_dialogue[index], 150,
        )
        for index in range(3)
    ]
    defaults = {
        "quest_title": f"Relight {level_name}",
        "currency_name": currency,
        "quest_giver_name": quest_giver,
        "boss_name": boss_name,
        "enemy_name": enemy_name,
        "relic_name": relic_name,
        "ability_name": ability_name,
        "collect_objective": f"Recover {quest_cost} {currency}",
        "return_objective": f"Return to {quest_giver}",
        "boss_objective": f"Defeat {boss_name}",
        "victory_text": _clean_narrative_text(
            level.get("outro_beat"), f"{level_name} awakens again.", 150
        ),
    }
    narrative = {
        field: _clean_narrative_text(supplied.get(field), defaults[field], 150)
        for field in ACTION_RPG_NARRATIVE_FIELDS
    }
    selected_room_names = [room_names[0], *room_names[1 : max(1, room_count - 1)]]
    if room_count > 1:
        selected_room_names.append(room_names[-1])
    narrative.update({
        "contract_version": 1,
        "room_names": selected_room_names[:room_count],
        "dialogue_lines": dialogue_lines,
        "source": "designer" if all(supplied.get(field) for field in ACTION_RPG_NARRATIVE_FIELDS) else "compiled_from_design",
        "source_fingerprint": hashlib.sha256(
            json.dumps({
                "title": title,
                "level": level_name,
                "key_item": design_doc.get("key_item") or {},
                "sprites": design_doc.get("extra_sprites") or [],
            }, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16],
    })
    return narrative


def build_action_rpg_experience_contract(
    design_doc: dict, level_index: int
) -> dict[str, Any]:
    """Compile the brief into testable player-experience requirements."""
    levels = design_doc.get("levels") or [{}]
    level = levels[min(level_index, len(levels) - 1)]
    intensity = max(1, min(10, int(level.get("intensity") or 5)))
    return {
        "contract_version": 1,
        "intent": str(
            design_doc.get("theme_thread")
            or design_doc.get("story_premise")
            or "Recover power, earn trust, and overcome a guarded climax."
        ),
        "level_fantasy": str(level.get("description") or "A dangerous forgotten keep."),
        "experience_beats": [
            {"id": "orient", "target_intensity": max(1, intensity - 3), "purpose": "learn"},
            {"id": "pressure", "target_intensity": intensity, "purpose": "master"},
            {"id": "recover", "target_intensity": max(1, intensity - 4), "purpose": "breathe"},
            {"id": "climax", "target_intensity": min(10, intensity + 2), "purpose": "prove"},
        ],
        "personas": {
            "achiever": "clear the quest and defeat every mandatory threat",
            "explorer": "find an optional relic away from the direct route",
            "survivor": "receive a recovery opportunity before the boss",
            "speedrunner": "retain a readable traversal lane through every room",
        },
        "quality_floor": {
            "minimum_score": 78,
            "minimum_enemy_roles": 3,
            "minimum_layout_variants": 4,
            "recovery_before_boss": True,
            "placeholder_geometry_allowed": False,
        },
        "feedback_contract": {
            "melee_hit": ["hit_flash", "knockback", "impact_burst"],
            "pickup": ["color_identity", "collection_burst", "hud_update"],
            "room": ["distinct_palette", "distinct_layout", "room_title"],
        },
    }


def _position_is_clear(position: list[int], obstacles: list[dict[str, Any]]) -> bool:
    x, y = position
    if x < 100 or x > 930 or y < 115 or y > 515:
        return False
    for obstacle in obstacles:
        ox, oy = obstacle["position"]
        width, height = obstacle["size"]
        if abs(x - ox) < width / 2 + 42 and abs(y - oy) < height / 2 + 42:
            return False
    return True


def _pick_clear(
    rng: random.Random,
    choices: list[list[int]],
    obstacles: list[dict[str, Any]],
    occupied: list[list[int]],
) -> list[int]:
    candidates = choices[:]
    rng.shuffle(candidates)
    for point in candidates:
        if _position_is_clear(point, obstacles) and all(
            (point[0] - other[0]) ** 2 + (point[1] - other[1]) ** 2 >= 105**2
            for other in occupied
        ):
            occupied.append(point)
            return point
    # Every authored layout has valid points; this is a deterministic safety net.
    fallback = [512, 288]
    occupied.append(fallback)
    return fallback


def _candidate_plan(
    design_doc: dict,
    level_index: int,
    candidate_index: int,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Compile one bounded ContentIR candidate from a seeded pacing grammar.

    The first two rooms retain stable quest affordances used by the runtime and
    normal-input playtester.  The middle journey is genuinely variable: room
    count, layouts, roles, pressure, rewards, themes and optional exploration
    beats all derive from the brief seed.  The boss is always the final room,
    so the stable pack can consume the result without generated gameplay code.
    """
    seed = _seed_for(design_doc, level_index)
    rng = random.Random(f"{seed}:{candidate_index}")
    intensity = max(
        1,
        min(
            10,
            int(
                ((design_doc.get("levels") or [{}])[level_index]).get("intensity")
                or 5
            ),
        ),
    )
    # A nonlinear quest needs enough authored space for a readable junction,
    # a genuinely optional discovery, a recovery room and the boss.  Five is
    # the smallest graph that can provide all four without turning a room into
    # a pile of unrelated responsibilities.
    room_count = 5 + rng.randrange(2)
    theme_offset = int(seed[:4], 16) % len(ACTION_RPG_THEMES)
    themes = list(ACTION_RPG_THEMES)
    themes = themes[theme_offset:] + themes[:theme_offset]
    journey_layouts = [layout for layout in ACTION_RPG_LAYOUTS if layout != "open_arena"]
    rng.shuffle(journey_layouts)
    selected_layouts = journey_layouts[: room_count - 1] + ["open_arena"]
    role_order = list(ACTION_RPG_ROLE_COSTS)
    rng.shuffle(role_order)
    enemy_health = 2 + intensity // 3
    combat_points = [
        [250, 170], [280, 420], [470, 150], [500, 440],
        [650, 170], [690, 430], [820, 160], [850, 420],
    ]
    pickup_points = [
        [220, 150], [250, 450], [470, 460], [620, 140],
        [760, 450], [870, 150], [865, 410],
    ]

    room_specs: list[dict[str, Any]] = []
    for layout_id in selected_layouts[:-1]:
        obstacles = deepcopy(ACTION_RPG_LAYOUTS[layout_id])
        occupied: list[list[int]] = []
        room_specs.append(
            {
                "layout_id": layout_id,
                "obstacles": obstacles,
                "enemy_positions": [
                    _pick_clear(rng, combat_points, obstacles, occupied)
                    for _ in range(3)
                ],
                "pickup_positions": [
                    _pick_clear(rng, pickup_points, obstacles, occupied)
                    for _ in range(3)
                ],
            }
        )

    spark_entry = rng.choice([3, 4, 5])
    narrative = compile_action_rpg_narrative(design_doc, level_index, room_count)
    room_name_roots = narrative["room_names"]
    rooms: list[dict[str, Any]] = []
    for room_index in range(room_count - 1):
        spec = room_specs[room_index]
        role_count = 1 if room_index == 0 else min(3, 1 + room_index)
        enemies = []
        for enemy_index in range(role_count):
            role = role_order[(room_index + enemy_index) % len(role_order)]
            enemies.append(
                {
                    "id": f"foe_{room_index}_{enemy_index}",
                    "role": role,
                    "health": enemy_health + room_index // 2 + (1 if role == "bruiser" else 0),
                    "position": spec["enemy_positions"][enemy_index],
                    "display_name": f"{narrative['enemy_name']} {role.title()}",
                }
            )
        pickups: list[dict[str, Any]] = []
        if room_index == 0:
            pickups.append(
                {
                    "id": "entry_sparks", "kind": "sparks", "amount": spark_entry,
                    "position": spec["pickup_positions"][0],
                    "display_name": narrative["currency_name"],
                }
            )
        elif room_index == 1:
            pickups.extend(
                [
                    {
                        "id": "vault_sparks", "kind": "sparks", "amount": 10 - spark_entry,
                        "position": spec["pickup_positions"][0],
                        "display_name": narrative["currency_name"],
                    },
                    {
                        "id": "ember_charm", "kind": "item", "amount": 1,
                        "position": spec["pickup_positions"][1],
                        "display_name": narrative["relic_name"],
                    },
                ]
            )
        elif room_index == 2:
            pickups.append(
                {
                    "id": "optional_relic_branch", "kind": "item", "amount": 1,
                    "position": spec["pickup_positions"][2],
                    "display_name": narrative["relic_name"],
                }
            )
        elif room_index == room_count - 2:
            pickups.append(
                {
                    "id": "restoration_tonic", "kind": "health", "amount": 2,
                    "position": spec["pickup_positions"][2],
                    "display_name": "Restoration Tonic",
                }
            )
        elif room_index % 2 == 0:
            pickups.append(
                {
                    "id": f"optional_relic_{room_index}", "kind": "item", "amount": 1,
                    "position": spec["pickup_positions"][2],
                    "display_name": narrative["relic_name"],
                }
            )
        beat = "orient" if room_index == 0 else (
            "recover" if room_index == room_count - 2 else "pressure"
        )
        room = {
            "index": room_index,
            "id": "hermit_court" if room_index == 0 else (
                "rust_vault" if room_index == 1 else (
                    "relic_branch" if room_index == 2 else f"journey_{room_index}"
                )
            ),
            "name": room_name_roots[room_index],
            "theme_id": themes[room_index % len(themes)],
            "layout_id": selected_layouts[room_index],
            "obstacles": spec["obstacles"],
            "enemies": enemies,
            "pickups": pickups,
            "beat": beat,
            "pressure": sum(ACTION_RPG_ROLE_COSTS[enemy["role"]] for enemy in enemies),
            "optional_discovery": room_index == 2,
        }
        if room_index == 0:
            room.update({
                "npc": {
                    "id": "quest_giver",
                    "name": narrative["quest_giver_name"],
                    "lines": narrative["dialogue_lines"],
                },
                "npc_position": [850, 285],
            })
        rooms.append(room)

    boss_index = room_count - 1
    rooms.append(
        {
            "index": boss_index,
            "id": "heart_forge",
            "name": room_name_roots[boss_index],
            "theme_id": themes[boss_index % len(themes)],
            "layout_id": "open_arena",
            "obstacles": deepcopy(ACTION_RPG_LAYOUTS["open_arena"]),
            "requires_quest_stage": "forge_open",
            "boss": {
                "id": "forge_warden",
                "name": narrative["boss_name"],
                "health": 10 + intensity + max(0, room_count - 4) * 2,
                "phases": 2,
                "position": [760, 300],
            },
            "enemies": [],
            "pickups": [],
            "beat": "climax",
            "pressure": 10 + intensity,
            "optional_discovery": False,
        }
    )
    # Index two is a north branch off the first junction.  Its east exit is a
    # real return shortcut into the recovery path, producing a small cycle the
    # player can understand and exploit.  Edges describe both directions so
    # the stable runtime never guesses travel from array order.
    main_route = [rooms[0]["id"], rooms[1]["id"]] + [
        rooms[index]["id"] for index in range(3, room_count)
    ]
    edges = [
        {
            "id": "threshold_to_junction", "from": rooms[0]["id"],
            "to": rooms[1]["id"], "direction": "east",
            "return_direction": "west", "kind": "main_route",
        },
        {
            "id": "junction_to_relic", "from": rooms[1]["id"],
            "to": rooms[2]["id"], "direction": "north",
            "return_direction": "south", "kind": "optional_branch",
        },
        {
            "id": "junction_to_recovery", "from": rooms[1]["id"],
            "to": rooms[3]["id"], "direction": "east",
            "return_direction": "west", "kind": "main_route",
        },
        {
            "id": "relic_return_shortcut", "from": rooms[2]["id"],
            "to": rooms[3]["id"], "direction": "east",
            "return_direction": "north", "kind": "shortcut",
        },
    ]
    for index in range(3, room_count - 1):
        edges.append(
            {
                "id": f"room_{index}_to_{index + 1}",
                "from": rooms[index]["id"], "to": rooms[index + 1]["id"],
                "direction": "east", "return_direction": "west",
                "kind": "gated" if index + 1 == boss_index else "main_route",
                **(
                    {"requires_quest_stage": "forge_open"}
                    if index + 1 == boss_index else {}
                ),
            }
        )
    plan: dict[str, Any] = {
        "schema_version": 5,
        "seed": seed,
        "compiler": {
            "id": "encounter_progression",
            "version": 3,
            "candidate_index": candidate_index,
        },
        "quest_stages": ["collect_sparks", "return_to_hermit", "forge_open", "complete"],
        "quest": {"spark_cost": 10, "reward": "spark_dash", "opens_room": boss_index},
        "narrative": narrative,
        "experience_contract": contract,
        "world_graph": {
            "version": 2,
            "start": rooms[0]["id"],
            "boss": rooms[-1]["id"],
            "main_route": main_route,
            "optional_rooms": [rooms[2]["id"]],
            "edges": edges,
        },
        "rooms": rooms,
    }
    return plan


def score_action_rpg_candidate(plan: dict[str, Any]) -> dict[str, Any]:
    """Score a plan using executable proxies for four player personas."""
    rooms = plan.get("rooms") or []
    roles = {
        str(enemy.get("role"))
        for room in rooms
        for enemy in room.get("enemies", [])
    }
    layouts = {str(room.get("layout_id")) for room in rooms}
    clear_placements = all(
        _position_is_clear(entity.get("position", [0, 0]), room.get("obstacles", []))
        for room in rooms
        for entity in room.get("enemies", []) + room.get("pickups", [])
    )
    separated_placements = True
    for room in rooms:
        positions = [
            entity.get("position", [0, 0])
            for entity in room.get("enemies", []) + room.get("pickups", [])
        ]
        for index, position in enumerate(positions):
            if any(
                (float(position[0]) - float(other[0])) ** 2
                + (float(position[1]) - float(other[1])) ** 2
                < 72.0**2
                for other in positions[index + 1 :]
            ):
                separated_placements = False
                break
    clear_placements = clear_placements and separated_placements
    room_threat = [
        sum(ACTION_RPG_ROLE_COSTS.get(str(enemy.get("role")), 2) for enemy in room.get("enemies", []))
        for room in rooms[:-1]
    ]
    pressure_steps = [
        later - earlier for earlier, later in zip(room_threat, room_threat[1:])
    ]
    pacing_gains = sum(1 for step in pressure_steps if step >= 0)
    pacing = bool(pressure_steps) and pacing_gains >= max(1, len(pressure_steps) - 1)
    recovery_pickup = next(
        (
            pickup
            for room in rooms[:-1]
            for pickup in room.get("pickups", [])
            if pickup.get("kind") == "health"
        ),
        None,
    )
    optional_relic = next(
        (
            pickup
            for room in rooms
            for pickup in room.get("pickups", [])
            if str(pickup.get("id") or "").startswith("optional_relic_")
        ),
        None,
    )
    mandatory_vault_pickup = next(
        (
            pickup
            for room in rooms
            for pickup in room.get("pickups", [])
            if pickup.get("id") == "vault_sparks"
        ),
        None,
    )
    sparks = sum(
        int(pickup.get("amount") or 0)
        for room in rooms
        for pickup in room.get("pickups", [])
        if pickup.get("kind") == "sparks"
    )
    quest_funded = sparks >= int((plan.get("quest") or {}).get("spark_cost") or 0)
    world = plan.get("world_graph") or {}
    world_edges = world.get("edges") or []
    main_route = world.get("main_route") or []
    optional_room_ids = set(world.get("optional_rooms") or [])
    branch_edges = sum(edge.get("kind") == "optional_branch" for edge in world_edges)
    shortcut_edges = sum(edge.get("kind") == "shortcut" for edge in world_edges)
    adjacency: dict[str, set[str]] = {
        str(room.get("id")): set() for room in rooms if room.get("id")
    }
    for edge in world_edges:
        source, target = str(edge.get("from") or ""), str(edge.get("to") or "")
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            if edge.get("return_direction"):
                adjacency[target].add(source)
    reachable: set[str] = set()
    pending = [str(world.get("start") or "")]
    while pending:
        current = pending.pop()
        if current in reachable or current not in adjacency:
            continue
        reachable.add(current)
        pending.extend(adjacency[current] - reachable)
    graph_reachable = len(reachable) == len(rooms)
    branching_junctions = sum(len(targets) >= 3 for targets in adjacency.values())
    explorer_separation = 0.0
    if optional_relic and mandatory_vault_pickup:
        relic_position = optional_relic.get("position", [0, 0])
        mandatory_position = mandatory_vault_pickup.get("position", [0, 0])
        distance = (
            (float(relic_position[0]) - float(mandatory_position[0])) ** 2
            + (float(relic_position[1]) - float(mandatory_position[1])) ** 2
        ) ** 0.5
        explorer_separation = min(1.0, distance / 520.0)
    # Recovery near the far side of the pressure room creates a deliberate
    # breathe beat before the player doubles back to turn in the quest.
    recovery_timing = 0.0
    if recovery_pickup:
        recovery_position = recovery_pickup.get("position", [0, 0])
        recovery_timing = min(1.0, max(0.0, (float(recovery_position[0]) - 180.0) / 620.0))
    # Prefer a clear high or low traversal lane. This is a cheap deterministic
    # speedrunner persona proxy; the live input agent remains the final proof.
    lane_scores: list[float] = []
    for lane_y in (145.0, 445.0):
        blockers = 0
        for room in rooms:
            for obstacle in room.get("obstacles", []):
                oy = float(obstacle["position"][1])
                height = float(obstacle["size"][1])
                if abs(lane_y - oy) <= height / 2.0 + 24.0:
                    blockers += 1
        lane_scores.append(max(0.0, 1.0 - blockers / 5.0))
    total_enemies = sum(len(room.get("enemies", [])) for room in rooms)
    optional_rooms = sum(bool(room.get("optional_discovery")) for room in rooms)
    estimated_travel_seconds = round(max(1, len(rooms) - 1) * 5.4, 1)
    estimated_combat_seconds = round(
        sum(
            int(enemy.get("health") or 1)
            for room in rooms
            for enemy in room.get("enemies", [])
        )
        * 0.72,
        1,
    )
    estimated_completion_seconds = round(
        estimated_travel_seconds + estimated_combat_seconds + 18.0, 1
    )
    backtrack_rooms = 2
    metrics = {
        "role_diversity": min(1.0, len(roles) / 3.0),
        "spatial_variety": min(1.0, len(layouts) / max(4.0, float(len(rooms)))),
        "pacing_curve": min(1.0, pacing_gains / max(1.0, float(len(pressure_steps)))),
        "placement_safety": 1.0 if clear_placements else 0.0,
        "achiever_path": 1.0 if quest_funded and rooms and bool(rooms[-1].get("boss")) else 0.0,
        "explorer_reward": min(1.0, explorer_separation + optional_rooms * 0.2),
        "survivor_recovery": recovery_timing,
        "speedrunner_lane": max(lane_scores, default=0.0),
        "nonlinear_world": 1.0 if graph_reachable and branch_edges > 0 and branching_junctions > 0 else 0.0,
        "shortcut_value": 1.0 if shortcut_edges > 0 and len(main_route) < len(rooms) else 0.0,
    }
    weights = {
        "role_diversity": 16,
        "spatial_variety": 10,
        "pacing_curve": 16,
        "placement_safety": 16,
        "achiever_path": 12,
        "explorer_reward": 6,
        "survivor_recovery": 10,
        "speedrunner_lane": 6,
        "nonlinear_world": 5,
        "shortcut_value": 5,
    }
    score = round(sum(metrics[key] * weights[key] for key in weights), 1)
    hard_constraints_passed = (
        5 <= len(rooms) <= 6
        and len(roles) >= 3
        and len(layouts) >= 4
        and clear_placements
        and pacing
        and recovery_pickup is not None
        and recovery_timing >= 0.35
        and optional_relic is not None
        and max(lane_scores, default=0.0) >= 0.4
        and quest_funded
        and graph_reachable
        and branch_edges >= 1
        and shortcut_edges >= 1
        and branching_junctions >= 1
        and bool(optional_room_ids)
    )
    personas = {
        "achiever": {
            "passed": bool(quest_funded and rooms and rooms[-1].get("boss")),
            "mandatory_rooms": len(rooms),
            "enemies_to_clear": total_enemies,
            "quest_currency": sparks,
        },
        "explorer": {
            "passed": optional_relic is not None and optional_rooms > 0 and branch_edges > 0,
            "optional_discoveries": optional_rooms,
            "reward_separation": round(explorer_separation, 3),
            "branch_rooms": len(optional_room_ids),
            "shortcuts": shortcut_edges,
        },
        "survivor": {
            "passed": recovery_pickup is not None and recovery_timing >= 0.35,
            "recovery_before_boss": recovery_pickup is not None,
            "recovery_timing": round(recovery_timing, 3),
        },
        "speedrunner": {
            "passed": max(lane_scores, default=0.0) >= 0.4,
            "lane_score": round(max(lane_scores, default=0.0), 3),
            "estimated_completion_seconds": estimated_completion_seconds,
        },
    }
    telemetry = {
        "room_count": len(rooms),
        "encounter_count": sum(bool(room.get("enemies")) for room in rooms),
        "enemy_count": total_enemies,
        "optional_discoveries": optional_rooms,
        "main_route_rooms": len(main_route),
        "optional_rooms": len(optional_room_ids),
        "branch_edges": branch_edges,
        "shortcut_edges": shortcut_edges,
        "branching_junctions": branching_junctions,
        "backtrack_rooms": backtrack_rooms,
        "estimated_travel_seconds": estimated_travel_seconds,
        "estimated_combat_seconds": estimated_combat_seconds,
        "estimated_completion_seconds": estimated_completion_seconds,
        "largest_pressure_jump": max(pressure_steps, default=0),
        "empty_room_count": sum(
            not room.get("enemies") and not room.get("boss") and not room.get("npc")
            for room in rooms
        ),
    }
    return {
        "score": score,
        "metrics": metrics,
        "passed": score >= 78 and hard_constraints_passed,
        "hard_constraints_passed": hard_constraints_passed,
        "personas": personas,
        "telemetry": telemetry,
    }


def repair_action_rpg_candidate(
    plan: dict[str, Any], result: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Apply one bounded, owner-specific content repair and return its ledger.

    This edits data only.  It never changes the stable runtime, and every edit
    is derived from a failed critic metric so weak candidates cannot silently
    receive unrelated mutations.
    """
    repaired = deepcopy(plan)
    edits: list[dict[str, str]] = []
    rooms = repaired.get("rooms") or []
    metrics = result.get("metrics") or {}
    if rooms and float(metrics.get("survivor_recovery") or 0.0) < 0.35:
        recovery = next(
            (
                pickup
                for room in rooms[:-1]
                for pickup in room.get("pickups", [])
                if pickup.get("kind") == "health"
            ),
            None,
        )
        if recovery is not None:
            recovery["position"] = [860, 450]
            edits.append({"owner": "progression", "action": "move_recovery_to_preboss_exit"})
    if rooms and float(metrics.get("explorer_reward") or 0.0) < 0.55:
        target_index = 2 if len(rooms) > 4 else max(1, len(rooms) - 2)
        target = rooms[target_index]
        if not any(
            str(pickup.get("id") or "").startswith("optional_relic_")
            for pickup in target.get("pickups", [])
        ):
            occupied = [
                list(entity.get("position", [0, 0]))
                for entity in target.get("enemies", []) + target.get("pickups", [])
            ]
            relic_position = _pick_clear(
                random.Random(f"{repaired.get('seed', 'repair')}:optional_relic"),
                [[875, 145], [850, 445], [650, 145], [250, 445], [220, 150]],
                target.get("obstacles", []),
                occupied,
            )
            target.setdefault("pickups", []).append(
                {
                    "id": f"optional_relic_{target_index}",
                    "kind": "item",
                    "amount": 1,
                    "position": relic_position,
                    "display_name": str(
                        (repaired.get("narrative") or {}).get("relic_name")
                        or "Optional Relic"
                    ),
                }
            )
            target["optional_discovery"] = True
            edits.append({"owner": "encounter", "action": "add_separated_optional_relic"})
    if rooms and float(metrics.get("speedrunner_lane") or 0.0) < 0.4:
        for room in rooms[:-1]:
            room["obstacles"] = [
                obstacle
                for obstacle in room.get("obstacles", [])
                if not (
                    float(obstacle["position"][1]) < 190
                    and float(obstacle["size"][1]) > 100
                )
            ]
        edits.append({"owner": "world", "action": "clear_upper_speedrunner_lane"})
    repaired["repair_ledger"] = edits
    return repaired, edits


def search_action_rpg_plan(
    design_doc: dict, level_index: int, candidate_count: int = 24
) -> dict[str, Any]:
    """Generate, evaluate and select content instead of accepting first output."""
    if candidate_count < 2:
        raise ValueError("experience search requires at least two candidates")
    contract = build_action_rpg_experience_contract(design_doc, level_index)
    ranked: list[tuple[float, str, int, dict[str, Any], dict[str, Any], bool]] = []
    repairs_evaluated = 0
    for candidate_index in range(candidate_count):
        plan = _candidate_plan(design_doc, level_index, candidate_index, contract)
        result = score_action_rpg_candidate(plan)
        repaired = False
        if not result["passed"]:
            revised, edits = repair_action_rpg_candidate(plan, result)
            if edits:
                revised_result = score_action_rpg_candidate(revised)
                repairs_evaluated += 1
                if revised_result["score"] >= result["score"]:
                    plan, result, repaired = revised, revised_result, True
        signature = hashlib.sha256(
            json.dumps(plan["rooms"], sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        # Signature provides deterministic tie-breaking without always selecting
        # candidate zero when several candidates satisfy the same constraints.
        ranked.append((float(result["score"]), signature, candidate_index, plan, result, repaired))
    ranked.sort(key=lambda item: (bool(item[4]["passed"]), item[0], item[1]), reverse=True)
    score, signature, candidate_index, selected, result, repaired = ranked[0]
    selected["experience_search"] = {
        "algorithm_version": 2,
        "candidates_evaluated": candidate_count,
        "repairs_evaluated": repairs_evaluated,
        "selected_candidate": candidate_index,
        "selected_after_repair": repaired,
        "selected_signature": signature,
        "score": score,
        "metrics": result["metrics"],
        "personas": result["personas"],
        "telemetry": result["telemetry"],
        "runner_up_score": ranked[1][0],
    }
    return selected
