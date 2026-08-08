from types import SimpleNamespace

from saga.agents import studio_director as director


def _state(retry_count):
    return {
        "design_doc": {
            "title": "Test Game",
            "mechanic_template": "collect",
            "levels": [{"name": "One", "description": "A test arena."}],
            "extra_sprites": [],
        },
        "current_level": 0,
        "retry_count": retry_count,
        "qa_errors": ["Parse error"],
        "director_history": [],
    }


def test_deterministic_director_never_calls_a_model(monkeypatch):
    monkeypatch.setattr(
        director, "settings", SimpleNamespace(director_backend="deterministic")
    )
    monkeypatch.setattr(
        director,
        "_decide_local",
        lambda *_args: (_ for _ in ()).throw(AssertionError("model was called")),
    )

    result = director._triage(_state(1))

    assert result["director_action"] == "fix"


def test_deterministic_director_regenerates_after_three_failed_fixes(monkeypatch):
    monkeypatch.setattr(
        director, "settings", SimpleNamespace(director_backend="deterministic")
    )

    result = director._triage(_state(3))

    assert result["director_action"] == "regenerate"
