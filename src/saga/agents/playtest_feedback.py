"""Playtest Feedback agents - capture a human's post-play reaction and turn it
into routable revisions.

Two pieces: capture_playtest_feedback() asks the human three questions on
stdin after they play the build, and interpret_feedback() is a cloud-Claude
call (same cloud-for-judgment / local-for-production split as the Game
Designer) that converts the raw answers plus the current design doc and
Main.gd into a structured FeedbackRevision: which route each issue takes
(tune / reasset / redesign / out_of_scope) and the concrete delta. The
routing itself lives in saga.playtest, a thin CLI driver around the agent
functions - a blocking input() inside a LangGraph node would couple graph
execution to a live terminal, so the interactive loop stays outside the
compiled graph.
"""

import json

import anthropic

from saga.state import DesignDoc

MODEL = "claude-sonnet-5"

# Human cycles cost minutes of a real person's attention plus possible GPU
# regeneration. Cycle one catches the show-stopper, two catches the tuning,
# three is polish; a design still wrong after three human passes has a wrong
# design, not wrong numbers.
MAX_PLAYTEST_CYCLES = 3

REVISION_ROUTES = ["tune", "reasset", "redesign", "out_of_scope"]

REASSET_FIELDS = ["art_style", "audio_mood", "key_item.description"]
REDESIGN_FIELDS = ["mechanic_template", "theme_thread", "win_condition", "lose_condition"]

FEEDBACK_REVISION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["ship", "revise"]},
        "revisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "route": {"type": "string", "enum": REVISION_ROUTES},
                    "evidence": {"type": "string"},
                    "diagnosis": {"type": "string"},
                    "delta": {"type": "string"},
                    # reasset: art_style | audio_mood | key_item.description
                    # redesign: mechanic_template | theme_thread | win_condition | lose_condition
                    # tune / out_of_scope: ""
                    "target_field": {"type": "string"},
                },
                "required": ["route", "evidence", "diagnosis", "delta", "target_field"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["verdict", "revisions"],
    "additionalProperties": False,
}

INTERPRETER_SYSTEM_PROMPT = (
    "You are the Playtest Feedback Interpreter in an automated game studio. A "
    "human just played the current build and answered three questions. Your "
    "job is to convert their words into the cheapest set of revisions that "
    "plausibly fixes what they experienced. You are given their answers, the "
    "game's design doc (JSON), and the complete Main.gd source.\n\n"
    "Routes, in strict cost order - always pick the cheapest route that can "
    "plausibly fix the symptom:\n"
    "1. tune - numeric edits to Main.gd: movement speed, lives, timer "
    "durations, hazard/patroller velocity, drain/refill rates, spawn counts "
    "and positions, collision radii. The delta names the exact variable or "
    "literal with before -> after values read from the provided source.\n"
    "2. reasset - re-describe one generated asset and regenerate it: "
    "art_style, audio_mood, or key_item.description. Costs real GPU time. "
    "Use only when the complaint is about how something looks or sounds, "
    "never how it behaves. The delta is the complete new value for "
    "target_field.\n"
    "3. redesign - change mechanic_template, theme_thread, win_condition, or "
    "lose_condition and rebuild from the Game Designer down. The most "
    "expensive route. Use only when the mechanic itself contradicts the "
    "premise or the human rejected the core loop - not merely its numbers. "
    "The delta is the complete new value for target_field.\n\n"
    "Humans often prescribe solutions ('make me faster') when they mean "
    "symptoms ('I couldn't reach the pool in time'). Diagnose the symptom "
    "from their words and the source before choosing a delta - the right fix "
    "may be a different variable than the one they named.\n\n"
    "If a request requires anything outside this pipeline - new input "
    "actions or buttons, jumping or physics bodies, multiple scenes or "
    "levels with distinct mechanics, multiplayer, saving, or UI beyond the "
    "status label - route it to out_of_scope with a delta following exactly "
    "this template: 'Not possible in this pipeline: <the request, in the "
    "human's words>. This engine layer supports a single-scene game with "
    "held arrow-key movement, touch-based (Area2D) interactions, one hero "
    "sprite, one key-item icon, and one background per level. Closest "
    "achievable alternative: <alternative, or none>.' Never invent a "
    "revision that pretends to satisfy an impossible request.\n\n"
    "Rules: if any revision routes to redesign, drop all tune and reasset "
    "revisions - the rebuild replaces them anyway. If the human typed "
    "'ship', the verdict is 'ship' with an empty revisions list regardless "
    "of minor gripes. Output only JSON matching the FeedbackRevision schema."
)


def capture_playtest_feedback() -> dict[str, str]:
    """Ask the three post-playtest questions on stdin.

    Q1 is the loop's termination oracle - the human answers 'ship or revise'
    directly, so no model has to guess whether the build is good enough. Q2
    targets QA's known blind spot (headless QA has no eyes). Q3 fuses feel
    with forced prioritization - everyone can name their top irritation.
    """
    print("\n--- Playtest feedback ---")
    ship_or_fix = input(
        '[1/3] Ship it or fix it? (type "ship" to accept this build; anything else means we revise)\n> '
    ).strip()
    looks_wrong = input(
        "[2/3] Did anything LOOK or SOUND wrong - sizes, positions, art covering the screen,\n"
        "      missing images, silence where there should be music? (Enter to skip)\n> "
    ).strip()
    feel = input(
        "[3/3] How did it FEEL to play - and what's the ONE thing you'd fix first?\n> "
    ).strip()
    return {
        "ship_or_fix": ship_or_fix,
        "looks_or_sounds_wrong": looks_wrong,
        "feel_and_one_fix": feel,
    }


def interpret_feedback(answers: dict[str, str], design_doc: DesignDoc, main_gd: str) -> dict:
    """Cloud-Claude call turning raw playtest answers into a FeedbackRevision."""
    client = anthropic.Anthropic()

    user_content = (
        f"Playtest answers:\n{json.dumps(answers, indent=2)}\n\n"
        f"Design doc:\n{json.dumps(design_doc, indent=2)}\n\n"
        f"Main.gd:\n```gdscript\n{main_gd}\n```\n"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=INTERPRETER_SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": FEEDBACK_REVISION_SCHEMA},
        },
        messages=[{"role": "user", "content": user_content}],
    )

    text = next(block.text for block in response.content if block.type == "text")
    revision_doc = json.loads(text)

    routes = [r["route"] for r in revision_doc["revisions"]]
    print(f"[Feedback Interpreter] verdict={revision_doc['verdict']!r}, routes={routes}")
    return revision_doc
