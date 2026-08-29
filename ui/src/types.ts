export type Check = {
  name: string
  ok: boolean
  required: boolean
  detail: string
  marker: string
}

export type VideoQaResult = {
  status?: string
  model?: string
  player_visible?: boolean
  player_motion?: string
  movement_facing?: string
  animation?: string
  combat_feedback?: string
  encounter_readability?: string
  presentation_tier?: string
  hud_readable?: boolean
  scene_stable?: boolean
  code_defects?: string[]
  art_advisories?: string[]
  evidence?: string
}

export type CapabilityProbeResult = {
  id?: string
  status?: 'passed' | 'failed' | 'missing' | string
  observed?: boolean
  value?: unknown
  declared?: boolean
  configured?: boolean
  exercised?: boolean
  passed?: boolean
}

export type CapabilityCoverageEntry = {
  mode?: string
  capability_id?: string
  version?: number
  status?: 'passed' | 'failed' | 'blocked' | string
  declared?: boolean
  configured?: boolean
  exercised?: boolean
  observed?: boolean
  passed?: boolean
  probes?: CapabilityProbeResult[]
}

export type CapabilityCoverage = {
  coverage_version?: number
  assembly_hash?: string
  status?: 'passed' | 'failed' | 'blocked' | string
  capabilities_total?: number
  capabilities_passed?: number
  missing_evidence?: string[]
  failed_evidence?: string[]
  capabilities?: CapabilityCoverageEntry[]
}

export type ObjectiveResult = Record<string, unknown> & {
  capability_coverage?: CapabilityCoverage
  input_playthrough?: Record<string, unknown>
}

export type LevelAttempt = {
  attempt: number
  status: string
  stage?: string
  errors?: string[]
  screenshot_path?: string
  gameplay_video_path?: string
  vision_notes?: string[]
  vision_evaluated?: boolean
  balance_notes?: string[]
  video_notes?: string[]
  objective_result?: ObjectiveResult
  video_qa_result?: VideoQaResult
  coder_model?: string
  playability_result?: PlayabilityResult
  art_direction_hash?: string
}

export type ArtDirection = {
  art_direction_version?: number
  identity_hash?: string
  rendering_language?: string
  camera_contract?: {
    projection?: string
    camera?: string
    gameplay_plane?: string
    forbidden?: string[]
  }
  palette?: Record<string, string>
  coherence_rules?: string[]
  asset_contracts?: { logical_name?: string; role?: string }[]
}

export type AssetContractResult = {
  logical_name?: string
  path?: string
  status?: string
  errors?: string[]
  observed?: { size?: number[]; mode?: string; alpha_coverage?: number }
}

export type PlayabilityResult = {
  status?: string
  responsive?: boolean
  idle_rate?: number
  input_rate?: number
  label_states?: number
}

export type LevelResult = {
  level_index: number
  level_number?: number
  name?: string
  level_name?: string
  status: string
  retry_count?: number
  attempts?: LevelAttempt[]
  screenshot_path?: string
  gameplay_video_path?: string
  objective_result?: ObjectiveResult
  qa_errors?: string[]
  vision_notes?: string[]
  vision_evaluated?: boolean
  video_notes?: string[]
  playability_result?: PlayabilityResult
}

export type QualityDimension = {
  score: number
  weight: number
  confidence: string
}

export type QualityFinding = {
  dimension: string
  owner: string
  severity: 'critical' | 'high' | 'medium' | 'info'
  code: string
  summary: string
  evidence: string
  recommended_action: string
}

export type QualityLevelReport = {
  level_index: number
  level_number: number
  name: string
  overall_score: number
  dimensions: Record<string, QualityDimension>
  findings: QualityFinding[]
  gate: { passed: boolean; minimum_score: number; reasons: string[] }
}

export type QualityReport = {
  report_version: number
  status: string
  overall_score: number
  levels_reviewed: number
  expected_levels: number
  level_reports: QualityLevelReport[]
  findings: QualityFinding[]
  gate: { passed: boolean; minimum_score: number; reasons: string[] }
}

export type PersonaResult = {
  passed?: boolean
  [key: string]: unknown
}

export type ContentPlan = {
  schema_version?: number
  seed?: string
  compiler?: { id?: string; version?: number; candidate_index?: number }
  rooms?: { id?: string; name?: string; beat?: string; optional_discovery?: boolean }[]
  narrative?: {
    contract_version?: number
    quest_title?: string
    currency_name?: string
    quest_giver_name?: string
    boss_name?: string
    enemy_name?: string
    relic_name?: string
    ability_name?: string
    room_names?: string[]
    dialogue_lines?: string[]
    source?: string
    source_fingerprint?: string
  }
  experience_search?: {
    algorithm_version?: number
    candidates_evaluated?: number
    repairs_evaluated?: number
    selected_candidate?: number
    selected_after_repair?: boolean
    selected_signature?: string
    score?: number
    personas?: Record<string, PersonaResult>
    telemetry?: Record<string, number>
  }
}

export type SystemBuildResult = {
  level_index: number
  system_id: string
  kind: string
  status: string
  recommended_model?: string
  executed_model?: string
  errors?: string[]
  qa_confirmed?: boolean
  qa_evidence?: string[]
  builder_hash_matches_qa?: boolean
}

export type SagaRun = {
  id: string
  title?: string
  idea?: string
  status?: string
  ship_ready?: boolean
  complete?: boolean
  updated_at: string
  retry_count?: number
  coder_model?: string
  assembly_hash?: string
  content_plan?: ContentPlan
  art_direction?: ArtDirection
  art_direction_status?: string
  asset_contract_results?: AssetContractResult[]
  screenshot_path?: string
  gameplay_video_path?: string
  bgm_path?: string
  sprite_paths?: string[]
  video_qa_result?: VideoQaResult
  qa_errors?: string[]
  vision_notes?: string[]
  level_results?: LevelResult[]
  system_build_results?: SystemBuildResult[]
  quality_report?: QualityReport
}

export type RunFileEntry = { path: string; name: string; size: number }

export type RunFiles = {
  images: RunFileEntry[]
  audio: RunFileEntry[]
  videos: RunFileEntry[]
  script_count: number
  total_bytes: number
  has_design_doc: boolean
}

export type DesignLevel = {
  name?: string
  description?: string
  outro_beat?: string
  intensity?: number
  pressure_notes?: string
}

export type DesignDoc = {
  title?: string
  genre?: string
  mechanic_template?: string
  hero_description?: string
  core_mechanics?: string[]
  story_premise?: string
  theme_thread?: string
  win_condition?: string
  lose_condition?: string
  levels?: DesignLevel[]
  art_style?: string
  audio_mood?: string
  key_item?: { description?: string; role?: string }
  extra_sprites?: { name?: string; description?: string }[]
  narrative?: ContentPlan['narrative']
}

export type Job = {
  id: string
  idea: string
  levels: number
  status: string
  started_at?: string
  finished_at?: string
  run_id?: string
  exit_code?: number
  logs: string[]
}

export type JobSummary = Omit<Job, 'logs'>

export type Health = {
  ready: boolean
  checks: Check[]
  settings: { output_root: string; coder_backend: string; coder_model: string; video_qa: boolean }
}

export type ManagedService = {
  name: 'ollama' | 'comfyui' | 'musicgen'
  label: string
  port: number
  running: boolean
  configured: boolean
  optional: boolean
  detail: string
  command_hint: string
}

export type GpuStats = {
  name: string
  utilization: number | null
  memory_used_mb: number | null
  memory_total_mb: number | null
  temperature: number | null
  power_draw: number | null
}

export type SystemStats = {
  cpu_percent: number
  memory_used: number
  memory_total: number
  memory_percent: number
  disk_used: number
  disk_total: number
  gpu: GpuStats | null
}

export type ServiceAction = 'start' | 'restart' | 'stop'
export type View = 'studio' | 'create' | 'library' | 'services' | 'models'
