"""Reusable Godot archetype packs.

Unlike SAGA's classic mechanic few-shots, an archetype pack is executable
engine code owned by the studio.  The model (or deterministic adapter) supplies
only a small level definition while tested player, combat, AI, checkpoint and
boss modules remain identical across productions.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil


PACK_ROOT = Path(__file__).resolve().parent / "archetype_packs"


@dataclass(frozen=True)
class ArchetypePack:
    id: str
    version: int
    mechanic_template: str
    capabilities: tuple[str, ...]
    required_files: tuple[str, ...]
    root: Path


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"archetype file escapes its pack: {relative!r}") from exc
    return candidate


def load_pack(pack_id: str) -> ArchetypePack:
    root = (PACK_ROOT / pack_id).resolve()
    manifest_path = _inside(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = tuple(manifest.get("required_files") or ())
    if not required:
        raise ValueError(f"archetype {pack_id!r} declares no required files")
    missing = [relative for relative in required if not _inside(root, relative).is_file()]
    if missing:
        raise ValueError(f"archetype {pack_id!r} is missing required files: {missing}")
    return ArchetypePack(
        id=str(manifest["id"]),
        version=int(manifest["version"]),
        mechanic_template=str(manifest["mechanic_template"]),
        capabilities=tuple(str(item) for item in manifest.get("capabilities") or ()),
        required_files=required,
        root=root,
    )


def pack_for_template(template: str) -> ArchetypePack | None:
    pack_id = {
        "run_and_gun": "run_and_gun",
        "action_rpg": "action_rpg",
    }.get(template)
    return load_pack(pack_id) if pack_id else None


def scaffold_pack(project_dir: str | Path, template: str) -> ArchetypePack | None:
    pack = pack_for_template(template)
    if pack is None:
        return None
    destination = Path(project_dir) / "archetypes" / pack.id
    destination.mkdir(parents=True, exist_ok=True)
    for relative in pack.required_files:
        source = _inside(pack.root, relative)
        target = _inside(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # Runtime provenance belongs beside the copied code, not only in run.json.
    shutil.copy2(pack.root / "manifest.json", destination / "manifest.json")
    return pack


def _asset_with(asset_filenames: list[str], *needles: str) -> str:
    lowered = [(name, name.lower()) for name in asset_filenames]
    for needle in needles:
        for original, lower in lowered:
            if needle in lower:
                return original
    return ""


RUN_AND_GUN_LAYOUTS = ("rising_routes", "broken_bridge", "switchbacks")
RUN_AND_GUN_ROLE_COSTS = {
    "scout": 1,
    "hunter": 2,
    "turret": 2,
    "flyer": 2,
    "bruiser": 3,
}
RUN_AND_GUN_WEAPONS = ("pulse", "spread", "launcher")


def validate_run_and_gun_encounter_plan(plan: dict) -> list[str]:
    """Validate playable structural invariants before a plan reaches Godot."""
    errors: list[str] = []
    width = float(plan.get("world_width") or 0.0)
    checkpoint_x = float(plan.get("checkpoint_x") or 0.0)
    boss_arena = plan.get("boss_arena") or {}
    boss_start = float(boss_arena.get("start") or 0.0)
    platforms = plan.get("platforms") or []
    enemies = plan.get("enemy_spawns") or []
    hazards = plan.get("hazards") or []
    pickups = plan.get("pickups") or []
    beats = plan.get("encounter_beats") or []
    combat = plan.get("combat_plan") or {}
    waves = combat.get("waves") or []
    weapon_pickups = combat.get("weapon_pickups") or []

    if plan.get("layout_id") not in RUN_AND_GUN_LAYOUTS:
        errors.append("layout_id must name a supported topology")
    if width < 1600.0:
        errors.append("world_width must leave room for traversal and a boss arena")
    if not 500.0 < checkpoint_x < boss_start < width - 100.0:
        errors.append("checkpoint and boss arena must progress from left to right")
    if len(platforms) < 3:
        errors.append("at least three traversal platforms are required")
    if len(enemies) < 3:
        errors.append("at least three enemy encounters are required")
    all_roles = {
        str(item.get("role")) for item in enemies
    } | {
        str(member.get("role"))
        for wave in waves
        for member in (wave.get("members") or [])
    }
    if len(all_roles) < 4:
        errors.append("at least four enemy roles are required across the stage")
    if len({str(item.get("role")) for item in enemies}) < 2:
        errors.append("at least two enemy roles are required")
    if not hazards:
        errors.append("at least one readable hazard is required")
    if not pickups:
        errors.append("at least one recovery pickup is required")
    if len(beats) < 5:
        errors.append("the stage needs spawn, escalation, checkpoint, gauntlet and boss beats")
    if len(waves) < 2:
        errors.append("at least two bounded combat waves are required")
    pickup_weapons = {str(item.get("weapon")) for item in weapon_pickups}
    if not {"spread", "launcher"} <= pickup_weapons:
        errors.append("spread and launcher pickups are required")
    threat_limit = int(combat.get("threat_budget_limit") or 0)
    threat_spent = 0
    for wave in waves:
        members = wave.get("members") or []
        calculated = sum(
            RUN_AND_GUN_ROLE_COSTS.get(str(member.get("role")), 99)
            for member in members
        )
        declared = int(wave.get("threat_budget") or 0)
        if calculated != declared:
            errors.append("wave threat budget must equal the cost of its members")
            break
        threat_spent += calculated
    if threat_limit <= 0 or threat_spent > threat_limit:
        errors.append("combat waves exceed the stage threat budget")

    for collection_name, collection in (
        ("platform", platforms), ("enemy", enemies),
        ("hazard", hazards), ("pickup", pickups),
        ("weapon pickup", weapon_pickups),
    ):
        for item in collection:
            x = float(item.get("x") or 0.0)
            if not 80.0 <= x <= width - 80.0:
                errors.append(f"{collection_name} x position is outside the playable world")
                break
    return errors


def _run_and_gun_candidate(
    design_doc: dict, level_index: int, candidate_index: int
) -> dict:
    """Create deterministic authored-feeling stage structure from the brief.

    The plan is data, not generated GDScript. A stable digest selects one of
    several topology grammars, so repeated builds are reproducible while
    different premises and levels do not collapse into the same arrangement.
    """
    levels = design_doc.get("levels") or [{}]
    level = levels[min(level_index, len(levels) - 1)]
    intensity = max(1, min(10, int(level.get("intensity") or 5)))
    identity = "|".join((
        str(design_doc.get("title") or "Run and Gun"),
        str(level.get("name") or f"Level {level_index + 1}"),
        str(level.get("description") or ""),
        str(level_index),
        str(candidate_index),
    ))
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    layout_id = RUN_AND_GUN_LAYOUTS[digest[0] % len(RUN_AND_GUN_LAYOUTS)]
    world_width = 1900.0 + intensity * 95.0
    checkpoint_x = round(world_width * (0.48 + (digest[1] % 7) / 100.0), 1)
    boss_start = world_width - 470.0
    platform_count = 4 + intensity // 3
    platform_span = (boss_start - 420.0) / max(platform_count, 1)
    height_patterns = {
        "rising_routes": (455.0, 405.0, 350.0, 420.0, 330.0, 390.0, 315.0),
        "broken_bridge": (430.0, 365.0, 445.0, 340.0, 425.0, 355.0, 410.0),
        "switchbacks": (455.0, 350.0, 430.0, 325.0, 405.0, 345.0, 440.0),
    }
    heights = height_patterns[layout_id]
    platforms = []
    for index in range(platform_count):
        width = 185.0 + float((digest[(index + 2) % len(digest)] % 5) * 24)
        platforms.append({
            "id": f"route_{index + 1}",
            "x": round(360.0 + platform_span * index, 1),
            "y": heights[index % len(heights)],
            "width": width,
            "height": 22.0,
        })

    enemy_count = 2 + intensity // 4
    roles = ("scout", "bruiser", "hunter")
    enemy_spawns = []
    enemy_span = (boss_start - 560.0) / max(enemy_count - 1, 1)
    for index in range(enemy_count):
        role = roles[(index + digest[3]) % len(roles)]
        enemy_spawns.append({
            "id": f"enemy_{index + 1}",
            "x": round(460.0 + enemy_span * index, 1),
            "y": 500.0,
            "role": role,
        })

    hazard_count = 1 + intensity // 4
    hazards = []
    for index in range(hazard_count):
        fraction = (index + 1) / (hazard_count + 1)
        x = 650.0 + (boss_start - 1000.0) * fraction
        if abs(x - checkpoint_x) < 150.0:
            x += 180.0
        hazards.append({
            "id": f"hazard_{index + 1}",
            "x": round(min(x, boss_start - 130.0), 1),
            "y": 516.0,
            "width": 74.0 + float((digest[index + 8] % 3) * 18),
            "damage": 1,
        })

    pickups = [{
        "id": "recovery_1",
        "x": round(checkpoint_x - 120.0, 1),
        "y": 465.0,
        "kind": "health",
        "amount": 2,
    }]
    if intensity >= 7:
        pickups.append({
            "id": "recovery_2",
            "x": round(boss_start - 150.0, 1),
            "y": 465.0,
            "kind": "health",
            "amount": 1,
        })

    # Simultaneous bodies are capped deliberately. Filling a numeric budget to
    # the last point produced crowded, unfair arenas even though the accounting
    # looked valid in QA.
    threat_limit = 10 + intensity * 2
    wave_members = [
        [{"role": "scout"}, {"role": "turret"}, {"role": "scout"}],
        [{"role": "flyer"}, {"role": "bruiser"}, {"role": "hunter"}],
    ]
    threat_spent = sum(
        RUN_AND_GUN_ROLE_COSTS[member["role"]]
        for members in wave_members for member in members
    )
    if intensity >= 8:
        expansion_roles = ("scout", "hunter", "turret", "flyer")
        for wave_index in range(2):
            role = expansion_roles[(digest[10] + wave_index) % len(expansion_roles)]
            cost = RUN_AND_GUN_ROLE_COSTS[role]
            if threat_spent + cost <= threat_limit:
                wave_members[wave_index].append({"role": role})
                threat_spent += cost

    waves = []
    wave_specs = (
        ("bridge_lock", world_width * 0.32, world_width * 0.24, world_width * 0.53),
        ("final_gauntlet", checkpoint_x + 190.0, checkpoint_x + 80.0, boss_start - 30.0),
    )
    for index, (wave_id, trigger_x, lock_start, lock_end) in enumerate(wave_specs):
        members = wave_members[index]
        member_spacing = min(95.0, (lock_end - trigger_x - 240.0) / max(len(members) - 1, 1))
        rendered_members = []
        for member_index, member in enumerate(members):
            rendered_members.append({
                "id": f"{wave_id}_{member_index + 1}",
                "role": member["role"],
                "x": round(min(lock_end - 70.0, trigger_x + 210.0 + member_index * member_spacing), 1),
                "y": 430.0 if member["role"] == "flyer" else 500.0,
            })
        waves.append({
            "id": wave_id,
            "trigger_x": round(trigger_x, 1),
            "lock_start": round(lock_start, 1),
            "lock_end": round(lock_end, 1),
            "threat_budget": sum(RUN_AND_GUN_ROLE_COSTS[item["role"]] for item in members),
            "members": rendered_members,
        })

    combat_plan = {
        "schema_version": 1,
        "default_weapon": "pulse",
        "weapon_pickups": [
            {
                "id": "spread_cache",
                "weapon": "spread",
                "ammo": 18,
                "x": 570.0,
                "y": 465.0,
            },
            {
                "id": "launcher_cache",
                "weapon": "launcher",
                "ammo": 6,
                "x": round(checkpoint_x + 175.0, 1),
                "y": 465.0,
            },
        ],
        "waves": waves,
        "threat_budget_limit": threat_limit,
        "threat_budget_spent": threat_spent,
        "enemy_roles": sorted({
            item["role"] for item in enemy_spawns
        } | {
            member["role"] for wave in waves for member in wave["members"]
        }),
    }

    plan = {
        "schema_version": 2,
        "compiler": {
            "id": "encounter_progression",
            "version": 1,
            "candidate_index": candidate_index,
        },
        "layout_id": layout_id,
        "seed": digest.hex()[:16],
        "world_width": world_width,
        "checkpoint_x": checkpoint_x,
        "platforms": platforms,
        "enemy_spawns": enemy_spawns,
        "hazards": hazards,
        "pickups": pickups,
        "encounter_beats": [
            {"id": "arrival", "kind": "spawn", "start": 0.0, "end": 360.0},
            {"id": "first_contact", "kind": "skirmish", "start": 360.0, "end": checkpoint_x - 180.0},
            {"id": "relay", "kind": "checkpoint", "start": checkpoint_x - 180.0, "end": checkpoint_x + 140.0},
            {"id": "pressure_lane", "kind": "gauntlet", "start": checkpoint_x + 140.0, "end": boss_start},
            {"id": "commander", "kind": "boss", "start": boss_start, "end": world_width},
        ],
        "boss_arena": {"start": boss_start, "end": world_width, "spawn_x": world_width - 190.0},
        "combat_plan": combat_plan,
    }
    errors = validate_run_and_gun_encounter_plan(plan)
    if errors:  # This is studio-owned data; fail before generating a broken game.
        raise ValueError("invalid run-and-gun encounter plan: " + "; ".join(errors))
    return plan


def score_run_and_gun_candidate(plan: dict) -> dict:
    combat = plan.get("combat_plan") or {}
    waves = combat.get("waves") or []
    roles = set(combat.get("enemy_roles") or [])
    checkpoint = float(plan.get("checkpoint_x") or 0.0)
    boss_start = float((plan.get("boss_arena") or {}).get("start") or 0.0)
    recovery = [
        float(item.get("x") or 0.0)
        for item in plan.get("pickups") or []
        if item.get("kind") == "health"
    ]
    platform_x = sorted(float(item.get("x") or 0.0) for item in plan.get("platforms") or [])
    gaps = [later - earlier for earlier, later in zip(platform_x, platform_x[1:])]
    max_gap = max(gaps, default=999.0)
    hazard_distances = [
        min(abs(float(item.get("x") or 0.0) - point) for point in (0.0, checkpoint, boss_start))
        for item in plan.get("hazards") or []
    ]
    fair_hazards = all(distance >= 90.0 for distance in hazard_distances)
    preboss_recovery = any(checkpoint - 180.0 <= point < boss_start for point in recovery)
    threat_limit = int(combat.get("threat_budget_limit") or 0)
    threat_spent = int(combat.get("threat_budget_spent") or 0)
    metrics = {
        "role_diversity": min(1.0, len(roles) / 4.0),
        "route_continuity": min(1.0, 280.0 / max(280.0, max_gap)),
        "hazard_fairness": 1.0 if fair_hazards else 0.0,
        "survivor_recovery": 1.0 if preboss_recovery else 0.0,
        "pressure_use": min(1.0, (threat_spent / max(1, threat_limit)) / 0.65),
        "weapon_expression": min(1.0, len(combat.get("weapon_pickups") or []) / 2.0),
    }
    weights = {
        "role_diversity": 20, "route_continuity": 20, "hazard_fairness": 18,
        "survivor_recovery": 16, "pressure_use": 14, "weapon_expression": 12,
    }
    score = round(sum(metrics[name] * weight for name, weight in weights.items()), 1)
    personas = {
        "achiever": {"passed": len(waves) >= 2 and boss_start > checkpoint, "waves": len(waves)},
        "explorer": {"passed": len(combat.get("weapon_pickups") or []) >= 2, "weapon_caches": len(combat.get("weapon_pickups") or [])},
        "survivor": {"passed": preboss_recovery and fair_hazards, "preboss_recovery": preboss_recovery},
        "speedrunner": {"passed": max_gap <= 360.0, "largest_route_gap": round(max_gap, 1)},
    }
    return {
        "score": score,
        "metrics": metrics,
        "personas": personas,
        "telemetry": {
            "stage_width": plan.get("world_width"),
            "encounter_count": len(plan.get("enemy_spawns") or []) + len(waves),
            "enemy_count": len(plan.get("enemy_spawns") or []) + sum(len(wave.get("members") or []) for wave in waves),
            "optional_discoveries": len(combat.get("weapon_pickups") or []),
            "largest_route_gap": round(max_gap, 1),
            "threat_budget_used": threat_spent,
            "threat_budget_limit": threat_limit,
        },
        "passed": score >= 78 and all(item["passed"] for item in personas.values()),
    }


def build_run_and_gun_encounter_plan(
    design_doc: dict, level_index: int, candidate_count: int = 16
) -> dict:
    """Search several safe stage candidates and retain critic provenance."""
    if candidate_count < 2:
        raise ValueError("run-and-gun candidate search requires at least two candidates")
    ranked = []
    for candidate_index in range(candidate_count):
        plan = _run_and_gun_candidate(design_doc, level_index, candidate_index)
        result = score_run_and_gun_candidate(plan)
        signature = hashlib.sha256(
            json.dumps(plan, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        ranked.append((bool(result["passed"]), float(result["score"]), signature, plan, result))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    passed, score, signature, selected, result = ranked[0]
    selected["experience_search"] = {
        "algorithm_version": 2,
        "candidates_evaluated": candidate_count,
        "repairs_evaluated": 0,
        "selected_candidate": selected["compiler"]["candidate_index"],
        "selected_after_repair": False,
        "selected_signature": signature,
        "score": score,
        "metrics": result["metrics"],
        "personas": result["personas"],
        "telemetry": result["telemetry"],
        "runner_up_score": ranked[1][1],
    }
    if not passed:
        raise ValueError("no run-and-gun candidate passed the experience floor")
    return selected


def build_run_and_gun_adapter(
    design_doc: dict,
    level_index: int,
    asset_filenames: list[str],
    plan: dict | None = None,
) -> str:
    """Render the tiny game-specific layer consumed by the stable pack."""
    levels = design_doc.get("levels") or [{}]
    level = levels[min(level_index, len(levels) - 1)]
    intensity = max(1, min(10, int(level.get("intensity") or 5)))
    hero = _asset_with(asset_filenames, "hero_sprite", "hero")
    hero_walk = _asset_with(asset_filenames, "hero_walk") or hero
    background = _asset_with(asset_filenames, f"level_{level_index}_", "level_")
    enemy = _asset_with(asset_filenames, "enemy", "soldier", "guard", "drone")
    scout = _asset_with(asset_filenames, "scout", "runner", "guard") or enemy
    bruiser = _asset_with(asset_filenames, "bruiser", "heavy", "tank") or enemy
    hunter = _asset_with(asset_filenames, "hunter", "sniper", "shooter") or enemy
    turret = _asset_with(asset_filenames, "turret", "cannon", "sentry") or enemy
    flyer = _asset_with(asset_filenames, "flyer", "flying", "aerial", "drone") or enemy
    boss = _asset_with(asset_filenames, "boss", "commander", "titan") or enemy
    checkpoint = _asset_with(asset_filenames, "key_item", "checkpoint", "beacon")
    encounter_plan = plan or build_run_and_gun_encounter_plan(design_doc, level_index)
    definition = {
        "pack_version": 7,
        "title": str(design_doc.get("title") or "Run and Gun"),
        "level_name": str(level.get("name") or f"Level {level_index + 1}"),
        "level_index": level_index,
        "total_levels": len(levels),
        "has_next_level": level_index + 1 < len(levels),
        "intensity": intensity,
        "world_width": encounter_plan["world_width"],
        "enemy_count": len(encounter_plan["enemy_spawns"]),
        "player_health": max(3, 7 - intensity // 2),
        "enemy_health": 1 + intensity // 4,
        "boss_health": 6 + intensity * 2,
        "move_speed": 230.0 + intensity * 4.0,
        "enemy_speed": 65.0 + intensity * 7.0,
        "projectile_speed": 620.0 + intensity * 18.0,
        "progression": {
            "reward_id": f"level_{level_index}_boss",
            "currency_reward": 14 + intensity * 2,
            "xp_reward": 20 + intensity * 4,
            "upgrade_cost": 10 + level_index * 2,
        },
        "encounter_plan": encounter_plan,
        "assets": {
            "hero": f"res://assets/{hero}" if hero else "",
            "hero_walk": f"res://assets/{hero_walk}" if hero_walk else "",
            "background": f"res://assets/{background}" if background else "",
            "enemy": f"res://assets/{enemy}" if enemy else "",
            "enemy_scout": f"res://assets/{scout}" if scout else "",
            "enemy_bruiser": f"res://assets/{bruiser}" if bruiser else "",
            "enemy_hunter": f"res://assets/{hunter}" if hunter else "",
            "enemy_turret": f"res://assets/{turret}" if turret else "",
            "enemy_flyer": f"res://assets/{flyer}" if flyer else "",
            "boss": f"res://assets/{boss}" if boss else "",
            "checkpoint": f"res://assets/{checkpoint}" if checkpoint else "",
        },
    }
    payload = json.dumps(definition, ensure_ascii=False, indent=2)
    return (
        'extends "res://archetypes/run_and_gun/run_and_gun_level.gd"\n\n'
        "# Game-specific adapter. Stable gameplay lives in the versioned pack.\n"
        "func level_definition() -> Dictionary:\n"
        f"\treturn JSON.parse_string({json.dumps(payload)})\n"
    )


def scaffold_run_and_gun_level(
    project_dir: str | Path,
    design_doc: dict,
    level_index: int,
    asset_filenames: list[str],
    plan: dict | None = None,
) -> ArchetypePack:
    pack = scaffold_pack(project_dir, "run_and_gun")
    if pack is None:  # pragma: no cover - protected by the fixed template above
        raise ValueError("run_and_gun archetype is unavailable")
    adapter = build_run_and_gun_adapter(
        design_doc, level_index, asset_filenames, plan=plan
    )
    (Path(project_dir) / f"Level_{level_index}.gd").write_text(adapter, encoding="utf-8")
    return pack


def validate_action_rpg_plan(plan: dict) -> list[str]:
    """Reject an RPG shell that lacks a complete explore-to-boss loop."""
    errors: list[str] = []
    rooms = plan.get("rooms") or []
    if not 4 <= len(rooms) <= 6:
        errors.append("action RPG v4 requires four to six connected rooms")
    if [room.get("index") for room in rooms] != list(range(len(rooms))):
        errors.append("room indices must be contiguous from zero")
    total_sparks = sum(
        int(pickup.get("amount") or 0)
        for room in rooms
        for pickup in (room.get("pickups") or [])
        if pickup.get("kind") == "sparks"
    )
    quest_cost = int((plan.get("quest") or {}).get("spark_cost") or 0)
    if quest_cost < 1 or total_sparks < quest_cost:
        errors.append("reachable spark pickups must fund the quest")
    if not any(room.get("npc") for room in rooms):
        errors.append("at least one room must contain the quest NPC")
    if not (rooms and rooms[-1].get("boss")):
        errors.append("the final room must contain the boss")
    if len(plan.get("quest_stages") or []) < 4:
        errors.append("quest must expose collect, return, forge-open and complete stages")
    if int(plan.get("schema_version") or 0) >= 2:
        from saga.experience import score_action_rpg_candidate

        search = plan.get("experience_search") or {}
        if int(search.get("candidates_evaluated") or 0) < 2:
            errors.append("experience search must evaluate multiple candidates")
        roles = {
            str(enemy.get("role") or "")
            for room in rooms
            for enemy in (room.get("enemies") or [])
        }
        if len(roles) < 3:
            errors.append("action RPG encounters require at least three enemy roles")
        if len({str(room.get("layout_id") or "") for room in rooms}) < 4:
            errors.append("action RPG journey requires at least four spatial layouts")
        if not score_action_rpg_candidate(plan)["passed"]:
            errors.append("action RPG experience score is below the playable quality floor")
    if int(plan.get("schema_version") or 0) >= 3:
        compiler = plan.get("compiler") or {}
        if compiler.get("id") != "encounter_progression":
            errors.append("action RPG v4 requires the encounter progression compiler")
        world = plan.get("world_graph") or {}
        edges = world.get("edges") or []
        if len(edges) != max(0, len(rooms) - 1):
            errors.append("world graph must connect every authored room")
        search = plan.get("experience_search") or {}
        personas = search.get("personas") or {}
        if set(personas) != {"achiever", "explorer", "survivor", "speedrunner"}:
            errors.append("all four persona critics must report evidence")
        elif not all(bool(item.get("passed")) for item in personas.values()):
            errors.append("every persona critic must pass before selection")
    if int(plan.get("schema_version") or 0) >= 4:
        narrative = plan.get("narrative") or {}
        required_narrative = {
            "quest_title", "currency_name", "quest_giver_name", "boss_name", "enemy_name",
            "relic_name", "ability_name", "collect_objective", "return_objective",
            "boss_objective", "victory_text", "source_fingerprint",
        }
        if any(not str(narrative.get(field) or "").strip() for field in required_narrative):
            errors.append("narrative compiler must provide every player-facing identity field")
        room_names = narrative.get("room_names") or []
        if len(room_names) != len(rooms) or [room.get("name") for room in rooms] != room_names:
            errors.append("compiled room names must match the narrative contract")
        npc_data = next((room.get("npc") for room in rooms if room.get("npc")), {})
        if not isinstance(npc_data, dict) or npc_data.get("name") != narrative.get("quest_giver_name"):
            errors.append("quest NPC identity must match the narrative contract")
        boss_data = (rooms[-1].get("boss") if rooms else {}) or {}
        if boss_data.get("name") != narrative.get("boss_name"):
            errors.append("boss identity must match the narrative contract")
        if (plan.get("compiler") or {}).get("version") != 2:
            errors.append("action RPG narrative ContentIR requires compiler version 2")
    return errors


def build_action_rpg_plan(design_doc: dict, level_index: int) -> dict:
    from saga.experience import search_action_rpg_plan

    plan = search_action_rpg_plan(design_doc, level_index)
    errors = validate_action_rpg_plan(plan)
    if errors:
        raise ValueError("invalid action-RPG plan: " + "; ".join(errors))
    return plan


def build_action_rpg_adapter(
    design_doc: dict,
    level_index: int,
    asset_filenames: list[str],
    plan: dict | None = None,
) -> str:
    levels = design_doc.get("levels") or [{}]
    level = levels[min(level_index, len(levels) - 1)]
    intensity = max(1, min(10, int(level.get("intensity") or 5)))
    hero = _asset_with(asset_filenames, "hero_sprite", "hero")
    background = _asset_with(asset_filenames, f"level_{level_index}_", "level_")
    enemy = _asset_with(
        asset_filenames,
        "stalker", "sentinel", "skirmisher", "bruiser", "guard", "enemy", "creature", "thorn",
    )
    boss = _asset_with(asset_filenames, "boss", "warden", "golem") or enemy
    npc = _asset_with(
        asset_filenames,
        "hermit", "archivist", "keeper", "merchant", "guide", "npc",
    )
    pickup = _asset_with(asset_filenames, "key_item", "spark", "charm")
    role_assets = {
        role: _asset_with(asset_filenames, role) or enemy
        for role in ("stalker", "sentinel", "skirmisher", "bruiser", "guard")
    }
    plan = plan or build_action_rpg_plan(design_doc, level_index)
    errors = validate_action_rpg_plan(plan)
    if errors:
        raise ValueError("invalid action-RPG plan: " + "; ".join(errors))
    definition = {
        "pack_version": 5,
        "title": str(design_doc.get("title") or "Action RPG"),
        "level_name": str(level.get("name") or f"Level {level_index + 1}"),
        "level_index": level_index,
        "total_levels": len(levels),
        "intensity": intensity,
        "player_health": max(4, 7 - intensity // 3),
        "move_speed": 175.0 + intensity * 3.0,
        "room_plan": plan,
        "assets": {
            "hero": f"res://assets/{hero}" if hero else "",
            "background": f"res://assets/{background}" if background else "",
            "enemy": f"res://assets/{enemy}" if enemy else "",
            **{
                f"enemy_{role}": f"res://assets/{filename}" if filename else ""
                for role, filename in role_assets.items()
            },
            "boss": f"res://assets/{boss}" if boss else "",
            "npc": f"res://assets/{npc}" if npc else "",
            "pickup": f"res://assets/{pickup}" if pickup else "",
        },
    }
    payload = json.dumps(definition, ensure_ascii=False, indent=2)
    return (
        'extends "res://archetypes/action_rpg/action_rpg_level.gd"\n\n'
        "# Game-specific adapter. Stable RPG systems live in the versioned pack.\n"
        "func level_definition() -> Dictionary:\n"
        f"\treturn JSON.parse_string({json.dumps(payload)})\n"
    )


def scaffold_action_rpg_level(
    project_dir: str | Path,
    design_doc: dict,
    level_index: int,
    asset_filenames: list[str],
    plan: dict | None = None,
) -> ArchetypePack:
    pack = scaffold_pack(project_dir, "action_rpg")
    if pack is None:  # pragma: no cover - protected by the fixed template above
        raise ValueError("action_rpg archetype is unavailable")
    adapter = build_action_rpg_adapter(
        design_doc, level_index, asset_filenames, plan=plan
    )
    (Path(project_dir) / f"Level_{level_index}.gd").write_text(adapter, encoding="utf-8")
    return pack
