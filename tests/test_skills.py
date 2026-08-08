from types import SimpleNamespace

import pytest

from saga import skills
from saga.blueprint import SYSTEM_KINDS


def _settings(enabled, limit=2):
    return SimpleNamespace(skill_context=enabled, skill_context_limit=limit)


@pytest.fixture
def skills_on(monkeypatch):
    monkeypatch.setattr(skills, "settings", _settings(True))


def test_every_system_kind_has_a_route():
    """A blueprint kind with no route silently builds without guidance, which
    is exactly the gap the router exists to close."""
    unrouted = [kind for kind in SYSTEM_KINDS if kind not in skills.SKILL_ROUTES]

    assert unrouted == []


def test_every_routed_skill_is_actually_vendored():
    """Routes and vendor/ drift apart the moment someone edits one of them;
    a route to a missing skill degrades to silence rather than an error."""
    present = skills.available_skills()
    missing = sorted(
        {skill for routed in skills.SKILL_ROUTES.values() for skill in routed} - present
    )

    assert missing == [], "run: uv run python scripts/vendor_skills.py"


def test_every_vendored_skill_is_reachable_from_some_route():
    """Vendored-but-unrouted skills are dead weight in the repo."""
    routed = {skill for skills_list in skills.SKILL_ROUTES.values() for skill in skills_list}
    orphans = sorted(skills.available_skills() - routed)

    assert orphans == []


def test_context_is_empty_unless_explicitly_enabled(monkeypatch):
    """Off by default until the A/B benchmark says the tokens pay for
    themselves - callers concatenate the result unconditionally."""
    monkeypatch.setattr(skills, "settings", _settings(False))

    assert skills.skill_context("movement") == ""


def test_enabled_context_carries_the_routed_skills(skills_on):
    context = skills.skill_context("movement")

    assert "godot-2d-movement" in context
    assert "CharacterBody2D" in context
    assert "godot-physics" in context


def test_frontmatter_is_stripped_from_injected_text(skills_on):
    """Routing metadata has already done its job by the time the text is
    assembled; paying context for it twice is the opposite of the point."""
    context = skills.skill_context("movement")

    assert "license: Apache-2.0" not in context
    assert "difficulty:" not in context


def test_context_defers_to_the_harness_rules_that_follow(skills_on):
    """Several skills assume many scripts and resources while the template
    Coder emits one Level_N.gd, so precedence has to be stated."""
    context = skills.skill_context("hud")

    assert "the rules that follow win" in context


def test_limit_caps_how_much_reference_one_prompt_absorbs(skills_on):
    assert len(skills.skills_for("movement", limit=1)) == 1
    assert skills.skills_for("movement", limit=0) == []


def test_unknown_kind_gets_silence_not_a_default(skills_on):
    """Guessing guidance for an unmapped system is how a prompt fills with
    irrelevant text."""
    assert skills.skills_for("teleportation") == []
    assert skills.skill_context("teleportation") == ""


def test_whole_game_selection_spreads_across_kinds_before_going_deep(skills_on):
    """The monolithic Coder writes every system in one script, so a capped
    budget must cover several kinds rather than two skills about one."""
    kinds = ["movement", "pickup", "hud", "objective"]

    assert skills.skills_for_kinds(kinds, limit=2) == [
        "godot/godot-2d-movement",
        "godot/godot-signals-groups",
    ]
    assert skills.skills_for_kinds(kinds, limit=1) == ["godot/godot-2d-movement"]


def test_whole_game_selection_deduplicates_shared_skills(skills_on):
    """pickup and objective both route to signals-groups; paying for it twice
    would waste half a two-skill budget."""
    selected = skills.skills_for_kinds(["pickup", "objective"], limit=4)

    assert len(selected) == len(set(selected))
    assert "godot/godot-signals-groups" in selected


def test_whole_game_context_is_empty_without_kinds(skills_on):
    """A run with no blueprint gets no reference rather than a default."""
    assert skills.skill_context_for_kinds([]) == ""


def _coder_state():
    return {
        "blueprint": {
            "systems": [
                {"id": "movement", "kind": "movement"},
                {"id": "pickup", "kind": "pickup"},
                {"id": "hud", "kind": "hud"},
            ]
        },
        "blueprint_build_plan": [
            {"system_id": "movement"},
            {"system_id": "pickup"},
            {"system_id": "hud"},
        ],
    }


def test_the_monolithic_coder_reaches_the_skill_layer(skills_on):
    """The default path writes almost all of SAGA's GDScript; a skill layer
    that only reached the specialist builder could never affect a normal run."""
    from saga.agents.coder import _skill_reference

    reference = _skill_reference(_coder_state())

    assert "Engine reference" in reference
    assert "godot-2d-movement" in reference
    assert reference.endswith("\n\n"), "must separate cleanly from the prompt below"


def test_coder_reference_is_empty_without_a_blueprint(skills_on):
    from saga.agents.coder import _skill_reference

    assert _skill_reference({}) == ""


def test_coder_reference_is_empty_when_the_feature_is_off(monkeypatch):
    from saga.agents.coder import _skill_reference

    monkeypatch.setattr(skills, "settings", _settings(False))

    assert _skill_reference(_coder_state()) == ""


def test_routes_cover_the_pipeline_tasks_that_are_not_systems():
    for kind in ("architecture", "repair", "baseline"):
        assert skills.SKILL_ROUTES[kind]
