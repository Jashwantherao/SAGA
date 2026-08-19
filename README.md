# SAGA — Studio of Autonomous Game Agents

Multi-agent LangGraph pipeline that turns a one-line prompt into a playable, multi-level 2D Godot game. Runs fully autonomously and entirely for free on local GPU inference; a cloud Claude path exists for every reasoning-heavy agent as a premium upgrade once the API is funded.

```
Studio Director -> Game Designer -> Systems Architect -> (Asset Maker, Audio Agent)
    -> Coder <-> QA Agent -> Quality Director  (repeats per level, advancing through the design
       doc's levels; every failure returns to the Studio Director, which
       triages it: fix / regenerate / new art)
    -> [--gate: human plays this level] -> [--playtest] -> done
```

The Systems Architect writes `blueprint.json` before any asset or code work.
`run.json` records its version, provider status, errors, dependency-ordered
build plan, and recommended specialist/fallback models. Use `--blueprint` to
replay a reviewed contract without another architect call.

Enable `SAGA_INCREMENTAL_BUILD=1` for protected quality mode. After the first
complete level draft establishes a compiling Godot baseline, SAGA gives each
blueprint system a focused builder pass in dependency order. Static contracts
and a transactional Godot startup gate must both pass before a candidate can
replace the active script; failures preserve the last working hash and block
dependent systems. The manifest deliberately distinguishes `integrated`
(compiled and promoted) from `qa_confirmed` (observed later by movement,
objective, or video QA). This costs up to one extra Coder call per system.

## SAGA Studio desktop UI

The `ui/` directory contains a Tauri 2 + React control room backed by a
loopback-only FastAPI service. The desktop UI keeps API keys and privileged
operations in Python while providing:

- live preflight and local-service health, plus a GPU/CPU/RAM monitor
  (VRAM, utilization, and temperature via `nvidia-smi`) in the sidebar;
- a one-sentence game creation form with level count, preflight controls,
  an idea randomizer, and Ctrl+Enter submission;
- generation job state, cancellation, WebSocket log streaming with a
  follow/copy log console, and a session history of past generations;
- a generated-game library with screenshots, search, and status filters;
- a full run detail view: gameplay video player, evidence-based Quality
  Director score, per-level QA ledger with objective metrics and Video-QA evidence, an asset gallery with lightbox,
  background-music playback, the design document, and run deletion;
- allow-listed start/stop/restart controls and a log viewer for Ollama,
  ComfyUI, and MusicGen (Ollama is launched with its D: models root); and
- per-agent model routing for local Ollama, DeepSeek, NVIDIA, Anthropic, and
  OpenAI-compatible APIs without exposing saved keys to the frontend.

For frontend/API development, install dependencies and launch the browser
version from PowerShell:

```powershell
cd D:\SAGA
D:\SAGA\.venv\Scripts\python.exe -m pip install -e .
cd D:\SAGA\ui
npm.cmd install
npm.cmd run dev:stack
```

Open `http://127.0.0.1:5173`. The API listens only on
`http://127.0.0.1:8765`. To run the native desktop shell, install the standard
Tauri Windows prerequisites (Rust, Microsoft C++ Build Tools, and the Windows
SDK), then run `npm.cmd run desktop` from `D:\SAGA\ui`.

This workspace also supports the portable D:-local toolchain used during UI
development. Once `.tooling` has been provisioned, launch it without writing
build caches to C: with:

```powershell
D:\SAGA\scripts\saga_ui.ps1 -Mode desktop
```

Use **Services** in the sidebar to start, stop, or restart one service or the
complete local stack, and to tail each service's log. SAGA verifies the process
owning a service port before terminating it, refuses stops and restarts during
generation, and writes service logs under `D:\SAGA\output\service_logs`. If a service uses a custom location, set the
corresponding `SAGA_OLLAMA_EXE`, `SAGA_COMFYUI_*`, or `SAGA_MUSICGEN_*` value in
`.env`; all documented defaults are on D:.

Use **Models & APIs** to select a backend and model independently for Designer,
Director, Coder, Vision QA, and Feedback. The same screen configures Dot Maze and
gameplay-video QA models. Saved API keys stay backend-only: the UI receives only
whether each key is configured. Configuration changes apply to the next game and
are intentionally locked while a generation is active.

| Agent | Runs on | Does |
|---|---|---|
| Studio Director | local (shares the Coder's model) or cloud | Intake, then supervision: every QA failure comes back to it and it routes the failure to the cheapest plausible fix - hand the errors to the Coder (with a one-line diagnosis when the evidence supports one), discard the script and regenerate fresh (when its own history shows a repair that didn't take), or re-describe one art asset and rebuild on top of it. Any failure of the triage call falls back to the deterministic fix-then-regenerate policy it replaced; the graph still owns the retry budget |
| Game Designer | local (`qwen3-coder:30b-a3b`) or cloud (`claude-sonnet-5`) | One-line idea -> structured design doc: picks one of 10 mechanic templates/archetypes, a hero description, key item (with a gameplay role), story, 3-5 levels each with its own background, an authored non-decreasing difficulty curve (`intensity` 1-10), which of the mechanic's tuning levers rise per level, and a narrative beat shown between levels |
| Systems Architect | NVIDIA Nemotron 3 Super by default; deterministic fallback | Converts the creative design into a versioned `blueprint.json`: dependency-ordered gameplay systems, observable acceptance criteria, and benchmark-informed model recommendations for each future specialist build step. Canonical premise and win/loss rules cannot drift. The current Coder consumes the complete contract; protected one-system-at-a-time builders are the next migration step. Provider failure is recorded and falls back without blocking production |
| Asset Maker | local GPU, ComfyUI + Flux.1 schnell + rembg | The hero in a resting **and** a walking pose (sharing one seed, so they render the same character), the key-item icon, up to four `extra_sprites` the design doc asked for by name, and one background per level. Icons generate at 512x512 for reliable full-body framing, are background-removed via rembg since Flux can't emit alpha, then cropped to the alpha bounding box and downscaled to 128x128. Without `extra_sprites`, anything that isn't a hero, icon or background - platforms, enemies, walls - had no image and the Coder drew it as an untextured rectangle |
| Audio Agent | local GPU, MusicGen (`transformers`) | Background music from the design doc's audio mood; loops continuously across level changes via a harness-owned autoload |
| Coder | local GPU, hosted API, or deterministic archetype pack | Classic templates write one `Level_N.gd` from a template-matched few-shot. `run_and_gun` instead scaffolds a versioned multi-file Godot capability pack and writes only a compact level definition: the model cannot silently reimplement movement, projectiles, enemy AI, checkpoints or boss state. The harness also writes `project.godot`, scenes, procedural SFX, ambience, narrative interludes and Victory flow |
| QA Agent | Godot 4.7, headless + optional NVIDIA video QA | Imports assets and runs each level, then **plays it**. Autoplay proves input-driven movement; ten deterministic mechanic probes cover the nine classic templates plus run-and-gun structure, weapons, waves, progression/save integrity, combat transitions and victory. Structured results and every artifact remain in the truthful per-level ledger |
| Quality Director | deterministic evidence review | Reviews every technically passing level across playability, objective completion, visual and motion presentation, balance, and reliability. It assigns findings to the responsible agent, permits one bounded polish pass, and closes the ship gate when a release misses the measured quality floor |

Coder repairs are transactional. SAGA preserves the previous gameplay script,
rechecks corrected output for contracts, asset references, and unsafe APIs, then
runs a bounded Godot scene smoke test against the candidate. Only a clean
candidate is promoted. A compiler error, timeout, or interrupted validation
restores the checkpoint and records a `repair_gate` failure in the level ledger
without spending time on screenshot, objective, or video QA.
| Playtest loop (`--playtest`) | stdin capture + local, OpenAI-compatible, or Claude Feedback Interpreter | After a QA-passed build, asks a human three post-play questions and routes their feedback to the cheapest fix: `tune` (a targeted `Level_N.gd` numeric edit), `reasset` (regenerate assets and rebuild affected references), or `redesign` (full rebuild) |

Two kinds of decisions run this studio, and the split is deliberate. Models make the judgment calls: what game to design, what code to write, and - since the Studio Director became a real supervisor - where every failure should be routed, a decision that used to be a hardcoded `if`. The harness owns everything that must not be creative: retry budgets, template contracts, the QA gates, and all the deterministic Godot boilerplate. When no model is reachable for a judgment call, each agent degrades to a deterministic fallback rather than blocking the run. The opt-in agentic Coder (`SAGA_CODER_AGENTIC=1`) extends the same principle to the code itself: a tool-using loop that runs, looks at, and revises its own level, with a measured score ratchet so it can never ship worse than its draft.

Nothing requires a paid API key — the whole pipeline runs on local inference. But the local models are also what shaped the architecture, and it is worth being explicit about that: the mechanic templates, the long few-shots and the single-file-per-level constraint all exist because a 14-30B model on one consumer GPU could not be trusted with more. Pointing the Coder at a frontier model removes that ceiling entirely — it will write a side-scrolling platformer with gravity, coyote time and a scrolling camera from a description alone, with no template and no worked example. `SAGA_CODER_BACKEND=deepseek` (or any OpenAI-compatible endpoint, see Model overrides) switches it; roughly a cent per game.

### Animation

Generated sprites are single still images — there is no sprite sheet anywhere in the pipeline — so a hero used to be a static PNG sliding across a background. Three harness-owned mechanisms close most of that gap without frame-based art:

- **Pose swapping.** The hero is drawn twice at a shared seed with an explicit screen-left native facing, and `Anim.set_poses` swaps texture by movement state. `Anim.walk` mirrors that native pose only for rightward travel, so the character visibly stands up to move, settles when it stops, and faces its actual movement direction.
- **Procedural motion.** `Anim.walk` bobs, leans and flips to face travel, falling back to a slow idle breath so nothing is ever completely frozen; `Anim.hover` drifts anything that floats.
- **Leg deformation.** A canvas shader shears the lower part of the sprite on a sine wave, near and far halves in opposite phase, so the legs scissor. This exists because image generation cannot draw a gait: seed-locking holds a character consistent across poses but gives no control over limb position, and a request for two consecutive walk frames returns two standing poses.

### Mechanic templates

The Game Designer picks whichever of these best fits the one-line idea, instead of defaulting to "collect":

`collect` · `survive_hazards` · `ordered_switches` · `depletion` · `herd_to_goal` · `capture_zones` · `survive_and_deplete` (escalating drain + finite-fuel refill zones + roaming hazards) · `maze_chase` (walled corridors via axis-separated collision, pickups, a patrolling hazard) · `dot_maze` (a dense corridor maze, dots, patrollers, a hunter and power reversal) · `run_and_gun` (side-view running/jumping, projectiles, patrol/chase enemies, checkpoint respawn and a multi-phase boss)

The nine classic templates each have a worked few-shot example in `coder.py`, since showing a local model a complete example of the structure it's asked to produce remains its biggest reliability lever. The dedicated examples expose the stable mechanic state required by autonomous QA, including switch sequence, territory ownership, and permanent creature settlement. `dot_maze`'s few-shot is the largest (244 lines) and routes to a bigger model via `TEMPLATE_MODEL_OVERRIDES` - the 14B reliably dropped variable declarations at that length. `run_and_gun` deliberately bypasses that monolithic path and scaffolds the pack below.

### Archetype packs

`run_and_gun` is SAGA's first OpenGame-style capability family. Its versioned
manifest and ten reusable Godot modules live under
`src/saga/archetype_packs/run_and_gun/`. The level script is a small adapter;
stable engine code owns player physics, firing, projectile collision, enemy
patrol/chase, health and loss, checkpoint respawn, camera/HUD, boss phases and
level completion. Pack v4 compiles each brief into a reproducible encounter
plan: one of three stage topologies, traversal platforms, five paced encounter
beats, differentiated enemy roles, hazards, recovery pickups, checkpoint
placement and a separate boss arena. The plan is validated before Godot runs.
Its Combat Director adds pulse, spread and explosive weapon patterns, collectible
loadouts with switching, five behaviorally distinct enemy roles, arena locks,
two threat-budgeted waves and boss phases with 1/3/5-projectile attacks. Loss
restores the default loadout and restarts an active wave from its authored plan.
Its Campaign Progression layer awards currency and XP exactly once per boss,
offers firepower/mobility/vitality choices between levels, carries upgrades and
unlocked weapons forward, and stores a schema-versioned profile through an
atomic temporary/backup save path. Malformed or incompatible saves recover to
a valid default profile rather than breaking startup.
The deterministic blueprint exposes the runtime capabilities as separate,
dependency-ordered systems. QA calls a stable pack interface and refuses to
ship unless all seven core transitions, the encounter-structure contract, ten
combat-depth assertions and seven progression/persistence assertions pass.
This is the pattern future action RPG and creature-collection packs
should extend instead of adding larger monolithic few-shots.

### Retrieval strategy

SAGA's opt-in experience memory is already a conservative form of RAG: it can
retrieve only complete, first-pass, QA-proven scripts from the same mechanic
template. It intentionally uses a local lexical ranker and a hard prompt budget
because an unrelated or partly repaired script can reduce generation quality.
The next retrieval layer should remain typed and evidence-gated: Godot API notes
for implementation, verified encounter plans for design, and diagnosed
failure/fix pairs for repair. Hosted embeddings (including an OpenAI-compatible
NVIDIA embedding NIM) are useful as an optional reranker once the corpus is
large enough to benchmark; they must not replace template/version filters,
provenance, deterministic pack code, or executable QA.

### Model overrides

Every model is swappable via environment variable without touching code:

| Variable | Default | Controls |
|---|---|---|
| `SAGA_DESIGNER_BACKEND` | `local` | `local` or `claude` |
| `SAGA_DIRECTOR_BACKEND` | `local` | Studio Director triage: `local`, `claude`, `deepseek`/`openai`/`remote`, or `deterministic` for bounded no-model repair routing |
| `SAGA_DIRECTOR_MODEL` | the Coder's model | Director's local triage model. Defaults to whatever the Coder is using so a triage between attempts costs no VRAM swap |
| `SAGA_DIRECTOR_REMOTE_MODEL` | `deepseek-v4-pro` | Director's model when hosted |
| `SAGA_ARCHITECT_BACKEND` | `nvidia` | Systems Architect transport: hosted, `local`, or `deterministic`/`off` for the no-call fallback |
| `SAGA_ARCHITECT_MODEL` | `nvidia/nemotron-3-super-120b-a12b` | Model that expands the design doc into the Game Blueprint |
| `SAGA_ARCHITECT_BASE_URL` | `https://integrate.api.nvidia.com/v1` | OpenAI-compatible architect endpoint |
| `SAGA_ARCHITECT_KEY_ENV` | `NVIDIA_API_KEY` | Environment variable holding the architect provider key |
| `SAGA_ARCHITECT_TIMEOUT` | `180` | Architect timeout in seconds before deterministic fallback |
| `SAGA_INCREMENTAL_BUILD` | unset | Set to `1` for protected dependency-ordered specialist refinement after the initial draft |
| `SAGA_INCREMENTAL_MAX_SYSTEMS` | `6` | Maximum focused system-builder calls per level in quality mode |
| `SAGA_EXPERIENCE_MEMORY` | unset | Set to `1` to give fresh Coder generations a compact, similar, first-pass script from the QA-verified same-mechanic corpus; remains opt-in pending broader A/B evidence |
| `SAGA_EXPERIENCE_MEMORY_LIMIT` | `1` | Maximum verified prior scripts injected into one fresh-generation prompt |
| `SAGA_EXPERIENCE_MEMORY_MAX_CHARS` | `12000` | Hard prompt budget for complete memory examples; partial scripts are never included |
| `SAGA_DESIGNER_MODEL` | `hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_S` | Game Designer's local model |
| `SAGA_DESIGNER_TIMEOUT` | `180` | Maximum seconds for one hosted Designer attempt; SDK auto-retries are disabled so a stalled design call fails visibly |
| `SAGA_CODER_MODEL` | `qwen2.5-coder:14b` | Coder's model |
| `SAGA_DOTMAZE_MODEL` | `batiai/qwen3.6-35b:q3` | Coder's model specifically for `dot_maze` (its few-shot exceeds the 14B's reliable imitation length) |
| `SAGA_VISION_MODEL` | `gemma4:12b` | QA's screenshot reviewer (local backend) |
| `SAGA_CODER_BACKEND` | `ollama` | `ollama`, or `deepseek`/`openai`/`remote` for any OpenAI-compatible API |
| `SAGA_CODER_REMOTE_MODEL` | `deepseek-v4-pro` | Coder's model when hosted |
| `SAGA_CODER_TIMEOUT` | `300` | Maximum seconds for one hosted Coder or specialist attempt before it fails visibly; SDK auto-retries are disabled so the ceiling is real |
| `SAGA_OPENAI_BASE_URL` | `https://api.deepseek.com` | Any OpenAI-compatible endpoint |
| `SAGA_OPENAI_KEY_ENV` | `DEEPSEEK_API_KEY` | Which env var holds the key |
| `SAGA_VISION_BACKEND` | `local` | `nvidia` routes screenshot review to a hosted VLM |
| `SAGA_VISION_REMOTE_MODEL` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | Hosted vision model |
| `SAGA_VIDEO_QA` | unset | Set to `1` to require gameplay MP4 capture and NVIDIA video QA for every level |
| `SAGA_VIDEO_MODEL` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | NVIDIA model used for gameplay video understanding |
| `SAGA_VIDEO_TIMEOUT` | `120` | Hosted video-review timeout in seconds |
| `SAGA_FFMPEG_EXE` | `ffmpeg` | FFmpeg executable used to convert Godot's AVI capture to MP4 |
| `SAGA_FEEDBACK_BACKEND` | `local` | Playtest interpreter: `local`, `claude`, or `deepseek`/`openai`/`remote` |
| `SAGA_FEEDBACK_MODEL` | the matching local/remote default | Playtest interpreter model |
| `SAGA_STOP_GPU_SERVICES` | unset | Set to `1` to stop ComfyUI/MusicGen once assets and BGM are done, freeing VRAM for a large coder model (see Known limitations) |

These defaults are the result of head-to-head benchmarking, not guesses - see Known limitations for what lost and why.

## Setup

### Cloud (optional - Game Designer premium path)

```sh
uv sync
cp .env.example .env   # add ANTHROPIC_API_KEY only when selecting a Claude backend
```

### Local GPU services (everything else)

These run as separate local services the graph calls over HTTP/CLI. Start all three in their own terminal windows *before* running the pipeline - the graph will fail or hang waiting on whichever one isn't up.

**1. Ollama** (Game Designer, Coder, QA's vision review):
```sh
ollama pull hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_S   # Game Designer
ollama pull qwen2.5-coder:14b                                        # Coder
ollama pull gemma4:12b                                               # vision QA
```
If Ollama has a non-default models directory configured (check with `[Environment]::GetEnvironmentVariable('OLLAMA_MODELS','User')` in PowerShell), a plain `ollama serve` from a fresh shell can silently see zero models - check first with `ollama list`. If it's already running (a `bind: Only one usage of each socket address...` error on `ollama serve` means it is) but `ollama list` comes back empty, stop it and restart with the models directory set explicitly - substitute your own path from the check above, this is only an example:
```powershell
Get-Process ollama* | Stop-Process -Force
$env:OLLAMA_MODELS = "D:\ollama\models"; ollama serve   # replace with your actual OLLAMA_MODELS path
```

**2. ComfyUI + Flux.1 schnell** (image generation, port 8188).

First-time install — ComfyUI lives outside this repo, in its own venv, because
its CUDA torch build is pinned separately from SAGA's:
```powershell
git clone https://github.com/comfyanonymous/ComfyUI D:\ComfyUI\ComfyUI
uv venv --python 3.11 D:\ComfyUI\.venv
# CUDA build first - the plain `pip install torch` from requirements.txt is CPU-only
D:\ComfyUI\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130
D:\ComfyUI\.venv\Scripts\python.exe -m pip install -r D:\ComfyUI\ComfyUI\requirements.txt
```

Then the Flux.1 schnell weights, into ComfyUI's model folders. These are four
separate files, not one checkpoint — the workflow in `asset_maker.py` loads the
diffusion model, both text encoders and the VAE independently, so a missing one
fails at generation time rather than at startup:

| File | Goes in | From |
|---|---|---|
| `flux1-schnell-fp8.safetensors` | `models\diffusion_models\` | [Comfy-Org/flux1-schnell](https://huggingface.co/Comfy-Org/flux1-schnell) |
| `clip_l.safetensors` | `models\text_encoders\` | [comfyanonymous/flux_text_encoders](https://huggingface.co/comfyanonymous/flux_text_encoders) |
| `t5xxl_fp8_e4m3fn.safetensors` | `models\text_encoders\` | same repo (the fp8 build — fp16 is ~9GB and needlessly tight on 16GB) |
| `ae.safetensors` | `models\vae\` | [black-forest-labs/FLUX.1-schnell](https://huggingface.co/black-forest-labs/FLUX.1-schnell) (gated: accept the licence on the model page first) |

Start it:
```sh
cd D:\ComfyUI\ComfyUI
..\.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188
```

**3. MusicGen FastAPI server** (BGM generation, port 8189).

First-time install. MusicGen is loaded through `transformers` rather than the
`audiocraft` package — the standalone library pins old torch versions that
conflict with a current CUDA build, and `transformers` ships the same model:
```powershell
uv venv --python 3.11 D:\AudioCraft\.venv
D:\AudioCraft\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu130
D:\AudioCraft\.venv\Scripts\python.exe -m pip install transformers fastapi uvicorn scipy
```
Copy `musicgen_server.py` from this repo's `services/` into `D:\AudioCraft\`.
It downloads `facebook/musicgen-small` on first start (~2GB, cached in
`~\.cache\huggingface`), so the first launch takes a minute before `/health`
reports `model_loaded: true` — starting the pipeline before then fails the
health check rather than waiting.

Start it:
```sh
cd D:\AudioCraft
.venv\Scripts\python.exe musicgen_server.py
```

Both paths are only defaults. Nothing reads `D:\ComfyUI` or `D:\AudioCraft`
directly — the graph talks to `127.0.0.1:8188` and `127.0.0.1:8189` over HTTP,
so install them wherever you like as long as those ports match.

Verify all three are actually listening before running the pipeline:
```powershell
Invoke-WebRequest http://127.0.0.1:11434/api/tags -UseBasicParsing | Select StatusCode   # Ollama
Invoke-WebRequest http://127.0.0.1:8188/system_stats -UseBasicParsing | Select StatusCode # ComfyUI
Invoke-WebRequest http://127.0.0.1:8189/health -UseBasicParsing | Select StatusCode       # MusicGen
```
All three should return `200`. If any hangs or refuses the connection, that service isn't actually up yet - check its terminal window for errors before moving on.

**Godot 4.7** (QA Agent) — download the portable build and set `SAGA_GODOT_EXE` in `.env` if your install path differs from `D:\Godot\Godot_v4.7-stable_win64_console.exe`.

**FFmpeg** (required only with `SAGA_VIDEO_QA=1`) — install it so `ffmpeg -version` works, or point `SAGA_FFMPEG_EXE` at the executable. Godot records a deterministic 1024×576 AVI; SAGA converts it to a 640×360, 10 FPS H.264 MP4 before sending it to NVIDIA, typically reducing an eight-second clip from tens of megabytes to a few hundred kilobytes.

**rembg** (Asset Maker's background removal) is a `uv sync` dependency, no separate service - but its first call downloads the ~170MB U2-Net model to `~/.u2net/`.

#### Fixing a broken `uv`-managed venv launcher on Windows

If `..\.venv\Scripts\python.exe` fails with `No Python at '"...\uv\python\cpython-...\python.exe'`, that venv's `uv`-generated launcher binary is corrupted - it's not a PATH, quoting, or activation issue, and it will not fix itself by retrying or opening a new terminal. Run this yourself in a PowerShell window, once per broken venv (this only replaces the tiny launcher stub - it never touches the venv's installed packages):

```powershell
# 1. Build a scratch venv just to get a known-good launcher (same Python version)
uv venv --python 3.11.15 $env:TEMP\repair

# 2. Confirm the scratch launcher actually works
& "$env:TEMP\repair\Scripts\python.exe" --version

# 3. Back up the broken launcher, then replace it - point $venv at the broken one
$venv = "D:\ComfyUI\.venv"   # or D:\AudioCraft\.venv
Copy-Item "$venv\Scripts\python.exe" "$venv\Scripts\python.exe.broken_backup" -Force
Copy-Item "$env:TEMP\repair\Scripts\python.exe" "$venv\Scripts\python.exe" -Force

# 4. Verify the fix actually preserved the installed packages, not just that it runs
& "$venv\Scripts\python.exe" -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # ComfyUI
# or: & "$venv\Scripts\python.exe" -c "import transformers; print(transformers.__version__)"           # AudioCraft
```

If step 4 prints a version and (for ComfyUI) `True`, the fix worked - retry the service's start command in that **same** terminal window. If the exact same error comes back after this, something is actively reverting the file (a mismatched OneDrive sync on that folder, or antivirus real-time protection quarantining a freshly-copied unsigned `.exe` - check `Get-MpThreatDetection` for a recent detection on `python.exe`) - add an exclusion for the `.venv\Scripts` folder and repeat steps 3-4.

## Run

Once all three local services are confirmed up (see above):

```sh
uv sync
uv run saga --doctor
uv run python -m saga.main "a mouse thief robbing a museum patrolled by a clockwork cat"

# quick one-level end-to-end prototype
uv run python -m saga.main --levels 1 "a mouse thief robbing a one-room vault"

# require gameplay-video evidence and NVIDIA temporal review
$env:SAGA_VIDEO_QA = "1"
uv run saga --levels 1 "a maintenance robot surviving a failing sea station"

# or, to enter the human playtest loop once QA passes:
uv run python -m saga.main "a mouse thief robbing a museum patrolled by a clockwork cat" --playtest

# or, to review each level before the rest of the game is built on it:
uv run python -m saga.main "a mouse thief robbing a museum patrolled by a clockwork cat" --gate
```

`--gate` is the one that catches expensive mistakes. `--playtest` runs after
the whole pipeline finishes, which is too late to stop a mechanic that is wrong
in level 1 from being faithfully reproduced in every level after it - observed
directly, when a herding game whose creatures could never be caught was built
three times before anyone played it. `--gate` stops the moment a level passes
QA and nothing has been built on top of it yet, launches it, and takes one line
of plain feedback ("the creatures run away too fast, I can't push them
anywhere") which it turns into concrete edits naming that script's own
variables. A blank line moves on. It needs a real terminal; EOF on stdin is
treated as approval so batch runs cannot hang.

This is a real example, not a placeholder - it's what produced "The Clockwork Heist," a 4-level maze-chase game, fully autonomously, zero hand-authoring anywhere in the loop.

What happens, in order: Studio Director allocates an isolated `output/runs/<run-id>/` workspace and passes your prompt to the Game Designer, which returns a full design doc (title, mechanic, 3-5 levels with an authored difficulty curve and narrative beats) printed to the console and saved in that workspace; Asset Maker and Audio Agent then generate the hero/key-item/background art and the BGM in parallel; the Coder writes each level's GDScript and QA Agent builds and verifies it in Godot, with every failure triaged by the Studio Director - repair the script, regenerate it fresh, or regenerate a wrong asset - within `MAX_RETRIES` per level before moving to the next level. Total time for a 3-4 level game is typically several minutes, dominated by image generation and Coder retries.

Final output reports sprite/BGM paths, the generated Godot project path, aggregate QA status, the latest screenshot, the latest mechanic-specific gameplay completion score, and—when enabled—the gameplay MP4. The isolated run directory also contains `design_doc.json`, `quality_report.json`, and a machine-readable versioned `run.json` manifest. Its `level_results` ledger retains every QA attempt, error, retry, advisory, objective metric, screenshot, video path and structured NVIDIA verdict per level; `quality_results` preserves each pre/post-polish review, while `quality_report` exposes the current 0–100 score, evidence confidence, findings, ownership, repair plan, and gate decision. `ship_ready` is true only when every designed level has a recorded clean pass and the Quality Director gate is open. When the Studio Director identifies an art-side defect, Asset Maker now regenerates only the named hero pose set, key item, extra sprite, or current-level background. The replaced file is backed up under `assets/revisions/`, and the old/new paths plus the Director's evidence are retained in both the affected level ledger and manifest. Advisory-only builds are labelled `passed_with_warnings`, and a required QA probe that cannot produce a verdict is labelled `blocked` rather than silently passing.

To play the result:
```sh
"D:\Godot\Godot_v4.7-stable_win64_console.exe" --path output\runs\<run-id>\godot_project
```

With `--playtest`, after QA passes you'll be asked three questions (ship or fix / anything look or sound wrong / how did it feel), then a Feedback Interpreter routes your answer to a `tune` (numeric edit), `reasset` (art/audio regeneration), or `redesign` (full rebuild) pass automatically, for up to `MAX_PLAYTEST_CYCLES` rounds.

## Validation snapshot (2026-08-01)

The current deterministic QA stack was measured with DeepSeek V4 Pro on nine
fresh one-level generations—one for every mechanic template. All **9/9 passed
on their first generated script** through Godot import, scene execution,
movement responsiveness, the template-specific objective solver, and the
balance gate. Every objective completion score was 100; the full matrix took
624 seconds. This test reused one known-good art set so it measured Coder and
gameplay-QA reliability without image-generation variance.

A separate full-pipeline run generated **Clockwork Vespers**, a one-level
`herd_to_goal` game, from a one-line prompt. ComfyUI produced six fresh images,
MusicGen produced a 14.9-second soundtrack, and DeepSeek produced the level.
Godot completed all 5/5 herding milestones with all five creatures permanently
settled, a completion score of 100, and zero QA retries. Screenshot review found
no gating defect; NVIDIA Nemotron video QA verified visible animated movement,
correct facing, a readable HUD, and a stable scene. The v11 run manifest ended
with `status=passed` and `ship_ready=true`. The repository suite currently has
**85 passing tests** plus a clean `compileall` run.

## Known limitations

- Generic autoplay still finds only the movement floor, but every one of SAGA's nine mechanic templates now also has a deterministic objective solver. Resource, territory, sequence, survival, maze, collection, and herding QA measure live behavior rather than trusting advertised rates or labels. The original motivating failure—a herding game whose creatures could never actually be pushed into the goal—is now explicitly gated through real flee displacement, goal progress, permanent settlement, and win verification.
- Gameplay video QA observes the full deterministic right/down/left/up autoplay sequence, not an expert playthrough. It can catch temporal presentation defects such as reversed facing, rigid sliding, jitter and disappearing objects, but it cannot prove a template-specific objective is winnable; that remains the mechanic solver's job. The gate is opt-in because it uploads the generated MP4 to the configured NVIDIA endpoint.
- The generic autoplay probe's label-change signal remains advisory because random directional input cannot solve a puzzle. Ordered-switch progress is now gated separately by its deterministic two-pass sequence solver.
- Vision QA gates only on defects the Coder can fix - a hero that never made it on screen, a background not filling, clipped text. Placeholder art is reported as advisory instead, because no rewrite can conjure a sprite the Asset Maker never generated. Precision is good (no false positives across the builds measured) but recall is limited: both candidate models missed a label sitting behind a message box. A code-fixable visual defect remains a failed QA attempt until it is repaired or the retry budget is exhausted; it can no longer be converted into a clean pass after one correction.
- Nothing reconciles art against code. Backgrounds routinely contain painted objects that look interactive but aren't - a pool the player aims for that is part of the image, jellyfish that are scenery. Art and code are generated independently and no check compares them.
- The Game Designer defaults to a local 30B model rather than the larger Gemma 4 26B: in a head-to-head on the same schema, Gemma failed 2 of 3 test prompts with truncated JSON output (even after raising the request's context/output token budget, which fixed a real under-provisioning bug and was kept regardless). The Coder likewise stays on the 14B by default rather than a 35B alternative (Qwen 3.6) after benchmarking showed the bigger model ~2x slower with a real reliability regression on one run - the few-shot anchoring, not model size, is what makes Coder generation reliable for most templates, so bigger doesn't automatically mean better. The one exception is `dot_maze`, whose 244-line few-shot is long enough that the 14B drops variable declarations and a first attempt on the 30B silently deleted an entire system rather than just failing to compile - that template routes to the 35B specifically, per-template, not as a global default change.
- Large coder models are tight on a 16GB card, and the failure mode is ugly. `dot_maze`'s 35B model needs ~14.1GB; ComfyUI and MusicGen each keep holding VRAM for the entire run despite finishing their work up front, and that residency (measured: 1817 MiB with both alive vs 961 MiB without) leaves only ~354 MiB of headroom - the model dies mid-load with a Windows CUDA-init failure (`0xc0000409`) rather than reporting a clean out-of-memory. Set `SAGA_STOP_GPU_SERVICES=1` to have the Coder stop those services at the start of the code phase (assets and BGM are already generated by then), which raises headroom to ~1210 MiB and lets the model load reliably. Note this stops servers you started - restart them before the next run, or before a `--playtest` `reasset` cycle that needs ComfyUI again. The retry-with-backoff in `coder.py` remains as a safety net but is not the fix: no amount of retrying helps when the model cannot fit.
- The cloud (`claude`) backends of the Game Designer, Studio Director, and Feedback Interpreter remain less exercised than the local paths while the Anthropic API is unfunded. Every role has a local or OpenAI-compatible path, so this no longer blocks autonomous or human-playtest runs.
- The Studio Director's triage has been validated on synthetic failure evidence — fix on a first-time compile error, regenerate on an error that survived two repairs, reasset on an art-side defect: all three routed correctly on the local 14B — but not yet against a full autonomous run's real failure distribution. Targeted `reasset` repairs preserve approved art, but still need validation against naturally occurring art failures in full autonomous runs.
- No Art Director agent yet — Asset Maker and Audio Agent read the design doc directly.
- Background art tends toward perspective rendering while gameplay is flat top-down, causing objects to visually "float" against the scene. Asset Maker's background prompt now explicitly requests a strict top-down orthographic view, which measurably helps (walls read as blocks with visible tops instead of a receding vanishing-point corridor) but doesn't fully eliminate it - Flux follows perspective instructions unreliably, a known limitation of diffusion image models generally, not something prompt wording alone can fully close.
