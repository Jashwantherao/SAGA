"""Map runtime QA evidence back to every locked gameplay capability.

An assembly lock is only useful if release evidence closes the loop.  This
module builds the ``declared -> exercised -> observed -> passed`` matrix from
the durable QA result.  A false observation is a gameplay failure; a missing
observation is a harness/contract block and must never be laundered into a
clean ship decision.
"""

from __future__ import annotations

from saga.capabilities import validate_assembly_lock


PASS_STATUSES = {"passed", "completed", "won", "ok"}


def _flatten(prefix: str, value: object, output: dict[str, object]) -> None:
    if not isinstance(value, dict):
        output[prefix] = value
        return
    for key, nested in value.items():
        child = f"{prefix}.{key}" if prefix else str(key)
        if child in {"objective.input_playthrough", "objective.campaign_scene_probe"}:
            alias = "input" if child.endswith("input_playthrough") else "campaign"
            _flatten(alias, nested, output)
        else:
            _flatten(child, nested, output)


def runtime_evidence(
    *,
    objective_result: dict | None,
    playability_result: dict | None,
    vision_evaluated: bool = False,
    video_qa_result: dict | None = None,
) -> dict[str, object]:
    evidence: dict[str, object] = {}
    _flatten("objective", objective_result or {}, evidence)
    _flatten("playability", playability_result or {}, evidence)
    # ``vision_evaluated`` means a complete structured verdict exists. False
    # is absence of proof, not an observed negative gameplay result.
    if vision_evaluated:
        evidence["vision.evaluated"] = True
    _flatten("video", video_qa_result or {}, evidence)
    return evidence


def _passes(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.lower() in PASS_STATUSES
    return False


def evaluate_capability_coverage(
    assembly_lock: object,
    *,
    objective_result: dict | None,
    playability_result: dict | None,
    vision_evaluated: bool = False,
    video_qa_result: dict | None = None,
) -> dict:
    lock_problems = validate_assembly_lock(assembly_lock)
    if lock_problems:
        return {
            "coverage_version": 1,
            "assembly_hash": (
                assembly_lock.get("assembly_hash")
                if isinstance(assembly_lock, dict)
                else None
            ),
            "status": "blocked",
            "capabilities_total": 0,
            "capabilities_passed": 0,
            "missing_evidence": [
                f"assembly_lock:{problem}" for problem in lock_problems
            ],
            "failed_evidence": [],
            "capabilities": [],
        }
    assert isinstance(assembly_lock, dict)
    evidence = runtime_evidence(
        objective_result=objective_result,
        playability_result=playability_result,
        vision_evaluated=vision_evaluated,
        video_qa_result=video_qa_result,
    )
    exercised_sources = {
        "objective": objective_result is not None,
        "playability": playability_result is not None,
        "input": isinstance(objective_result, dict)
        and "input_playthrough" in objective_result,
        "campaign": isinstance(objective_result, dict)
        and "campaign_scene_probe" in objective_result,
        "vision": vision_evaluated,
        "video": video_qa_result is not None,
    }
    coverage = []
    missing_total: list[str] = []
    failed_total: list[str] = []
    for mode in assembly_lock.get("modes") or []:
        for component in mode.get("components") or []:
            probes = []
            for probe in component.get("required_probes") or []:
                observed = probe in evidence
                exercised = exercised_sources.get(probe.split(".", 1)[0], False)
                if not observed:
                    status = "missing"
                    missing_total.append(f"{component.get('id')}:{probe}")
                    value = None
                else:
                    value = evidence[probe]
                    status = "passed" if _passes(value) else "failed"
                    if status == "failed":
                        failed_total.append(f"{component.get('id')}:{probe}")
                probes.append(
                    {
                        "id": probe,
                        "status": status,
                        "declared": True,
                        "configured": True,
                        "exercised": exercised,
                        "observed": observed,
                        "value": value,
                        "passed": status == "passed",
                    }
                )
            component_passed = bool(probes) and all(
                item["status"] == "passed" for item in probes
            )
            component_observed = bool(probes) and all(
                item["status"] != "missing" for item in probes
            )
            coverage.append(
                {
                    "mode": mode.get("id"),
                    "capability_id": component.get("id"),
                    "version": component.get("version"),
                    "declared": bool(component.get("declared", True)),
                    "configured": True,
                    "exercised": bool(probes) and all(
                        item["exercised"] for item in probes
                    ),
                    "observed": component_observed,
                    "passed": component_passed,
                    "status": (
                        "blocked"
                        if any(item["status"] == "missing" for item in probes)
                        else (
                            "failed"
                            if any(item["status"] == "failed" for item in probes)
                            else "passed"
                        )
                    ),
                    "probes": probes,
                }
            )

    status = "blocked" if missing_total else ("failed" if failed_total else "passed")
    return {
        "coverage_version": 1,
        "assembly_hash": assembly_lock.get("assembly_hash"),
        "status": status,
        "capabilities_total": len(coverage),
        "capabilities_passed": sum(item["status"] == "passed" for item in coverage),
        "missing_evidence": missing_total,
        "failed_evidence": failed_total,
        "capabilities": coverage,
    }


def validate_capability_coverage(assembly_lock: object, coverage: object) -> list[str]:
    """Reject forged, stale, partial, or structurally invalid release proof."""
    problems = validate_assembly_lock(assembly_lock)
    if not isinstance(coverage, dict):
        return problems + ["capability coverage must be an object"]
    if problems:
        return problems
    safe_lock = assembly_lock if isinstance(assembly_lock, dict) else {}
    if coverage.get("coverage_version") != 1:
        problems.append("capability coverage version must be 1")
    if coverage.get("assembly_hash") != safe_lock.get("assembly_hash"):
        problems.append("capability coverage assembly hash does not match the lock")

    expected = {}
    for mode in safe_lock.get("modes") or []:
        if not isinstance(mode, dict):
            continue
        for component in mode.get("components") or []:
            if not isinstance(component, dict):
                continue
            key = (mode.get("id"), component.get("id"), component.get("version"))
            expected[key] = component

    rows = coverage.get("capabilities")
    if not isinstance(rows, list):
        return problems + ["capability coverage rows must be a list"]
    actual = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"capability coverage row {index} must be an object")
            continue
        key = (row.get("mode"), row.get("capability_id"), row.get("version"))
        if key in actual:
            problems.append(f"duplicate capability coverage row {key!r}")
        actual[key] = row

    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual), key=str)
        extra = sorted(set(actual) - set(expected), key=str)
        if missing:
            problems.append(f"capability coverage is missing rows: {missing}")
        if extra:
            problems.append(f"capability coverage has unexpected rows: {extra}")

    for key in set(actual) & set(expected):
        row = actual[key]
        component = expected[key]
        expected_declared = bool(component.get("declared", True))
        if row.get("declared") is not expected_declared:
            problems.append(f"capability {key!r} has incorrect declared provenance")
        for field in ("configured", "exercised", "observed", "passed"):
            if row.get(field) is not True:
                problems.append(f"capability {key!r} did not prove {field}")
        if row.get("status") != "passed":
            problems.append(f"capability {key!r} status is not passed")

        probes = row.get("probes")
        if not isinstance(probes, list):
            problems.append(f"capability {key!r} probes must be a list")
            continue
        probe_rows = {
            probe.get("id"): probe
            for probe in probes
            if isinstance(probe, dict) and isinstance(probe.get("id"), str)
        }
        expected_probes = set(component.get("required_probes") or [])
        if set(probe_rows) != expected_probes or len(probe_rows) != len(probes):
            problems.append(f"capability {key!r} probe rows do not match the lock")
            continue
        for probe_id, probe in probe_rows.items():
            for field in ("declared", "configured", "exercised", "observed", "passed"):
                if probe.get(field) is not True:
                    problems.append(
                        f"capability {key!r} probe {probe_id!r} did not prove {field}"
                    )
            if probe.get("status") != "passed":
                problems.append(
                    f"capability {key!r} probe {probe_id!r} status is not passed"
                )

    expected_total = len(expected)
    if coverage.get("capabilities_total") != expected_total:
        problems.append("capabilities_total does not match the assembly")
    if coverage.get("capabilities_passed") != expected_total:
        problems.append("capabilities_passed does not match the assembly")
    if coverage.get("status") != "passed":
        problems.append("aggregate capability coverage status is not passed")
    if coverage.get("missing_evidence") not in ([], None):
        problems.append("capability coverage still reports missing evidence")
    if coverage.get("failed_evidence") not in ([], None):
        problems.append("capability coverage still reports failed evidence")
    return list(dict.fromkeys(problems))
