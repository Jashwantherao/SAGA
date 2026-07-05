from typing import Optional, TypedDict


class DesignDoc(TypedDict):
    title: str
    genre: str
    core_mechanics: list[str]
    story_premise: str
    levels: list[dict[str, str]]  # each: {"name": ..., "description": ...}
    art_style: str
    audio_mood: str
    collectible: str


class GraphState(TypedDict):
    user_prompt: str
    design_doc: Optional[DesignDoc]
    sprite_paths: Optional[list[str]]
    bgm_path: Optional[str]
    godot_project_path: Optional[str]
    qa_passed: Optional[bool]
    qa_errors: Optional[list[str]]
    retry_count: int
