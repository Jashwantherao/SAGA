"""Studio Director - the supervisor that routes the pipeline's failures.

Intake is unchanged: receive the one-line idea, initialize state, hand off to
the Game Designer. The real work is triage mode, entered whenever QA fails a
level with retry budget remaining. What used to happen there was hardcoded -
graph.py sent every failure straight back to the Coder, and coder.py cleared
the errors after three attempts to force a fresh generation. Those were
routing decisions made by Python that a model is better placed to make: the
Director reads the actual evidence (the errors, the advisory findings, what
was already tried for this level) and picks the cheapest route that can
plausibly work.

Routes, in cost order:
- fix: hand the errors to the Coder's fix path, optionally with a
  one-sentence diagnosis attached. The default for a first-time error.
- regenerate: discard the script and generate fresh. For when the history
  shows a repair that did not take - repeating a failed fix spends a retry
  and changes nothing (observed: a .bind()/handler-arity mismatch the fix
  path missed three times in a row), while fresh sampling luck is free.
- reasset: re-describe one art asset, regenerate it, and rebuild the level's
  code on top. The expensive route, and the rare one: QA's gating findings
  are code-fixable by design, so this fires only when the evidence says the
  picture itself is wrong.

The decision is one bounded structured-output call, local by default and
swappable like every other agent (SAGA_DIRECTOR_BACKEND). Any failure of the
call - service down, bad JSON, an invented route - falls back to exactly the
deterministic policy this node replaced, so the pipeline never blocks on its
own supervisor. The retry budget stays in graph.py: the model decides
direction, the harness enforces limits.
"""

import copy
import json

from saga.config import settings
from saga.state import GraphState
from saga.workspace import create_run_dir

REMOTE_MODEL = settings.director_remote_model
CLAUDE_MODEL = "claude-sonnet-5"

ROUTES = ["fix", "regenerate", "reasset"]
REASSET_FIELDS = ["hero_description", "key_item.description", "level_background"]

DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ROUTES},
        "reasoning": {"type": "string"},
        # fix only: a one-sentence diagnosis appended to the Coder's error
        # list, or "" - a wrong guess is worse than none.
        "note_to_coder": {"type": "string"},
        # reasset only: hero_description | key_item.description |
        # level_background | extra:<name>; "" otherwise.
        "reasset_field": {"type": "string"},
        "reasset_value": {"type": "string"},
    },
    "required": ["action", "reasoning", "note_to_coder", "reasset_field", "reasset_value"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are the Studio Director in an automated game studio. A level of a "
    "2D Godot game just failed QA, and your job is to route the failure to "
    "the cheapest fix that can plausibly work. You are given the failure "
    "evidence, the retry budget, and what was already tried for this level.\n\n"
    "Routes, in strict cost order:\n"
    "1. fix - hand the errors back to the Coder to repair the existing "
    "script. The default for any error seen for the FIRST time. If the "
    "evidence makes the cause obvious, put a one-sentence diagnosis in "
    "note_to_coder; otherwise leave it empty - a wrong guess sends the "
    "Coder chasing the wrong thing, which is worse than no note.\n"
    "2. regenerate - discard the script and write the level fresh. Choose "
    "this when the history shows the same error already survived a fix "
    "attempt (repeating a failed repair spends a retry and changes "
    "nothing), or when the errors are so many and unrelated that the "
    "script is structurally confused.\n"
    "3. reasset - re-describe one art asset and regenerate it, then "
    "rebuild the level's code on top. The most expensive route: image "
    "generation plus a fresh code pass. Choose it ONLY when the evidence "
    "says the picture itself is wrong - a sprite that is not what it "
    "should be, art invisible against its background - never for compile "
    "errors, runtime errors, or anything a code change could plausibly "
    "cure. Set reasset_field to one of hero_description, "
    "key_item.description, level_background for the current level's "
    "background, or extra:<name> for an extra sprite, and "
    "reasset_value to the complete new visual description.\n\n"
    "For fix and regenerate, leave reasset_field and reasset_value empty. "
    "Keep reasoning to one or two sentences. Output only JSON matching "
    "the schema."
)


def studio_director(state: GraphState) -> GraphState:
    # Triage mode is unambiguous: a design doc exists and QA just reported
    # errors. Anything else is intake.
    if state.get("design_doc") and state.get("qa_errors"):
        return _triage(state)
    print(f"[Studio Director] Received prompt: {state['user_prompt']!r}")
    run_dir = state.get("run_dir") or str(create_run_dir())
    print(f"[Studio Director] Run workspace: {run_dir}")
    return {
        "user_prompt": state["user_prompt"],
        "run_dir": run_dir,
        # Benchmark and replay runs may provide an already-authored design.
        # Preserve it so Game Designer can validate and pass it through.
        "design_doc": state.get("design_doc"),
        # A replay may also supply a reviewed systems contract.
        "blueprint": state.get("blueprint"),
        "director_action": None,
    }


def _triage(state: GraphState) -> GraphState:
    from saga.graph import MAX_RETRIES  # lazy: graph.py imports this module

    backend = settings.director_backend
    retry_count = state.get("retry_count") or 0
    print(
        f"[Studio Director] Level {(state.get('current_level') or 0) + 1} failed QA "
        f"(retry {retry_count}/{MAX_RETRIES}) - triaging"
    )
    evidence = _evidence_text(state, MAX_RETRIES)
    if backend in {"deterministic", "off"}:
        decision = _deterministic_decision(retry_count)
    else:
        try:
            if backend == "claude":
                decision = _decide_claude(evidence)
            elif backend in ("deepseek", "openai", "remote"):
                decision = _decide_remote(evidence)
            else:
                decision = _decide_local(evidence, _director_model(state))
        except Exception as e:
            decision = _fallback(retry_count, f"{type(e).__name__}: {e}")
    decision = _sanitize(decision, state, retry_count)
    print(f"[Studio Director/{backend}] {decision['action']}: {decision['reasoning']}")
    return _apply(state, decision)


def _director_model(state: GraphState) -> str:
    override = settings.director_model
    if override:
        return override
    # Default to whatever model the Coder just used: triage runs between
    # Coder attempts, so sharing its model means the decision costs no VRAM
    # swap - on a 16GB card a model swap each retry would dominate the loop.
    from saga.agents.coder_backend import MODEL, TEMPLATE_MODEL_OVERRIDES

    template = (state.get("design_doc") or {}).get("mechanic_template", "")
    return TEMPLATE_MODEL_OVERRIDES.get(template, MODEL)


def _evidence_text(state: GraphState, max_retries: int) -> str:
    design_doc = state.get("design_doc") or {}
    idx = state.get("current_level") or 0
    levels = design_doc.get("levels") or []
    level = levels[idx] if idx < len(levels) else {}

    lines = [
        f"Game: {design_doc.get('title')!r}, mechanic template: {design_doc.get('mechanic_template')}.",
        f"Level {idx + 1} of {len(levels)}: {level.get('name', '')} - {level.get('description', '')}",
        f"Retry {state.get('retry_count') or 0} of {max_retries} for this level.",
        "",
        "QA errors this attempt:",
    ]
    lines += [f"- {e}" for e in (state.get("qa_errors") or [])]

    notes = (state.get("vision_notes") or []) + (state.get("balance_notes") or [])
    if notes:
        lines += ["", "Advisory findings (non-gating):"] + [f"- {n}" for n in notes]

    history = [h for h in (state.get("director_history") or []) if h.get("level") == idx]
    if history:
        lines += ["", "Already tried for this level:"]
        for h in history[-4:]:
            errors = "; ".join(h.get("errors") or [])[:400]
            lines.append(f"- retry {h['retry']}: chose {h['action']}; the errors were: {errors}")

    art = [
        f"hero_description: {design_doc.get('hero_description', '')!r}",
        f"key_item.description: {(design_doc.get('key_item') or {}).get('description', '')!r}",
        f"level_background: {level.get('description', '')!r}",
    ]
    art += [f"extra:{s['name']}: {s['description']!r}" for s in design_doc.get("extra_sprites") or []]
    lines += ["", "Generated art (the reasset candidates):"] + [f"- {a}" for a in art]
    return "\n".join(lines)


def _decide_local(evidence: str, model: str) -> dict:
    import ollama

    resp = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": evidence},
        ],
        format=DECISION_SCHEMA,
        options={"num_ctx": 8192, "num_predict": 1024},
    )
    return json.loads(resp["message"]["content"])


def _decide_remote(evidence: str) -> dict:
    from saga.llm import chat

    schema_note = (
        "Respond with a single JSON object matching this schema exactly - no "
        "prose, no markdown fence:\n" + json.dumps(DECISION_SCHEMA, indent=2)
    )
    return json.loads(
        chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + schema_note},
                {"role": "user", "content": evidence},
            ],
            model=REMOTE_MODEL,
            json_mode=True,
            max_tokens=2000,
            timeout=120,
        )
    )


def _decide_claude(evidence: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": DECISION_SCHEMA},
        },
        messages=[{"role": "user", "content": evidence}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def _fallback(retry_count: int, why: str) -> dict:
    """The deterministic policy this agent replaced, kept as its safety net:
    fix for the first three attempts, then regenerate - the exact escalation
    coder.py used to hardcode. The pipeline must never block on its own
    supervisor."""
    print(f"[Studio Director] LLM triage unavailable ({why}) - deterministic fallback")
    return _deterministic_decision(retry_count)


def _deterministic_decision(retry_count: int) -> dict:
    """Stable no-model triage for benchmarks and offline productions."""
    if retry_count >= 3:
        action = "regenerate"
        reasoning = "three fix attempts have not converged; fresh sampling beats repeating a failed repair"
    else:
        action = "fix"
        reasoning = "hand the errors to the Coder's fix path"
    return {"action": action, "reasoning": reasoning, "note_to_coder": "", "reasset_field": "", "reasset_value": ""}


def _sanitize(decision: dict, state: GraphState, retry_count: int) -> dict:
    """Harness-side guard on a model-made decision: an invented route falls
    back to the deterministic policy, and a reasset the pipeline cannot
    actually perform is downgraded rather than obeyed."""
    if decision.get("action") not in ROUTES:
        return _fallback(retry_count, f"model chose unknown route {decision.get('action')!r}")
    if decision["action"] != "reasset":
        return decision

    field = (decision.get("reasset_field") or "").strip()
    value = (decision.get("reasset_value") or "").strip()
    extra_names = {s["name"] for s in (state.get("design_doc") or {}).get("extra_sprites") or []}
    known_field = field in REASSET_FIELDS or (field.startswith("extra:") and field[6:] in extra_names)
    if not known_field or not value:
        print(f"[Studio Director] reasset target {field!r} unusable - downgrading to fix")
        return {**decision, "action": "fix", "note_to_coder": ""}

    # Reasset needs ComfyUI, which SAGA_STOP_GPU_SERVICES may have stopped to
    # make VRAM room for the coder model. Art cannot change then, so spend the
    # retry on fresh code instead of crashing the Asset Maker.
    try:
        from saga.agents.asset_maker import _check_comfyui_reachable

        _check_comfyui_reachable()
    except RuntimeError:
        print("[Studio Director] reasset needs ComfyUI, which is not up - downgrading to regenerate")
        return {**decision, "action": "regenerate", "reasset_field": "", "reasset_value": ""}
    return decision


def _apply(state: GraphState, decision: dict) -> GraphState:
    """Turn a sanitized decision into a state update the graph can route on."""
    action = decision["action"]
    history = list(state.get("director_history") or [])
    history.append(
        {
            "level": state.get("current_level") or 0,
            "retry": state.get("retry_count") or 0,
            "action": action,
            # Raw errors, pre-diagnosis, so a repeat is recognizable next time.
            "errors": [e[:200] for e in (state.get("qa_errors") or [])][:6],
        }
    )
    update: GraphState = {"director_action": action, "director_history": history}

    if action == "fix":
        note = (decision.get("note_to_coder") or "").strip()
        if note:
            update["qa_errors"] = list(state.get("qa_errors") or []) + [
                f"Studio Director's diagnosis: {note}"
            ]
    elif action == "regenerate":
        # No qa_errors is what sends the Coder down its fresh-generation path.
        update["qa_errors"] = None
    elif action == "reasset":
        design_doc = copy.deepcopy(state["design_doc"])
        field = decision["reasset_field"].strip()
        value = decision["reasset_value"].strip()
        if field == "key_item.description":
            design_doc["key_item"]["description"] = value
        elif field == "level_background":
            level_index = state.get("current_level") or 0
            design_doc["levels"][level_index]["description"] = value
        elif field.startswith("extra:"):
            name = field[6:]
            for sprite in design_doc.get("extra_sprites") or []:
                if sprite["name"] == name:
                    sprite["description"] = value
        else:
            design_doc[field] = value
        print(f"[Studio Director] Re-describing {field}: {value!r}")
        update["design_doc"] = design_doc
        update["qa_errors"] = None
        update["reasset_request"] = {
            "field": field,
            "value": value,
            "reasoning": decision.get("reasoning") or "",
            "level_index": state.get("current_level") or 0,
            "retry": state.get("retry_count") or 0,
            "qa_errors": list(state.get("qa_errors") or []),
        }
    return update
