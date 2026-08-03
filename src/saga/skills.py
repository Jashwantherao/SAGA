"""Curated gamedev skill context, routed by blueprint system kind.

The vendored corpus (vendor/gamedev-skills, Apache-2.0, pinned - see
scripts/vendor_skills.py) carries one SKILL.md per topic. Handing all of them
to a specialist would be worse than handing it none: the local 14B Coder
already drops declarations once a prompt grows past its comfortable few-shot
size, so this module practises the same progressive disclosure the upstream
router does - two skills for the kind being built, and nothing else.

Skills are *knowledge*, not capability. Injecting the rpg skill does not give
SAGA inventories; the scope firewall still decides which kinds the pipeline
can actually build and verify. And because several skills assume a project of
many scripts and resources while SAGA's template Coder emits one Level_N.gd,
callers must append their harness rules *after* skill_context(), never before.

Off by default (SAGA_SKILL_CONTEXT=1 to enable) until an A/B benchmark says
the extra prompt earns its tokens.
"""

from functools import lru_cache
from pathlib import Path

from saga.config import settings

VENDOR_ROOT = Path(__file__).resolve().parent.parent.parent / "vendor" / "gamedev-skills"

# One route per task kind: the blueprint's SYSTEM_KINDS plus the pipeline
# tasks that are not buildable systems, mirroring saga.router's key space.
# Ordered most- to least- specific; the limit truncates from the tail.
SKILL_ROUTES: dict[str, list[str]] = {
    "movement": ["godot/godot-2d-movement", "godot/godot-physics"],
    "camera": ["disciplines/camera-systems", "godot/godot-nodes-scenes"],
    "combat": ["godot/godot-physics", "disciplines/game-feel"],
    "enemy_ai": ["disciplines/game-ai", "godot/godot-2d-movement"],
    "pickup": ["godot/godot-signals-groups", "godot/godot-physics"],
    "inventory": ["genres/rpg", "godot/godot-resources"],
    "dialogue": ["disciplines/dialogue-systems", "godot/godot-ui-control"],
    "quest": ["genres/rpg", "disciplines/save-systems"],
    "progression": ["genres/rpg", "disciplines/save-systems"],
    "save_load": ["disciplines/save-systems", "godot/godot-resources"],
    "level_transition": ["godot/godot-nodes-scenes", "disciplines/level-design"],
    "boss": ["disciplines/game-ai", "disciplines/game-feel"],
    "hud": ["godot/godot-ui-control", "disciplines/game-ui-ux"],
    "objective": ["godot/godot-signals-groups", "disciplines/level-design"],
    "resource": ["godot/godot-ui-control", "disciplines/game-feel"],
    "hazard": ["godot/godot-physics", "disciplines/level-design"],
    "switch": ["godot/godot-signals-groups", "disciplines/level-design"],
    "zone_control": ["godot/godot-physics", "disciplines/level-design"],
    "herding": ["disciplines/game-ai", "godot/godot-physics"],
    "maze": ["godot/godot-tilemap", "disciplines/level-design"],
    # Pipeline tasks that are not buildable systems.
    "architecture": ["godot/godot-nodes-scenes", "godot/godot-gdscript"],
    "repair": ["godot/godot-gdscript"],
    "baseline": ["godot/godot-gdscript", "godot/godot-animation"],
}


def available_skills() -> set[str]:
    """Every vendored skill, as 'category/name'."""
    if not VENDOR_ROOT.is_dir():
        return set()
    return {
        f"{path.parent.parent.name}/{path.parent.name}"
        for path in VENDOR_ROOT.glob("*/*/SKILL.md")
    }


def skills_for(kind: str, *, limit: int | None = None) -> list[str]:
    """The skills routed to a task kind, capped and filtered to what exists.

    An unknown kind gets nothing rather than a default: guessing at guidance
    for a system nobody mapped is how a prompt fills with irrelevant text.
    """
    routed = SKILL_ROUTES.get(kind, [])
    if not routed:
        return []
    cap = settings.skill_context_limit if limit is None else limit
    present = available_skills()
    return [skill for skill in routed if skill in present][: max(cap, 0)]


@lru_cache(maxsize=64)
def _skill_body(skill: str) -> str:
    """A skill's prose, minus the YAML frontmatter.

    The frontmatter is routing metadata - name, description, category - which
    this module has already acted on by the time the text is assembled. Paying
    context for it twice would be the opposite of progressive disclosure.
    """
    text = (VENDOR_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, remainder = text.partition("---")
        body, marker, tail = remainder.partition("\n---")
        if marker:
            text = tail
    return text.strip()


def skill_context(kind: str, *, limit: int | None = None) -> str:
    """Reference material for one task kind, or "" when there is none.

    Empty is the normal answer: the feature is off by default, and callers
    concatenate the result unconditionally.
    """
    if not settings.skill_context:
        return ""
    selected = skills_for(kind, limit=limit)
    if not selected:
        return ""
    sections = [
        f"### Reference: {skill.split('/')[-1]}\n\n{_skill_body(skill)}"
        for skill in selected
    ]
    return (
        "## Engine reference (background knowledge)\n\n"
        "Vendored Godot/game-design references for this system. They describe "
        "general Godot 4 practice, not SAGA's output contract - where they "
        "disagree with the rules that follow, the rules that follow win.\n\n"
        + "\n\n".join(sections)
    )
