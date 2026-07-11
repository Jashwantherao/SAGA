# SAGA — Studio of Autonomous Game Agents

Multi-agent LangGraph pipeline that turns a one-line prompt into a playable 2D Godot game. A hybrid of cloud Claude (reasoning/design) and local GPU inference (assets, audio, code) so the loop stays free to run repeatedly.

```
Studio Director -> Game Designer -> Asset Maker  \
                                  -> Audio Agent   -> Coder <-> QA Agent -> [--playtest] -> done
```

| Agent | Runs on | Does |
|---|---|---|
| Studio Director | in-process | Thin pass-through entry point |
| Game Designer | Claude API (`claude-sonnet-5`) | One-line idea -> structured design doc: picks one of 7 mechanic templates, a hero description, key item (with a gameplay role), story, levels, art style, audio mood, win/lose conditions |
| Asset Maker | local GPU, ComfyUI + Flux.1 schnell + rembg | Hero sprite + key-item icon (128x128, background-removed via rembg since Flux can't emit alpha) + one background per level (1024x576) |
| Audio Agent | local GPU, MusicGen (`transformers`) | Background music from the design doc's audio mood |
| Coder | local GPU, Ollama (`qwen2.5-coder:14b`) | Writes `Main.gd` from a template-matched few-shot; harness writes the deterministic `project.godot`/`Main.tscn`/`screenshot.gd` boilerplate |
| QA Agent | Godot 4.7, headless | Imports assets, syntax-checks, runs the scene for a bounded number of frames, then a non-blocking windowed pass captures a screenshot; routes failures back to the Coder (up to `MAX_RETRIES`) |
| Playtest loop (`--playtest`) | stdin capture + Claude API | After a QA-passed build, asks a human three post-play questions and routes their feedback to the cheapest fix: `tune` (surgical numeric edit), `reasset` (regenerate one asset), or `redesign` (full rebuild) |

Only the Game Designer and the playtest Feedback Interpreter need a paid API key. Everything else - including the entire Coder<->QA retry loop and the `tune`/`reasset` playtest routes - runs locally against your own GPU for free.

### Mechanic templates

The Game Designer picks whichever of these best fits the one-line idea, instead of defaulting to "collect":

`collect` · `survive_hazards` · `ordered_switches` · `depletion` · `herd_to_goal` · `capture_zones` · `survive_and_deplete` (the richest: escalating drain + finite-fuel refill zones + roaming hazards)

Each maps to the structurally nearest of four worked few-shot examples in `coder.py`, since showing a 14B local model a complete example remains its biggest reliability lever.

## Setup

### Cloud (Game Designer)

```sh
uv sync
cp .env.example .env   # then edit .env and add your ANTHROPIC_API_KEY
```

### Local GPU services (Asset Maker, Audio Agent, Coder, QA Agent)

These run as separate local services the graph calls over HTTP/CLI — start them before running the pipeline.

**ComfyUI + Flux.1 schnell** (image generation, port 8188):
```sh
cd D:\ComfyUI\ComfyUI
..\.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188
```

**MusicGen FastAPI server** (BGM generation, port 8189):
```sh
cd D:\AudioCraft
.venv\Scripts\python.exe musicgen_server.py
```

**Ollama** (Coder agent):
```sh
ollama pull qwen2.5-coder:14b
```

**Godot 4.7** (QA Agent) — download the portable build and update `GODOT_EXE` in `src/saga/agents/qa_agent.py` if your install path differs from `D:\Godot\Godot_v4.7-stable_win64_console.exe`.

**rembg** (Asset Maker's background removal) is a `uv sync` dependency, no separate service - but its first call downloads the ~170MB U2-Net model to `~/.u2net/`.

## Run

```sh
uv run python -m saga.main "a puzzle platformer about a shape-shifting golem"

# or, to enter the human playtest loop once QA passes:
uv run python -m saga.main "a puzzle platformer about a shape-shifting golem" --playtest
```

Prints the generated design doc as JSON (also saved to `output/design_doc.json`), then reports sprite/BGM paths, the generated Godot project path, final QA status (pass/fail + retry count), and the screenshot path.

To play the result:
```sh
"D:\Godot\Godot_v4.7-stable_win64_console.exe" --path output\godot_project
```

With `--playtest`, after QA passes you'll be asked three questions (ship or fix / anything look or sound wrong / how did it feel), then a Feedback Interpreter routes your answer to a `tune` (numeric edit), `reasset` (art/audio regeneration), or `redesign` (full rebuild) pass automatically, for up to `MAX_PLAYTEST_CYCLES` rounds.

## Known limitations

- QA's headless run never simulates input, so a bug gated behind a keypress can pass QA undetected - the design brief now requires held-key-only win conditions to route around this rather than catch it.
- The QA screenshot pass is a lens, not a gate - it never blocks a build, so visual bugs (wrong sizing, off-screen placement) still need a human or the playtest loop to catch.
- No Art Director agent yet — Asset Maker and Audio Agent read the design doc directly.
- No SFX generation — no `transformers`-compatible audio effects model was found; deferred.
- The Game Designer and Feedback Interpreter are cloud-only and unexercised while the Anthropic API is unfunded; Claude can stand in for one-off runs (see git history for examples), but there's no automated substitute yet.
