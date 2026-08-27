import copy
import hashlib
import json
from pathlib import Path

import pytest

from saga.capabilities import (
    CompositionError,
    load_registry,
    registry_from_manifests,
    resolve_game_spec,
    validate_assembly_lock,
    verify_project_assembly,
)
from saga.game_spec import LEGACY_TEMPLATE_CAPABILITIES, game_spec_from_legacy_design


def _design(template: str) -> dict:
    return {
        "title": "Clockwork Crossing",
        "genre": "mechanical adventure",
        "mechanic_template": template,
        "hero_description": "a brass courier carrying a blue signal lantern",
        "core_mechanics": ["move", "read danger", "complete the objective"],
        "story_premise": "A courier restores a route through a sleeping machine city.",
        "theme_thread": "Each repaired crossing wakes another part of the city.",
        "win_condition": "Restore the final crossing.",
        "lose_condition": "The courier runs out of health.",
        "levels": [
            {
                "name": "The First Crossing",
                "description": "A compact route through the machine city's outer gate.",
                "outro_beat": "The bridge turns toward the inner city.",
                "intensity": 5,
                "pressure_notes": "Teach the objective before increasing pressure.",
            }
        ],
        "art_style": "high-contrast painterly pixel art",
        "audio_mood": "ticking percussion and warm brass",
        "key_item": {"description": "a cobalt gear key", "role": "objective"},
        "extra_sprites": [],
    }


def _component(component_id: str, **overrides) -> dict:
    suffix = component_id.replace(".", "_")
    component = {
        "id": component_id,
        "version": 1,
        "implementation": "legacy_generated",
        "requires": [],
        "conflicts": [],
        "provides": [f"port.{suffix}"],
        "requires_ports": [],
        "input_actions": [],
        "emits": [],
        "consumes": [],
        "state_owners": [f"state.{suffix}"],
        "runtime_files": [],
        "required_probes": [f"probe.{suffix}"],
    }
    component.update(overrides)
    return component


def _registry(*components: dict):
    return registry_from_manifests(
        [
            {
                "id": "resolver_test",
                "manifest_version": 2,
                "components": list(components),
                "template_profiles": {},
            }
        ]
    )


def _spec(*component_ids: str) -> dict:
    spec = game_spec_from_legacy_design(_design("collect"))
    # Synthetic resolver tests must exercise the declared components directly,
    # not the legacy template's compatibility profile.
    spec.pop("legacy")
    spec["capabilities"] = list(component_ids)
    spec["modes"][0]["capabilities"] = [
        {"id": component_id, "version": 1} for component_id in component_ids
    ]
    namespace = f"state.{component_ids[0].replace('.', '_')}"
    for fact in spec["state"]["facts"]:
        fact["namespace"] = namespace
    return spec


@pytest.mark.parametrize("template", sorted(LEGACY_TEMPLATE_CAPABILITIES))
def test_real_registry_resolves_every_legacy_template_profile(template):
    registry = load_registry()
    spec = game_spec_from_legacy_design(_design(template))

    lock = resolve_game_spec(spec, registry)

    expected = {request["id"] for request in registry.profiles[template]}
    actual = {
        component["id"]
        for mode in lock["modes"]
        for component in mode["components"]
    }
    assert expected <= actual
    assert lock["lock_version"] == 1
    assert lock["game_spec_version"] == 2
    assert len(lock["game_spec_hash"]) == 64
    assert len(lock["assembly_hash"]) == 64
    assert lock["required_probes"]
    assert all(component["component_digest"] for component in lock["modes"][0]["components"])


def test_real_stable_components_lock_the_exact_runtime_file_hashes():
    lock = resolve_game_spec(game_spec_from_legacy_design(_design("action_rpg")))

    for component in lock["modes"][0]["components"]:
        assert set(component["runtime_digests"]) == set(component["runtime_files"])
        assert all(len(digest) == 64 for digest in component["runtime_digests"].values())


def test_selective_builtin_pack_load_accepts_known_cross_pack_conflicts():
    manifest = (
        Path(__file__).parents[1]
        / "src"
        / "saga"
        / "archetype_packs"
        / "run_and_gun"
        / "manifest.json"
    )

    registry = load_registry([manifest])

    assert "movement.side_view" in registry.components
    assert "movement.top_down" not in registry.components


def test_resolved_assembly_lock_passes_public_integrity_validation():
    lock = resolve_game_spec(game_spec_from_legacy_design(_design("collect")))

    assert validate_assembly_lock(lock) == []


def test_assembly_lock_hash_covers_every_locked_field():
    lock = resolve_game_spec(game_spec_from_legacy_design(_design("collect")))
    lock["title"] = "Tampered Title"

    assert "assembly lock assembly_hash does not match its contents" in (
        validate_assembly_lock(lock)
    )


def test_rehashed_empty_assembly_still_fails_structural_validation():
    lock = resolve_game_spec(game_spec_from_legacy_design(_design("collect")))
    lock["modes"] = []
    body = {key: value for key, value in lock.items() if key != "assembly_hash"}
    lock["assembly_hash"] = hashlib.sha256(
        json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    assert "assembly lock modes must be a non-empty list" in validate_assembly_lock(
        lock
    )


def test_runtime_code_mutation_changes_the_locked_component_identity(tmp_path):
    runtime_file = tmp_path / "module.gd"
    manifest_file = tmp_path / "manifest.json"
    runtime_file.write_text("extends Node\n", encoding="utf-8")
    manifest = {
        "id": "mutation_test",
        "manifest_version": 2,
        "components": [
            _component(
                "feature.stable",
                implementation="stable_pack",
                runtime_files=["module.gd"],
            )
        ],
        "template_profiles": {},
    }
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    before = load_registry([manifest_file]).component("feature.stable")
    runtime_file.write_text("extends Node\nvar changed = true\n", encoding="utf-8")
    after = load_registry([manifest_file]).component("feature.stable")

    assert before["component_digest"] == after["component_digest"]
    assert before["runtime_digests"] != after["runtime_digests"]


def test_runtime_file_paths_cannot_escape_the_pack():
    with pytest.raises(CompositionError, match="unsafe runtime file"):
        _registry(_component("feature.escape", runtime_files=["../outside.gd"]))


def test_manifest_component_version_rejects_boolean_integer_subclass():
    with pytest.raises(CompositionError, match="positive integer version"):
        _registry(_component("feature.boolean", version=True))


def test_manifest_dependency_version_rejects_boolean_integer_subclass():
    with pytest.raises(CompositionError, match="requirement.*needs a version"):
        _registry(
            _component("feature.dependency"),
            _component(
                "feature.boolean",
                requires=[{"id": "feature.dependency", "version": True}],
            ),
        )


def test_manifest_profile_version_rejects_boolean_integer_subclass():
    component = _component("feature.boolean")
    with pytest.raises(CompositionError, match="positive integer version"):
        registry_from_manifests(
            [{
                "id": "profile_test",
                "manifest_version": 2,
                "components": [component],
                "template_profiles": {
                    "boolean": [{"id": component["id"], "version": True}]
                },
            }]
        )


def test_manifest_version_requires_the_plain_integer_schema_version():
    with pytest.raises(CompositionError, match="version must be 2"):
        registry_from_manifests(
            [{
                "id": "version_test",
                "manifest_version": 2.0,
                "components": [_component("feature.versioned")],
                "template_profiles": {},
            }]
        )


def test_qa_verifies_the_copied_runtime_and_project_lock(tmp_path):
    runtime_dir = tmp_path / "archetypes" / "stable_pack"
    runtime_dir.mkdir(parents=True)
    runtime = runtime_dir / "module.gd"
    runtime.write_text("extends Node\n", encoding="utf-8")
    digest = hashlib.sha256(runtime.read_bytes()).hexdigest()
    lock = {
        "assembly_hash": "proof",
        "modes": [{
            "id": "main",
            "components": [{
                "id": "feature.stable",
                "manifest_id": "stable_pack",
                "runtime_digests": {"module.gd": digest},
            }],
        }],
    }
    (tmp_path / "assembly.lock.json").write_text(
        json.dumps(lock), encoding="utf-8"
    )

    verify_project_assembly(tmp_path, lock)
    runtime.write_text("extends Node\nvar tampered = true\n", encoding="utf-8")

    with pytest.raises(CompositionError, match="runtime file hash mismatch"):
        verify_project_assembly(tmp_path, lock)


def test_qa_rejects_a_project_lock_different_from_pipeline_state(tmp_path):
    (tmp_path / "assembly.lock.json").write_text(
        json.dumps({"assembly_hash": "other", "modes": []}), encoding="utf-8"
    )

    with pytest.raises(CompositionError, match="does not match pipeline state"):
        verify_project_assembly(
            tmp_path, {"assembly_hash": "expected", "modes": []}
        )


def test_lock_and_hash_are_independent_of_capability_request_order():
    registry = _registry(
        _component("feature.alpha"),
        _component("feature.beta"),
        _component(
            "feature.root",
            requires=[
                {"id": "feature.beta", "version": 1},
                {"id": "feature.alpha", "version": 1},
            ],
        ),
    )
    forward = _spec("feature.root", "feature.beta", "feature.alpha")
    reversed_spec = copy.deepcopy(forward)
    reversed_spec["capabilities"].reverse()
    reversed_spec["modes"][0]["capabilities"].reverse()

    forward_lock = resolve_game_spec(forward, registry)
    reversed_lock = resolve_game_spec(reversed_spec, registry)

    assert reversed_lock == forward_lock
    assert reversed_lock["assembly_hash"] == forward_lock["assembly_hash"]


def test_assembly_hash_covers_game_spec_content_not_only_components():
    registry = _registry(_component("feature.alpha"))
    original = _spec("feature.alpha")
    changed = copy.deepcopy(original)
    changed["world"]["zones"][0]["description"] = "A meaningfully different world."

    original_lock = resolve_game_spec(original, registry)
    changed_lock = resolve_game_spec(changed, registry)

    assert original_lock["game_spec_hash"] != changed_lock["game_spec_hash"]
    assert original_lock["assembly_hash"] != changed_lock["assembly_hash"]


def test_legacy_profile_declarations_cannot_be_silently_replaced():
    spec = game_spec_from_legacy_design(_design("collect"))
    spec["capabilities"] = ["feature.fake"]
    spec["modes"][0]["capabilities"] = [{"id": "feature.fake", "version": 1}]

    with pytest.raises(CompositionError, match="legacy profile 'collect' drifted"):
        resolve_game_spec(spec, load_registry())


def test_state_facts_require_a_namespace_owned_by_the_assembly():
    registry = _registry(_component("feature.alpha"))
    spec = _spec("feature.alpha")
    spec["state"]["facts"][0]["namespace"] = "state.unowned"

    with pytest.raises(CompositionError, match="uses unowned namespace 'state.unowned'"):
        resolve_game_spec(spec, registry)


def test_state_facts_can_use_a_namespace_owned_by_a_different_component_id():
    registry = _registry(
        _component("persistence.profile", state_owners=["profile.save"])
    )
    spec = _spec("persistence.profile")
    for fact in spec["state"]["facts"]:
        fact["namespace"] = "profile.save"

    lock = resolve_game_spec(spec, registry)

    assert lock["state_facts"]["profile.save.level_0_complete"] == {
        "owner": "persistence.profile",
        "type": "bool",
    }


def test_unknown_requested_component_is_rejected():
    registry = _registry(_component("feature.known"))

    with pytest.raises(CompositionError, match="unknown capability 'feature.unknown'"):
        resolve_game_spec(_spec("feature.unknown"), registry)


def test_missing_dependency_is_rejected():
    registry = _registry(
        _component(
            "feature.root",
            requires=[{"id": "feature.missing", "version": 1}],
        )
    )

    with pytest.raises(CompositionError, match="unknown capability 'feature.missing'"):
        resolve_game_spec(_spec("feature.root"), registry)


def test_dependency_version_mismatch_is_rejected():
    registry = _registry(
        _component("feature.dependency"),
        _component(
            "feature.root",
            requires=[{"id": "feature.dependency", "version": 2}],
        ),
    )

    with pytest.raises(
        CompositionError,
        match=r"feature\.dependency.*requires version 2.*registry has 1",
    ):
        resolve_game_spec(_spec("feature.root"), registry)


def test_selected_component_conflict_is_rejected():
    registry = _registry(
        _component("movement.walk", conflicts=["movement.fly"]),
        _component("movement.fly"),
    )

    with pytest.raises(CompositionError, match=r"movement\.walk.*conflicts.*movement\.fly"):
        resolve_game_spec(_spec("movement.walk", "movement.fly"), registry)


def test_manifest_conflicts_must_name_registered_capabilities():
    with pytest.raises(CompositionError, match=r"conflicts with unknown capabilities.*feature\.missing"):
        _registry(
            _component("feature.known", conflicts=["feature.missing"]),
        )


def test_two_components_cannot_own_the_same_state_namespace():
    registry = _registry(
        _component("feature.alpha", state_owners=["player.health"]),
        _component("feature.beta", state_owners=["player.health"]),
    )

    with pytest.raises(
        CompositionError,
        match=r"state namespace 'player\.health'.*feature\.alpha.*feature\.beta",
    ):
        resolve_game_spec(_spec("feature.alpha", "feature.beta"), registry)


def test_consumed_event_requires_a_selected_provider():
    registry = _registry(
        _component("feature.listener", consumes=["quest.completed"]),
    )

    with pytest.raises(
        CompositionError,
        match=r"feature\.listener.*consumes event 'quest\.completed' with no provider",
    ):
        resolve_game_spec(_spec("feature.listener"), registry)


def test_allowlisted_engine_event_does_not_require_a_capability_provider():
    registry = _registry(
        _component("feature.listener", consumes=["engine.physics_tick"]),
    )

    lock = resolve_game_spec(_spec("feature.listener"), registry)

    assert lock["modes"][0]["components"][0]["id"] == "feature.listener"


def test_arbitrary_engine_event_is_not_treated_as_an_external_provider():
    registry = _registry(
        _component("feature.listener", consumes=["engine.frame_ready"]),
    )

    with pytest.raises(
        CompositionError,
        match=r"feature\.listener.*consumes event 'engine\.frame_ready' with no provider",
    ):
        resolve_game_spec(_spec("feature.listener"), registry)


def test_missing_required_port_is_rejected():
    registry = _registry(
        _component("feature.consumer", requires_ports=["service.navigation"]),
    )

    with pytest.raises(
        CompositionError,
        match=r"feature\.consumer.*requires port 'service\.navigation'.*got \[\]",
    ):
        resolve_game_spec(_spec("feature.consumer"), registry)


def test_ambiguous_required_port_is_rejected():
    registry = _registry(
        _component("feature.consumer", requires_ports=["service.navigation"]),
        _component("feature.nav_a", provides=["service.navigation"]),
        _component("feature.nav_b", provides=["service.navigation"]),
    )

    with pytest.raises(
        CompositionError,
        match=r"feature\.consumer.*requires port 'service\.navigation'.*nav_a.*nav_b",
    ):
        resolve_game_spec(
            _spec("feature.consumer", "feature.nav_a", "feature.nav_b"),
            registry,
        )


def test_conflicting_input_action_meanings_are_rejected():
    registry = _registry(
        _component(
            "feature.gameplay_input",
            input_actions=[{"action": "move_left", "meaning": "movement.left"}],
        ),
        _component(
            "feature.menu_input",
            input_actions=[{"action": "move_left", "meaning": "menu.previous"}],
        ),
    )

    with pytest.raises(
        CompositionError,
        match=r"input action 'move_left'.*movement\.left.*menu\.previous",
    ):
        resolve_game_spec(
            _spec("feature.gameplay_input", "feature.menu_input"),
            registry,
        )


def test_dependency_cycle_reports_the_closed_path():
    registry = _registry(
        _component(
            "feature.alpha",
            requires=[{"id": "feature.beta", "version": 1}],
        ),
        _component(
            "feature.beta",
            requires=[{"id": "feature.alpha", "version": 1}],
        ),
    )

    with pytest.raises(
        CompositionError,
        match=r"dependency cycle: feature\.alpha -> feature\.beta -> feature\.alpha",
    ):
        resolve_game_spec(_spec("feature.alpha"), registry)
