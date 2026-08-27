import json

import pytest

from saga.agents.coder import (
    _assembly_contract,
    _assert_pack_matches_assembly,
    _persist_assembly_lock,
)
from saga.capabilities import profile_requests


def _lock(*, manifest_id="action_rpg", runtime_digests=None, full=False):
    requests = (
        profile_requests("action_rpg")
        if full and manifest_id == "action_rpg"
        else [{"id": "combat.melee", "version": 1}]
    )
    components = [
        {
            "id": request["id"],
            "version": request["version"],
            "manifest_id": manifest_id,
            "runtime_digests": (
                runtime_digests if index == 0 else {}
            ) or {},
        }
        for index, request in enumerate(requests)
    ]
    return {
        "assembly_hash": "abc123",
        "required_probes": ["objective.status", "input.win_verified"],
        "modes": [
            {
                "id": "main",
                "components": components,
            }
        ],
    }


def test_coder_receives_a_compact_immutable_assembly_contract():
    contract = _assembly_contract({"assembly_lock": _lock()})

    assert "abc123" in contract
    assert "combat.melee@1" in contract
    assert "input.win_verified" in contract
    assert "do not add undeclared gameplay systems" in contract


def test_exact_assembly_lock_is_copied_beside_the_runtime(tmp_path):
    lock = _lock()

    _persist_assembly_lock(tmp_path, {"assembly_lock": lock})

    assert json.loads(
        (tmp_path / "assembly.lock.json").read_text(encoding="utf-8")
    ) == lock


def test_packed_builder_must_match_the_locked_runtime_manifest():
    # A lock without runtime manifests is the compatibility/no-op path.
    _assert_pack_matches_assembly({"assembly_lock": {}}, "action_rpg")

    with pytest.raises(ValueError, match="Coder selected pack"):
        _assert_pack_matches_assembly(
            {"assembly_lock": _lock(manifest_id="run_and_gun")},
            "action_rpg",
        )


def test_packed_builder_rejects_a_same_manifest_component_subset():
    with pytest.raises(ValueError, match="only its complete profile"):
        _assert_pack_matches_assembly({"assembly_lock": _lock()}, "action_rpg")


def test_packed_builder_rejects_copied_files_outside_locked_components():
    with pytest.raises(ValueError, match="copies files outside"):
        _assert_pack_matches_assembly(
            {"assembly_lock": _lock(full=True)},
            "action_rpg",
            pack_required_files=("undeclared.gd",),
        )


def test_packed_builder_rejects_runtime_code_changed_after_lock(tmp_path):
    runtime = tmp_path / "player.gd"
    runtime.write_text("extends Node\n", encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
    state = {
        "assembly_lock": _lock(
            runtime_digests={"player.gd": digest}, full=True
        )
    }
    _assert_pack_matches_assembly(state, "action_rpg", tmp_path)

    runtime.write_text("extends Node\nvar changed = true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after composition"):
        _assert_pack_matches_assembly(state, "action_rpg", tmp_path)
