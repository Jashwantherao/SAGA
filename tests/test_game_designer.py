from saga.agents.asset_maker import HERO_NATIVE_FACING
from saga.agents.game_designer import _level_system_prompt, _normalize, _validate, game_designer


def _doc():
    return {
        "title": "Test",
        "genre": "arcade",
        "mechanic_template": "collect",
        "hero_description": "a bright blue mouse",
        "core_mechanics": ["move", "collect"],
        "story_premise": "Collect the keys.",
        "theme_thread": "Curiosity opens doors.",
        "win_condition": "Collect every key.",
        "lose_condition": "none",
        "levels": [
            {
                "name": f"Level {index}",
                "description": "A room.",
                "outro_beat": "The next door opens.",
                "intensity": intensity,
                "pressure_notes": "More pickups.",
            }
            for index, intensity in enumerate([3, 2, 12])
        ],
        "art_style": "pixel art",
        "audio_mood": "playful",
        "key_item": {"description": "a brass key", "role": "pickup"},
        "extra_sprites": [
            {"name": "Patrol Drone", "description": "a small drone"},
            {"name": "patrol_drone", "description": "duplicate"},
        ],
    }


def test_normalize_clamps_curve_and_deduplicates_sprites():
    normalized = _normalize(_doc())

    assert [level["intensity"] for level in normalized["levels"]] == [3, 3, 10]
    assert normalized["extra_sprites"] == [
        {"name": "patrol_drone", "description": "a small drone"}
    ]
    assert _validate(normalized) == []


def test_one_level_override_changes_prompt_and_validation():
    doc = _doc()
    doc["levels"] = doc["levels"][:1]

    assert _validate(doc, level_count=1) == []
    assert "exactly 1 level" in _level_system_prompt(1)
    assert "need 3-5 levels" in _validate(doc)[0]


def test_level_override_rejects_wrong_count():
    assert _validate(_doc(), level_count=1)[0] == "need exactly 1 level, got 3"


def test_hero_generation_has_an_explicit_native_facing_contract():
    assert "screen-left" in HERO_NATIVE_FACING


def test_supplied_design_is_validated_normalized_and_does_not_call_model(monkeypatch):
    doc = _doc()
    doc["levels"] = doc["levels"][:1]
    monkeypatch.setattr(
        "saga.agents.game_designer._design_local",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model called")),
    )

    result = game_designer({
        "user_prompt": "fixed benchmark",
        "requested_levels": 1,
        "design_doc": doc,
    })

    assert result["design_doc"] is not doc
    assert result["design_doc"]["extra_sprites"][0]["name"] == "patrol_drone"
