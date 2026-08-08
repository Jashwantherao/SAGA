# SAGA model-quality benchmark

This benchmark compares coder models while holding the design document, game case, deterministic Systems Architect contract, local repair director, asset pipeline, deterministic QA, and NVIDIA video reviewer constant. It reports truthful ship rate, first-pass completion, objective performance, repair behavior, advisories, wall time, and code-size diagnostics. Coder suites default the architect to `deterministic` so an extra Nemotron call cannot change the input under test; full-studio suites may opt into a model architect explicitly.

No API secret is stored in a suite or result. Profiles contain only the name of the environment variable that already holds a key.

## Readiness

Run preflight before spending any model calls:

```powershell
.\.venv\Scripts\python.exe -m saga.main --doctor
```

The benchmark requires Godot, Ollama, ComfyUI, FFmpeg, `DEEPSEEK_API_KEY`, and `NVIDIA_API_KEY`. MusicGen is optional. Keep every executable, model cache, run artifact, and temporary directory on D:.

## Inspect without spending

```powershell
.\.venv\Scripts\python.exe -m saga.benchmark benchmarks\quality_pilot.json --max-runs 15 --dry-run
```

## Six-model pilot

Start with one identical simple case across all six profiles:

```powershell
.\.venv\Scripts\python.exe -m saga.benchmark benchmarks\quality_pilot.json `
  --cases signal-orchard `
  --max-runs 6 `
  --max-minutes 150 `
  --timeout-minutes 30 `
  --output-dir output\benchmarks\coder-pilot-v1
```

The output directory is resumable. Running the same command again skips completed jobs. It contains per-job pipeline logs and manifests plus `results.json`, `results.csv`, and `leaderboard.md`.

## Full matrix

After the pilot proves provider compatibility and sensible costs:

```powershell
.\.venv\Scripts\python.exe -m saga.benchmark benchmarks\quality_pilot.json `
  --max-runs 18 `
  --max-minutes 450 `
  --timeout-minutes 30 `
  --output-dir output\benchmarks\coder-matrix-v1
```

Do not compare runs created with different suite files as though they were the same experiment. Add repetitions only after the first matrix works, because a single sample measures model luck as well as model quality.

## Incremental-build A/B

`incremental_ab.json` measures whether the protected incremental builder earns
its extra cost (one specialist call plus one Godot gate run per system). It
pairs the two pilot leaders with `SAGA_INCREMENTAL_BUILD` off and on, holding
everything else constant:

```powershell
.\.venv\Scripts\python.exe -m saga.benchmark benchmarks\incremental_ab.json `
  --max-runs 12 `
  --max-minutes 400 `
  --timeout-minutes 40 `
  --output-dir output\benchmarks\incremental-ab-v1
```

Compare the paired profiles' quality, retries, and median time; the per-system
ledger for each job is in its manifest's `system_build_results`.

## Verified-experience-memory A/B

`experience_memory_ab.json` isolates retrieval from the local QA-passed Coder
corpus. Both arms use the same model, deterministic architect, fixed design
documents, assets, and QA stack; only `SAGA_EXPERIENCE_MEMORY` changes. The
retriever never crosses mechanic templates and emits only complete scripts.

```powershell
.\.venv\Scripts\python.exe -m saga.benchmark benchmarks\experience_memory_ab.json `
  --max-runs 6 `
  --max-minutes 240 `
  --timeout-minutes 40 `
  --output-dir output\benchmarks\experience-memory-ab-v1
```

Promote memory to the default only if the on arm improves first-pass levels or
quality without reducing truthful ship rate. A larger prompt by itself is not
evidence of a better agent.

The first `experience-memory-ab-v1` pilot (2026-08-08, one repetition per
case) kept ship rate even at 67%, but was mixed by mechanic: `collect` improved
from 4 retries/78.33 quality to 0 retries/98.33, while
`survive_and_deplete` regressed from 0 retries/100 to 2 retries/80 and both
`dot_maze` arms failed. Memory therefore remains opt-in. The retriever now
admits only compact (at most 8,000 characters), first-pass examples with at
least 20% query-token overlap; this excludes the two harmful references from
that pilot while retaining the useful `collect` example. Repeat the suite
before changing the default.

Comparability note: the Systems Architect contract is now appended to every
Coder prompt, so runs made after that change are not comparable with
`coder-pilot-v1` results even on the same cases. Rerun under a new suite id
(or a fresh output dir) instead of extending old result files.
