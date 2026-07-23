# SAGA — Studio of Autonomous Game Agents

Multi-agent LangGraph pipeline that turns a one-line prompt into a playable, multi-level 2D Godot game. Runs fully autonomously and entirely for free on local GPU inference; a cloud Claude path exists for every reasoning-heavy agent as a premium upgrade once the API is funded.

```
Studio Director -> Game Designer -> (Asset Maker, Audio Agent)
    -> Coder <-> QA Agent  (repeats per level, advancing through the design
       doc's levels)  -> [--playtest] -> done
```

| Agent | Runs on | Does |
|---|---|---|
| Studio Director | in-process | Thin pass-through entry point |
| Game Designer | local (`qwen3-coder:30b-a3b`) or cloud (`claude-sonnet-5`) | One-line idea -> structured design doc: picks one of 8 mechanic templates, a hero description, key item (with a gameplay role), story, 3-5 levels each with its own background, an authored non-decreasing difficulty curve (`intensity` 1-10), which of the mechanic's tuning levers rise per level, and a narrative beat shown between levels |
| Asset Maker | local GPU, ComfyUI + Flux.1 schnell + rembg | Hero sprite + key-item icon (generated at 512x512 for reliable full-body framing, background-removed via rembg since Flux can't emit alpha, then cropped to the alpha bounding box and downscaled to 128x128) + one background per level (1024x576) |
| Audio Agent | local GPU, MusicGen (`transformers`) | Background music from the design doc's audio mood; loops continuously across level changes via a harness-owned autoload |
| Coder | local GPU, Ollama (`qwen2.5-coder:14b`) | Writes one `Level_N.gd` per level from a template-matched few-shot, rendering that level's authored difficulty via an intensity anchor (the few-shot's own numbers = intensity 4/10, ~15% more pressure per point via that template's specific levers); harness writes all deterministic boilerplate - `project.godot`, `Level_N.tscn`, procedural SFX, ambient particles, the title/win/lose/restart state machine's autoloads, the between-level narrative interlude, and the Victory scene |
| QA Agent | Godot 4.7, headless | Imports assets, runs each level's scene for a bounded number of frames (also catches compile errors), then a non-blocking windowed pass captures a screenshot and a local vision model (`gemma4:12b`) reviews it for visual defects; routes failures back to the Coder per level (up to `MAX_RETRIES`), escalating to a fresh regeneration if 3 fix attempts don't converge |
| Playtest loop (`--playtest`) | stdin capture + local/cloud Feedback Interpreter | After a QA-passed build, asks a human three post-play questions and routes their feedback to the cheapest fix: `tune` (surgical numeric edit), `reasset` (regenerate one asset), or `redesign` (full rebuild) |

Nothing requires a paid API key. `SAGA_DESIGNER_BACKEND=claude` switches the Game Designer to the Anthropic API as a premium option once it's funded; every other agent is local-only.

### Mechanic templates

The Game Designer picks whichever of these best fits the one-line idea, instead of defaulting to "collect":

`collect` · `survive_hazards` · `ordered_switches` · `depletion` · `herd_to_goal` · `capture_zones` · `survive_and_deplete` (escalating drain + finite-fuel refill zones + roaming hazards) · `maze_chase` (walled corridors via axis-separated collision, pickups, a patrolling hazard)

Each maps to the structurally nearest of five worked few-shot examples in `coder.py`, since showing a local model a complete example of the structure it's asked to produce remains its biggest reliability lever.

### Model overrides

Every model is swappable via environment variable without touching code:

| Variable | Default | Controls |
|---|---|---|
| `SAGA_DESIGNER_BACKEND` | `local` | `local` or `claude` |
| `SAGA_DESIGNER_MODEL` | `hf.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q3_K_S` | Game Designer's local model |
| `SAGA_CODER_MODEL` | `qwen2.5-coder:14b` | Coder's model |
| `SAGA_VISION_MODEL` | `gemma4:12b` | QA's screenshot reviewer |

These defaults are the result of head-to-head benchmarking, not guesses - see Known limitations for what lost and why.

## Setup

### Cloud (optional - Game Designer premium path)

```sh
uv sync
cp .env.example .env   # then edit .env and add your ANTHROPIC_API_KEY
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

**2. ComfyUI + Flux.1 schnell** (image generation, port 8188):
```sh
cd D:\ComfyUI\ComfyUI
..\.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188
```

**3. MusicGen FastAPI server** (BGM generation, port 8189):
```sh
cd D:\AudioCraft
.venv\Scripts\python.exe musicgen_server.py
```

Verify all three are actually listening before running the pipeline:
```powershell
Invoke-WebRequest http://127.0.0.1:11434/api/tags -UseBasicParsing | Select StatusCode   # Ollama
Invoke-WebRequest http://127.0.0.1:8188/system_stats -UseBasicParsing | Select StatusCode # ComfyUI
Invoke-WebRequest http://127.0.0.1:8189/health -UseBasicParsing | Select StatusCode       # MusicGen
```
All three should return `200`. If any hangs or refuses the connection, that service isn't actually up yet - check its terminal window for errors before moving on.

**Godot 4.7** (QA Agent) — download the portable build and update `GODOT_EXE` in `src/saga/agents/qa_agent.py` if your install path differs from `D:\Godot\Godot_v4.7-stable_win64_console.exe`.

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
uv run python -m saga.main "a mouse thief robbing a museum patrolled by a clockwork cat"

# or, to enter the human playtest loop once QA passes:
uv run python -m saga.main "a mouse thief robbing a museum patrolled by a clockwork cat" --playtest
```

This is a real example, not a placeholder - it's what produced "The Clockwork Heist," a 4-level maze-chase game, fully autonomously, zero hand-authoring anywhere in the loop.

What happens, in order: Studio Director passes your prompt to the Game Designer, which returns a full design doc (title, mechanic, 3-5 levels with an authored difficulty curve and narrative beats) printed to the console and saved to `output/design_doc.json`; Asset Maker and Audio Agent then generate the hero/key-item/background art and the BGM in parallel; the Coder writes each level's GDScript and QA Agent builds and verifies it in Godot, retrying failures automatically (up to `MAX_RETRIES` per level) before moving to the next level. Total time for a 3-4 level game is typically several minutes, dominated by image generation and Coder retries.

Final output reports sprite/BGM paths, the generated Godot project path, final QA status per level (pass/fail + retry count), and each level's screenshot path.

To play the result:
```sh
"D:\Godot\Godot_v4.7-stable_win64_console.exe" --path output\godot_project
```

With `--playtest`, after QA passes you'll be asked three questions (ship or fix / anything look or sound wrong / how did it feel), then a Feedback Interpreter routes your answer to a `tune` (numeric edit), `reasset` (art/audio regeneration), or `redesign` (full rebuild) pass automatically, for up to `MAX_PLAYTEST_CYCLES` rounds.

## Known limitations

- QA's headless run never simulates input, so a bug gated behind a keypress can pass QA undetected - the design brief requires held-key-only win conditions (plus `ui_accept` for start/restart only) to route around this rather than catch it.
- The QA screenshot and vision review are a lens, not a gate - they never block a build, so visual bugs still need a human or the playtest loop to catch. Vision QA runs on `gemma4:12b` after it beat the original `qwen2.5vl:7b` head-to-head (0 false positives across 5 known-clean screenshots vs. 5 false positives for the old model, same spurious "background does not fill the screen" every time).
- The Game Designer defaults to a local 30B model rather than the larger Gemma 4 26B: in a head-to-head on the same schema, Gemma failed 2 of 3 test prompts with truncated JSON output (even after raising the request's context/output token budget, which fixed a real under-provisioning bug and was kept regardless). The Coder likewise stays on the 14B rather than a 35B alternative (Qwen 3.6) after benchmarking showed the bigger model ~2x slower with a real reliability regression on one run - the few-shot anchoring, not model size, is what makes Coder generation reliable, so bigger doesn't currently mean better here.
- The playtest loop's Feedback Interpreter and the Game Designer's cloud (`claude`) backend are unexercised while the Anthropic API is unfunded; Claude can stand in for one-off runs (see git history for examples), but there's no automated substitute for that specific path yet - the local Game Designer backend covers autonomous end-to-end runs today.
- No Art Director agent yet — Asset Maker and Audio Agent read the design doc directly.
- Background art is rendered in perspective while gameplay is flat top-down, so generated objects can visually "float" against the scene - an art-direction gap, not a functional bug.
