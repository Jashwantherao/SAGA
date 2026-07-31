from typing import Optional, TypedDict


class KeyItem(TypedDict):
    description: str  # concrete visual description - drives the 128x128 icon generation
    role: str  # pickup | hazard | switch | creature | zone_marker


class ExtraSprite(TypedDict):
    # Lowercase slug; becomes the stable filename (extra_<name>.png) and
    # is how the Coder refers to the sprite, so it should say what the thing is.
    name: str
    description: str  # concrete visual description - drives the 128x128 generation


class Level(TypedDict):
    name: str
    description: str  # drives this level's background generation
    outro_beat: str  # 1-2 sentences shown on the interlude screen after winning this level
    # 1-10 authored pressure; non-decreasing across the sequence. The harness
    # anchors the matched few-shot's numbers at intensity 4 and scales ~15%
    # pressure per point, so this is literal arithmetic for the Coder.
    intensity: int
    pressure_notes: str  # which of the template's levers rise this level; final level names the climax


class DesignDoc(TypedDict):
    title: str
    genre: str
    # collect | survive_hazards | ordered_switches | depletion | herd_to_goal
    # | capture_zones | survive_and_deplete | maze_chase | dot_maze
    mechanic_template: str
    hero_description: str  # concrete, high-contrast visual description of the hero sprite
    core_mechanics: list[str]
    story_premise: str
    theme_thread: str  # one sentence: how the mechanic embodies the premise
    win_condition: str
    lose_condition: str  # or "none"
    levels: list[Level]
    art_style: str
    audio_mood: str
    key_item: KeyItem
    # Everything else this particular game needs drawn - platforms, enemies,
    # walls, doors. Without these the Coder has only a hero, one icon and a
    # background, so it falls back to untextured ColorRects for anything else.
    extra_sprites: list[ExtraSprite]


class GraphState(TypedDict, total=False):
    user_prompt: str
    # Optional CLI override for quick prototypes; normal authored runs remain
    # 3-5 levels when this is absent.
    requested_levels: int
    # Unique output/runs/<id> workspace allocated during Studio Director intake.
    run_dir: str
    design_doc: Optional[DesignDoc]
    sprite_paths: Optional[list[str]]
    bgm_path: Optional[str]
    godot_project_path: Optional[str]
    qa_passed: Optional[bool]
    qa_errors: Optional[list[str]]
    retry_count: int
    # Which of the design doc's levels the Coder<->QA loop is currently
    # building; advanced by the graph's advance_level node after each level
    # passes QA.
    current_level: int
    # Numeric tuning instructions from the playtest feedback loop; consumed
    # (and cleared) by the Coder's tune path.
    tune_notes: Optional[list[str]]
    screenshot_path: Optional[str]
    # Non-gating findings from the local vision model's screenshot review.
    vision_notes: Optional[list[str]]
    # Non-gating findings from the balance check - a level that is winnable but
    # toothless, or a fight that drags. These are tuning notes, not defects, so
    # they feed the playtest loop rather than failing a build; see saga.balance.
    balance_notes: Optional[list[str]]
    # Structured evidence from a mechanic-specific objective solver. For
    # dot_maze this includes collected/total/remaining counts and frame cost.
    objective_result: Optional[dict]
    # Set by the Coder so QA can record a verified (brief -> script) training
    # pair once the level passes; see saga.corpus.
    coder_prompt: Optional[str]
    coder_model: Optional[str]
    # Studio Director triage: the supervisor's routing decision for the
    # current QA failure (fix | regenerate | reasset; None outside triage),
    # and a per-run history of what was already tried so the Director can
    # recognize a repair that did not take instead of repeating it.
    director_action: Optional[str]
    director_history: Optional[list[dict]]
    # Durable, per-level QA history. Unlike qa_errors/vision_notes above,
    # which describe only the current graph step, this ledger is never reset
    # when the graph advances. Each entry contains every attempt plus the
    # level's final status and artifacts, and is written verbatim to run.json.
    level_results: list[dict]
    # A broken QA harness is different from generated code that needs repair.
    # When a required probe cannot produce a verdict, stop the graph and
    # report "blocked" instead of spending Coder retries or claiming a pass.
    ship_blocked: bool
