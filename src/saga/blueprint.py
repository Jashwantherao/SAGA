"""Game Blueprint - the machine-verifiable systems contract for Agent Team v2.

The design doc answers "what game is this?". The blueprint answers "what
systems must exist, in what order, and how is each one proven?". Every
system carries its own acceptance criteria and an explicit dependency
list, so specialist builder agents can implement one system at a time
against a shared contract instead of one coder regenerating the whole
game and gambling on the basics every run.

The live graph creates this contract after game design and before assets or
code.  The Coder receives the ordered acceptance criteria as immutable
context, while the compiled plan records which specialist model should own
each system once protected incremental builders are enabled.
"""

import json
import re
from pathlib import Path

from saga.router import candidates


BLUEPRINT_VERSION = 1

# One system = one buildable, provable unit. Kinds are deliberately
# coarse: they key model routing (saga.router) and, later, QA probe
# selection - they do not dictate code layout.
SYSTEM_KINDS = [
    "movement",
    "camera",
    "combat",
    "enemy_ai",
    "pickup",
    "inventory",
    "dialogue",
    "quest",
    "progression",
    "save_load",
    "level_transition",
    "boss",
    "hud",
    # Current arcade templates need first-class system names too. Treating a
    # resource drain or a maze as a generic "pickup" loses the very contract
    # evidence the blueprint is meant to preserve.
    "objective",
    "resource",
    "hazard",
    "switch",
    "zone_control",
    "herding",
    "maze",
]

# System ids and entity names travel through prompts, filenames and QA
# evidence, so they get the same slug discipline as extra sprites.
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

REQUIRED_FIELDS = [
    "blueprint_version",
    "title",
    "premise",
    "core_loop",
    "win_condition",
    "lose_condition",
    "player",
    "systems",
]


def validate_blueprint(bp: dict) -> list[str]:
    """Structural checks, returned as a problem list so a corrective retry
    can quote them verbatim - the same contract as the design doc validator."""
    problems = []
    for key in REQUIRED_FIELDS:
        if not bp.get(key):
            problems.append(f"missing or empty field {key!r}")

    version = bp.get("blueprint_version")
    if version is not None and version != BLUEPRINT_VERSION:
        problems.append(
            f"blueprint_version must be {BLUEPRINT_VERSION}, got {version!r}"
        )

    player = bp.get("player") or {}
    if not player.get("controls"):
        problems.append("player.controls must list every input the game responds to")
    if not isinstance(player.get("abilities", []), list):
        problems.append("player.abilities must be a list (use [] if none)")

    for i, entity in enumerate(bp.get("entities") or []):
        name = entity.get("name", "")
        if not SLUG_RE.match(str(name)):
            problems.append(f"entities[{i}].name {name!r} must be a lowercase slug")
        if not entity.get("description"):
            problems.append(f"entities[{i}].description is required")
        if not entity.get("ai_states"):
            problems.append(f"entities[{i}].ai_states must name at least one state")

    systems = bp.get("systems") or []
    if not 3 <= len(systems) <= 12:
        problems.append(
            f"systems must contain 3-12 buildable systems, got {len(systems)}"
        )
    seen_ids = set()
    for i, system in enumerate(systems):
        sid = system.get("id", "")
        if not SLUG_RE.match(str(sid)):
            problems.append(f"systems[{i}].id {sid!r} must be a lowercase slug")
        elif sid in seen_ids:
            problems.append(f"duplicate system id {sid!r}")
        seen_ids.add(sid)
        if system.get("kind") not in SYSTEM_KINDS:
            problems.append(f"systems[{i}].kind must be one of {SYSTEM_KINDS}")
        if not system.get("description"):
            problems.append(f"systems[{i}].description is required")
        acceptance = system.get("acceptance") or []
        if not acceptance or not all(isinstance(item, str) and item.strip() for item in acceptance):
            problems.append(
                f"systems[{i}] ({sid!r}) needs at least one concrete acceptance criterion"
            )
        for dep in system.get("depends_on") or []:
            if dep not in seen_ids:
                problems.append(
                    f"systems[{i}] ({sid!r}) depends on {dep!r}, which is not declared earlier"
                )

    if bp.get("save_state") and not any(
        system.get("kind") == "save_load" for system in systems
    ):
        problems.append("save_state is declared but no save_load system exists to honor it")

    if not problems and systems:
        try:
            build_order(systems)
        except ValueError as exc:
            problems.append(str(exc))

    # Legacy bridge: a blueprint may embed a classic design doc so the
    # current asset and level pipeline keeps working during the migration.
    supplied_doc = bp.get("design_doc")
    if supplied_doc:
        from saga.agents.game_designer import _validate

        levels = supplied_doc.get("levels") or []
        for problem in _validate(supplied_doc, len(levels) or None):
            problems.append(f"design_doc: {problem}")

    return problems


def build_order(systems: list[dict]) -> list[str]:
    """Dependency-respecting build order; declaration order breaks ties so
    the plan is deterministic. Raises ValueError on a cycle - a blueprint
    that cannot be built in some order is a contract bug, not a runtime
    condition to work around."""
    ids = [system["id"] for system in systems]
    remaining = {
        system["id"]: set(system.get("depends_on") or []) for system in systems
    }
    order = []
    while remaining:
        ready = [sid for sid in ids if sid in remaining and not remaining[sid]]
        if not ready:
            stuck = sorted(remaining)
            raise ValueError(f"dependency cycle among systems {stuck}")
        for sid in ready:
            order.append(sid)
            del remaining[sid]
            for deps in remaining.values():
                deps.discard(sid)
    return order


def compile_build_plan(
    bp: dict,
    overrides: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Compile the architect's systems into an executable-order handoff.

    This is intentionally data, not hidden routing state: run manifests show
    which model was recommended for each system and which fallbacks were
    available, making future specialist-builder decisions auditable.
    """
    by_id = {system["id"]: system for system in bp.get("systems") or []}
    plan = []
    for index, system_id in enumerate(build_order(list(by_id.values()))):
        system = by_id[system_id]
        routed = candidates(system["kind"], overrides)
        plan.append(
            {
                "step": index + 1,
                "system_id": system_id,
                "kind": system["kind"],
                "depends_on": list(system.get("depends_on") or []),
                "recommended_model": routed[0],
                "fallback_models": routed[1:],
                "acceptance": list(system.get("acceptance") or []),
            }
        )
    return plan


def load_blueprint(path: str | Path) -> dict:
    """Read and validate a blueprint file; invalid contracts fail loudly
    before any model call is spent on them."""
    bp = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = validate_blueprint(bp)
    if problems:
        raise ValueError(f"invalid blueprint {Path(path).name}: {problems}")
    return bp
