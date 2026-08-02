# SAGA model-quality benchmark

This benchmark compares coder models while holding the design document, game case, local repair director, asset pipeline, deterministic QA, and NVIDIA video reviewer constant. It reports truthful ship rate, first-pass completion, objective performance, repair behavior, advisories, wall time, and code-size diagnostics.

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
