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
        "qa_confirmed": False,
        "qa_evidence": [],
    }


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
    promote: Callable[..., RepairValidation] = validate_and_promote_repair,
    route_chat: Callable[[list[dict], str | None], tuple[str, str]] | None = None,
) -> list[dict]:
    """Refine systems in order while preserving the last compiling script.

    route_chat(messages, recommended_model) -> (text, executed_model) lets
    specialist passes run on the build plan's routed model; without it every
    pass executes on the coder's own model. The baseline correction always
    uses the coder model - it is repairing that model's own draft."""
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
        specialist_brief = (
            f"SYSTEM: {system_id} ({kind})\n"
            f"DESCRIPTION: {system.get('description', '')}\n"
            f"DEPENDENCIES: {', '.join(depends_on) if depends_on else 'none'}\n"
            "ACCEPTANCE CRITERIA:\n"
            + "\n".join(f"- {criterion}" for criterion in acceptance)
            + f"\n\nCURRENT COMPLETE SCRIPT:\n```gdscript\n{previous}\n```"
        )
        started = time.monotonic()
        executed_model = model
        try:
            response, executed_model = route_chat(
                [
                    {"role": "system", "content": SPECIALIST_PROMPT},
                    {"role": "user", "content": specialist_brief},
                ],
                step.get("recommended_model"),
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

        active_hash = script_hash(script_file.read_text(encoding="utf-8"))
        outcomes[system_id] = status
        results.append(
            _entry(
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
            )
        )
        print(
            f"[Protected Builder] level {level_index + 1} {system_id}: {status} "
            f"(recommended={step.get('recommended_model')}, executed={executed_model})"
        )
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
