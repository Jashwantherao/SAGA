import hashlib
import json

from saga.capability_evidence import evaluate_capability_coverage
from saga.main import assess_ship_status, unconfirmed_systems


def _result(level_results, *, qa_passed=True, blocked=False, builds=None, template=None):
    return {
        "design_doc": {
            "levels": [{"name": "L1"}, {"name": "L2"}],
            "mechanic_template": template,
        },
        "qa_passed": qa_passed,
        "ship_blocked": blocked,
        "level_results": level_results,
        "system_build_results": builds or [],
    }


def _clean_levels():
    return [
        {"level_index": 0, "status": "passed"},
        {"level_index": 1, "status": "passed"},
    ]


def test_every_designed_level_needs_a_clean_ledger_entry():
    status, ready = assess_ship_status(
        _result([{"level_index": 1, "status": "passed"}])
    )
    assert (status, ready) == ("failed", False)


def test_failed_earlier_level_cannot_be_hidden_by_final_success():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "failed"},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )
    assert (status, ready) == ("failed", False)


def test_advisories_are_explicit_but_remain_shippable():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "passed", "vision_notes": ["placeholder"]},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )
    assert (status, ready) == ("passed_with_warnings", True)


def test_clean_complete_ledger_passes():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "passed"},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )
    assert (status, ready) == ("passed", True)


def test_run_and_gun_quality_gate_blocks_placeholder_environment():
    result = _result(
        [
            {
                "level_index": 0,
                "status": "passed",
                "vision_notes": [
                    "Vision (quality gate): placeholder art: plain platform rectangles"
                ],
            },
            {"level_index": 1, "status": "passed"},
        ],
        template="run_and_gun",
    )

    assert assess_ship_status(result) == ("failed", False)


def test_run_and_gun_quality_gate_blocks_perspective_mismatch():
    result = _result(
        [
            {
                "level_index": 0,
                "status": "passed",
                "vision_notes": [
                    "Vision (quality gate): perspective mismatch: diagonal train behind side view"
                ],
            },
            {"level_index": 1, "status": "passed"},
        ],
        template="run_and_gun",
    )

    assert assess_ship_status(result) == ("failed", False)


def test_shipped_system_without_an_acceptance_probe_is_a_warning():
    """Per-level QA proves the game runs, not that a system did what its
    acceptance criteria promised - so an unprobed system downgrades a clean
    pass rather than shipping silently."""
    result = _result(
        _clean_levels(),
        builds=[{"level_index": 0, "system_id": "combat", "status": "integrated"}],
    )

    assert assess_ship_status(result) == ("passed_with_warnings", True)
    assert unconfirmed_systems(result) == [
        "combat: no acceptance probe confirmed this system"
    ]


def test_confirmed_systems_still_ship_clean():
    result = _result(
        _clean_levels(),
        builds=[
            {
                "level_index": 0,
                "system_id": "movement",
                "status": "integrated",
                "qa_confirmed": True,
                "builder_hash_matches_qa": True,
            }
        ],
    )

    assert assess_ship_status(result) == ("passed", True)
    assert unconfirmed_systems(result) == []


def test_evidence_for_a_different_script_does_not_count_as_proof():
    result = _result(
        _clean_levels(),
        builds=[
            {
                "level_index": 0,
                "system_id": "hud",
                "status": "integrated",
                "qa_confirmed": True,
                "builder_hash_matches_qa": False,
            }
        ],
    )

    assert assess_ship_status(result) == ("passed_with_warnings", True)
    assert unconfirmed_systems(result) == [
        "hud: QA evidence describes a different script"
    ]


def test_systems_that_shipped_no_code_carry_no_acceptance_claim():
    """Rejected and superseded candidates contribute nothing to the build, so
    they must not be reported as missing evidence."""
    result = _result(
        _clean_levels(),
        builds=[
            {"level_index": 0, "system_id": "combat", "status": "rejected_gate"},
            {"level_index": 0, "system_id": "hud", "status": "superseded"},
            {"level_index": 1, "system_id": "boss", "status": "skipped_limit"},
        ],
    )

    assert unconfirmed_systems(result) == []
    assert assess_ship_status(result) == ("passed", True)


def test_runs_without_the_incremental_builder_are_unaffected():
    """Incremental mode is off by default; a run with an empty ledger must
    reach exactly the verdict it reached before this gate existed."""
    assert assess_ship_status(_result(_clean_levels())) == ("passed", True)


def test_required_probe_failure_blocks_shipping():
    status, ready = assess_ship_status(_result([], qa_passed=False, blocked=True))
    assert (status, ready) == ("blocked", False)


def test_quality_director_gate_can_block_a_technically_passing_run():
    result = _result(_clean_levels())
    result["quality_report"] = {
        "status": "needs_improvement",
        "gate": {"passed": False, "reasons": ["visual presentation below threshold"]},
    }

    assert assess_ship_status(result) == ("failed", False)


def test_passing_quality_report_preserves_clean_ship_status():
    result = _result(_clean_levels())
    result["quality_report"] = {
        "status": "passed",
        "gate": {"passed": True, "reasons": []},
    }

    assert assess_ship_status(result) == ("passed", True)


def test_video_advisory_is_reported_as_a_shippable_warning():
    status, ready = assess_ship_status(
        _result(
            [
                {"level_index": 0, "status": "passed", "video_notes": ["minor art drift"]},
                {"level_index": 1, "status": "passed"},
            ]
        )
    )

    assert (status, ready) == ("passed_with_warnings", True)


def _with_capability_coverage(result, statuses):
    lock = {
        "lock_version": 1,
        "game_spec_version": 2,
        "game_spec_hash": "a" * 64,
        "title": "Ship Proof",
        "modes": [{
            "id": "main",
            "perspective": "top_down_2d",
            "entry": True,
            "declared_capabilities": [{"id": "feature.test", "version": 1}],
            "components": [{
                "id": "feature.test",
                "version": 1,
                "implementation": "legacy_generated",
                "manifest_id": "ship_test",
                "component_digest": "b" * 64,
                "declared": True,
                "runtime_files": [],
                "runtime_digests": {},
                "required_probes": ["objective.status"],
            }],
        }],
        "state_owners": {"state.feature_test": "feature.test"},
        "state_facts": {},
        "required_probes": ["objective.status"],
    }
    lock["assembly_hash"] = hashlib.sha256(
        json.dumps(
            lock, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    result["assembly_lock"] = lock
    for level, status in zip(result["level_results"], statuses):
        objective = None if status == "blocked" else {"status": status}
        level["objective_result"] = {
            "capability_coverage": evaluate_capability_coverage(
                result["assembly_lock"],
                objective_result=objective,
                playability_result={},
            )
        }
    return result


def test_composed_run_requires_passing_capability_proof_for_every_level():
    result = _with_capability_coverage(_result(_clean_levels()), ["passed", "passed"])

    assert assess_ship_status(result) == ("passed", True)


def test_missing_composition_evidence_blocks_shipping_even_with_green_qa():
    result = _result(_clean_levels())
    result["assembly_lock"] = {"assembly_hash": "assembly-1"}
    result["level_results"][0]["objective_result"] = {
        "capability_coverage": {"status": "passed"}
    }

    assert assess_ship_status(result) == ("blocked", False)


def test_empty_composition_lock_cannot_bypass_the_ship_gate():
    result = _result(_clean_levels())
    result["assembly_lock"] = {}

    assert assess_ship_status(result) == ("blocked", False)


def test_failed_composition_evidence_closes_the_ship_gate():
    result = _with_capability_coverage(_result(_clean_levels()), ["passed", "failed"])

    assert assess_ship_status(result) == ("failed", False)


def test_forged_pass_status_without_locked_rows_is_blocked():
    result = _with_capability_coverage(_result(_clean_levels()), ["passed", "passed"])
    forged = {
        "coverage_version": 1,
        "assembly_hash": result["assembly_lock"]["assembly_hash"],
        "status": "passed",
        "capabilities_total": 0,
        "capabilities_passed": 0,
        "missing_evidence": [],
        "failed_evidence": [],
        "capabilities": [],
    }
    for level in result["level_results"]:
        level["objective_result"]["capability_coverage"] = forged

    assert assess_ship_status(result) == ("blocked", False)


def test_tampered_composition_lock_cannot_ship_with_stale_green_coverage():
    result = _with_capability_coverage(_result(_clean_levels()), ["passed", "passed"])
    result["assembly_lock"]["title"] = "Tampered after composition"

    assert assess_ship_status(result) == ("blocked", False)
