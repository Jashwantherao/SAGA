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
}

ACTION_RPG_THEMES = (
    "ember_ruins",
    "moon_archive",
    "verdant_foundry",
    "storm_crypt",
)


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
            "minimum_layout_variants": 3,
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
    theme_offset = int(seed[:4], 16) % len(ACTION_RPG_THEMES)
    themes = list(ACTION_RPG_THEMES)
    themes = themes[theme_offset:] + themes[:theme_offset]
    entry_layout = rng.choice(["broken_ring", "lantern_lanes", "split_shrine"])
    vault_layout = rng.choice(
        [layout for layout in ("broken_ring", "lantern_lanes", "split_shrine", "forge_teeth") if layout != entry_layout]
    )
    boss_layout = "open_arena"
    role_order = list(ACTION_RPG_ROLE_COSTS)
    rng.shuffle(role_order)
    # Keep the opening readable while guaranteeing three mechanically distinct roles.
    entry_role = role_order[0]
    vault_roles = role_order[1:3]
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
    for layout_id in (entry_layout, vault_layout):
        obstacles = deepcopy(ACTION_RPG_LAYOUTS[layout_id])
        occupied: list[list[int]] = []
        room_specs.append(
            {
                "layout_id": layout_id,
                "obstacles": obstacles,
                "enemy_positions": [
                    _pick_clear(rng, combat_points, obstacles, occupied)
                    for _ in range(2)
                ],
                "pickup_positions": [
                    _pick_clear(rng, pickup_points, obstacles, occupied)
                    for _ in range(3)
                ],
            }
        )

    spark_entry = rng.choice([3, 4, 5])
    plan: dict[str, Any] = {
        "schema_version": 2,
        "seed": seed,
        "quest_stages": ["collect_sparks", "return_to_hermit", "forge_open", "complete"],
        "quest": {"spark_cost": 10, "reward": "spark_dash", "opens_room": 2},
        "experience_contract": contract,
        "rooms": [
            {
                "index": 0,
                "id": "hermit_court",
                "name": "Hermit's Court",
                "theme_id": themes[0],
                "layout_id": entry_layout,
                "obstacles": room_specs[0]["obstacles"],
                "npc": "hermit",
                "npc_position": [850, 285],
                "enemies": [
                    {
                        "id": "stalker_entry",
                        "role": entry_role,
                        "health": enemy_health,
                        "position": room_specs[0]["enemy_positions"][0],
                    }
                ],
                "pickups": [
                    {
                        "id": "entry_sparks",
                        "kind": "sparks",
                        "amount": spark_entry,
                        "position": room_specs[0]["pickup_positions"][0],
                    }
                ],
                "beat": "orient",
            },
            {
                "index": 1,
                "id": "rust_vault",
                "name": "Rust Vault",
                "theme_id": themes[1],
                "layout_id": vault_layout,
                "obstacles": room_specs[1]["obstacles"],
                "enemies": [
                    {
                        "id": "stalker_vault_a",
                        "role": vault_roles[0],
                        "health": enemy_health + 1,
                        "position": room_specs[1]["enemy_positions"][0],
                    },
                    {
                        "id": "stalker_vault_b",
                        "role": vault_roles[1],
                        "health": enemy_health,
                        "position": room_specs[1]["enemy_positions"][1],
                    },
                ],
                "pickups": [
                    {
                        "id": "vault_sparks",
                        "kind": "sparks",
                        "amount": 10 - spark_entry,
                        "position": room_specs[1]["pickup_positions"][0],
                    },
                    {
                        "id": "ember_charm",
                        "kind": "item",
                        "amount": 1,
                        "position": room_specs[1]["pickup_positions"][1],
                    },
                    {
                        "id": "restoration_tonic",
                        "kind": "health",
                        "amount": 2,
                        "position": room_specs[1]["pickup_positions"][2],
                    },
                ],
                "beat": "pressure_then_recover",
            },
            {
                "index": 2,
                "id": "heart_forge",
                "name": "Heart Forge",
                "theme_id": themes[2],
                "layout_id": boss_layout,
                "obstacles": deepcopy(ACTION_RPG_LAYOUTS[boss_layout]),
                "requires_quest_stage": "forge_open",
                "boss": {
                    "id": "forge_warden",
                    "health": 10 + intensity,
                    "phases": 2,
                    "position": [760, 300],
                },
                "enemies": [],
                "pickups": [],
                "beat": "climax",
            },
        ],
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
    room_threat = [
        sum(ACTION_RPG_ROLE_COSTS.get(str(enemy.get("role")), 2) for enemy in room.get("enemies", []))
        for room in rooms[:2]
    ]
    pacing_delta = room_threat[1] - room_threat[0] if len(room_threat) == 2 else -1
    pacing = pacing_delta > 0
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
            if pickup.get("kind") == "item"
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
    metrics = {
        "role_diversity": min(1.0, len(roles) / 3.0),
        "spatial_variety": min(1.0, len(layouts) / 3.0),
        "pacing_curve": min(1.0, max(0.0, pacing_delta / 3.0)),
        "placement_safety": 1.0 if clear_placements else 0.0,
        "achiever_path": 1.0 if quest_funded and rooms and bool(rooms[-1].get("boss")) else 0.0,
        "explorer_reward": explorer_separation,
        "survivor_recovery": recovery_timing,
        "speedrunner_lane": max(lane_scores, default=0.0),
    }
    weights = {
        "role_diversity": 16,
        "spatial_variety": 14,
        "pacing_curve": 16,
        "placement_safety": 16,
        "achiever_path": 12,
        "explorer_reward": 8,
        "survivor_recovery": 10,
        "speedrunner_lane": 8,
    }
    score = round(sum(metrics[key] * weights[key] for key in weights), 1)
    hard_constraints_passed = (
        len(roles) >= 3
        and len(layouts) >= 3
        and clear_placements
        and pacing
        and recovery_pickup is not None
        and optional_relic is not None
        and quest_funded
    )
    return {
        "score": score,
        "metrics": metrics,
        "passed": score >= 78 and hard_constraints_passed,
        "hard_constraints_passed": hard_constraints_passed,
    }


def search_action_rpg_plan(
    design_doc: dict, level_index: int, candidate_count: int = 24
) -> dict[str, Any]:
    """Generate, evaluate and select content instead of accepting first output."""
    if candidate_count < 2:
        raise ValueError("experience search requires at least two candidates")
    contract = build_action_rpg_experience_contract(design_doc, level_index)
    ranked: list[tuple[float, str, int, dict[str, Any], dict[str, Any]]] = []
    for candidate_index in range(candidate_count):
        plan = _candidate_plan(design_doc, level_index, candidate_index, contract)
        result = score_action_rpg_candidate(plan)
        signature = hashlib.sha256(
            json.dumps(plan["rooms"], sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        # Signature provides deterministic tie-breaking without always selecting
        # candidate zero when several candidates satisfy the same constraints.
        ranked.append((float(result["score"]), signature, candidate_index, plan, result))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    score, signature, candidate_index, selected, result = ranked[0]
    selected["experience_search"] = {
        "algorithm_version": 1,
        "candidates_evaluated": candidate_count,
        "selected_candidate": candidate_index,
        "selected_signature": signature,
        "score": score,
        "metrics": result["metrics"],
        "runner_up_score": ranked[1][0],
    }
    return selected
