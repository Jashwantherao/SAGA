"""Protected, dependency-ordered system refinement for Agent Team v2.

The monolithic Coder still creates the first playable draft. In quality mode,
this module then gives each blueprint system a focused pass. The current script
is a protected baseline: a candidate cannot replace it unless static SAGA
contracts and a real Godot startup gate both pass. Behavioral proof remains the
QA Agent's job and is attached separately, so the ledger never calls a compile
success a gameplay verification.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Callable

from saga.repair_gate import RepairValidation, validate_and_promote_repair
from saga.skills import skill_context


SPECIALIST_PROMPT = """You are a specialist builder inside an automated Godot studio.
You receive a complete gameplay script that has already passed a Godot startup
gate. Make the SMALLEST changes necessary for the named system to satisfy its
acceptance criteria. Preserve every existing mechanic, public state variable,
node type, asset filename, win/loss flow and authored difficulty value. Do not
rewrite unrelated code. If the system already satisfies every criterion,
return the script byte-for-byte unchanged. Return the COMPLETE script in one
```gdscript fenced block and no other code block.
"""

BASELINE_PROMPT = """You are the integration builder inside an automated Godot studio.
The first complete gameplay draft still violates mandatory SAGA contracts, so
it cannot become the protected baseline. Fix ONLY the listed contract defects.
Preserve all existing gameplay, public state, assets, difficulty values and
win/loss behavior. Return the COMPLETE corrected script in one ```gdscript
fenced block. This candidate must compile before any specialist work can begin.
"""


def script_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(
    *,
    level_index: int,
    system_id: str,
    kind: str,
    status: str,
    executed_model: str,
    recommended_model: str | None = None,
    depends_on: list[str] | None = None,
    errors: list[str] | None = None,
    previous_hash: str | None = None,
    candidate_hash: str | None = None,
    active_hash: str | None = None,
    elapsed_seconds: float = 0.0,
    probe_status: str | None = None,
    probe: dict | None = None,
) -> dict:
    return {
        "level_index": level_index,
        "system_id": system_id,
        "kind": kind,
        "status": status,
        "recommended_model": recommended_model,
        "executed_model": executed_model,
        "depends_on": list(depends_on or []),
        "errors": [str(error)[:500] for error in (errors or [])][:10],
        "previous_sha256": previous_hash,
        "candidate_sha256": candidate_hash,
        "active_sha256": active_hash,
        "elapsed_seconds": round(elapsed_seconds, 3),
        # Behavioral verdict from the template's objective probe, when one
        # ran for this pass: passed | failed | regression | blocked | None.
        "probe_status": probe_status,
        "probe": probe,
        "qa_confirmed": False,
        "qa_evidence": [],
    }


def _probe_summary(result: dict | None) -> dict | None:
    if not result:
        return None
    keep = ("status", "reason", "collected", "total", "completion_score", "frames")
    return {key: result[key] for key in keep if key in result}


def _supersede_previous(results: list[dict], level_index: int) -> list[dict]:
    updated = []
    for item in results:
        copy = dict(item)
        if copy.get("level_index") == level_index and copy.get("status") not in {
            "superseded",
            "skipped_limit",
        }:
            copy["status"] = "superseded"
            copy["qa_confirmed"] = False
            copy["qa_evidence"] = []
        updated.append(copy)
    return updated


def protected_incremental_build(
    *,
    script_file: Path,
    project_dir: Path,
    scene: str,
    level_index: int,
    blueprint: dict,
    build_plan: list[dict],
    model: str,
    chat: Callable[[list[dict], str], str],
    extract_gdscript: Callable[[str], str],
    candidate_errors: Callable[[str], list[str]],
    existing_results: list[dict] | None = None,
    max_systems: int = 6,
    max_attempts: int = 2,
    promote: Callable[..., RepairValidation] = validate_and_promote_repair,
    route_chat: Callable[[list[dict], str | None], tuple[str, str]] | None = None,
    probe: Callable[[], tuple[dict | None, list[str], bool]] | None = None,
) -> list[dict]:
    """Refine systems in order while preserving the last compiling script.

    route_chat(messages, recommended_model) -> (text, executed_model) lets
    specialist passes run on the build plan's routed model; without it every
    pass executes on the coder's own model. The baseline correction always
    uses the coder model - it is repairing that model's own draft.

    probe() -> (result, errors, blocked) runs the mechanic's deterministic
    objective solver. Compiling is not behaving: without a probe a specialist
    can delete the win condition and still integrate, and the loss only
    surfaces at end-of-level QA where the retry costs the full gameplay and
    video stack. When the baseline demonstrably completes its objective, a
    candidate that stops completing it is a regression and is rolled back
    here. A baseline that never completed cannot be regressed against, so its
    passes record the probe verdict without gating on it.

    max_attempts bounds how many models may try one system: the routed pick
    first, then the plan's fallbacks, each shown why its predecessors were
    rejected. Every attempt is its own ledger entry."""
    if route_chat is None:
        route_chat = lambda messages, _preferred: (chat(messages, model), model)  # noqa: E731
    results = _supersede_previous(list(existing_results or []), level_index)
    if not script_file.is_file():
        results.append(
            _entry(
                level_index=level_index,
                system_id="__baseline__",
                kind="baseline",
                status="missing_baseline",
                executed_model=model,
                errors=["No generated gameplay script exists"],
            )
        )
        return results

    initial = script_file.read_text(encoding="utf-8")
    initial_hash = script_hash(initial)
    started = time.monotonic()
    static_errors = candidate_errors(initial)
    baseline_defects = list(static_errors)
    corrected_hash = initial_hash

    # Static contracts cannot see parser/runtime startup failures. Establish
    # the baseline with the real Godot gate first; either class of evidence
    # gets the same one bounded correction call below.
    if not baseline_defects:
        validation = promote(
            script_file,
            initial,
            project_dir=project_dir,
            scene=scene,
        )
        if validation.passed:
            baseline_ok = True
            status = "baseline_compiles"
            errors = []
        else:
            baseline_ok = False
            status = "rejected_gate"
            errors = validation.errors
            baseline_defects = list(validation.errors)

    if baseline_defects:
        error_list = "\n".join(f"- {error}" for error in baseline_defects)
        try:
            corrected = extract_gdscript(
                chat(
                    [
                        {"role": "system", "content": BASELINE_PROMPT},
                        {
                            "role": "user",
                            "content": (
                                f"BASELINE DEFECTS FROM STATIC/GODOT VALIDATION:\n{error_list}\n\n"
                                f"CURRENT COMPLETE SCRIPT:\n```gdscript\n{initial}\n```"
                            ),
                        },
                    ],
                    model,
                )
            )
            corrected_hash = script_hash(corrected)
            remaining = candidate_errors(corrected)
            if remaining:
                status = "rejected_static"
                errors = remaining
                baseline_ok = False
            else:
                validation = promote(
                    script_file,
                    corrected,
                    project_dir=project_dir,
                    scene=scene,
                )
                errors = validation.errors
                baseline_ok = validation.passed
                status = "baseline_corrected" if baseline_ok else "rejected_gate"
        except Exception as exc:
            corrected_hash = initial_hash
            status = "builder_error"
            errors = [f"{type(exc).__name__}: {exc}"]
            baseline_ok = False
    # Behavioral reference point. Only a baseline that actually completes its
    # objective can be regressed against; anything else makes later failures
    # unattributable to the specialist that happened to run last.
    baseline_probe = None
    baseline_probe_status = None
    if probe and baseline_ok:
        baseline_probe, probe_errors, probe_blocked = probe()
        baseline_probe_status = (
            "blocked"
            if probe_blocked
            else ("passed" if not probe_errors else "failed")
        )
        print(
            f"[Protected Builder] level {level_index + 1} baseline objective probe: "
            f"{baseline_probe_status}"
        )

    active_hash = script_hash(script_file.read_text(encoding="utf-8"))
    results.append(
        _entry(
            level_index=level_index,
            system_id="__baseline__",
            kind="baseline",
            status=status,
            executed_model=model,
            errors=errors,
            previous_hash=initial_hash,
            candidate_hash=corrected_hash,
            active_hash=active_hash,
            elapsed_seconds=time.monotonic() - started,
            probe_status=baseline_probe_status,
            probe=_probe_summary(baseline_probe),
        )
    )
    print(f"[Protected Builder] level {level_index + 1} baseline: {status}")

    systems = {system.get("id"): system for system in blueprint.get("systems") or []}
    selected = list(build_plan[: max(0, max_systems)])
    for skipped in build_plan[len(selected) :]:
        results.append(
            _entry(
                level_index=level_index,
                system_id=skipped.get("system_id", "unknown"),
                kind=skipped.get("kind", "unknown"),
                status="skipped_limit",
                executed_model=model,
                recommended_model=skipped.get("recommended_model"),
                depends_on=skipped.get("depends_on") or [],
                errors=[f"SAGA_INCREMENTAL_MAX_SYSTEMS limited this pass to {max_systems}"],
            )
        )

    outcomes: dict[str, str] = {}
    accepted = {"integrated", "unchanged"}
    for step in selected:
        system_id = step.get("system_id", "unknown")
        kind = step.get("kind", "unknown")
        depends_on = list(step.get("depends_on") or [])
        system = systems.get(system_id) or {}

        if not baseline_ok:
            status = "blocked_baseline"
            errors = ["The initial script did not establish a compiling protected baseline"]
        else:
            failed_dependencies = [
                dependency
                for dependency in depends_on
                if outcomes.get(dependency) not in accepted
            ]
            status = ""
            errors = []
            if failed_dependencies:
                status = "blocked_dependency"
                errors = [f"Dependency did not integrate: {name}" for name in failed_dependencies]
        if status:
            outcomes[system_id] = status
            results.append(
                _entry(
                    level_index=level_index,
                    system_id=system_id,
                    kind=kind,
                    status=status,
                    executed_model=model,
                    recommended_model=step.get("recommended_model"),
                    depends_on=depends_on,
                    errors=errors,
                )
            )
            continue

        previous = script_file.read_text(encoding="utf-8")
        previous_hash = script_hash(previous)
        acceptance = system.get("acceptance") or step.get("acceptance") or []
        # Background knowledge first, this system's contract last: several
        # vendored skills assume a project of many scripts, so the acceptance
        # criteria and the actual script must be what the model reads most
        # recently. SPECIALIST_PROMPT stays in the system role above both.
        # Empty string unless SAGA_SKILL_CONTEXT is on.
        reference = skill_context(kind)
        specialist_brief = (
            (f"{reference}\n\n" if reference else "")
            + f"SYSTEM: {system_id} ({kind})\n"
            f"DESCRIPTION: {system.get('description', '')}\n"
            f"DEPENDENCIES: {', '.join(depends_on) if depends_on else 'none'}\n"
            "ACCEPTANCE CRITERIA:\n"
            + "\n".join(f"- {criterion}" for criterion in acceptance)
            + f"\n\nCURRENT COMPLETE SCRIPT:\n```gdscript\n{previous}\n```"
        )

        # The router's fallbacks exist for exactly this: a model that cannot
        # satisfy one system is not a reason to abandon that system, and the
        # next candidate gets to see why its predecessor was rejected. Bounded
        # so one stubborn system cannot consume the whole build's budget.
        attempt_models = [step.get("recommended_model"), *(step.get("fallback_models") or [])]
        attempt_models = list(dict.fromkeys(attempt_models))[:max_attempts]
        rejected_attempts: list[dict] = []

        for attempt_index, preferred_model in enumerate(attempt_models):
            started = time.monotonic()
            status = ""
            errors = []
            executed_model = model
            pass_probe = None
            pass_probe_status = None
            brief = specialist_brief
            if rejected_attempts:
                history = "\n".join(
                    f"- {item['executed_model']} was rejected ({item['status']}): "
                    + "; ".join(item["errors"][:3])
                    for item in rejected_attempts
                )
                brief = (
                    f"{specialist_brief}\n\nEARLIER ATTEMPTS AT THIS SYSTEM WERE "
                    f"REJECTED. Do not repeat them:\n{history}"
                )
            try:
                response, executed_model = route_chat(
                    [
                        {"role": "system", "content": SPECIALIST_PROMPT},
                        {"role": "user", "content": brief},
                    ],
                    preferred_model,
                )
                candidate = extract_gdscript(response)
            except Exception as exc:
                status = "builder_error"
                errors = [f"{type(exc).__name__}: {exc}"]
                candidate = previous
            candidate_hash = script_hash(candidate)

            if status == "builder_error":
                pass
            elif candidate == previous:
                status = "unchanged"
            else:
                errors = candidate_errors(candidate)
                if errors:
                    status = "rejected_static"
                else:
                    validation = promote(
                        script_file,
                        candidate,
                        project_dir=project_dir,
                        scene=scene,
                    )
                    errors = validation.errors
                    status = "integrated" if validation.passed else "rejected_gate"

                # Compiling is not behaving. A candidate that starts cleanly
                # but stops completing an objective the baseline completed is
                # rolled back here, where the retry is cheap, not at full QA.
                if status == "integrated" and probe:
                    pass_probe, probe_errors, probe_blocked = probe()
                    pass_probe_status = (
                        "blocked"
                        if probe_blocked
                        else ("passed" if not probe_errors else "failed")
                    )
                    # "blocked" means the probe itself could not produce a
                    # verdict. A broken harness is not a generated-code defect,
                    # so it never discards a candidate that compiled - the
                    # run's own ship gate already refuses to call an
                    # unverifiable build shippable.
                    if pass_probe_status == "failed" and baseline_probe_status == "passed":
                        script_file.write_text(previous, encoding="utf-8")
                        status = "rejected_probe"
                        pass_probe_status = "regression"
                        errors = probe_errors or [
                            f"{system_id} stopped completing the objective the baseline completed"
                        ]

            active_hash = script_hash(script_file.read_text(encoding="utf-8"))
            entry = _entry(
                level_index=level_index,
                system_id=system_id,
                kind=kind,
                status=status,
                executed_model=executed_model,
                recommended_model=step.get("recommended_model"),
                depends_on=depends_on,
                errors=errors,
                previous_hash=previous_hash,
                candidate_hash=candidate_hash,
                active_hash=active_hash,
                elapsed_seconds=time.monotonic() - started,
                probe_status=pass_probe_status,
                probe=_probe_summary(pass_probe),
            )
            entry["attempt"] = attempt_index + 1
            results.append(entry)
            probe_note = f", probe={pass_probe_status}" if pass_probe_status else ""
            print(
                f"[Protected Builder] level {level_index + 1} {system_id} "
                f"attempt {attempt_index + 1}/{len(attempt_models)}: {status} "
                f"(recommended={preferred_model}, executed={executed_model}{probe_note})"
            )
            if status in accepted:
                break
            rejected_attempts.append(entry)

        outcomes[system_id] = status
    return results


def attach_qa_evidence(
    results: list[dict],
    *,
    level_index: int,
    active_script: str,
    objective_result: dict | None,
    video_qa_result: dict | None,
) -> list[dict]:
    """Attach only evidence the full QA stack actually observed."""
    active_hash = script_hash(active_script)
    objective_passed = (objective_result or {}).get("status") in {
        "passed",
        "completed",
        "won",
    }
    video = video_qa_result or {}
    updated = []
    objective_kinds = {
        "objective",
        "pickup",
        "resource",
        "hazard",
        "switch",
        "zone_control",
        "herding",
        "maze",
        "combat",
        "enemy_ai",
        "boss",
    }
    for item in results:
        copy = dict(item)
        if copy.get("level_index") != level_index or copy.get("status") not in {
            "baseline_compiles",
            "baseline_corrected",
            "integrated",
            "unchanged",
        }:
            updated.append(copy)
            continue
        evidence = ["full level QA completed on the active script"]
        confirmed = copy.get("kind") == "baseline"
        if copy.get("kind") == "movement":
            evidence.append("autoplay movement and scene execution passed")
            confirmed = True
        if copy.get("kind") in objective_kinds and objective_passed:
            evidence.append("mechanic-specific objective probe passed")
            confirmed = True
        if copy.get("kind") == "hud" and video.get("status") == "passed" and video.get(
            "hud_readable"
        ):
            evidence.append("NVIDIA gameplay video confirmed a readable HUD")
            confirmed = True
        copy["qa_confirmed"] = confirmed
        copy["qa_evidence"] = evidence
        copy["qa_active_sha256"] = active_hash
        copy["builder_hash_matches_qa"] = copy.get("active_sha256") == active_hash
        updated.append(copy)
    return updated
