"""Deterministic post-QA quality review and bounded polish routing.

QA answers whether a generated level is demonstrably playable.  The Quality
Director answers the stricter production question: did the evidence show a
level that is polished enough to ship?  It never invents observations; every
score and finding points back to the durable QA ledger.
"""

from __future__ import annotations

import copy
from collections import defaultdict

from saga.state import GraphState


REPORT_VERSION = 1
MINIMUM_SCORE = 75
MINIMUM_DIMENSION_SCORE = 45
MAX_POLISH_REPAIRS_PER_LEVEL = 1
MAX_TOTAL_RETRIES_PER_LEVEL = 6

OBJECTIVE_TEMPLATES = {
    "collect",
    "ordered_switches",
    "survive_hazards",
    "depletion",
    "survive_and_deplete",
    "capture_zones",
    "herd_to_goal",
    "dot_maze",
    "maze_chase",
    "run_and_gun",
}


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _finding(
    dimension: str,
    owner: str,
    severity: str,
    code: str,
    summary: str,
    evidence: str,
    action: str,
) -> dict:
    return {
        "dimension": dimension,
        "owner": owner,
        "severity": severity,
        "code": code,
        "summary": summary,
        "evidence": evidence,
        "recommended_action": action,
    }


def _vision_owner(note: str) -> str:
    lowered = note.lower()
    if any(word in lowered for word in ("facing", "reversed", "sliding", "animation", "movement")):
        return "coder"
    return "asset_maker"


def _active_systems(state: GraphState, level_index: int) -> list[dict]:
    live = {"baseline_compiles", "baseline_corrected", "integrated", "unchanged"}
    return [
        item
        for item in (state.get("system_build_results") or [])
        if item.get("level_index") == level_index and item.get("status") in live
    ]


def review_level(state: GraphState, level_index: int | None = None) -> dict:
    """Score one level from its latest durable evidence."""
    index = (state.get("current_level") or 0) if level_index is None else level_index
    entries = {
        item.get("level_index"): item for item in (state.get("level_results") or [])
    }
    level = entries.get(index, {})
    template = (state.get("design_doc") or {}).get("mechanic_template", "")
    findings: list[dict] = []

    passed = level.get("status") == "passed"
    playability = level.get("playability_result") or {}
    responsive = playability.get("responsive")
    playability_score = 100 if passed and responsive is not False else 0
    if not passed:
        findings.append(_finding(
            "playability", "coder", "critical", "level_not_passed",
            "Level has no clean QA pass", str(level.get("qa_errors") or "missing pass"),
            "Repair the failing gameplay or runtime contract, then rerun QA.",
        ))
    elif not playability:
        # Older ledgers imply this because a pass could only be reached through
        # autoplay, but make the lower confidence visible instead of pretending
        # the metric was persisted.
        playability_score = 90

    objective = level.get("objective_result") or {}
    if template in OBJECTIVE_TEMPLATES:
        objective_status = str(objective.get("status") or "").lower()
        objective_ok = objective_status in {"passed", "completed", "won"}
        completion = objective.get("completion_score")
        if isinstance(completion, (int, float)):
            objective_score = _clamp(float(completion) * 100)
        else:
            objective_score = 100 if objective_ok else 0
        if not objective_ok:
            findings.append(_finding(
                "objective", "coder", "critical", "objective_unproven",
                "The designed objective is not proven complete", str(objective or "missing objective verdict"),
                "Repair the objective flow and produce a passing deterministic completion probe.",
            ))
    else:
        objective_score = 90 if passed else 0

    vision_notes = [str(note) for note in (level.get("vision_notes") or [])]
    visual_score = 100
    for note in vision_notes:
        hard = note.startswith("Vision (quality gate):")
        visual_score -= 55 if hard else 20
        owner = _vision_owner(note)
        findings.append(_finding(
            "visual_presentation", owner, "high" if hard else "medium",
            "visual_quality_gate" if hard else "visual_advisory",
            "Visual evidence shows a production-quality issue", note,
            "Regenerate the affected art asset with stricter composition constraints."
            if owner == "asset_maker" else
            "Repair sprite orientation or animation behavior without changing the input contract.",
        ))
    screenshot = level.get("screenshot_path")
    if not screenshot:
        visual_score -= 10
        findings.append(_finding(
            "visual_presentation", "qa_agent", "info", "screenshot_missing",
            "No final gameplay screenshot was captured", "screenshot_path is empty",
            "Capture an active gameplay frame so visual quality can be inspected.",
        ))
    visual_score = _clamp(visual_score)

    video = level.get("video_qa_result") or {}
    video_notes = [str(note) for note in (level.get("video_notes") or [])]
    if video:
        motion_score = 100 if video.get("status") == "passed" else 0
        if video.get("status") != "passed":
            findings.append(_finding(
                "motion_presentation", "coder", "critical", "video_qa_failed",
                "Gameplay motion failed video QA", str(video.get("evidence") or video),
                "Repair movement, facing, animation, or scene stability using the video verdict.",
            ))
    else:
        motion_score = 70
        findings.append(_finding(
            "motion_presentation", "qa_agent", "info", "video_not_evaluated",
            "Temporal presentation was not evaluated", "video QA was disabled for this run",
            "Enable NVIDIA video QA for release-candidate runs.",
        ))
    motion_score = _clamp(motion_score - 15 * len(video_notes))
    for note in video_notes:
        findings.append(_finding(
            "motion_presentation", "asset_maker", "medium", "video_advisory",
            "Video review found an art-presentation issue", note,
            "Tighten asset consistency and verify the replacement in a new gameplay capture.",
        ))

    balance_notes = [str(note) for note in (level.get("balance_notes") or [])]
    balance_score = _clamp(100 - 20 * len(balance_notes))
    for note in balance_notes:
        findings.append(_finding(
            "balance", "coder", "medium", "balance_advisory",
            "The level passes but its tuning needs polish", note,
            "Adjust only the named numeric pressure variables and rerun the objective probe.",
        ))

    retries = int(level.get("retry_count") or 0)
    systems = _active_systems(state, index)
    unconfirmed = [
        item for item in systems
        if not item.get("qa_confirmed") or item.get("builder_hash_matches_qa") is False
    ]
    reliability_score = _clamp(100 - 12 * retries - 10 * len(unconfirmed))
    for item in unconfirmed:
        system_id = item.get("system_id") or item.get("kind") or "unknown"
        findings.append(_finding(
            "reliability", "systems_architect", "medium", "system_unconfirmed",
            f"Shipped system {system_id!r} lacks matching acceptance evidence",
            str(item.get("qa_evidence") or "no matching behavioral proof"),
            "Add or repair the system-specific probe before treating the feature as verified.",
        ))

    dimensions = {
        "playability": {"score": playability_score, "weight": 25, "confidence": "measured" if playability else "inferred"},
        "objective": {"score": objective_score, "weight": 25, "confidence": "measured" if objective else "inferred"},
        "visual_presentation": {"score": visual_score, "weight": 20, "confidence": "measured" if screenshot else "limited"},
        "motion_presentation": {"score": motion_score, "weight": 15, "confidence": "measured" if video else "not_evaluated"},
        "balance": {"score": balance_score, "weight": 10, "confidence": "static_analysis"},
        "reliability": {"score": reliability_score, "weight": 5, "confidence": "measured"},
    }
    overall = round(sum(
        item["score"] * item["weight"] / 100 for item in dimensions.values()
    ), 1)
    blocking = [
        finding for finding in findings if finding["severity"] in {"critical", "high"}
    ]
    weak_dimensions = [
        name for name, item in dimensions.items()
        if item["score"] < MINIMUM_DIMENSION_SCORE
    ]
    gate_passed = overall >= MINIMUM_SCORE and not blocking and not weak_dimensions
    reasons = [finding["summary"] for finding in blocking]
    reasons += [f"{name.replace('_', ' ')} scored below {MINIMUM_DIMENSION_SCORE}" for name in weak_dimensions]
    if overall < MINIMUM_SCORE:
        reasons.append(f"overall score {overall} is below {MINIMUM_SCORE}")

    by_owner: dict[str, list[dict]] = defaultdict(list)
    for finding in findings:
        if finding["severity"] != "info":
            by_owner[finding["owner"]].append(finding)
    repair_plan = [
        {
            "owner": owner,
            "finding_codes": [item["code"] for item in items],
            "action": items[0]["recommended_action"],
        }
        for owner, items in by_owner.items()
    ]

    return {
        "level_index": index,
        "level_number": index + 1,
        "name": level.get("name") or f"Level {index + 1}",
        "overall_score": overall,
        "dimensions": dimensions,
        "findings": findings,
        "repair_plan": repair_plan,
        "gate": {
            "passed": gate_passed,
            "minimum_score": MINIMUM_SCORE,
            "minimum_dimension_score": MINIMUM_DIMENSION_SCORE,
            "reasons": list(dict.fromkeys(reasons)),
        },
    }


def build_quality_report(quality_results: list[dict], expected_levels: int) -> dict:
    """Aggregate the latest review for every designed level."""
    latest = [item.get("latest") or {} for item in quality_results]
    latest = sorted(
        (item for item in latest if isinstance(item.get("level_index"), int)),
        key=lambda item: item["level_index"],
    )
    complete = expected_levels > 0 and [item["level_index"] for item in latest] == list(range(expected_levels))
    scores = [float(item.get("overall_score") or 0) for item in latest]
    overall = round(sum(scores) / len(scores), 1) if scores else 0.0
    reasons = []
    if not complete:
        reasons.append(f"quality review covers {len(latest)} of {expected_levels} levels")
    for item in latest:
        reasons.extend(
            f"Level {item['level_index'] + 1}: {reason}"
            for reason in (item.get("gate") or {}).get("reasons") or []
        )
    passed = complete and all((item.get("gate") or {}).get("passed") for item in latest)
    findings = [finding for item in latest for finding in (item.get("findings") or [])]
    return {
        "report_version": REPORT_VERSION,
        "status": "passed" if passed else "needs_improvement",
        "overall_score": overall,
        "levels_reviewed": len(latest),
        "expected_levels": expected_levels,
        "level_reports": latest,
        "findings": findings,
        "repair_plan": [plan for item in latest for plan in (item.get("repair_plan") or [])],
        "gate": {
            "passed": passed,
            "minimum_score": MINIMUM_SCORE,
            "reasons": list(dict.fromkeys(reasons)),
        },
    }


def _repair_target(state: GraphState, review: dict) -> tuple[str, str | None, str | None]:
    actionable = [
        item for item in review.get("findings") or []
        if item.get("severity") != "info"
    ]
    owners = [item.get("owner") for item in actionable]
    if "coder" in owners:
        return "coder", None, None

    design = state.get("design_doc") or {}
    index = state.get("current_level") or 0
    levels = design.get("levels") or []
    if "asset_maker" in owners:
        evidence = " ".join(str(item.get("evidence") or "") for item in actionable).lower()
        if "hero" in evidence or "player" in evidence or "sprite" in evidence:
            field = "hero_description"
            original = str(design.get("hero_description") or "")
            value = original + "; high-contrast side-view game sprite, readable silhouette, facing left, no text"
        else:
            field = "level_background"
            original = str(levels[index].get("description") or "") if index < len(levels) else ""
            value = original + "; strict side-view composition, clear gameplay plane, no isometric perspective, no UI text"
        return "asset_maker", field, value.strip("; ")
    return "coder", None, None


def quality_director(state: GraphState) -> GraphState:
    """LangGraph node: review a passing level and request at most one polish pass."""
    index = state.get("current_level") or 0
    review = review_level(state, index)
    quality_results = copy.deepcopy(state.get("quality_results") or [])
    existing_index = next(
        (i for i, item in enumerate(quality_results) if item.get("level_index") == index),
        None,
    )
    previous = quality_results[existing_index] if existing_index is not None else {}
    reviews = list(previous.get("reviews") or []) + [review]
    entry = {"level_index": index, "latest": review, "reviews": reviews}
    if existing_index is None:
        quality_results.append(entry)
    else:
        quality_results[existing_index] = entry
    quality_results.sort(key=lambda item: item.get("level_index", 0))

    expected = len((state.get("design_doc") or {}).get("levels") or [])
    report = build_quality_report(quality_results, expected)
    print(
        f"[Quality Director] Level {index + 1}: {review['overall_score']}/100 - "
        f"{'PASS' if review['gate']['passed'] else 'POLISH REQUIRED'}"
    )

    prior_failed_reviews = sum(
        not (item.get("gate") or {}).get("passed") for item in reviews[:-1]
    )
    may_repair = (
        not review["gate"]["passed"]
        and prior_failed_reviews < MAX_POLISH_REPAIRS_PER_LEVEL
        and (state.get("retry_count") or 0) < MAX_TOTAL_RETRIES_PER_LEVEL
    )
    if may_repair:
        owner, field, value = _repair_target(state, review)
        errors = [
            f"Quality Director [{finding['owner']}/{finding['code']}]: "
            f"{finding['evidence']} Required action: {finding['recommended_action']}"
            for finding in review["findings"]
            if finding["severity"] != "info"
        ]
        print(f"[Quality Director] Routing one bounded polish pass to {owner}")
        update: GraphState = {
            "quality_results": quality_results,
            "quality_report": report,
            "quality_repair_requested": True,
            "quality_repair_owner": owner,
            "qa_passed": False,
            "qa_errors": errors or review["gate"]["reasons"],
            "retry_count": (state.get("retry_count") or 0) + 1,
        }
        if field and value:
            update["quality_reasset_field"] = field
            update["quality_reasset_value"] = value
        return update

    if not review["gate"]["passed"]:
        print("[Quality Director] Polish retry exhausted; truthful ship gate remains closed")
    return {
        "quality_results": quality_results,
        "quality_report": report,
        "quality_repair_requested": False,
        "quality_repair_owner": None,
        "qa_passed": bool(review["gate"]["passed"]),
        "qa_errors": [] if review["gate"]["passed"] else review["gate"]["reasons"],
    }
