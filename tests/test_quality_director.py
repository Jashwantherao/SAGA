from saga.quality_director import build_quality_report, quality_director, review_level
from saga.graph import _route_after_qa, _route_after_quality


def _state(**level_overrides):
    level = {
        "level_index": 0,
        "level_number": 1,
        "name": "Iron Bridge",
        "status": "passed",
        "retry_count": 0,
        "playability_result": {
            "status": "passed",
            "responsive": True,
            "idle_rate": 0.2,
            "input_rate": 2.4,
            "label_states": 3,
        },
        "objective_result": {"status": "passed", "completion_score": 1.0},
        "screenshot_path": "screenshot.png",
        "vision_evaluated": True,
        "video_qa_result": {"status": "passed", "evidence": "clean motion"},
        "vision_notes": [],
        "video_notes": [],
        "balance_notes": [],
        **level_overrides,
    }
    return {
        "current_level": 0,
        "retry_count": level["retry_count"],
        "qa_passed": True,
        "design_doc": {
            "mechanic_template": "run_and_gun",
            "hero_description": "masked courier",
            "levels": [{"name": "Iron Bridge", "description": "ruined bridge"}],
        },
        "level_results": [level],
        "system_build_results": [],
    }


def test_clean_measured_level_receives_full_quality_credit():
    review = review_level(_state())

    assert review["overall_score"] == 100
    assert review["gate"]["passed"] is True
    assert review["findings"] == []


def test_visual_quality_defect_closes_gate_and_assigns_asset_owner():
    review = review_level(_state(
        vision_notes=["Vision (quality gate): background uses isometric perspective"],
    ))

    assert review["gate"]["passed"] is False
    assert review["dimensions"]["visual_presentation"]["score"] == 45
    assert review["findings"][0]["owner"] == "asset_maker"


def test_packed_game_without_a_valid_visual_verdict_cannot_ship():
    state = _state(vision_evaluated=False)

    review = review_level(state)
    result = quality_director(state)

    assert review["gate"]["passed"] is False
    assert review["dimensions"]["visual_presentation"] == {
        "score": 30,
        "weight": 20,
        "confidence": "not_evaluated",
    }
    assert any(
        finding["code"] == "visual_review_unavailable"
        and finding["owner"] == "qa_agent"
        for finding in review["findings"]
    )
    assert result["quality_repair_requested"] is False
    assert result["qa_passed"] is False


def test_motion_orientation_defect_is_owned_by_coder():
    review = review_level(_state(
        vision_notes=["Vision (quality gate): player facing is reversed during movement"],
    ))

    assert review["findings"][0]["owner"] == "coder"


def test_quality_director_requests_only_one_bounded_polish_retry():
    state = _state(
        vision_notes=["Vision (quality gate): background uses isometric perspective"],
    )

    first = quality_director(state)
    assert first["quality_repair_requested"] is True
    assert first["quality_repair_owner"] == "asset_maker"
    assert first["retry_count"] == 1

    repeated_state = {**state, **first}
    second = quality_director(repeated_state)
    assert second["quality_repair_requested"] is False
    assert second["qa_passed"] is False
    assert len(second["quality_results"][0]["reviews"]) == 2


def test_aggregate_report_requires_every_level_review():
    one = review_level(_state())
    report = build_quality_report(
        [{"level_index": 0, "latest": one, "reviews": [one]}],
        expected_levels=2,
    )

    assert report["gate"]["passed"] is False
    assert report["levels_reviewed"] == 1
    assert "covers 1 of 2 levels" in report["gate"]["reasons"][0]


def test_graph_places_quality_review_between_qa_and_level_advance():
    state = _state()

    assert _route_after_qa(state) == "quality"
    assert _route_after_quality(state) == "done"


def test_graph_routes_requested_polish_back_through_triage():
    state = {**_state(), "quality_repair_requested": True, "qa_passed": False}

    assert _route_after_quality(state) == "triage"


def test_quality_polish_does_not_exceed_the_global_retry_budget():
    state = _state(
        retry_count=6,
        vision_notes=["Vision (quality gate): background uses isometric perspective"],
    )

    result = quality_director(state)

    assert result["quality_repair_requested"] is False
    assert "retry_count" not in result
