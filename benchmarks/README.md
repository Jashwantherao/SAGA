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

Comparability note: the Systems Architect contract is now appended to every
Coder prompt, so runs made after that change are not comparable with
`coder-pilot-v1` results even on the same cases. Rerun under a new suite id
(or a fresh output dir) instead of extending old result files.
