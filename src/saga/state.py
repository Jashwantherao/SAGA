from typing import Optional, TypedDict


class KeyItem(TypedDict):
    description: str  # concrete visual description - drives the 128x128 icon generation
    role: str  # pickup | hazard | switch | creature | zone_marker


class DesignDoc(TypedDict):
    title: str
    genre: str
    # collect | survive_hazards | ordered_switches | depletion | herd_to_goal
    # | capture_zones | survive_and_deplete | maze_chase
    mechanic_template: str
    hero_description: str  # concrete, high-contrast visual description of the hero sprite
    core_mechanics: list[str]
    story_premise: str
    theme_thread: str  # one sentence: how the mechanic embodies the premise
    win_condition: str
    lose_condition: str  # or "none"
    levels: list[dict[str, str]]  # each: {"name": ..., "description": ...}
    art_style: str
    audio_mood: str
    key_item: KeyItem


class GraphState(TypedDict):
    user_prompt: str
    design_doc: Optional[DesignDoc]
    sprite_paths: Optional[list[str]]
    bgm_path: Optional[str]
    godot_project_path: Optional[str]
    qa_passed: Optional[bool]
    qa_errors: Optional[list[str]]
    retry_count: int
    # Numeric tuning instructions from the playtest feedback loop; consumed
    # (and cleared) by the Coder's tune path.
    tune_notes: Optional[list[str]]
    screenshot_path: Optional[str]
    # Non-gating findings from the local vision model's screenshot review.
    vision_notes: Optional[list[str]]
