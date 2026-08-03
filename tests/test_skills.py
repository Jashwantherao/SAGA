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


def test_routes_cover_the_pipeline_tasks_that_are_not_systems():
    for kind in ("architecture", "repair", "baseline"):
        assert skills.SKILL_ROUTES[kind]
