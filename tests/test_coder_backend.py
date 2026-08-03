import httpx
import pytest

from saga.agents import coder_backend
from saga.agents.coder_backend import extract_gdscript
from saga.agents.coder import ANIM_GD, AUTOPLAY_GD, OBJECTIVE_PROBE_GD, PROJECT_GODOT_TEMPLATE


@pytest.fixture(params=["sdk", "httpx"])
def failing_runner(request, monkeypatch):
    """Ollama that always refuses, with sleeps recorded instead of taken.

    Parametrised over both refusal shapes: the SDK raises a *builtin*
    ConnectionError when the daemon is not listening, while httpx.ConnectError
    comes from the transport layer. Catching only the latter let a dead daemon
    escape as a raw traceback.
    """
    error = (
        ConnectionError("Failed to connect to Ollama")
        if request.param == "sdk"
        else httpx.ConnectError("refused")
    )
    slept = []
    monkeypatch.setattr(coder_backend.time, "sleep", slept.append)
    monkeypatch.setattr(
        coder_backend.ollama,
        "chat",
        lambda **_kwargs: (_ for _ in ()).throw(error),
    )
    return slept


def test_local_chat_does_not_wait_out_a_daemon_that_is_not_listening(
    monkeypatch, failing_runner
):
    """Sleeping cannot start a dead daemon, so the ladder must stop early -
    six kinds route local-first, and the full ladder each would cost minutes."""
    monkeypatch.setattr("saga.router.local_backend_reachable", lambda **_kwargs: False)

    with pytest.raises(RuntimeError, match="not listening"):
        coder_backend._local_chat([], "qwen2.5-coder:14b")

    assert failing_runner == [], "a dead daemon must cost no backoff at all"


def test_local_chat_still_waits_out_a_loading_runner(monkeypatch, failing_runner):
    """A model swap or VRAM reload makes a live daemon refuse calls for a
    while; waiting is the only cure, so that ladder stays intact."""
    monkeypatch.setattr("saga.router.local_backend_reachable", lambda **_kwargs: True)

    with pytest.raises(RuntimeError, match="did not recover after 4 attempts"):
        coder_backend._local_chat([], "qwen2.5-coder:14b")

    assert failing_runner == [20, 40, 60]


def test_extracts_tagged_gdscript():
    assert extract_gdscript("```gdscript\nextends Node2D\n```") == "extends Node2D"


def test_falls_back_to_generic_code_fence():
    assert extract_gdscript("```\nextends Node2D\n```") == "extends Node2D"


def test_generated_projects_install_the_objective_probe_autoload():
    assert 'ObjectiveProbe="*res://objective_probe.gd"' in PROJECT_GODOT_TEMPLATE
    assert "--objective-template=" in OBJECTIVE_PROBE_GD
    assert "template=%s" in OBJECTIVE_PROBE_GD
    assert "total_gems" in OBJECTIVE_PROBE_GD
    assert "patroller" in OBJECTIVE_PROBE_GD
    assert "_placement_preflight" in OBJECTIVE_PROBE_GD
    assert "unreachable_pickup" in OBJECTIVE_PROBE_GD


def test_autoplay_quit_stays_inside_report_function():
    lines = AUTOPLAY_GD.splitlines()
    quit_line = next(line for line in lines if "get_tree().quit()" in line)

    assert quit_line.startswith("\t")


def test_walk_animation_matches_left_facing_generated_art():
    assert "faces screen-left" in ANIM_GD
    assert "sprite.flip_h = dir_x > 0.0" in ANIM_GD
