"""QA agent - runs the generated Godot project headlessly and checks for errors.

Two checks, cheapest first: import assets, then an actual bounded headless
run of the scene. (There used to be a parse-only --check-only pass between
them, but it cannot see autoload singletons like Sfx, so a correct script
that calls an autoload fails it - the scene run catches real compile errors
anyway, since a broken script fails to load.) After both pass, a fresh
windowed process captures active gameplay via the harness-owned screenshot.gd
autoload. Capture infrastructure remains non-blocking. Structured visible
defects can gate a build, while free-form art criticism stays advisory. When
video QA is enabled, its temporal evidence reconciles contradictory
single-frame findings before SAGA spends a Coder retry.
"""

import json
import re
import subprocess
from pathlib import Path

from saga.balance import check_level
from saga.config import settings
from saga.corpus import record_level
from saga.repair_gate import godot_environment
from saga.safety import UnsafeGeneratedCodeError, assert_safe_gdscript
from saga.state import GraphState

GODOT_EXE = settings.godot_exe
VISION_MODEL = settings.vision_model

# A hosted vision model is enough better than a local 7-12B one to gate on.
# Measured against a real build whose platforms were untextured grey
# rectangles: the local model never mentioned them, while three hosted models
# named them as placeholder art unprompted. nemotron-3-nano-omni was the pick
# at ~3s with no false positives; llama-3.2-90b-vision agreed but took ~16s,
# and nemotron-nano-12b-v2-vl caught the real defect but also invented text
# clipping that was not in the image - which is disqualifying for a gate,
# since a false positive spends a Coder retry on nothing.
VISION_BACKEND = settings.vision_backend
VISION_REMOTE_MODEL = settings.vision_remote_model
VISION_BASE_URL = settings.vision_base_url
VISION_KEY_ENV = settings.vision_key_env
# Free tiers have been measured hanging for minutes on models they list.
VISION_TIMEOUT = settings.vision_timeout

VIDEO_QA_ENABLED = settings.video_qa_enabled
VIDEO_MODEL = settings.video_model
VIDEO_BASE_URL = settings.video_base_url
VIDEO_KEY_ENV = settings.video_key_env
VIDEO_TIMEOUT = settings.video_timeout
FFMPEG_EXE = settings.ffmpeg_exe
VIDEO_CAPTURE_FPS = 30
VIDEO_CAPTURE_MAX_FRAMES = 260
VIDEO_REVIEW_FPS = 10

ERROR_PATTERNS = re.compile(
    r"SCRIPT ERROR|Parse Error|Invalid call|Nonexistent function|ERROR:",
    re.IGNORECASE,
)

OBJECTIVE_VERDICT = re.compile(
    r"\[OBJECTIVE\] status=(passed|failed) template=([a-z_]+) "
    r"reason=([a-z_]+) collected=(\d+) total=(\d+) remaining=(\d+) frames=(\d+)"
)
OBJECTIVE_DETAIL = re.compile(
    r"\[OBJECTIVE_DETAIL\] node=\S+ position=\(([-\d.]+),([-\d.]+)\) "
    r"(?:ghost|ignored)=false"
)
OBJECTIVE_METRICS = re.compile(
    r"\[OBJECTIVE_METRICS\] completion_seconds=([\d.]+) progress_events=(\d+) "
    r"max_stall_frames=(\d+) stuck=(true|false) "
    r"restart=(passed|failed|not_applicable|not_tested) deaths=(\d+)"
)
SWITCH_METRICS = re.compile(
    r"\[SWITCH_METRICS\] sequence_length=(\d+) activations=(\d+) "
    r"wrong_order_reset=(true|false) clean_reload=(true|false) correct_progress=(\d+)"
)
SURVIVAL_METRICS = re.compile(
    r"\[SURVIVAL_METRICS\] starting_lives=(\d+) damage_events=(\d+) "
    r"single_hit_exact=(true|false) lose_verified=(true|false) "
    r"clean_restart=(true|false) timer_win=(true|false)"
)
DEPLETION_METRICS = re.compile(
    r"\[DEPLETION_METRICS\] resource_max=([\d.]+) drained_amount=([\d.]+) "
    r"refilled_amount=([\d.]+) drain_verified=(true|false) "
    r"refill_verified=(true|false) lose_verified=(true|false) "
    r"clean_restart=(true|false) timer_win=(true|false)"
)
HYBRID_METRICS = re.compile(
    r"\[HYBRID_METRICS\] drain_first=([\d.]+) drain_second=([\d.]+) "
    r"refill=([\d.]+) fuel_used=([\d.]+) hazard_damage=([\d.]+) "
    r"ramp=(true|false) refill_ok=(true|false) fuel_ok=(true|false) "
    r"hazard_ok=(true|false) lose=(true|false) restart_ok=(true|false) timer_win=(true|false)"
)
CAPTURE_METRICS = re.compile(
    r"\[CAPTURE_METRICS\] capture_gain=([\d.]+) decay=([\d.]+) "
    r"owned=(\d+) zones=(\d+) capture=(true|false) contest=(true|false) "
    r"ownership=(true|false) win=(true|false)"
)
HERD_METRICS = re.compile(
    r"\[HERD_METRICS\] still_drift=([\d.]+) flee_distance=([\d.]+) "
    r"goal_gain=([\d.]+) settled=(\d+) creatures=(\d+) still=(true|false) "
    r"flee=(true|false) settle=(true|false) persistent=(true|false) win=(true|false)"
)
RUN_AND_GUN_METRICS = re.compile(
    r"\[RUN_AND_GUN_METRICS\] fire=(true|false) checkpoint=(true|false) "
    r"lose=(true|false) restart=(true|false) enemy=(true|false) "
    r"boss_damage=(true|false) win=(true|false)"
)
RUN_AND_GUN_STRUCTURE = re.compile(
    r"\[RUN_AND_GUN_STRUCTURE\] layout=([a-z0-9_]+) platforms=(\d+) "
    r"encounters=(\d+) hazards=(\d+) pickups=(\d+) roles=(\d+) valid=(true|false)"
)
MAX_COLLECT_SOLVER_SECONDS = 60.0
MAX_SWITCH_SOLVER_SECONDS = 60.0
MAX_SURVIVAL_SOLVER_SECONDS = 30.0
MAX_DEPLETION_SOLVER_SECONDS = 30.0
MAX_HYBRID_SOLVER_SECONDS = 30.0
MAX_CAPTURE_SOLVER_SECONDS = 30.0
MAX_HERD_SOLVER_SECONDS = 60.0

# Godot's forced `--quit-after` shutdown doesn't wait for the AudioServer to
# release an autoplaying stream, so any project with BGM prints these on exit
# regardless of whether the generated GDScript is correct. Real GDScript bugs
# never produce this specific shutdown-order noise, so it's safe to ignore.
BENIGN_EXIT_NOISE = re.compile(
    r"resources? still in use at exit|Leaked instance:|ObjectDB instances were leaked at exit|"
    r"Orphan StringName|unclaimed string names at exit|RID allocations of type|"
    r"Failed to read the root certificate store",
    re.IGNORECASE,
)

HARNESS_SCRIPT_ERROR = re.compile(
    r"res://(?:autoplay|objective_probe|switch_probe|survival_probe|depletion_probe|hybrid_probe|capture_probe|herd_probe|screenshot|sfx|music|ambience|anim|game|"
    r"run_and_gun_probe|interlude|victory)\.gd|"
    r"res://archetypes/run_and_gun/[^\s)]+\.gd",
    re.IGNORECASE,
)


def _has_harness_error(errors: list[str]) -> bool:
    """Return true when generated code cannot possibly repair the failure."""
    return any(HARNESS_SCRIPT_ERROR.search(error) for error in errors)


def _run(args: list[str], cwd: str | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    command = [GODOT_EXE, *args]
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=godot_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=stdout,
            stderr=f"ERROR: Godot timed out after {timeout:.0f}s",
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            command,
            127,
            stdout="",
            stderr=f"ERROR: Could not start Godot: {type(exc).__name__}: {exc}",
        )


def _find_errors(output: str) -> list[str]:
    """Collect error lines, deduplicated and capped: a per-frame runtime bug
    repeats identically hundreds of times, which would otherwise flood the
    Coder's fix prompt and break the model's output format. The following
    'at: ...' line is attached when present - it carries the script location
    the model needs to find the bug."""
    lines = output.splitlines()
    found = []
    for i, line in enumerate(lines):
        if ERROR_PATTERNS.search(line) and not BENIGN_EXIT_NOISE.search(line):
            entry = line.strip()
            if i + 1 < len(lines) and lines[i + 1].lstrip().startswith("at:"):
                entry += f" ({lines[i + 1].strip()})"
            entry = entry[:300]
            if entry not in found:
                found.append(entry)
            if len(found) >= 10:
                break
    return found


# A probe that refuses a level because its numbers make the mechanic
# unsolvable reports only a reason code, and the per-template requirement text
# describes the mechanic rather than the threshold that was violated. A real
# run spent all six retries on invalid_herd_balance without ever learning which
# numbers were wrong. These name the rule so one repair can satisfy it.
PROBE_REASON_HINTS = {
    "invalid_herd_balance": (
        " Specifically: panic_radius, goal_radius, speed and flee_speed must all "
        "be positive, and flee_speed must be less than 0.6 x speed."
    ),
    "invalid_depletion_settings": (
        " Specifically: the maximum resource, drain_rate and survival_time must "
        "all be positive, and refill_rate must be strictly greater than drain_rate."
    ),
    "invalid_survival_settings": (
        " Specifically: the starting resource must be at least 2 and "
        "survival_time must be positive."
    ),
    "invalid_capture_rates": (
        " Specifically: capture_required, capture_radius, capture_rate and "
        "decay_rate must all be positive."
    ),
}


def _run_objective_probe(
    project_dir: str,
    scene: str,
    template: str,
) -> tuple[dict | None, list[str], bool]:
    """Run and parse the harness-owned deterministic completion solver.

    Returns ``(result, errors, blocked)``. ``blocked`` is reserved for a
    missing/broken required probe; an ordinary failed completion verdict is a
    generated-level defect that the Coder can repair.
    """
    probe = _run(
        [
            "--headless",
            "--path",
            project_dir,
            scene,
            "--quit-after",
            "12030",
            "--",
            "--objective-probe",
            f"--objective-template={template}",
        ],
        timeout=150,
    )
    output = probe.stdout + probe.stderr
    process_errors = _find_errors(output)
    if probe.returncode != 0 or process_errors:
        errors = process_errors or [f"Objective probe exited with code {probe.returncode}"]
        blocked = _has_harness_error(errors)
        return None, errors, blocked

    verdict = OBJECTIVE_VERDICT.search(output)
    if not verdict:
        return (
            None,
            [f"QA infrastructure: {template} objective probe produced no verdict."],
            True,
        )

    status, reported_template, reason, collected, total, remaining, frames = verdict.groups()
    result = {
        "status": status,
        "template": reported_template,
        "reason": reason,
        "collected": int(collected),
        "total": int(total),
        "remaining": int(remaining),
        "frames": int(frames),
    }
    if reported_template != template:
        return (
            result,
            [
                "QA infrastructure: objective probe reported template "
                f"{reported_template!r} while testing {template!r}."
            ],
            True,
        )
    metrics = OBJECTIVE_METRICS.search(output)
    if not metrics:
        return (
            result,
            [f"QA infrastructure: {template} objective probe produced no metrics verdict."],
            True,
        )
    completion_seconds, progress_events, max_stall_frames, stuck, restart, deaths = (
        metrics.groups()
    )
    result.update(
        {
            "completion_seconds": float(completion_seconds),
            "progress_events": int(progress_events),
            "max_stall_frames": int(max_stall_frames),
            "stuck": stuck == "true",
            "restart_status": restart,
            "deaths": int(deaths),
        }
    )
    progress_ratio = int(collected) / max(int(total), 1)
    result["completion_score"] = (
        100 if status == "passed" else min(60, round(progress_ratio * 60))
    )
    if template == "ordered_switches":
        switch_metrics = SWITCH_METRICS.search(output)
        if not switch_metrics:
            return (
                result,
                ["QA infrastructure: ordered-switch probe produced no sequence metrics."],
                True,
            )
        sequence_length, activations, wrong_reset, clean_reload, correct_progress = (
            switch_metrics.groups()
        )
        result.update(
            {
                "sequence_length": int(sequence_length),
                "activations": int(activations),
                "wrong_order_reset": wrong_reset == "true",
                "clean_reload": clean_reload == "true",
                "correct_progress": int(correct_progress),
            }
        )
    if template == "survive_hazards":
        survival_metrics = SURVIVAL_METRICS.search(output)
        if not survival_metrics:
            return (
                result,
                ["QA infrastructure: survival probe produced no survival metrics."],
                True,
            )
        starting_lives, damage_events, single_hit, lose, clean_restart, timer_win = (
            survival_metrics.groups()
        )
        result.update(
            {
                "starting_lives": int(starting_lives),
                "damage_events": int(damage_events),
                "single_hit_exact": single_hit == "true",
                "lose_verified": lose == "true",
                "clean_restart": clean_restart == "true",
                "timer_win_verified": timer_win == "true",
            }
        )
    if template == "depletion":
        depletion_metrics = DEPLETION_METRICS.search(output)
        if not depletion_metrics:
            return (
                result,
                ["QA infrastructure: depletion probe produced no resource metrics."],
                True,
            )
        resource_max, drained, refilled, drain, refill, lose, clean_restart, timer_win = (
            depletion_metrics.groups()
        )
        result.update(
            {
                "resource_max": float(resource_max),
                "drained_amount": float(drained),
                "refilled_amount": float(refilled),
                "drain_verified": drain == "true",
                "refill_verified": refill == "true",
                "lose_verified": lose == "true",
                "clean_restart": clean_restart == "true",
                "timer_win_verified": timer_win == "true",
            }
        )
    if template == "survive_and_deplete":
        hybrid = HYBRID_METRICS.search(output)
        if not hybrid:
            return result, ["QA infrastructure: hybrid probe produced no hybrid metrics."], True
        values = hybrid.groups()
        result.update({
            "drain_first": float(values[0]), "drain_second": float(values[1]),
            "refilled_amount": float(values[2]), "fuel_used": float(values[3]),
            "hazard_damage": float(values[4]), "ramp_verified": values[5] == "true",
            "refill_verified": values[6] == "true", "fuel_verified": values[7] == "true",
            "hazard_verified": values[8] == "true", "lose_verified": values[9] == "true",
            "clean_restart": values[10] == "true", "timer_win_verified": values[11] == "true",
        })
    if template == "capture_zones":
        capture = CAPTURE_METRICS.search(output)
        if not capture:
            return result, ["QA infrastructure: capture probe produced no capture metrics."], True
        gain, decay, owned, zones, captured, contested, ownership, won = capture.groups()
        result.update(
            {
                "capture_gain": float(gain),
                "decay_amount": float(decay),
                "owned_zones": int(owned),
                "total_zones": int(zones),
                "capture_verified": captured == "true",
                "contest_verified": contested == "true",
                "ownership_verified": ownership == "true",
                "zone_win_verified": won == "true",
            }
        )
    if template == "herd_to_goal":
        herd = HERD_METRICS.search(output)
        if not herd:
            return result, ["QA infrastructure: herd probe produced no herd metrics."], True
        drift, flee_distance, goal_gain, settled, creatures, still, flee, settle, persistent, won = herd.groups()
        result.update(
            {
                "still_drift": float(drift),
                "flee_distance": float(flee_distance),
                "goal_gain": float(goal_gain),
                "settled_creatures": int(settled),
                "total_creatures": int(creatures),
                "still_verified": still == "true",
                "flee_verified": flee == "true",
                "settle_verified": settle == "true",
                "persistent_settle_verified": persistent == "true",
                "herd_win_verified": won == "true",
            }
        )
    if template == "run_and_gun":
        combat = RUN_AND_GUN_METRICS.search(output)
        if not combat:
            return result, ["QA infrastructure: run-and-gun probe produced no capability metrics."], True
        fire, checkpoint, lose, restart, enemy, boss_damage, win = combat.groups()
        result.update(
            {
                "fire_verified": fire == "true",
                "checkpoint_verified": checkpoint == "true",
                "lose_verified": lose == "true",
                "clean_restart": restart == "true",
                "enemy_defeat_verified": enemy == "true",
                "boss_damage_verified": boss_damage == "true",
                "boss_win_verified": win == "true",
            }
        )
        structure = RUN_AND_GUN_STRUCTURE.search(output)
        if not structure:
            return result, ["QA infrastructure: run-and-gun probe produced no structure metrics."], True
        layout, platforms, encounters, hazards, pickups, roles, valid = structure.groups()
        result.update(
            {
                "layout_id": layout,
                "platform_count": int(platforms),
                "encounter_count": int(encounters),
                "hazard_count": int(hazards),
                "pickup_count": int(pickups),
                "enemy_role_count": int(roles),
                "structure_verified": valid == "true",
            }
        )
        if valid != "true":
            return result, [
                "QA infrastructure: the studio-owned run-and-gun encounter plan failed its structure contract."
            ], True
    blocked_positions = [
        [float(x), float(y)] for x, y in OBJECTIVE_DETAIL.findall(output)
    ]
    if blocked_positions:
        result["blocked_positions"] = blocked_positions
    if status == "failed":
        position_note = ""
        if blocked_positions:
            formatted = ", ".join(f"({x:g}, {y:g})" for x, y in blocked_positions)
            position_note = (
                f" Hazard under test: {formatted}."
                if template == "survive_hazards"
                else (
                    f" Refill zone under test: {formatted}."
                    if template == "depletion"
                    else f" Suspect unreachable Area2D positions: {formatted}."
                )
            )
        objective_requirement = (
            "Every switch must react, a wrong order must reset progress, and the full "
            "correct order must set state to 'won'."
            if template == "ordered_switches"
            else (
                "Collision damage must reach the lose state, restart must restore clean "
                "state, and timer expiry must reach the win state."
                if template == "survive_hazards"
                else (
                    "Resource must drain outside zones, refill inside one, empty-resource "
                    "loss must restart cleanly, and timer expiry must win."
                    if template == "depletion"
                    else (
                        "Drain must accelerate, refill must consume finite fuel, hazards must "
                        "damage resource, loss must restart cleanly, and timer expiry must win."
                        if template == "survive_and_deplete"
                        else (
                            "Player presence must capture zones, patroller contest must decay "
                            "them and reset ownership, and owning every zone must win."
                            if template == "capture_zones"
                            else (
                                "Firing, checkpoint activation, player loss/restart, enemy defeat, boss damage and boss victory must all use the stable archetype interface."
                                if template == "run_and_gun"
                                else (
                                "Creatures must stay calm outside panic range, flee toward the "
                                "goal when approached, settle permanently, and all settled must win."
                                if template == "herd_to_goal"
                                else "Every pickup must be reachable and collecting all of them must set state to 'won'."
                                )
                            )
                        )
                    )
                )
            )
        )
        return (
            result,
            [
                f"Objective completion: {template} solver failed "
                f"({reason}); collected {collected}/{total} with {remaining} remaining. "
                f"{objective_requirement}"
                f"{PROBE_REASON_HINTS.get(reason, '')}"
                f"{position_note}"
            ],
            False,
        )
    if result["stuck"]:
        return (
            result,
            ["Objective completion: probe reported a pass while also reporting a stuck run."],
            True,
        )
    if int(remaining) != 0 or int(collected) < int(total):
        item = (
            "milestones"
            if template in {"survive_hazards", "depletion", "survive_and_deplete", "capture_zones", "herd_to_goal", "run_and_gun"}
            else "objective items"
        )
        return (
            result,
            [
                f"Objective completion: probe reported a pass without completing every {item} "
                f"({collected}/{total}, {remaining} remaining)."
            ],
            True,
        )
    if template == "collect":
        if result["restart_status"] != "not_applicable":
            return (
                result,
                [
                    "QA infrastructure: collect objective reported restart status "
                    f"{result['restart_status']!r}; expected 'not_applicable'."
                ],
                True,
            )
        if result["completion_seconds"] > MAX_COLLECT_SOLVER_SECONDS:
            return (
                result,
                [
                    "Objective completion: collect solver reached the win state but took "
                    f"{result['completion_seconds']:.1f}s, above the "
                    f"{MAX_COLLECT_SOLVER_SECONDS:.0f}s quality ceiling. Reduce empty travel "
                    "or the number of pickups."
                ],
                False,
            )
    if template == "ordered_switches":
        if not result["wrong_order_reset"]:
            return (
                result,
                ["Objective completion: a wrong switch did not reset sequence progress."],
                False,
            )
        if not result["clean_reload"] or result["restart_status"] != "passed":
            return (
                result,
                ["Objective completion: switch puzzle did not reload into a clean state."],
                False,
            )
        if (
            result["correct_progress"] != result["sequence_length"]
            or result["sequence_length"] != int(total)
        ):
            return (
                result,
                [
                    "Objective completion: ordered-switch pass has inconsistent sequence "
                    f"progress ({result['correct_progress']}/{result['sequence_length']})."
                ],
                True,
            )
        if result["completion_seconds"] > MAX_SWITCH_SOLVER_SECONDS:
            return (
                result,
                [
                    "Objective completion: ordered-switch solver passed but took "
                    f"{result['completion_seconds']:.1f}s, above the "
                    f"{MAX_SWITCH_SOLVER_SECONDS:.0f}s quality ceiling. Reduce empty travel "
                    "or sequence length."
                ],
                False,
            )
    if template == "survive_hazards":
        required = {
            "single_hit_exact": result["single_hit_exact"],
            "lose_verified": result["lose_verified"],
            "clean_restart": result["clean_restart"],
            "timer_win_verified": result["timer_win_verified"],
        }
        missing = [name for name, passed in required.items() if not passed]
        if missing:
            return (
                result,
                [
                    "Objective completion: survival pass omitted required phase(s): "
                    + ", ".join(missing)
                    + "."
                ],
                True,
            )
        if result["restart_status"] != "passed":
            return (
                result,
                ["Objective completion: survival restart did not produce a clean state."],
                False,
            )
        if (
            result["damage_events"] != result["starting_lives"]
            or result["deaths"] != 1
        ):
            return (
                result,
                [
                    "Objective completion: survival damage accounting is inconsistent "
                    f"({result['damage_events']} hits for {result['starting_lives']} lives, "
                    f"{result['deaths']} terminal losses)."
                ],
                True,
            )
        if result["completion_seconds"] > MAX_SURVIVAL_SOLVER_SECONDS:
            return (
                result,
                [
                    "Objective completion: survival solver passed but took "
                    f"{result['completion_seconds']:.1f}s, above the "
                    f"{MAX_SURVIVAL_SOLVER_SECONDS:.0f}s QA ceiling."
                ],
                False,
            )
    if template == "depletion":
        required = {
            "drain_verified": result["drain_verified"],
            "refill_verified": result["refill_verified"],
            "lose_verified": result["lose_verified"],
            "clean_restart": result["clean_restart"],
            "timer_win_verified": result["timer_win_verified"],
        }
        missing = [name for name, passed in required.items() if not passed]
        if missing:
            return (
                result,
                [
                    "Objective completion: depletion pass omitted required phase(s): "
                    + ", ".join(missing)
                    + "."
                ],
                True,
            )
        if result["drained_amount"] <= 0.0 or result["refilled_amount"] <= 0.0:
            return (
                result,
                ["Objective completion: depletion pass reported no resource change."],
                True,
            )
        if result["restart_status"] != "passed" or result["deaths"] != 1:
            return (
                result,
                ["Objective completion: depletion lose/restart accounting is inconsistent."],
                True,
            )
        if result["completion_seconds"] > MAX_DEPLETION_SOLVER_SECONDS:
            return (
                result,
                [
                    "Objective completion: depletion solver passed but took "
                    f"{result['completion_seconds']:.1f}s, above the "
                    f"{MAX_DEPLETION_SOLVER_SECONDS:.0f}s QA ceiling."
                ],
                False,
            )
    if template == "survive_and_deplete":
        flags = ["ramp_verified", "refill_verified", "fuel_verified", "hazard_verified", "lose_verified", "clean_restart", "timer_win_verified"]
        missing = [name for name in flags if not result[name]]
        if missing:
            return result, ["Objective completion: hybrid pass omitted: " + ", ".join(missing) + "."], True
        if not (result["drain_second"] > result["drain_first"] > 0 and result["refilled_amount"] > 0 and result["fuel_used"] > 0 and result["hazard_damage"] > 0):
            return result, ["Objective completion: hybrid measurements are inconsistent."], True
        if result["restart_status"] != "passed" or result["deaths"] != 1:
            return result, ["Objective completion: hybrid lose/restart accounting is inconsistent."], True
        if result["completion_seconds"] > MAX_HYBRID_SOLVER_SECONDS:
            return result, [f"Objective completion: hybrid solver exceeded {MAX_HYBRID_SOLVER_SECONDS:.0f}s QA ceiling."], False
    if template == "capture_zones":
        flags = ["capture_verified", "contest_verified", "ownership_verified", "zone_win_verified"]
        missing = [name for name in flags if not result[name]]
        if missing:
            return result, ["Objective completion: capture pass omitted: " + ", ".join(missing) + "."], True
        if result["capture_gain"] <= 0 or result["decay_amount"] <= 0:
            return result, ["Objective completion: capture progress/decay measurements are inconsistent."], True
        if result["total_zones"] < 2 or result["owned_zones"] != result["total_zones"]:
            return result, ["Objective completion: capture ownership accounting is inconsistent."], True
        if result["restart_status"] != "not_applicable" or result["deaths"] != 0:
            return result, ["Objective completion: capture terminal accounting is inconsistent."], True
        if result["completion_seconds"] > MAX_CAPTURE_SOLVER_SECONDS:
            return result, [f"Objective completion: capture solver exceeded {MAX_CAPTURE_SOLVER_SECONDS:.0f}s QA ceiling."], False
    if template == "herd_to_goal":
        flags = ["still_verified", "flee_verified", "settle_verified", "persistent_settle_verified", "herd_win_verified"]
        missing = [name for name in flags if not result[name]]
        if missing:
            return result, ["Objective completion: herd pass omitted: " + ", ".join(missing) + "."], True
        if result["still_drift"] > 0.5 or result["flee_distance"] <= 0 or result["goal_gain"] <= 0:
            return result, ["Objective completion: herd movement measurements are inconsistent."], True
        if result["total_creatures"] < 1 or result["settled_creatures"] != result["total_creatures"]:
            return result, ["Objective completion: herd settlement accounting is inconsistent."], True
        if result["restart_status"] != "not_applicable" or result["deaths"] != 0:
            return result, ["Objective completion: herd terminal accounting is inconsistent."], True
        if result["completion_seconds"] > MAX_HERD_SOLVER_SECONDS:
            return result, [f"Objective completion: herd solver exceeded {MAX_HERD_SOLVER_SECONDS:.0f}s QA ceiling."], False
    if template == "run_and_gun":
        flags = [
            "fire_verified",
            "checkpoint_verified",
            "lose_verified",
            "clean_restart",
            "enemy_defeat_verified",
            "boss_damage_verified",
            "boss_win_verified",
        ]
        missing = [name for name in flags if not result[name]]
        if missing:
            return result, ["Objective completion: run-and-gun pass omitted: " + ", ".join(missing) + "."], True
        if result["restart_status"] != "passed" or result["deaths"] != 1:
            return result, ["Objective completion: run-and-gun loss/restart accounting is inconsistent."], True
    return result, [], False


def _run_maze_objective_probe(
    project_dir: str,
    scene: str,
    template: str,
) -> tuple[dict | None, list[str], bool]:
    """Compatibility wrapper for the original maze-only probe API."""
    return _run_objective_probe(project_dir, scene, template)


def _run_dot_maze_objective_probe(
    project_dir: str,
    scene: str,
) -> tuple[dict | None, list[str], bool]:
    """Compatibility wrapper for existing callers and developer tooling."""
    return _run_objective_probe(project_dir, scene, "dot_maze")


def _vision_prompt(design_doc) -> str:
    hero = (design_doc or {}).get("hero_description", "the player character")
    title = (design_doc or {}).get("title", "the game")
    return (
        f"This is a screenshot of an auto-generated 2D game called {title!r} "
        f"taken about one second into gameplay, at 1024x576. The hero is: "
        f"{hero}. Report only defects you can actually see - do not guess or "
        "invent problems. Answer ONLY with JSON matching: "
        '{"hero_visible": bool, "background_fills_screen": bool, '
        '"text_clipped": bool, "placeholder_art": string or null, '
        '"looks_broken": string or null}. '
        "Set text_clipped true only if some text runs off the screen edge or "
        "is hidden behind another element. Set placeholder_art to a short "
        "description if plain untextured coloured rectangles are standing in "
        "for game objects, otherwise null. Set looks_broken if a sprite is "
        "gigantic, cut off, or floating somewhere nonsensical, otherwise null."
    )


def _vision_raw(screenshot_path: str, design_doc) -> dict:
    """Run the configured vision backend and return the parsed verdict."""
    prompt = _vision_prompt(design_doc)

    if VISION_BACKEND in ("nvidia", "remote", "openai"):
        import base64

        from saga.llm import chat

        b64 = base64.b64encode(Path(screenshot_path).read_bytes()).decode()
        text = chat(
            [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
            model=VISION_REMOTE_MODEL,
            max_tokens=4000,
            base_url=VISION_BASE_URL,
            key_env=VISION_KEY_ENV,
            timeout=VISION_TIMEOUT,
        )
        # No JSON mode on every hosted VLM, so salvage the object from prose.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return json.loads(match.group(0) if match else text)

    import ollama

    resp = ollama.chat(
        model=VISION_MODEL,
        format="json",
        messages=[{"role": "user", "content": prompt, "images": [screenshot_path]}],
    )
    return json.loads(resp["message"]["content"])


def _vision_review(screenshot_path: str, design_doc) -> tuple[list[str], list[str]]:
    """Review the screenshot and split findings by who can actually fix them.

    Returns (gating, advisory). Gating findings are defects the Coder can
    repair by changing code - a hero that never made it on screen, text
    running off the edge, a background not stretched to fill. Advisory
    findings are real but not the Coder's to fix: placeholder art means the
    Asset Maker never produced a suitable sprite, so failing QA over it would
    spend retries on a problem no rewrite can solve.

    Any failure (model unavailable, timeout, unparseable reply) returns no
    findings at all - the vision pass must never fail a build by breaking.
    """
    try:
        data = _vision_raw(screenshot_path, design_doc)
    except Exception as e:
        print(f"[QA Agent] Vision review skipped ({type(e).__name__}: {e})")
        return [], []

    gating, advisory = [], []
    if data.get("hero_visible") is False:
        gating.append(
            "Visual defect: the hero sprite is not visible on screen. Make sure it is "
            "added to the tree, positioned inside the 1024x576 viewport, and not "
            "scaled to zero or hidden behind the background."
        )
    if data.get("background_fills_screen") is False:
        gating.append(
            "Visual defect: the background does not fill the screen. A background "
            "Sprite2D needs centered = false and position = Vector2.ZERO."
        )
    if data.get("text_clipped") is True:
        gating.append(
            "Visual defect: on-screen text is clipped or hidden behind another "
            "element. Reposition the labels so every one is fully readable."
        )
    if data.get("looks_broken"):
        # This is free-form model prose from one frame. Structured observations
        # above can identify a concrete failure, but vague composition or art
        # criticism must not spend a Coder retry. Temporal video QA can still
        # gate an actual layering, stability, or disappearance defect.
        advisory.append(f"Vision (advisory): {data['looks_broken']}")
    if data.get("placeholder_art"):
        advisory.append(f"Vision (advisory): {data['placeholder_art']}")
    return gating, advisory


def _reconcile_visual_evidence(
    screenshot_gating: list[str],
    screenshot_advisory: list[str],
    video_result: dict | None,
) -> tuple[list[str], list[str]]:
    """Resolve single-frame findings against stronger temporal evidence.

    A gameplay video showing the player or readable HUD directly contradicts
    a screenshot model claiming the opposite. Those findings remain visible
    in the ledger as advisories, but cannot trigger code regeneration. Other
    concrete screenshot defects remain gating.
    """
    remaining = []
    notes = list(screenshot_advisory)
    for finding in screenshot_gating:
        lower = finding.lower()
        contradicted_by = None
        if (
            "hero sprite is not visible" in lower
            and video_result
            and video_result.get("player_visible") is True
        ):
            contradicted_by = "the gameplay video shows the player"
        elif (
            "on-screen text is clipped" in lower
            and video_result
            and video_result.get("hud_readable") is True
        ):
            contradicted_by = "the gameplay video shows a readable HUD"

        if contradicted_by:
            detail = finding.removeprefix("Visual defect: ").strip()
            notes.append(
                f"Vision (advisory, contradicted): {detail} ({contradicted_by})."
            )
        else:
            remaining.append(finding)

    return remaining, remaining + notes


def _capture_gameplay_video(
    project_dir: str,
    scene: str,
    level_index: int,
) -> tuple[str | None, list[str], bool]:
    """Record deterministic autoplay and convert Godot's AVI to compact MP4.

    Returns ``(path, errors, blocked)``. Capture/transcode infrastructure
    failures block a requested video gate; generated runtime failures remain
    ordinary Coder-repairable QA failures.
    """
    project = Path(project_dir)
    stem = f"gameplay_Level{level_index}"
    avi_path = project / f"{stem}.avi"
    mp4_path = project / f"{stem}.mp4"
    avi_path.unlink(missing_ok=True)
    mp4_path.unlink(missing_ok=True)

    capture = _run(
        [
            "--path",
            project_dir,
            scene,
            "--write-movie",
            f"res://{stem}.avi",
            "--fixed-fps",
            str(VIDEO_CAPTURE_FPS),
            "--disable-vsync",
            "--quit-after",
            str(VIDEO_CAPTURE_MAX_FRAMES),
            "--",
            "--autoplay",
        ],
        timeout=120,
    )
    output = capture.stdout + capture.stderr
    capture_errors = _find_errors(output)
    if capture.returncode != 0 or capture_errors:
        errors = capture_errors or [
            f"Gameplay video capture exited with code {capture.returncode}"
        ]
        return None, errors, _has_harness_error(errors)
    if not avi_path.exists() or avi_path.stat().st_size == 0:
        return (
            None,
            ["QA infrastructure: Godot gameplay capture produced no AVI file."],
            True,
        )

    try:
        converted = subprocess.run(
            [
                FFMPEG_EXE,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(avi_path),
                "-vf",
                f"fps={VIDEO_REVIEW_FPS},scale=640:-2:flags=lanczos",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "24",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(mp4_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (
            None,
            [f"QA infrastructure: FFmpeg video conversion failed: {type(exc).__name__}: {exc}"],
            True,
        )
    if converted.returncode != 0 or not mp4_path.exists() or mp4_path.stat().st_size == 0:
        detail = (converted.stderr or converted.stdout or "no MP4 produced").strip()[-500:]
        return (
            None,
            [f"QA infrastructure: FFmpeg video conversion failed: {detail}"],
            True,
        )
    avi_path.unlink(missing_ok=True)
    return str(mp4_path), [], False


def _video_prompt(design_doc) -> str:
    title = (design_doc or {}).get("title", "the game")
    hero = (design_doc or {}).get("hero_description", "the player character")
    return (
        f"Review this deterministic 8-second gameplay clip from {title!r}. "
        f"The player character is: {hero}. After a short idle period, the harness "
        "holds RIGHT, DOWN, LEFT, then UP. Judge only visible evidence across the "
        "whole clip. Do not infer mechanics or defects that cannot be seen. "
        "For movement_facing, inspect the horizontal RIGHT and LEFT segments; use "
        "'reversed' only when the character clearly looks opposite its travel, and "
        "'indeterminate' for frontal or symmetric art. For animation, use 'sliding' "
        "only when the player visibly translates as a rigid still image. Return ONLY "
        "JSON matching exactly: "
        '{"player_visible": bool, "player_motion": "moves|stationary|indeterminate", '
        '"movement_facing": "correct|reversed|indeterminate", '
        '"animation": "animated|sliding|indeterminate", "hud_readable": bool, '
        '"scene_stable": bool, "code_defects": [string], '
        '"art_advisories": [string], "evidence": string}. '
        "code_defects is only for obvious temporal failures fixable in gameplay code, "
        "such as severe jitter, disappearing required objects, frozen gameplay, or "
        "broken layering. Put art-quality concerns in art_advisories instead."
    )


def _video_raw(video_path: str, design_doc) -> dict:
    import base64

    from saga.llm import chat

    encoded = base64.b64encode(Path(video_path).read_bytes()).decode("ascii")
    text = chat(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "video_url",
                        "video_url": {"url": f"data:video/mp4;base64,{encoded}"},
                    },
                    {"type": "text", "text": _video_prompt(design_doc)},
                ],
            }
        ],
        model=VIDEO_MODEL,
        json_mode=True,
        max_tokens=2000,
        base_url=VIDEO_BASE_URL,
        key_env=VIDEO_KEY_ENV,
        timeout=VIDEO_TIMEOUT,
        temperature=0.2,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0) if match else text)


def _validate_video_verdict(data: dict) -> list[str]:
    problems = []
    for field in ("player_visible", "hud_readable", "scene_stable"):
        if not isinstance(data.get(field), bool):
            problems.append(f"{field} must be boolean")
    allowed = {
        "player_motion": {"moves", "stationary", "indeterminate"},
        "movement_facing": {"correct", "reversed", "indeterminate"},
        "animation": {"animated", "sliding", "indeterminate"},
    }
    for field, values in allowed.items():
        if data.get(field) not in values:
            problems.append(f"{field} must be one of {sorted(values)}")
    for field in ("code_defects", "art_advisories"):
        value = data.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            problems.append(f"{field} must be a list of strings")
    if not isinstance(data.get("evidence"), str):
        problems.append("evidence must be a string")
    return problems


def _video_review(
    video_path: str,
    design_doc,
) -> tuple[dict | None, list[str], list[str], str | None]:
    """Return structured result, gating defects, advisories, infrastructure error."""
    try:
        data = _video_raw(video_path, design_doc)
    except Exception as exc:
        return None, [], [], f"{type(exc).__name__}: {exc}"
    problems = _validate_video_verdict(data)
    if problems:
        return None, [], [], "; ".join(problems)

    gating = []
    if data["player_visible"] is False:
        gating.append("Video defect: the player is not visible during gameplay.")
    if data["player_motion"] == "stationary":
        gating.append("Video defect: the player remains stationary while movement input is held.")
    if data["movement_facing"] == "reversed":
        gating.append(
            "Video defect: the player sprite faces opposite its horizontal movement. "
            "Use Anim.walk(sprite, is_moving, direction.x) and preserve the harness's "
            "native-left sprite convention."
        )
    if data["animation"] == "sliding":
        gating.append(
            "Video defect: the player slides as a rigid still image. Register the idle/walk "
            "textures with Anim.set_poses and call Anim.walk every frame."
        )
    if data["hud_readable"] is False:
        gating.append("Video defect: the HUD becomes unreadable during gameplay.")
    if data["scene_stable"] is False:
        gating.append("Video defect: the gameplay scene visibly jitters, tears, or destabilizes.")
    gating.extend(f"Video defect: {defect}" for defect in data["code_defects"])
    advisory = [f"Video (advisory): {note}" for note in data["art_advisories"]]
    result = {
        "status": "failed" if gating else "passed",
        "model": VIDEO_MODEL,
        **data,
    }
    return result, gating, advisory, None


def _record_attempt(
    state: GraphState,
    *,
    passed: bool,
    stage: str,
    errors: list[str] | None = None,
    screenshot_path: str | None = None,
    vision_notes: list[str] | None = None,
    balance_notes: list[str] | None = None,
    objective_result: dict | None = None,
    gameplay_video_path: str | None = None,
    video_qa_result: dict | None = None,
    video_notes: list[str] | None = None,
    blocked: bool = False,
) -> list[dict]:
    """Return a new durable QA ledger with this attempt appended.

    LangGraph node updates replace ordinary list fields, so this helper copies
    the existing ledger instead of mutating state in place. The compact
    current-step fields remain useful to the Coder and Director; this ledger
    is the source of truth for reporting and the final ship decision.
    """
    current_level = state.get("current_level") or 0
    retry_count = state.get("retry_count") or 0
    design_levels = (state.get("design_doc") or {}).get("levels") or []
    level_name = (
        design_levels[current_level].get("name", f"Level {current_level + 1}")
        if current_level < len(design_levels)
        else f"Level {current_level + 1}"
    )
    errors = list(errors or [])
    vision_notes = list(vision_notes or [])
    balance_notes = list(balance_notes or [])
    video_notes = list(video_notes or [])

    ledger = [dict(item) for item in (state.get("level_results") or [])]
    entry_index = next(
        (i for i, item in enumerate(ledger) if item.get("level_index") == current_level),
        None,
    )
    previous = ledger[entry_index] if entry_index is not None else {}
    asset_replacements = list(previous.get("asset_replacements") or [])
    attempts = [dict(item) for item in previous.get("attempts", [])]
    attempts.append(
        {
            "attempt": retry_count + 1,
            "status": "blocked" if blocked else ("passed" if passed else "failed"),
            "stage": stage,
            "errors": errors,
            "screenshot_path": screenshot_path,
            "vision_notes": vision_notes,
            "balance_notes": balance_notes,
            "objective_result": objective_result,
            "gameplay_video_path": gameplay_video_path,
            "video_qa_result": video_qa_result,
            "video_notes": video_notes,
            "coder_model": state.get("coder_model"),
        }
    )
    entry = {
        "level_index": current_level,
        "level_number": current_level + 1,
        "name": level_name,
        "status": "blocked" if blocked else ("passed" if passed else "failed"),
        "attempts": attempts,
        "retry_count": retry_count if passed else retry_count + 1,
        "qa_errors": errors,
        "screenshot_path": screenshot_path,
        "vision_notes": vision_notes,
        "balance_notes": balance_notes,
        "objective_result": objective_result,
        "gameplay_video_path": gameplay_video_path,
        "video_qa_result": video_qa_result,
        "video_notes": video_notes,
        "coder_model": state.get("coder_model"),
        "asset_replacements": asset_replacements,
    }
    if entry_index is None:
        ledger.append(entry)
    else:
        ledger[entry_index] = entry
    return sorted(ledger, key=lambda item: item.get("level_index", 0))


def _failed_attempt(
    state: GraphState,
    *,
    stage: str,
    errors: list[str],
    screenshot_path: str | None = None,
    vision_notes: list[str] | None = None,
    balance_notes: list[str] | None = None,
    objective_result: dict | None = None,
    gameplay_video_path: str | None = None,
    video_qa_result: dict | None = None,
    video_notes: list[str] | None = None,
    blocked: bool = False,
) -> GraphState:
    retry_count = state.get("retry_count") or 0
    return {
        "qa_passed": False,
        "qa_errors": errors,
        "retry_count": retry_count + 1,
        "screenshot_path": screenshot_path,
        "vision_notes": vision_notes or [],
        "balance_notes": balance_notes or [],
        "objective_result": objective_result,
        "gameplay_video_path": gameplay_video_path,
        "video_qa_result": video_qa_result,
        "video_notes": video_notes or [],
        "level_results": _record_attempt(
            state,
            passed=False,
            stage=stage,
            errors=errors,
            screenshot_path=screenshot_path,
            vision_notes=vision_notes,
            balance_notes=balance_notes,
            objective_result=objective_result,
            gameplay_video_path=gameplay_video_path,
            video_qa_result=video_qa_result,
            video_notes=video_notes,
            blocked=blocked,
        ),
        "ship_blocked": blocked,
    }


def qa_agent(state: GraphState) -> GraphState:
    project_dir = state["godot_project_path"]
    retry_count = state.get("retry_count") or 0
    current_level = state.get("current_level") or 0
    scene = f"res://Level_{current_level}.tscn"
    script_file = Path(project_dir) / f"Level_{current_level}.gd"

    if state.get("repair_rejected"):
        errors = list(state.get("repair_validation_errors") or [
            "Repair candidate was rejected before promotion"
        ])
        print(f"[QA Agent] Repair gate rejected candidate; skipping full QA: {errors}")
        result = _failed_attempt(state, stage="repair_gate", errors=errors)
        result["repair_rejected"] = False
        result["repair_validation_errors"] = []
        return result

    # Defense in depth: the Coder checks before writing, and QA checks again
    # immediately before launching Godot so agentic edits or manual changes
    # cannot bypass the generated-code policy.
    try:
        assert_safe_gdscript(script_file.read_text(encoding="utf-8"))
    except (OSError, UnsafeGeneratedCodeError) as exc:
        print(f"[QA Agent] BLOCKED unsafe or unreadable generated script: {exc}")
        return _failed_attempt(state, stage="safety", errors=[str(exc)])

    # 1. Import assets
    import_result = _run(["--headless", "--path", project_dir, "--import", "--quit"])
    import_errors = _find_errors(import_result.stdout + import_result.stderr)
    if import_result.returncode != 0 or import_errors:
        blocked = _has_harness_error(import_errors)
        label = "BLOCKED" if blocked else "FAILED"
        print(f"[QA Agent] {label} at import step: {import_errors or 'non-zero exit'}")
        return _failed_attempt(
            state,
            stage="harness" if blocked else "import",
            errors=import_errors or ["Import step failed"],
            blocked=blocked,
        )

    # 2. Actually run THIS level's scene for a bounded number of frames -
    # this also catches compile errors (a broken script fails to load),
    # which is why no separate --check-only pass is needed (or safe: it
    # can't see autoloads).
    run_result = _run(["--headless", "--path", project_dir, scene, "--quit-after", "120"], timeout=30)
    run_errors = _find_errors(run_result.stdout + run_result.stderr)
    if run_result.returncode != 0 or run_errors:
        blocked = _has_harness_error(run_errors)
        label = "BLOCKED" if blocked else "FAILED"
        print(
            f"[QA Agent] {label} at scene run: "
            f"{run_errors or f'exit code {run_result.returncode}'}"
        )
        return _failed_attempt(
            state,
            stage="harness" if blocked else "scene_run",
            errors=run_errors or [f"Scene run exited with code {run_result.returncode}"],
            blocked=blocked,
        )

    # 2b. Actually play it. A scene that runs without errors can still be
    # completely inert - a hero that cannot move, or an objective that never
    # changes, passes every check above. The Autoplay autoload holds each
    # arrow key in turn and reports whether anything moved and whether the
    # status label ever said anything different.
    play = _run(
        ["--headless", "--path", project_dir, scene, "--quit-after", "600", "--", "--autoplay"],
        timeout=60,
    )
    play_out = play.stdout + play.stderr
    play_process_errors = _find_errors(play_out)
    if play.returncode != 0 or play_process_errors:
        blocked = _has_harness_error(play_process_errors)
        label = "BLOCKED" if blocked else "FAILED"
        print(
            f"[QA Agent] {label} during autoplay: "
            f"{play_process_errors or f'exit code {play.returncode}'}"
        )
        return _failed_attempt(
            state,
            stage="harness" if blocked else "autoplay",
            errors=play_process_errors or [f"Autoplay exited with code {play.returncode}"],
            blocked=blocked,
        )
    verdict = re.search(
        r"\[AUTOPLAY\] idle_rate=([\d.]+) input_rate=([\d.]+) label_states=(\d+)", play_out
    )
    if verdict:
        idle_rate, input_rate = float(verdict.group(1)), float(verdict.group(2))
        label_states = int(verdict.group(3))
        # Held keys must move the world markedly more than it moves on its own.
        # The ratio handles games with busy ambient motion; the absolute floor
        # handles still ones, where a ratio against nearly zero means nothing.
        # Measured on one real build and a copy of it with input disabled:
        # 4.28 vs 0.97 against an identical idle rate of ~0.89.
        moved = input_rate > max(idle_rate * 1.5, 0.5)
        print(
            f"[QA Agent] Autoplay: idle={idle_rate:.2f} input={input_rate:.2f} "
            f"responsive={moved} label_states={label_states}"
        )
        play_errors = []
        if not moved:
            play_errors.append(
                "Playability: holding each arrow key in turn moved nothing on screen. "
                "The player must move in response to ui_left/ui_right/ui_up/ui_down "
                "while state is 'playing'."
            )
        # Label change is NOT a gate. It assumes holding a direction advances
        # the game, which is true of timers, drains and touch-collection but
        # false of any puzzle: an ordered-switch level only updates its label
        # when the right switch is hit in the right order, which random input
        # will not achieve. Measured on a real build that was working fine.
        if label_states <= 1:
            print(
                "[QA Agent] Autoplay note (advisory): the status label did not change "
                "while arrow keys were held. Expected for a puzzle whose progress needs "
                "correct input; a problem for anything driven by a timer or resource."
            )
        if play_errors:
            print(f"[QA Agent] FAILED on {len(play_errors)} playability defect(s) - requesting a fix")
            return _failed_attempt(state, stage="playability", errors=play_errors)
    else:
        # A silent required probe means QA did not establish playability. This
        # is a harness/infrastructure block, not generated code to send through
        # six speculative Coder repairs.
        error = "QA infrastructure: autoplay produced no verdict, so responsiveness is unknown."
        print(f"[QA Agent] BLOCKED: {error}")
        return _failed_attempt(
            state,
            stage="autoplay_probe",
            errors=[error],
            blocked=True,
        )

    # 3. Mechanic-specific objective completion. Generic autoplay proves the
    # player responds; for deterministic mechanics we also require the actual
    # objective to be reachable and its real win state to fire.
    template = (state.get("design_doc") or {}).get("mechanic_template", "")
    objective_result = None
    if template in {
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
    }:
        objective_result, objective_errors, objective_blocked = _run_objective_probe(
            project_dir,
            scene,
            template,
        )
        if objective_errors:
            label = "BLOCKED" if objective_blocked else "FAILED"
            print(f"[QA Agent] {label} {template} objective completion: {objective_errors}")
            return _failed_attempt(
                state,
                stage="objective_probe" if objective_blocked else "objective_completion",
                errors=objective_errors,
                objective_result=objective_result,
                blocked=objective_blocked,
            )
        noun = {
            "ordered_switches": "switches",
            "survive_hazards": "survival milestones",
            "depletion": "resource milestones",
            "survive_and_deplete": "hybrid milestones",
            "capture_zones": "capture milestones",
            "herd_to_goal": "herding milestones",
        }.get(template, "pickups")
        print(
            f"[QA Agent] Objective: completed {objective_result['collected']}/"
            f"{objective_result['total']} {noun} and reached won in "
            f"{objective_result['completion_seconds']:.1f}s "
            f"(score={objective_result['completion_score']}, "
            f"max_stall={objective_result['max_stall_frames']} frames)"
        )

    # 4. Balance check. The script runs, but that says nothing about whether
    # its challenge is survivable - a drain that outpaces every refill, or a
    # pursuer faster than the player, compiles perfectly and is unwinnable.
    # Purely static and instant, so it runs before the screenshot pass. A
    # definitive unwinnability finding remains gating on every attempt; the
    # retry ledger makes a persistent defect visible instead of laundering it
    # into a pass.
    balance_notes = []
    if script_file.exists():
        bal_gating, balance_notes = check_level(script_file.read_text(encoding="utf-8"), template)
        for note in bal_gating + balance_notes:
            print(f"[QA Agent] {note}")
        if bal_gating:
            print(f"[QA Agent] FAILED on {len(bal_gating)} balance defect(s) - requesting a fix")
            return _failed_attempt(
                state,
                stage="balance",
                errors=bal_gating,
                balance_notes=balance_notes,
                objective_result=objective_result,
            )

    # 5. Active-gameplay screenshot pass (a window flashes for ~1.5s). This is
    # a fresh process: screenshot.gd dismisses the title screen and captures
    # frame 60, so the objective solver above cannot leave it on a win screen.
    # It no-ops in the headless runs above.
    screenshot_path = None
    screenshot_file = Path(project_dir) / f"screenshot_Level{current_level}.png"
    try:
        screenshot_file.unlink(missing_ok=True)  # never report a stale frame
        _run(["--path", project_dir, scene, "--quit-after", "90"], timeout=30)
        if screenshot_file.exists():
            screenshot_path = str(screenshot_file)
            print(f"[QA Agent] Active gameplay screenshot captured -> {screenshot_path}")
        else:
            print("[QA Agent] Screenshot pass produced no image (non-blocking)")
    except Exception as e:
        print(f"[QA Agent] Screenshot pass failed (non-blocking): {e}")

    # 6. Vision review. When video QA is enabled, hold single-frame gating
    # findings until the stronger temporal evidence can confirm or contradict
    # them. Free-form art/composition criticism is always advisory.
    vision_notes = []
    vision_gating = []
    vision_advisory = []
    if screenshot_path:
        vision_gating, vision_advisory = _vision_review(
            screenshot_path, state.get("design_doc")
        )
        vision_notes = vision_gating + vision_advisory
        if not VIDEO_QA_ENABLED:
            for note in vision_notes:
                print(f"[QA Agent] {note}")
        if vision_gating and not VIDEO_QA_ENABLED:
            print(
                f"[QA Agent] FAILED on {len(vision_gating)} visual defect(s) "
                "- requesting a fix"
            )
            return _failed_attempt(
                state,
                stage="vision",
                errors=vision_gating,
                screenshot_path=screenshot_path,
                vision_notes=vision_notes,
                balance_notes=balance_notes,
                objective_result=objective_result,
            )

    # 7. Required gameplay video review when explicitly enabled. Unlike the
    # screenshot, this observes temporal defects: reversed facing, rigid
    # sliding, frozen motion, jitter, and objects disappearing mid-play.
    gameplay_video_path = None
    video_qa_result = None
    video_notes = []
    if VIDEO_QA_ENABLED:
        gameplay_video_path, video_errors, video_blocked = _capture_gameplay_video(
            project_dir,
            scene,
            current_level,
        )
        if video_errors:
            label = "BLOCKED" if video_blocked else "FAILED"
            print(f"[QA Agent] {label} gameplay video capture: {video_errors}")
            return _failed_attempt(
                state,
                stage="video_capture_probe" if video_blocked else "video_capture",
                errors=video_errors,
                screenshot_path=screenshot_path,
                vision_notes=vision_notes,
                balance_notes=balance_notes,
                objective_result=objective_result,
                blocked=video_blocked,
            )
        print(f"[QA Agent] Gameplay video captured -> {gameplay_video_path}")
        video_qa_result, video_gating, video_notes, video_error = _video_review(
            gameplay_video_path,
            state.get("design_doc"),
        )
        if video_error:
            error = f"QA infrastructure: NVIDIA video QA produced no valid verdict ({video_error})."
            print(f"[QA Agent] BLOCKED: {error}")
            return _failed_attempt(
                state,
                stage="video_qa_probe",
                errors=[error],
                screenshot_path=screenshot_path,
                vision_notes=vision_notes,
                balance_notes=balance_notes,
                objective_result=objective_result,
                gameplay_video_path=gameplay_video_path,
                blocked=True,
            )
        for note in video_gating + video_notes:
            print(f"[QA Agent] {note}")
        if video_gating:
            print(f"[QA Agent] FAILED on {len(video_gating)} gameplay video defect(s)")
            return _failed_attempt(
                state,
                stage="video_qa",
                errors=video_gating,
                screenshot_path=screenshot_path,
                vision_notes=vision_notes,
                balance_notes=balance_notes,
                objective_result=objective_result,
                gameplay_video_path=gameplay_video_path,
                video_qa_result=video_qa_result,
                video_notes=video_notes,
            )
        print(
            f"[QA Agent] NVIDIA video QA passed: "
            f"{video_qa_result['evidence']}"
        )

        vision_gating, vision_notes = _reconcile_visual_evidence(
            vision_gating,
            vision_advisory,
            video_qa_result,
        )
        for note in vision_notes:
            print(f"[QA Agent] {note}")
        if vision_gating:
            print(
                f"[QA Agent] FAILED on {len(vision_gating)} confirmed visual "
                "defect(s) - requesting a fix"
            )
            return _failed_attempt(
                state,
                stage="vision",
                errors=vision_gating,
                screenshot_path=screenshot_path,
                vision_notes=vision_notes,
                balance_notes=balance_notes,
                objective_result=objective_result,
                gameplay_video_path=gameplay_video_path,
                video_qa_result=video_qa_result,
                video_notes=video_notes,
            )

    # This is the only point in the pipeline where a script is known-good
    # (compiled, ran, satisfied its template contract) - so it's where the
    # training corpus gets its verified pairs.
    record_level(
        prompt=state.get("coder_prompt"),
        script=script_file.read_text(encoding="utf-8") if script_file.exists() else "",
        template=(state.get("design_doc") or {}).get("mechanic_template", "unknown"),
        model=state.get("coder_model"),
        level_index=current_level,
        retry_count=retry_count,
        design_doc=state.get("design_doc"),
        vision_notes=vision_notes + video_notes,
    )

    system_build_results = state.get("system_build_results") or []
    if system_build_results:
        from saga.protected_builder import attach_qa_evidence

        system_build_results = attach_qa_evidence(
            system_build_results,
            level_index=current_level,
            active_script=script_file.read_text(encoding="utf-8"),
            objective_result=objective_result,
            video_qa_result=video_qa_result,
        )

    print("[QA Agent] PASSED - scene ran headlessly with no errors")
    return {
        "qa_passed": True,
        "qa_errors": [],
        "screenshot_path": screenshot_path,
        "vision_notes": vision_notes,
        "balance_notes": balance_notes,
        "objective_result": objective_result,
        "gameplay_video_path": gameplay_video_path,
        "video_qa_result": video_qa_result,
        "video_notes": video_notes,
        "level_results": _record_attempt(
            state,
            passed=True,
            stage="complete",
            screenshot_path=screenshot_path,
            vision_notes=vision_notes,
            balance_notes=balance_notes,
            objective_result=objective_result,
            gameplay_video_path=gameplay_video_path,
            video_qa_result=video_qa_result,
            video_notes=video_notes,
        ),
        "ship_blocked": False,
        "system_build_results": system_build_results,
    }
