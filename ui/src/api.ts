import type { SagaRun } from './types'

export const API = 'http://127.0.0.1:8765/api'
export const EVENTS = 'ws://127.0.0.1:8765/api/events'

export async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`)
  if (!response.ok) throw new Error(await detail(response))
  return response.json()
}

export async function sendJSON<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await detail(response))
  return response.json()
}

async function detail(response: Response): Promise<string> {
  try {
    const payload = await response.json()
    if (typeof payload.detail === 'string') return payload.detail
  } catch {
    /* fall through */
  }
  return `Request failed (${response.status})`
}

/** Build an artifact URL from either an absolute workspace path or a run-relative path. */
export function artifactUrl(runId: string, source?: string): string | undefined {
  if (!source) return undefined
  const normalized = source.replaceAll('\\', '/')
  const marker = `/runs/${runId}/`
  const relative = normalized.includes(marker)
    ? normalized.split(marker)[1]
    : normalized.replace(/^\/+/, '')
  if (!relative) return undefined
  return `${API}/artifacts/${encodeURIComponent(runId)}/${relative.split('/').map(encodeURIComponent).join('/')}`
}

export function runPreviewUrl(run: SagaRun): string | undefined {
  const lastLevel = run.level_results?.at(-1)
  return artifactUrl(run.id, run.screenshot_path || lastLevel?.screenshot_path)
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

export function formatDate(value?: string): string {
  if (!value) return 'Just now'
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

export function statusLabel(status?: string): string {
  return (status || 'building').replaceAll('_', ' ')
}

export function elapsedBetween(startedAt: string, end?: number): string {
  const seconds = Math.max(0, Math.floor(((end ?? Date.now()) - new Date(startedAt).getTime()) / 1000))
  const minutes = Math.floor(seconds / 60)
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
  return minutes ? `${minutes}m ${seconds % 60}s` : `${seconds}s`
}
