"""Game Designer agent — turns a one-line prompt into a structured game design doc."""

import json

import anthropic

from saga.state import GraphState

MODEL = "claude-sonnet-5"

DESIGN_DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "genre": {"type": "string"},
        "core_mechanics": {"type": "array", "items": {"type": "string"}},
        "story_premise": {"type": "string"},
        "levels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
                "additionalProperties": False,
            },
        },
        "art_style": {"type": "string"},
        "audio_mood": {"type": "string"},
    },
    "required": [
        "title",
        "genre",
        "core_mechanics",
        "story_premise",
        "levels",
        "art_style",
        "audio_mood",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are the Game Designer agent in an automated indie-game studio pipeline. "
    "Given a one-line game idea, produce a complete, playable game design: core "
    "mechanics, a short story premise, 3-5 levels with a name and one-sentence "
    "description each, an art style, and an audio mood. Keep scope achievable for "
    "a small 2D Godot game."
)


def game_designer(state: GraphState) -> GraphState:
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": DESIGN_DOC_SCHEMA},
        },
        messages=[{"role": "user", "content": state["user_prompt"]}],
    )

    text = next(block.text for block in response.content if block.type == "text")
    design_doc = json.loads(text)

    print(f"[Game Designer] Produced design doc: {design_doc['title']!r}")
    return {"user_prompt": state["user_prompt"], "design_doc": design_doc}
