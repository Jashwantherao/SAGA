# SAGA Agentic Studio Revamp

## Why the current games feel bad

SAGA's verification layer became stronger than its creation layer. It can prove
that controls, quests, checkpoints, bosses and win states work while the game is
still repetitive, visually incoherent, badly paced, or simply dull. The old
Action-RPG compiler demonstrated the problem: every brief produced the same
three room IDs, two gray rectangular obstacles, three identical stalkers, ten
sparks and one fixed boss loop. A truthful QA result for that shell was still a
truthful result for a weak game.

The revamp therefore separates three questions that were previously blurred:

1. **Does it run?** Runtime and deterministic system probes answer this.
2. **Can different players complete it?** Persona playtests and telemetry answer this.
3. **Is it worth playing?** Experience, pacing, novelty and presentation gates answer this.

Passing the first question can never substitute for the other two.

## What current research says

- [OpenGame](https://arxiv.org/abs/2604.18394) combines a stable template skill,
  an execution-grounded debug skill and dynamic game evaluation. Its
  [reference implementation](https://github.com/leigest519/OpenGame) evaluates
  build health, visual usability and intent alignment instead of treating code
  generation as the finish line.
- [AgenticPCG](https://github.com/JiangZehua/AgenticPCG) exposes structured level
  edits to an agent so content is evaluated and revised iteratively.
- [PCGRL](https://arxiv.org/abs/2001.09212) formulates level generation as
  sequential optimization against measurable content-quality objectives. SAGA
  can adopt this search/evaluate/edit loop without first training an RL model.
- Experience-driven PCG connects generated content to desired player experience.
  The [ExpREx validation study](https://ojs.aaai.org/index.php/AIIDE/article/download/31878/34045/35947)
  uses experience trajectories, persona agents and predictive evaluation rather
  than only structural validity.
- [Procedural personas](https://arxiv.org/abs/1802.06881) show why one scripted
  solution is insufficient: synthetic players with different utilities expose
  different content failures.
- [Godot RL Agents](https://github.com/edbeeching/godot_rl_agents) and
  [GamingAgent](https://github.com/lmgame-org/GamingAgent) provide useful models
  for reproducible observation/action interfaces, replay logs and video evidence.
- [VideoGameQA-Bench](https://arxiv.org/abs/2505.15952) separates visual unit,
  regression, UI, glitch and temporal video tasks; a single VLM verdict is not a
  complete visual QA strategy.
- [JAMER/JamBench](https://arxiv.org/abs/2606.19830) finds that runtime success
  collapses as Godot projects grow and that fixing compilation does not guarantee
  behavioral quality. This supports a modular content IR and stable runtime over
  monolithic generated scripts.

## Target studio architecture

```text
brief
  -> Experience Director (testable fantasy, beats, personas, novelty floor)
  -> Composition Director (compatible, versioned mechanic capabilities)
  -> Candidate Studio (generate N bounded ContentIR candidates)
  -> Critics (solvability, pacing, fairness, exploration, presentation)
  -> select / edit / rescore
  -> stable Godot runtime consumes selected ContentIR
  -> persona playtests + telemetry + visual regression + video QA
  -> ship, repair the owning layer, or reject
```

Models propose intent and edits. They do not get to declare their own work good.
Every critic produces evidence, every repair has an owner, and only a verified
repair can enter SAGA's experience memory.

## Delivered first vertical slice

Action-RPG pack v5 now compiles each brief into an `experience_contract`,
generates 24 deterministic candidates, scores them, and ships only the selected
candidate. The score covers enemy-role diversity, spatial variety, escalating
pressure, safe placements, quest reachability, optional exploration reward,
pre-boss recovery and a readable speedrun lane.

The selected ContentIR now controls room themes, layouts, obstacles, actor
positions and encounter roles. Stalker, skirmisher, sentinel and bruiser roles
have distinct motion and attack behavior. Obstacles are beveled themed structures
with outlines and sigils rather than unstyled gray rectangles; melee and pickup
events have impact bursts; a healing resource creates the planned recovery beat.

Pack v3 also consumes the generated idle/walk pose pair at runtime, removes
fallback geometry whenever authored sprites exist, and supplies attack/hurt/dash
motion, enemy and boss wind-ups, health response, particles, room transitions,
and deterministic gameplay SFX. Quality Report v3 separately requires visible
evidence for animation, combat feedback, encounter readability, and presentation
tier, preventing a clean-but-static prototype from scoring 100/100.

## Delivered third vertical slice: Encounter and Progression Compiler

Action-RPG now searches 24 seeded 4–6-room worlds instead of reskinning one
three-room shell. Topology, room theme and layout, encounter roles, pressure,
recovery, optional discovery, quest funding and the speed lane all vary while
stable mechanics remain locked. Run-and-Gun searches 16 scored stage plans.

Achiever, explorer, survivor and speedrunner critics must all pass. Runtime QA
then records actual traversal and completion telemetry, so a promising static
plan cannot hide a broken game. Failed Action-RPG metrics invoke a small,
allow-listed ContentIR repair—move recovery, separate the optional reward, or
clear the speed lane—followed by a complete rescore. No critic may rewrite
runtime code or declare its own repair successful.

The benchmark now ranks models using the truthful ship score, Quality Director
score, content score, persona pass rate, repair count, latency and an optional
model-blind human score. The rater scores playability, fun, visual coherence and
originality before the private identity key is opened.

The remaining generalization work is to give creature collection, capture zones
and survival their own editable ContentIR grammars. Their objective evidence is
already normalized into the same four-persona schema, but their layouts are not
yet candidate-searched.

## Delivered second vertical slice: Art Director v1

Art Director now runs after gameplay composition and before Asset Maker. It
locks one versioned `art_direction.json` containing the production camera,
projection, palette roles, value hierarchy, scale hierarchy, coherence rules,
and a silhouette/layer-separation contract for every generated asset.

Asset Maker quotes those exact constraints in each image prompt. This also
fixes a concrete old contradiction: Action-RPG actors are now requested as
top-down orthographic sprites instead of inheriting the run-and-gun hero's
side-view/facing language. Generated and frozen images receive local structural
inspection for dimensions, alpha separation, subject occupancy and edge
cropping before Godot imports them.

The composed gameplay screenshot is evaluated against the same locked bible.
A complete verdict must report camera compliance, actor-role readability and
style coherence. Any failure is durable quality-gate evidence owned by Asset
Maker; role failures target a role sprite while camera/style failures target
the current background. The art-direction hash is retained in each QA attempt,
so visual evidence can be traced to the exact contract it judged.

## Delivered fourth vertical slice: Narrative Content Compiler

The Tideglass Oath live test exposed a truthful but unacceptable gap: fresh art
and a fresh design still rendered “Ember Hermit” and “Hermit's Court.” Those
strings lived in the stable pack rather than the selected game's ContentIR.

Action-RPG pack v5 removes that shell. The Designer can now author a bounded
narrative contract containing quest title, collectible currency, quest giver,
enemy faction, boss, relic, unlocked ability, six room names, three dialogue lines, stage
objectives and victory text. The deterministic compiler sanitizes it, fills any
missing legacy fields from the reviewed design, fingerprints its source and
binds it to rooms, pickups, NPC dialogue, inventory, HUD and boss presentation.

Godot now performs a fourteenth objective check that compares rendered runtime
identity with the exact compiled contract. Quality Director exposes a separate
narrative-fidelity dimension and closes the ship gate if that evidence is absent
or false. Candidate Studio shows the identity and provenance in the desktop UI.
