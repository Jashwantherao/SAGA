# SAGA v1 release readiness

This checklist defines “complete” for the portfolio release. A feature is not
done because it exists in source; it is done when a fresh user can reach it,
the relevant automated evidence passes, and the public documentation explains
the result honestly.

## Product acceptance

- [x] Desktop control room covers creation, live progress, services, models,
  game library, QA evidence, artifacts, and play/open actions.
- [x] Packaged desktop executable starts and owns the loopback API without a
  second terminal, logs it, and stops only the process it launched.
- [x] A self-starting Windows executable can be produced with one D:-local
  command and without Tauri writing packaging tools to C:.
- [ ] Portable backend distribution: an installer must work without retaining
  the source checkout or its `.venv`.
- [ ] First-run setup must detect missing Godot/services/models and guide the
  user through every required action without sending them to the README.
- [ ] A cancelled or interrupted generation must recover cleanly after an app
  restart and retain its last useful run evidence.

## Game-quality acceptance

- [x] Every mechanic family has executable objective QA and a truthful ship
  gate; packed families also require normal-input playthrough evidence.
- [x] Action RPG worlds compile real directional branches and shortcuts rather
  than decorative graph metadata.
- [ ] Room Purpose & Encounter Director must make authored rooms mechanically
  distinct and reject repetitive “fight in another box” worlds.
- [ ] Produce one fresh flagship three-level game through the public UI with
  video QA enabled, zero manual project edits, and `ship_ready=true`.
- [ ] Run a blind human playtest against the current strongest benchmark and
  publish the scores, defects, and fixes.

## Engineering acceptance

- [x] Python unit/regression suite runs in GitHub Actions.
- [x] Frontend lint and production build run in GitHub Actions.
- [x] Tauri Rust compilation runs on a Windows GitHub runner.
- [x] Generate a SHA-256 checksum beside every local release executable.
- [ ] Add a portable installer smoke test.
- [ ] Merge superseded Action-RPG PR #26 and the current clean PR #27 without
  leaving overlapping open branches.
- [ ] Tag `v1.0.0`, publish the installer, changelog, and reproducible release
  notes from a clean default branch.

## Portfolio acceptance

- [x] Root MIT license matches package metadata.
- [ ] Replace the long setup-first README opening with a concise product demo,
  architecture diagram, verified results, and five-minute evaluator path.
- [ ] Record a 60–90 second SAGA Studio demo showing prompt → agents → QA →
  playable game, plus a short flagship gameplay clip.
- [ ] Add screenshots/GIFs that are committed or attached to the GitHub release
  rather than referenced from a private generated-output directory.
- [ ] Publish a recruiter-facing architecture case study covering constraints,
  multi-agent orchestration, deterministic capability packs, failure recovery,
  evaluation, benchmarks, and measured trade-offs.

## Current release artifacts

The source-bound portfolio package is built with:

```powershell
D:\SAGA\scripts\saga_ui.ps1 -Mode package
```

It emits `release/SAGA-Studio-0.1.0.exe` and a matching `.sha256` checksum
without invoking WiX or NSIS, whose Windows tool cache cannot be redirected
away from C: by the current Tauri bundler.

This package is suitable for demonstrating the current D:\SAGA checkout. It is
not the final portable release until the Python backend and runtime resources
are bundled independently of the checkout.
