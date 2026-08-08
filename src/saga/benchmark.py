"""Reproducible, cost-bounded model quality benchmark for SAGA."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

SAFE_ENV_KEYS = {
    "SAGA_CODER_BACKEND",
    "SAGA_CODER_MODEL",
    "SAGA_CODER_REMOTE_MODEL",
    "SAGA_CODER_TIMEOUT",
    "SAGA_DOTMAZE_MODEL",
    "SAGA_OPENAI_BASE_URL",
    "SAGA_OPENAI_KEY_ENV",
    "SAGA_DESIGNER_BACKEND",
    "SAGA_DIRECTOR_BACKEND",
    "SAGA_DIRECTOR_MODEL",
    "SAGA_VIDEO_QA",
    "SAGA_ARCHITECT_BACKEND",
    "SAGA_INCREMENTAL_BUILD",
    "SAGA_INCREMENTAL_MAX_SYSTEMS",
    "SAGA_INCREMENTAL_MAX_ATTEMPTS",
    "SAGA_SKILL_CONTEXT",
    "SAGA_SKILL_CONTEXT_LIMIT",
    "SAGA_EXPERIENCE_MEMORY",
    "SAGA_EXPERIENCE_MEMORY_LIMIT",
    "SAGA_EXPERIENCE_MEMORY_MAX_CHARS",
}


@dataclass(frozen=True)
class Job:
    profile: dict
    case: dict
    repetition: int

    @property
    def job_id(self) -> str:
        return f"{self.profile['id']}__{self.case['id']}__r{self.repetition}"


def load_suite(path: Path) -> dict:
    suite = json.loads(path.read_text(encoding="utf-8"))
    for field in ("id", "profiles", "cases"):
        if not suite.get(field):
            raise ValueError(f"benchmark suite missing {field!r}")
    for profile in suite["profiles"]:
        unknown = set(profile.get("env", {})) - SAFE_ENV_KEYS
        if unknown:
            raise ValueError(f"profile {profile.get('id')!r} has unsafe env keys: {sorted(unknown)}")
        if any(key.lower() in {"api_key", "token", "secret"} for key in profile):
            raise ValueError("profiles must name key environment variables, never contain secrets")
    return suite


def build_jobs(suite: dict, profiles: set[str], cases: set[str]) -> list[Job]:
    repetitions = int(suite.get("repetitions", 1))
    return [
        Job(profile, case, repetition)
        for profile in suite["profiles"]
        if not profiles or profile["id"] in profiles
        for case in suite["cases"]
        if not cases or case["id"] in cases
        for repetition in range(1, repetitions + 1)
    ]


def _latest_manifest(output_root: Path) -> Path | None:
    manifests = list((output_root / "runs").glob("*/run.json"))
    return max(manifests, key=lambda item: item.stat().st_mtime, default=None)


def _script_metrics(manifest: dict) -> dict:
    project = manifest.get("godot_project_path")
    if not project:
        return {"gdscript_lines": 0, "gdscript_functions": 0}
    scripts = list(Path(project).glob("*.gd"))
    lines = functions = 0
    for script in scripts:
        try:
            text = script.read_text(encoding="utf-8")
        except OSError:
            continue
        lines += len([line for line in text.splitlines() if line.strip()])
        functions += sum(line.lstrip().startswith("func ") for line in text.splitlines())
    return {"gdscript_lines": lines, "gdscript_functions": functions}


def score(manifest: dict) -> tuple[float, dict]:
    component_names = (
        "ship", "level_pass_rate", "first_pass_rate", "objective", "video",
        "repair_efficiency", "advisory_cleanliness",
    )
    if not manifest:
        return 0.0, {name: 0.0 for name in component_names}
    levels = manifest.get("level_results") or []
    passed = [item for item in levels if item.get("status") == "passed"]
    first_pass = [item for item in passed if (item.get("retry_count") or 0) == 0]
    retries = sum(item.get("retry_count") or 0 for item in levels)
    objective = manifest.get("objective_result") or {}
    objective_score = float(objective.get("completion_score") or 0)
    if objective.get("status") in {"passed", "completed", "won"}:
        objective_score = max(objective_score, 1.0)
    objective_score = max(0.0, min(1.0, objective_score))
    video = manifest.get("video_qa_result") or {}
    video_ok = video.get("status") == "passed" and not manifest.get("video_notes")
    warnings = sum(
        len(manifest.get(key) or []) for key in ("vision_notes", "balance_notes", "video_notes")
    )
    components = {
        "ship": 40.0 if manifest.get("ship_ready") else 0.0,
        "level_pass_rate": 15.0 * len(passed) / max(1, len(levels)),
        "first_pass_rate": 15.0 * len(first_pass) / max(1, len(levels)),
        "objective": 15.0 * objective_score,
        "video": 5.0 if video_ok else 0.0,
        "repair_efficiency": 5.0 * max(0.0, 1.0 - retries / max(1, 2 * len(levels))),
        "advisory_cleanliness": 5.0 * max(0.0, 1.0 - warnings / max(1, 3 * len(levels))),
    }
    return round(sum(components.values()), 2), {key: round(value, 2) for key, value in components.items()}


def extract_result(job: Job, output_root: Path, elapsed: float, exit_code: int, error: str = "") -> dict:
    manifest_path = _latest_manifest(output_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
    quality, components = score(manifest)
    levels = manifest.get("level_results") or []
    attempts = [attempt for level in levels for attempt in (level.get("attempts") or [])]
    return {
        "job_id": job.job_id,
        "profile": job.profile["id"],
        "provider": job.profile.get("provider", "unknown"),
        "model": job.profile.get("model", "unknown"),
        "case": job.case["id"],
        "repetition": job.repetition,
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed, 2),
        "status": manifest.get("status", "no_manifest"),
        "ship_ready": bool(manifest.get("ship_ready")),
        "quality_score": quality,
        "score_components": components,
        "level_count": len(levels),
        "first_pass_levels": sum((item.get("retry_count") or 0) == 0 and item.get("status") == "passed" for item in levels),
        "retries": sum(item.get("retry_count") or 0 for item in levels),
        "repair_gate_rejections": sum(item.get("stage") == "repair_gate" for item in attempts),
        "objective": manifest.get("objective_result"),
        "video_qa": manifest.get("video_qa_result"),
        "advisory_count": sum(len(manifest.get(key) or []) for key in ("vision_notes", "balance_notes", "video_notes")),
        "manifest_path": str(manifest_path) if manifest_path else None,
        "error": error,
        **_script_metrics(manifest),
    }


def build_job_environment(profile: dict, output_root: Path) -> dict[str, str]:
    """Build an isolated environment for one benchmark job.

    The parent process may have a model architect selected for normal studio
    runs.  A coder benchmark must not inherit that selection: doing so adds a
    second model call and changes the contract presented to the coder.  Only a
    profile that explicitly names ``SAGA_ARCHITECT_BACKEND`` may opt in.
    """
    env = os.environ.copy()
    profile_env = {
        key: str(value) for key, value in profile.get("env", {}).items()
    }
    env.update(profile_env)
    if "SAGA_ARCHITECT_BACKEND" not in profile_env:
        env["SAGA_ARCHITECT_BACKEND"] = "deterministic"
    env["SAGA_OUTPUT_ROOT"] = str(output_root)
    env["SAGA_RECORD_CORPUS"] = "0"
    return env


def run_job(job: Job, suite_path: Path, root: Path, timeout_minutes: float) -> dict:
    job_dir = root / "jobs" / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    result_path = job_dir / "benchmark_result.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    output_root = job_dir / "saga_output"
    env = build_job_environment(job.profile, output_root)
    design = (suite_path.parent / job.case["design_doc"]).resolve()
    command = [
        sys.executable, "-u", "-m", "saga.main", job.case["idea"],
        "--levels", str(job.case.get("levels", 1)), "--design-doc", str(design),
    ]
    asset_pack = job.case.get("asset_pack")
    if asset_pack:
        command.extend(["--asset-pack", str((suite_path.parent / asset_pack).resolve())])
    if job.case.get("skip_preflight", True):
        command.append("--skip-preflight")
    started = time.monotonic()
    error = ""
    try:
        with (job_dir / "pipeline.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command, env=env, stdout=log, stderr=subprocess.STDOUT,
                timeout=timeout_minutes * 60, check=False,
            )
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        exit_code, error = 124, f"timed out after {timeout_minutes:g} minutes"
    result = extract_result(job, output_root, time.monotonic() - started, exit_code, error)
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def write_reports(results: list[dict], root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    columns = [
        "profile", "provider", "model", "case", "repetition", "status", "ship_ready",
        "quality_score", "elapsed_seconds", "first_pass_levels", "retries",
        "repair_gate_rejections", "advisory_count", "gdscript_lines", "gdscript_functions",
    ]
    with (root / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    groups = {}
    for result in results:
        groups.setdefault(result["profile"], []).append(result)
    rows = []
    for profile, items in groups.items():
        rows.append({
            "profile": profile,
            "model": items[0]["model"],
            "runs": len(items),
            "ship_rate": mean(item["ship_ready"] for item in items) * 100,
            "quality": mean(item["quality_score"] for item in items),
            "median_seconds": median(item["elapsed_seconds"] for item in items),
            "mean_retries": mean(item["retries"] for item in items),
        })
    rows.sort(key=lambda item: (-item["quality"], -item["ship_rate"], item["median_seconds"]))
    lines = [
        "# SAGA model-quality benchmark", "",
        "The composite score rewards truthful shipping, deterministic level completion, first-pass success, objective completion, video evidence, repair efficiency, and low advisory counts. Code size is reported but never rewarded.", "",
        "| Rank | Profile | Model | Runs | Ship rate | Quality | Median time | Mean retries |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(rows, 1):
        lines.append(
            f"| {rank} | {row['profile']} | `{row['model']}` | {row['runs']} | "
            f"{row['ship_rate']:.0f}% | {row['quality']:.1f} | {row['median_seconds']:.1f}s | {row['mean_retries']:.2f} |"
        )
    (root / "leaderboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--profiles", nargs="*", default=[])
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--max-runs", type=int, default=3)
    parser.add_argument("--max-minutes", type=float, default=90)
    parser.add_argument("--timeout-minutes", type=float, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.max_runs < 1 or args.max_minutes <= 0 or args.timeout_minutes <= 0:
        parser.error("run and time limits must be positive")
    suite_path = args.suite.resolve()
    suite = load_suite(suite_path)
    jobs = build_jobs(suite, set(args.profiles), set(args.cases))[: args.max_runs]
    root = args.output_dir or (
        Path("output") / "benchmarks" /
        f"{suite['id']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    print(f"Benchmark: {suite['id']} | jobs: {len(jobs)} | output: {root}")
    for job in jobs:
        print(f"- {job.job_id}: {job.profile.get('model')} / {job.case['id']}")
    if args.dry_run:
        return
    started = time.monotonic()
    results_path = root / "results.json"
    results = (
        json.loads(results_path.read_text(encoding="utf-8"))
        if results_path.is_file()
        else []
    )
    for job in jobs:
        if time.monotonic() - started >= args.max_minutes * 60:
            print("Suite time budget reached; remaining jobs were not started.")
            break
        print(f"Running {job.job_id}...")
        result = run_job(job, suite_path, root, args.timeout_minutes)
        results = [item for item in results if item.get("job_id") != result["job_id"]]
        results.append(result)
        write_reports(results, root)
    print(f"Leaderboard: {root / 'leaderboard.md'}")


if __name__ == "__main__":
    main()
