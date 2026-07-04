# SAGA — Studio of Autonomous Game Agents

Multi-agent pipeline that turns a one-line prompt into a playable game. See `SAGA_Project_Proposal.docx` for the full architecture.

**Week 1 status:** Studio Director → Game Designer skeleton only. Takes a one-line idea and produces a structured JSON game design doc (mechanics, story, levels, art style, audio mood). Asset generation, the Coder↔QA loop, and the Streamlit UI are not built yet — see the proposal's roadmap.

## Setup

```sh
uv sync
cp .env.example .env   # then edit .env and add your ANTHROPIC_API_KEY
```

## Run

```sh
uv run python -m saga.main "a puzzle platformer about a shape-shifting golem"
```

Prints the generated design doc as JSON and saves a copy to `output/design_doc.json`.
