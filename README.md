# SAGA — Studio of Autonomous Game Agents

Multi-agent LangGraph pipeline that turns a one-line prompt into a playable 2D Godot game. A hybrid of cloud Claude (reasoning/design) and local GPU inference (assets, audio, code) so the loop stays free to run repeatedly.

```
Studio Director -> Game Designer -> Asset Maker  \
                                  -> Audio Agent   -> Coder <-> QA Agent -> done
```

| Agent | Runs on | Does |
|---|---|---|
| Studio Director | in-process | Thin pass-through entry point |
| Game Designer | Claude API (`claude-sonnet-5`) | One-line idea -> structured design doc (mechanics, story, levels, art style, audio mood, collectible) |
| Asset Maker | local GPU, ComfyUI + Flux.1 schnell | Hero sprite + collectible icon (128x128) + one background per level (1024x576) |
| Audio Agent | local GPU, MusicGen (`transformers`) | Background music from the design doc's audio mood |
| Coder | local GPU, Ollama (`qwen2.5-coder:14b`) | Writes `Main.gd` gameplay logic; harness writes the deterministic `project.godot`/`Main.tscn` boilerplate |
| QA Agent | Godot 4.7, headless | Imports assets, syntax-checks, then runs the scene for a bounded number of frames; routes failures back to the Coder (up to `MAX_RETRIES`) |

Only the Game Designer needs a paid API key. Everything else runs locally against your own GPU, so the Coder<->QA retry loop is free to iterate.

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

## Run

```sh
uv run python -m saga.main "a puzzle platformer about a shape-shifting golem"
```

Prints the generated design doc as JSON (also saved to `output/design_doc.json`), then reports sprite/BGM paths, the generated Godot project path, and final QA status (pass/fail + retry count).

To play the result:
```sh
"D:\Godot\Godot_v4.7-stable_win64_console.exe" --path output\godot_project
```

## Known limitations

- QA's headless run never simulates input, so a bug gated behind a keypress can pass QA undetected.
- No Art Director agent yet — Asset Maker and Audio Agent read the design doc directly.
- No SFX generation — no `transformers`-compatible audio effects model was found; deferred.
