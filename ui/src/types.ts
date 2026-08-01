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
  hud_readable?: boolean
  scene_stable?: boolean
  code_defects?: string[]
  art_advisories?: string[]
  evidence?: string
}

export type LevelAttempt = {
  attempt: number
  status: string
  stage?: string
  errors?: string[]
  screenshot_path?: string
  gameplay_video_path?: string
  vision_notes?: string[]
  balance_notes?: string[]
  video_notes?: string[]
  objective_result?: Record<string, unknown>
  video_qa_result?: VideoQaResult
  coder_model?: string
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
  objective_result?: Record<string, unknown>
  qa_errors?: string[]
  vision_notes?: string[]
  video_notes?: string[]
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
  screenshot_path?: string
  gameplay_video_path?: string
  bgm_path?: string
  sprite_paths?: string[]
  video_qa_result?: VideoQaResult
  qa_errors?: string[]
  vision_notes?: string[]
  level_results?: LevelResult[]
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
