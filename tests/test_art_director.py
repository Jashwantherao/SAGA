import json

from saga.agents.art_director import (
    art_director,
    compile_art_direction,
    validate_art_direction,
)
from saga.agents.asset_maker import _asset_requests


def _design(template="action_rpg"):
    return {
        "title": "The Glass Orchard",
        "genre": "fantasy action RPG",
        "mechanic_template": template,
        "hero_description": "an amber moth knight with a round white mask",
        "theme_thread": "Memory grows back as luminous fruit.",
        "art_style": "hand-painted pixel art with ink outlines",
        "key_item": {"description": "a cyan glass seed", "role": "pickup"},
        "extra_sprites": [
            {"name": "thorn_sentinel", "description": "a broad crimson thorn guardian"},
            {"name": "orchard_boss", "description": "a towering black glass stag"},
        ],
        "levels": [
            {"name": "Root Archive", "description": "moonlit roots around a circular archive"},
        ],
    }


def test_art_direction_is_deterministic_complete_and_camera_specific():
    first = compile_art_direction(_design())
    repeated = compile_art_direction(_design())

    assert first == repeated
    assert validate_art_direction(first, _design()) == []
    assert first["camera_contract"]["projection"] == "strict 2D top-down orthographic"
    assert set(first["palette"]) == {"shadow", "surface", "hero", "danger", "reward"}
    assert {item["logical_name"] for item in first["asset_contracts"]} == {
        "hero_sprite", "hero_walk", "key_item", "extra_thorn_sentinel",
        "extra_orchard_boss", "level_0_bg",
    }
    roles = {item["logical_name"]: item["role"] for item in first["asset_contracts"]}
    assert roles["extra_thorn_sentinel"] == "enemy"
    assert roles["extra_orchard_boss"] == "boss"


def test_run_and_gun_and_action_rpg_cannot_share_the_wrong_projection():
    top_down = compile_art_direction(_design("action_rpg"))
    side_view = compile_art_direction(_design("run_and_gun"))

    assert top_down["camera_contract"]["projection"] != side_view["camera_contract"]["projection"]
    assert "isometric angle" in top_down["camera_contract"]["forbidden"]
    assert "top-down view" in side_view["camera_contract"]["forbidden"]


def test_asset_prompts_quote_the_locked_contract_and_use_matching_actor_view():
    design = _design("action_rpg")
    direction = compile_art_direction(design)
    prompts = {request[1]: request[0] for request in _asset_requests(design, direction)}

    assert "ART DIRECTOR CONTRACT" in prompts["hero_sprite"]
    assert "strict top-down orthographic actor" in prompts["hero_sprite"]
    assert "still facing screen-left" not in prompts["hero_sprite"]
    assert "environment only; no hero" in prompts["level_0_bg"]
    assert direction["palette"]["hero"] in prompts["hero_sprite"]


def test_art_director_persists_the_exact_bible_before_asset_generation(tmp_path):
    result = art_director({"run_dir": str(tmp_path), "design_doc": _design()})
    persisted = json.loads((tmp_path / "art_direction.json").read_text(encoding="utf-8"))

    assert result["art_direction_status"] == "locked"
    assert persisted == result["art_direction"]
    assert result["art_direction_errors"] == []
