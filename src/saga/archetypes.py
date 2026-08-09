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
    if template != "run_and_gun":
        return None
    return load_pack("run_and_gun")


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
    if len({str(item.get("role")) for item in enemies}) < 2:
        errors.append("at least two enemy roles are required")
    if not hazards:
        errors.append("at least one readable hazard is required")
    if not pickups:
        errors.append("at least one recovery pickup is required")
    if len(beats) < 5:
        errors.append("the stage needs spawn, escalation, checkpoint, gauntlet and boss beats")

    for collection_name, collection in (
        ("platform", platforms), ("enemy", enemies),
        ("hazard", hazards), ("pickup", pickups),
    ):
        for item in collection:
            x = float(item.get("x") or 0.0)
            if not 80.0 <= x <= width - 80.0:
                errors.append(f"{collection_name} x position is outside the playable world")
                break
    return errors


def build_run_and_gun_encounter_plan(design_doc: dict, level_index: int) -> dict:
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

    enemy_count = 4 + intensity // 2
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

    plan = {
        "schema_version": 1,
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
    }
    errors = validate_run_and_gun_encounter_plan(plan)
    if errors:  # This is studio-owned data; fail before generating a broken game.
        raise ValueError("invalid run-and-gun encounter plan: " + "; ".join(errors))
    return plan


def build_run_and_gun_adapter(
    design_doc: dict,
    level_index: int,
    asset_filenames: list[str],
) -> str:
    """Render the tiny game-specific layer consumed by the stable pack."""
    levels = design_doc.get("levels") or [{}]
    level = levels[min(level_index, len(levels) - 1)]
    intensity = max(1, min(10, int(level.get("intensity") or 5)))
    hero = _asset_with(asset_filenames, "hero_sprite", "hero")
    hero_walk = _asset_with(asset_filenames, "hero_walk") or hero
    background = _asset_with(asset_filenames, f"level_{level_index}_", "level_")
    enemy = _asset_with(asset_filenames, "enemy", "soldier", "guard", "drone")
    boss = _asset_with(asset_filenames, "boss", "commander", "titan") or enemy
    checkpoint = _asset_with(asset_filenames, "key_item", "checkpoint", "beacon")
    encounter_plan = build_run_and_gun_encounter_plan(design_doc, level_index)
    definition = {
        "pack_version": 2,
        "title": str(design_doc.get("title") or "Run and Gun"),
        "level_name": str(level.get("name") or f"Level {level_index + 1}"),
        "intensity": intensity,
        "world_width": encounter_plan["world_width"],
        "enemy_count": len(encounter_plan["enemy_spawns"]),
        "player_health": max(3, 7 - intensity // 2),
        "enemy_health": 1 + intensity // 4,
        "boss_health": 6 + intensity * 2,
        "move_speed": 230.0 + intensity * 4.0,
        "enemy_speed": 65.0 + intensity * 7.0,
        "projectile_speed": 620.0 + intensity * 18.0,
        "encounter_plan": encounter_plan,
        "assets": {
            "hero": f"res://assets/{hero}" if hero else "",
            "hero_walk": f"res://assets/{hero_walk}" if hero_walk else "",
            "background": f"res://assets/{background}" if background else "",
            "enemy": f"res://assets/{enemy}" if enemy else "",
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
) -> ArchetypePack:
    pack = scaffold_pack(project_dir, "run_and_gun")
    if pack is None:  # pragma: no cover - protected by the fixed template above
        raise ValueError("run_and_gun archetype is unavailable")
    adapter = build_run_and_gun_adapter(design_doc, level_index, asset_filenames)
    (Path(project_dir) / f"Level_{level_index}.gd").write_text(adapter, encoding="utf-8")
    return pack
