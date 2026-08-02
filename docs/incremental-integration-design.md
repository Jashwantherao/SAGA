# Protected incremental integration — Agent Team v2 design

Status: design (nothing here is wired into the graph yet).
Depends on: the Game Blueprint schema (`saga.blueprint`) and model router
(`saga.router`), and on the shipped transactional repair gate
(`saga.repair_gate`) and Studio Director triage.

## Problem

Today the Coder generates one whole gameplay script per level in a single
completion, and QA judges the whole thing. That works for the nine mechanic
templates because each template is one system. It cannot scale to a game
with combat *and* inventory *and* dialogue *and* saves: a single completion
must get every system right simultaneously, one QA failure gives the model
vague whole-game evidence, and every retry regenerates working systems
alongside broken ones. The coder-pilot-v1 benchmark showed the ceiling is
the production process, not model intelligence.

## Core idea

Build the game the way the blueprint orders it: **one system per pass**,
where each pass extends the last *promoted* build and must prove two things
before it is promoted itself:

1. **Its own contract** — the acceptance criteria of the system it adds.
2. **No regression** — the cumulative contracts of every system already
   promoted still pass.

A candidate that fails either check is discarded and the promoted build
stays untouched. This generalizes the repair gate's transaction from
"repairs during QA" to "every build step, always."

## The system pass loop

```
blueprint.build_order() -> [movement, hud, combat, stalker_ai, ...]

for each system S (with per-system retry budget):
    1. BUILD    Coder extends the promoted script with S only.
                Prompt = promoted script (verbatim) + S's blueprint entry
                (description, acceptance criteria, entities involved)
                + the standing harness contract. Model chosen by
                router.candidates(S.kind).
    2. SMOKE    Candidate installed transactionally (build gate, below).
                Godot must load and run the scene clean — same check the
                repair gate performs today.
    3. VERIFY   Acceptance probes run for S *and* for every previously
                promoted system. Any failure = candidate rejected,
                promoted build restored, evidence recorded.
    4. PROMOTE  Candidate becomes the new promoted build; the system is
                marked done in the build ledger with its evidence.
```

The Studio Director keeps its triage role, but per system: on a failed
pass it decides fix / regenerate / reasset *for that system*, with the
director history preventing repeated identical repairs. A system that
exhausts its budget marks the build ledger honestly (`failed`) and the
run stops — shipping a partial game silently is exactly the untruthful
behavior the pipeline was built to prevent.

## Build gate (generalized repair gate)

`saga.repair_gate.validate_and_promote_repair` already implements the
transaction: backup, install candidate, headless smoke run, restore on
script errors. The build gate extends it in place rather than replacing it:

- Rename-in-spirit: the same function guards **every** system pass, not
  only Director-triaged repairs. First pass of the first system is the
  only exception (there is no previous script to protect; the gate's
  existing "no previous script" refusal relaxes to allow genesis).
- After the smoke run passes, the gate additionally runs the **cumulative
  acceptance probes** (step 3 above) before promoting. Restore-on-failure
  semantics are unchanged.
- The backup/candidate checkpoint files and interrupted-run recovery
  carry over as-is.

## Acceptance probes

Blueprint acceptance criteria are natural language for the model; the
harness needs machine verdicts. The bridge is a **probe registry** keyed
by system kind — the same pattern as today's per-template objective
probes (ObjectiveProbe / SwitchProbe / SurvivalProbe autoloads):

| Kind | Probe (deterministic, headless) | Phase |
|---|---|---|
| movement | inject directional input; assert position delta, wall block, playfield clamp | 1 |
| pickup / inventory | drive hero over a pickup; assert removal + count change; assert no dupes after revisit | 1 |
| hud | read label text; assert it reflects injected state changes same-frame | 1 |
| combat | spawn enemy in arc; inject attack; assert hp deltas, invulnerability window, floor at 0 | 2 |
| enemy_ai | place hero inside/outside detection radius; assert state transitions in order | 2 |
| save_load | write checkpoint, mutate state, load; diff every declared save_state field | 2 |
| dialogue / quest | scripted interact sequence; assert stage transitions and movement freeze | 3 |
| level_transition | walk through exit; assert room swap + entrance placement + persistence | 3 |
| boss | scripted fight; assert telegraph precedes damage, phase change at threshold, win flow | 3 |

Rules:

- A kind with no probe yet gets an **advisory** verdict (recorded, never
  gating) — the mechanical/visual QA authority split applies within
  system verification too. A vague complaint must never reject a
  candidate that passed its deterministic checks.
- Probes report concrete evidence ("pickup at (300,180) still present
  after contact"), which becomes the retry prompt. Never "system failed."
- Cumulative verification reruns only *probes*, not the video/vision
  stack — that stays end-of-build, exactly like the repair gate skips the
  expensive gameplay stack today.

## State and ledger

`GraphState` grows (mirroring the existing level fields):

```python
blueprint: Optional[dict]          # validated saga.blueprint contract
current_system: Optional[str]      # id being built; None outside v2 runs
system_results: list[dict]         # per-system ledger: attempts, model used,
                                   # probe evidence, final status — the
                                   # system-granular twin of level_results,
                                   # written verbatim to run.json
```

The promoted script on disk plus `system_results` *is* the protected
build: recovery after an interrupted run restores the backup (existing
`recover_interrupted_repair`) and resumes at the first system whose
ledger entry is not `promoted`.

## Graph changes

Minimal reshaping — the level loop's skeleton is reused one level down:

```
Studio Director -> Blueprint intake (validate, build_order)
    -> (Asset Maker, Audio Agent)                      [unchanged]
    -> Coder(system pass) <-> System QA (build gate + probes)
           |  pass: advance_system (next id in build_order)
           |  fail: Studio Director triage (per-system)
    -> all systems promoted -> full-game QA (objective, video, vision)
    -> END
```

- `advance_system` is the sibling of today's `advance_level`: fresh retry
  budget, next system id.
- Full-game QA (video capture, NVIDIA review, balance) runs once after
  the last promotion, not per system.
- Levels and systems compose: for multi-level blueprint games, the system
  loop builds level 1 completely; subsequent levels reuse promoted
  systems and only re-verify + retune (a level is then a content pass,
  not a systems rebuild). Out of scope for the first milestone.

## Model routing

`router.candidates(kind)` picks the builder per system; a pass that fails
its budget with model A may be retried once with the next candidate
before the Director escalates. Route effectiveness feeds back into the
ledger (`model` per attempt), so the benchmark and the router improve
from every run — the production-memory loop from the v2 proposal.

## Migration and compatibility

- The v2 path activates only when a blueprint is supplied
  (`--blueprint path.json`). Template games keep today's per-level path
  untouched — the nine templates are effectively single-system
  blueprints and gain nothing from the loop.
- `blueprint["design_doc"]` (the legacy bridge already in the schema)
  keeps Asset Maker / Audio Agent / background generation working
  without modification.
- Corpus recording gains system-granular pairs (blueprint system entry ->
  script diff) alongside level pairs — strictly more valuable training
  data, same `SAGA_RECORD_CORPUS` switch.

## Milestones (one PR each)

1. **Build gate + probe registry (phase-1 probes)** — generalize the
   repair gate transaction, add movement/pickup/hud probes, unit-tested
   against hand-written good and regressing scripts. No graph changes.
2. **System pass loop** — `--blueprint` flag, blueprint intake node,
   Coder system-pass prompt, `advance_system`, per-system Director
   triage, ledger. End-to-end on a 3-system blueprint (movement, pickup,
   hud) that today's templates already prove models can write.
3. **Phase-2 probes + routing fallback** — combat, enemy_ai, save_load;
   router fallback on exhausted budgets.
4. **Emberfall Warden** — the example blueprint end to end: the first
   genuinely complex benchmark case, run under `saga.benchmark` with a
   `--blueprint` case type.

## Non-goals (this design)

- Reusable Godot module library (v2 proposal item 3): valuable, separate
  track. The system pass loop works with generated code today and with
  configured modules later — the contract does not change.
- Fun QA: needs its own authority design; nothing here blocks it.
- Multi-level blueprint games beyond re-verification (noted above).
