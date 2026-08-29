from typing import Optional, TypedDict


class KeyItem(TypedDict):
    description: str  # concrete visual description - drives the 128x128 icon generation
    role: str  # pickup | hazard | switch | creature | zone_marker


class ExtraSprite(TypedDict):
    # Lowercase slug; becomes the stable filename (extra_<name>.png) and
    # is how the Coder refers to the sprite, so it should say what the thing is.
    name: str
    description: str  # concrete visual description - drives the 128x128 generation


class ActionRpgNarrative(TypedDict):
    """Player-facing identity compiled into the stable Action-RPG runtime."""
    quest_title: str
    currency_name: str
    quest_giver_name: str
    boss_name: str
    enemy_name: str
    relic_name: str
    ability_name: str
    room_names: list[str]
    dialogue_lines: list[str]
    collect_objective: str
    return_objective: str
    boss_objective: str
    victory_text: str


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
    # | run_and_gun | action_rpg
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
    # Required by the prompt for action_rpg. Older/fixed design documents are
    # upgraded deterministically by the Narrative Content Compiler.
    narrative: ActionRpgNarrative


class GraphState(TypedDict, total=False):
    user_prompt: str
    # Optional CLI override for quick prototypes; normal authored runs remain
    # 3-5 levels when this is absent.
    requested_levels: int
    # Unique output/runs/<id> workspace allocated during Studio Director intake.
    run_dir: str
    design_doc: Optional[DesignDoc]
    # Agent Team v2: the Systems Architect turns the creative design into an
    # ordered, machine-verifiable systems contract before assets or code are
    # produced. The plan records benchmark-informed specialist candidates;
    # the current monolithic Coder consumes the acceptance contract while
    # protected per-system builders are introduced incrementally.
    blueprint: Optional[dict]
    blueprint_status: Optional[str]
    blueprint_model: Optional[str]
    blueprint_errors: Optional[list[str]]
    blueprint_build_plan: Optional[list[dict]]
    # Composition Kernel v1: the validated data-only game contract and the
    # deterministic, versioned capability assembly resolved from it. These
    # are fixed before asset/audio work so every downstream agent and QA gate
    # can agree on exactly what the game contains and what must be proven.
    game_spec: Optional[dict]
    game_spec_status: Optional[str]
    game_spec_errors: Optional[list[str]]
    assembly_lock: Optional[dict]
    assembly_hash: Optional[str]
    # Encounter and Progression Compiler: selected, scored ContentIR for the
    # current level, including persona evidence and bounded repair provenance.
    content_plan: Optional[dict]
    # Art Director v1: a deterministic camera, palette, silhouette, scale and
    # layer-separation bible shared by image generation and visual QA.
    art_direction: Optional[dict]
    art_direction_status: Optional[str]
    art_direction_errors: Optional[list[str]]
    # Protected incremental builder ledger. "integrated" means the focused
    # candidate passed static contracts plus a Godot startup gate; behavioral
    # confirmation is attached later by the authoritative QA probes.
    system_build_results: list[dict]
    sprite_paths: Optional[list[str]]
    # Structural image evidence emitted by Asset Maker for dimensions, alpha
    # cutout separation, occupancy and framing before Godot imports the files.
    asset_contract_results: Optional[list[dict]]
    bgm_path: Optional[str]
    godot_project_path: Optional[str]
    qa_passed: Optional[bool]
    qa_errors: Optional[list[str]]
    # A deterministic failure in a locked stable capability is not repairable
    # through the generic Coder retry loop. QA marks it terminal so the run
    # stops truthfully after the first authoritative verdict.
    qa_terminal: bool
    retry_count: int
    # Which of the design doc's levels the Coder<->QA loop is currently
    # building; advanced by the graph's advance_level node after each level
    # passes QA.
    current_level: int
    # Numeric tuning instructions from the playtest feedback loop; consumed
    # (and cleared) by the Coder's tune path.
    tune_notes: Optional[list[str]]
    screenshot_path: Optional[str]
    # Optional deterministic 8-second autoplay clip and the required
    # structured NVIDIA verdict produced when SAGA_VIDEO_QA=1.
    gameplay_video_path: Optional[str]
    video_qa_result: Optional[dict]
    video_notes: Optional[list[str]]
    # Non-gating findings from the local vision model's screenshot review.
    vision_notes: Optional[list[str]]
    # True only when the screenshot backend returned the complete structured
    # verdict required by QA. A screenshot alone is not visual evaluation.
    vision_evaluated: bool
    # Non-gating findings from the balance check - a level that is winnable but
    # toothless, or a fight that drags. These are tuning notes, not defects, so
    # they feed the playtest loop rather than failing a build; see saga.balance.
    balance_notes: Optional[list[str]]
    # Structured evidence from a mechanic-specific objective solver. For
    # collectible mazes this includes counts, win state, and frame cost.
    objective_result: Optional[dict]
    # Set by the Coder so QA can record a verified (brief -> script) training
    # pair once the level passes; see saga.corpus.
    coder_prompt: Optional[str]
    coder_model: Optional[str]
    # Transactional repair gate. A rejected candidate never replaces the
    # previous script; QA records the compiler/contract evidence without
    # rerunning the expensive gameplay and video stack.
    repair_rejected: bool
    repair_validation_errors: Optional[list[str]]
    # Studio Director triage: the supervisor's routing decision for the
    # current QA failure (fix | regenerate | reasset; None outside triage),
    # and a per-run history of what was already tried so the Director can
    # recognize a repair that did not take instead of repeating it.
    director_action: Optional[str]
    director_history: Optional[list[dict]]
    # A sanitized, single-asset regeneration request created by the Studio
    # Director and consumed by Asset Maker. Completed replacements are kept as
    # durable provenance and copied into the affected level's result ledger.
    reasset_request: Optional[dict]
    asset_replacements: Optional[list[dict]]
    # Durable, per-level QA history. Unlike qa_errors/vision_notes above,
    # which describe only the current graph step, this ledger is never reset
    # when the graph advances. Each entry contains every attempt plus the
    # level's final status and artifacts, and is written verbatim to run.json.
    level_results: list[dict]
    # Quality Director v3: every technically passing level receives a
    # deterministic evidence-based review. Reviews are durable so a polish
    # retry cannot erase the original finding; quality_report is the latest
    # aggregate used by the ship gate and UI.
    quality_results: list[dict]
    quality_report: Optional[dict]
    quality_repair_requested: bool
    quality_repair_owner: Optional[str]
    quality_reasset_field: Optional[str]
    quality_reasset_value: Optional[str]
    # A broken QA harness is different from generated code that needs repair.
    # When a required probe cannot produce a verdict, stop the graph and
    # report "blocked" instead of spending Coder retries or claiming a pass.
    ship_blocked: bool
