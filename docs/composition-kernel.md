# Composition Kernel v1

SAGA previously mapped one prompt to one gameplay template. That made a game
reliable enough to launch, but it also made complex games fixed reskins: adding
features meant growing a monolithic script and hoping one model preserved every
old behavior.

Composition Kernel v1 changes the unit of production from “a large generated
script” to “a locked assembly of proven capabilities.” It is intentionally
model-free and runs before asset or audio generation.

## Contract flow

```text
DesignDoc
   -> GameSpec v2 (identity, modes, state, content, world, safe rules)
   -> capability registry resolution
   -> assembly.lock.json
   -> build
   -> runtime evidence
   -> per-capability coverage gate
```

`game_spec.json` is data only. Conditions are restricted to `always`, `never`,
`all`, `any`, `not`, `flag`, `counter_gte`, `owns_item`, and `party_has_tag`.
Effects are restricted to `set_flag`, `add_counter`, `grant_item`, and
`unlock_edge`. References, types, AST size, content IDs, and world reachability
are checked before resolution. Arbitrary code and expressions are not valid
GameSpec content.

Each manifest-v2 component declares:

- an exact ID and version;
- implementation owner (`stable_pack` or `legacy_generated`);
- dependencies and conflicts;
- provided and required ports;
- emitted and consumed events;
- the state namespaces it alone owns;
- input actions and their meanings;
- runtime files; and
- mandatory QA probe IDs.

The deterministic resolver expands dependencies and rejects version mismatch,
cycles, missing or ambiguous ports, missing event producers, conflicting input
meanings, component conflicts, and duplicate state ownership. Canonical JSON is
hashed, so request order cannot change assembly identity. Stable runtime files
are SHA-256 locked as well, and the Coder rechecks them immediately before a
pack is scaffolded; a source mutation after composition stops the build.

## Truthful release evidence

QA flattens its trusted objective, normal-input, playability, vision, and video
results into probe observations. Every locked component receives a coverage
row. A false observation is a product failure. A missing observation is an
infrastructure block. The final ship gate independently requires passing
coverage for every generated level, even if a ledger is later edited to say
that QA passed.

Stable pack failures are terminal after their first authoritative result. They
do not loop through a Coder that does not own the failing implementation.

## Compatibility and Encounter Compiler

All eleven existing mechanic templates compile through the kernel today. The
nine classic templates are represented by compatibility components; Action-RPG
and Run-and-Gun resolve into independently declared stable capabilities. This
keeps existing games reproducible while allowing the architecture to migrate
incrementally.

In v1, a supplied `--game-spec` must be paired with the reviewed
`--design-doc` from which it was translated. Compatibility packs still require
an exact translation because their builders consume DesignDoc. Action-RPG is
the first native consumer: its Composition Director compiles the supplied
GameSpec identity, actors, items, world, presentation, and rules back into the
reviewed build contract so downstream content cannot silently ignore it.

Encounter and Progression Compiler v1 is now delivered for Action-RPG and
experience-scored stage search is delivered for Run-and-Gun. A seed-stable
Candidate Studio varies topology, roles, beats, rewards and pacing, evaluates
four player personas, selects the strongest candidate, and permits only bounded
ContentIR edits such as moving recovery, separating a reward, or clearing a
speed lane. The stable Godot packs consume that selected plan unchanged. The
run manifest retains every score, signature, repair and telemetry value so QA
and benchmarks judge the exact game that was built.

Narrative ContentIR v1 extends that same rule to player-facing identity. Room,
quest, currency, NPC, enemy, relic, ability, dialogue, boss and ending strings are now
part of the selected plan rather than constants in the Action-RPG runtime. The
runtime must prove those compiled values reached its HUD and dialogue before the
quest capability receives complete evidence.
