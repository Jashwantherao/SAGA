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

## Compatibility and next milestone

All eleven existing mechanic templates compile through the kernel today. The
nine classic templates are represented by compatibility components; Action-RPG
and Run-and-Gun resolve into independently declared stable capabilities. This
keeps existing games reproducible while allowing the architecture to migrate
incrementally.

In v1, a supplied `--game-spec` must be paired with the reviewed
`--design-doc` from which it was translated and must match that translation.
Current builders still consume DesignDoc content, so accepting edited GameSpec
content would create a false contract. Custom GameSpec-authored content becomes
valid only when the next compiler consumes it directly.

The next milestone is the Encounter and Progression Compiler: a seeded world,
quest, and encounter grammar that varies topology, roles, beats, rewards, and
pacing while reusing these locked mechanics. That is where SAGA moves beyond
fixed three-room or fixed-wave reskins without returning to generated gameplay
monoliths.
