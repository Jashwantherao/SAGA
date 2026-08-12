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
