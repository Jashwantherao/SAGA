from saga.agents.playtest_feedback import _validate_revision_doc


def test_valid_targeted_tune_revision():
    document = {
        "verdict": "revise",
        "revisions": [
            {
                "route": "tune",
                "evidence": "Level two felt slow.",
                "diagnosis": "Player speed is low.",
                "delta": "player_speed: 180 -> 220",
                "target_field": "",
                "target_level": 2,
            }
        ],
    }
    assert _validate_revision_doc(document, level_count=3) == []


def test_reasset_must_not_target_a_level():
    document = {
        "verdict": "revise",
        "revisions": [
            {
                "route": "reasset",
                "evidence": "The key is invisible.",
                "diagnosis": "Low contrast.",
                "delta": "a bright gold key with a dark outline",
                "target_field": "key_item.description",
                "target_level": 2,
            }
        ],
    }
    problems = _validate_revision_doc(document, level_count=3)
    assert any("must be 0" in problem for problem in problems)
