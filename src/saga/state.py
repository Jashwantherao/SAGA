from typing import Optional, TypedDict


class DesignDoc(TypedDict):
    title: str
    genre: str
    core_mechanics: list[str]
    story_premise: str
    levels: list[dict[str, str]]  # each: {"name": ..., "description": ...}
    art_style: str
    audio_mood: str


class GraphState(TypedDict):
    user_prompt: str
    design_doc: Optional[DesignDoc]
