from pathlib import Path

import saga.agents.asset_maker as asset_maker_module
from saga.agents.asset_maker import _asset_requests, _target_names, asset_maker
from saga.agents.studio_director import _apply, _sanitize


def _doc():
    return {
        "title": "Repair Lab",
        "genre": "arcade",
        "mechanic_template": "collect",
        "hero_description": "a blue fox",
        "levels": [
            {"name": "L1", "description": "a bright room"},
            {"name": "L2", "description": "a dark room"},
        ],
        "art_style": "paper cutout",
        "key_item": {"description": "a gold bell", "role": "pickup"},
        "extra_sprites": [{"name": "door", "description": "a red door"}],
    }


def test_asset_plan_keeps_batch_seeds_when_filtered():
    requests = _asset_requests(_doc())
    seeds = {request[1]: request[5] for request in requests}

    assert seeds == {
        "hero_sprite": asset_maker_module.HERO_SEED,
        "hero_walk": asset_maker_module.HERO_SEED,
        "key_item": 2,
        "extra_door": 3,
        "level_0_bg": 4,
        "level_1_bg": 5,
    }
    assert _target_names({"field": "hero_description"}) == {
        "hero_sprite",
        "hero_walk",
    }
    assert _target_names({"field": "level_background", "level_index": 1}) == {
        "level_1_bg"
    }


def test_targeted_repair_replaces_only_requested_file_and_records_it(tmp_path, monkeypatch):
    asset_dir = tmp_path / "assets"
    asset_dir.mkdir()
    names = [request[1] for request in _asset_requests(_doc())]
    paths = []
    for name in names:
        path = asset_dir / f"{name}.png"
        path.write_bytes(f"old-{name}".encode())
        paths.append(str(path))

    generated = []

    def fake_generate(_prompt, name, **_kwargs):
        generated.append(name)
        path = asset_dir / f"{name}.png"
        path.write_bytes(f"new-{name}".encode())
        return path

    monkeypatch.setattr(asset_maker_module, "_check_comfyui_reachable", lambda: None)
    monkeypatch.setattr(asset_maker_module, "assets_dir", lambda _state: asset_dir)
    monkeypatch.setattr(asset_maker_module, "_generate_image", fake_generate)
    monkeypatch.setattr(asset_maker_module.httpx, "post", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(asset_maker_module.time, "sleep", lambda *_args: None)

    state = {
        "design_doc": _doc(),
        "sprite_paths": paths,
        "reasset_request": {
            "field": "key_item.description",
            "value": "a luminous gold bell",
            "reasoning": "The bell blends into the floor.",
            "level_index": 0,
            "retry": 1,
            "qa_errors": ["Key item is invisible."],
        },
        "level_results": [{"level_index": 0, "status": "failed", "attempts": []}],
    }

    result = asset_maker(state)

    assert generated == ["key_item"]
    assert result["sprite_paths"] == paths
    assert (asset_dir / "hero_sprite.png").read_bytes() == b"old-hero_sprite"
    assert (asset_dir / "key_item.png").read_bytes() == b"new-key_item"
    previous = asset_dir / "revisions" / "level_0_retry_1_key_item.png"
    assert previous.read_bytes() == b"old-key_item"
    event = result["asset_replacements"][0]
    assert event["field"] == "key_item.description"
    assert event["files"][0]["previous_path"] == str(previous)
    assert result["level_results"][0]["asset_replacements"] == [event]
    assert result["reasset_request"] is None


def test_director_creates_one_asset_request_without_mutating_input_doc():
    design_doc = _doc()
    state = {
        "design_doc": design_doc,
        "current_level": 1,
        "retry_count": 2,
        "qa_errors": ["Background is unreadable."],
    }
    decision = {
        "action": "reasset",
        "reasoning": "The current background has no contrast.",
        "note_to_coder": "",
        "reasset_field": "level_background",
        "reasset_value": "a dark room with bright walkable lanes",
    }

    result = _apply(state, decision)

    assert design_doc["levels"][1]["description"] == "a dark room"
    assert result["design_doc"]["levels"][1]["description"] == decision["reasset_value"]
    assert result["reasset_request"] == {
        "field": "level_background",
        "value": decision["reasset_value"],
        "reasoning": decision["reasoning"],
        "level_index": 1,
        "retry": 2,
        "qa_errors": ["Background is unreadable."],
    }


def test_global_art_style_is_not_accepted_as_a_targeted_repair():
    decision = {
        "action": "reasset",
        "reasoning": "Change everything.",
        "note_to_coder": "",
        "reasset_field": "art_style",
        "reasset_value": "neon",
    }

    result = _sanitize(decision, {"design_doc": _doc()}, retry_count=1)

    assert result["action"] == "fix"

