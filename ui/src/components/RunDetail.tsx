import { useEffect, useMemo, useState } from 'react'
import { artifactUrl, formatBytes, formatDate, getJSON, statusLabel } from '../api'
import type { DesignDoc, LevelAttempt, LevelResult, QualityReport, RunFiles, SagaRun, SystemBuildResult, VideoQaResult } from '../types'
import Icon from './Icon'

type Tab = 'qa' | 'assets' | 'design'

const HIDDEN_METRICS = new Set(['status', 'template', 'reason', 'restart_status'])

export default function RunDetail({ run, onClose, onOpen, onDelete, deletable }: {
  run: SagaRun
  onClose: () => void
  onOpen: (target: 'folder' | 'godot' | 'play') => void
  onDelete: () => void
  deletable: boolean
}) {
  const [detail, setDetail] = useState<SagaRun>(run)
  const [files, setFiles] = useState<RunFiles | null>(null)
  const [design, setDesign] = useState<DesignDoc | null>(null)
  const [tab, setTab] = useState<Tab>('qa')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [lightbox, setLightbox] = useState<string | null>(null)

  useEffect(() => {
    let disposed = false
    getJSON<SagaRun>(`/runs/${encodeURIComponent(run.id)}`).then((data) => { if (!disposed) setDetail(data) }).catch(() => undefined)
    getJSON<RunFiles>(`/runs/${encodeURIComponent(run.id)}/files`).then((data) => {
      if (disposed) return
      setFiles(data)
      if (data.has_design_doc) {
        fetch(artifactUrl(run.id, 'design_doc.json')!)
          .then((response) => (response.ok ? response.json() : null))
          .then((doc) => { if (!disposed && doc) setDesign(doc) })
          .catch(() => undefined)
      }
    }).catch(() => undefined)
    return () => { disposed = true }
  }, [run.id])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (lightbox) setLightbox(null)
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [lightbox, onClose])

  const videoUrl = artifactUrl(run.id, detail.gameplay_video_path || detail.level_results?.at(-1)?.gameplay_video_path)
  const screenshotUrl = artifactUrl(run.id, detail.screenshot_path || detail.level_results?.at(-1)?.screenshot_path)
  const levels = detail.level_results || []
  const passedLevels = levels.filter((level) => level.status === 'passed').length

  return (
    <div className="detail-backdrop" onMouseDown={onClose}>
      <section className="run-detail" onMouseDown={(event) => event.stopPropagation()}>
        <header className="detail-header">
          <div className="detail-title">
            <p className="eyebrow">RUN · {detail.id}</p>
            <h2>{detail.title || detail.idea || detail.id}</h2>
            <p className="detail-idea">{detail.idea}</p>
            <div className="detail-chips">
              <span className={`status ${detail.ship_ready ? 'passed' : detail.complete ? 'failed' : 'building'}`}>
                {detail.ship_ready ? 'Ship ready' : statusLabel(detail.status)}
              </span>
              {levels.length > 0 && <span className="chip">{passedLevels}/{levels.length} levels passed</span>}
              {detail.quality_report && (
                <span className={`chip quality-chip ${detail.quality_report.gate.passed ? 'passed' : 'failed'}`}>
                  Quality {detail.quality_report.overall_score}/100
                </span>
              )}
              {detail.retry_count !== undefined && <span className="chip">{detail.retry_count} retries</span>}
              {detail.coder_model && <span className="chip mono">{detail.coder_model}</span>}
              {files && <span className="chip">{formatBytes(files.total_bytes)} · {files.script_count} scripts</span>}
              <span className="chip">{formatDate(detail.updated_at)}</span>
            </div>
          </div>
          <button className="close-button" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        </header>

        <div className="detail-actions">
          <button className="primary" onClick={() => onOpen('play')}><Icon name="play" /> Play game</button>
          <button onClick={() => onOpen('godot')}><Icon name="godot" /> Open in Godot</button>
          <button onClick={() => onOpen('folder')}><Icon name="folder" /> Open folder</button>
          <div className="detail-actions-spacer" />
          {confirmingDelete ? (
            <>
              <button className="danger-solid" onClick={onDelete}>Confirm delete</button>
              <button onClick={() => setConfirmingDelete(false)}>Keep</button>
            </>
          ) : (
            <button className="danger-button" onClick={() => setConfirmingDelete(true)} disabled={!deletable}
              title={deletable ? 'Delete this run from disk' : 'Deletion is locked while a game is generating'}>
              <Icon name="trash" /> Delete run
            </button>
          )}
        </div>

        <div className="detail-hero">
          {videoUrl ? (
            <video key={videoUrl} src={videoUrl} poster={screenshotUrl} controls loop playsInline />
          ) : screenshotUrl ? (
            <img src={screenshotUrl} alt="Final gameplay screenshot" />
          ) : (
            <div className="placeholder-art hero-placeholder"><span>✦</span><p>No gameplay capture yet</p></div>
          )}
        </div>

        <nav className="detail-tabs">
          <button className={tab === 'qa' ? 'active' : ''} onClick={() => setTab('qa')}><Icon name="check" /> QA ledger</button>
          <button className={tab === 'assets' ? 'active' : ''} onClick={() => setTab('assets')}>
            <Icon name="image" /> Assets{files ? ` (${files.images.length + files.audio.length + files.videos.length})` : ''}
          </button>
          <button className={tab === 'design' ? 'active' : ''} onClick={() => setTab('design')} disabled={!design}><Icon name="doc" /> Design doc</button>
        </nav>

        {tab === 'qa' && (
          <>
            {detail.quality_report && <QualityReportCard report={detail.quality_report} />}
            <QaLedger run={detail} levels={levels} />
          </>
        )}
        {tab === 'assets' && <AssetGallery runId={run.id} files={files} onZoom={setLightbox} />}
        {tab === 'design' && design && <DesignView design={design} />}
      </section>

      {lightbox && (
        <div className="lightbox" onMouseDown={(event) => { event.stopPropagation(); setLightbox(null) }}>
          <img src={lightbox} alt="Asset preview" />
        </div>
      )}
    </div>
  )
}

function QualityReportCard({ report }: { report: QualityReport }) {
  const grouped = new Map<string, { score: number; count: number; confidence: Set<string> }>()
  for (const level of report.level_reports) {
    for (const [name, dimension] of Object.entries(level.dimensions)) {
      const current = grouped.get(name) || { score: 0, count: 0, confidence: new Set<string>() }
      current.score += dimension.score
      current.count += 1
      current.confidence.add(dimension.confidence)
      grouped.set(name, current)
    }
  }
  const actionable = report.findings.filter((finding) => finding.severity !== 'info')
  return (
    <section className={`quality-report ${report.gate.passed ? 'passed' : 'failed'}`}>
      <div className="quality-score">
        <strong>{Math.round(report.overall_score)}</strong><span>/100</span>
        <small>QUALITY SCORE</small>
      </div>
      <div className="quality-body">
        <div className="quality-head">
          <div>
            <p className="eyebrow">QUALITY DIRECTOR</p>
            <h3>{report.gate.passed ? 'Production bar cleared' : 'Polish gate is closed'}</h3>
          </div>
          <span className={`status ${report.gate.passed ? 'passed' : 'failed'}`}>
            {report.gate.passed ? 'Approved' : 'Needs improvement'}
          </span>
        </div>
        <div className="quality-dimensions">
          {[...grouped.entries()].map(([name, value]) => {
            const score = Math.round(value.score / value.count)
            return (
              <div key={name} title={`Evidence: ${[...value.confidence].join(', ')}`}>
                <span>{name.replaceAll('_', ' ')}</span><b>{score}</b>
                <i><em style={{ width: `${score}%` }} /></i>
              </div>
            )
          })}
        </div>
        {actionable.length > 0 && (
          <div className="quality-findings">
            {actionable.slice(0, 5).map((finding, index) => (
              <div key={`${finding.code}-${index}`}>
                <span>{finding.owner.replaceAll('_', ' ')}</span>
                <p><b>{finding.summary}</b>{finding.evidence}</p>
              </div>
            ))}
          </div>
        )}
        {!report.gate.passed && report.gate.reasons.length > 0 && (
          <small className="quality-gate-reason">Ship gate: {report.gate.reasons.join(' · ')}</small>
        )}
      </div>
    </section>
  )
}

function metricChips(objective?: Record<string, unknown>) {
  if (!objective) return []
  const chips: { key: string; value: string; good?: boolean }[] = []
  const entries = Object.entries(objective).sort(([left], [right]) => {
    const priority = (key: string) => key.endsWith('_verified') || key === 'clean_restart' ? 0 : 1
    return priority(left) - priority(right)
  })
  for (const [key, value] of entries) {
    if (HIDDEN_METRICS.has(key) || value === null || typeof value === 'object') continue
    if (typeof value === 'boolean') {
      // Only color-code positively phrased flags; "stuck: false" is healthy.
      chips.push({ key, value: value ? '✓' : '✗', good: value || undefined })
    } else if (typeof value === 'number') {
      chips.push({ key, value: key.includes('seconds') ? `${value.toFixed(1)}s` : String(Math.round(value * 100) / 100) })
    }
  }
  // Complex packs expose one independently verified chip per system. Keep the
  // complete Action-RPG contract visible instead of hiding the final checks
  // behind generic frame/accounting metrics.
  return chips.slice(0, 16)
}

function VideoQaCard({ result }: { result: VideoQaResult }) {
  return (
    <div className="video-qa">
      <div className="video-qa-head">
        <span className={`status ${result.status === 'passed' ? 'passed' : 'failed'}`}>Video QA {result.status}</span>
        {result.model && <span className="chip mono">{result.model}</span>}
      </div>
      {result.evidence && <p>{result.evidence}</p>}
      {(result.code_defects?.length || 0) > 0 && result.code_defects!.map((defect) => <small className="note bad" key={defect}>{defect}</small>)}
      {(result.art_advisories?.length || 0) > 0 && result.art_advisories!.map((note) => <small className="note" key={note}>{note}</small>)}
    </div>
  )
}

function AttemptCard({ attempt, runId }: { attempt: LevelAttempt; runId: string }) {
  const chips = metricChips(attempt.objective_result)
  const inputPlaythrough = attempt.objective_result?.input_playthrough
  const inputChips = typeof inputPlaythrough === 'object' && inputPlaythrough !== null
    ? metricChips(inputPlaythrough as Record<string, unknown>)
    : []
  return (
    <div className="attempt">
      <div className="attempt-head">
        <span className={`ledger-marker small ${attempt.status === 'passed' ? 'passed' : ''}`}>{attempt.status === 'passed' ? '✓' : '!'}</span>
        <strong>Attempt {attempt.attempt}</strong>
        <span className="attempt-stage">{statusLabel(attempt.status)}{attempt.stage ? ` · ${attempt.stage}` : ''}</span>
        {attempt.coder_model && <span className="chip mono">{attempt.coder_model}</span>}
      </div>
      {chips.length > 0 && (
        <div className="metric-chips">
          {chips.map((chip) => (
            <span key={chip.key} className={chip.good === undefined ? '' : chip.good ? 'good' : 'bad'}>
              <small>{chip.key.replaceAll('_', ' ')}</small><b>{chip.value}</b>
            </span>
          ))}
        </div>
      )}
      {inputChips.length > 0 && (
        <div className="video-qa">
          <div className="video-qa-head">
            <span className={`status ${inputPlaythrough && (inputPlaythrough as Record<string, unknown>).status === 'passed' ? 'passed' : 'failed'}`}>
              Normal-input playthrough
            </span>
          </div>
          <div className="metric-chips">
            {inputChips.map((chip) => (
              <span key={chip.key} className={chip.good === undefined ? '' : chip.good ? 'good' : 'bad'}>
                <small>{chip.key.replaceAll('_', ' ')}</small><b>{chip.value}</b>
              </span>
            ))}
          </div>
        </div>
      )}
      {attempt.vision_evaluated === false && (
        <small className="note bad">Visual review was not evaluated for this attempt. Packed archetypes cannot pass release quality without it.</small>
      )}
      {(attempt.errors?.length || 0) > 0 && attempt.errors!.map((error) => <small className="note bad" key={error}>{error}</small>)}
      {(attempt.vision_notes?.length || 0) > 0 && attempt.vision_notes!.map((note) => <small className="note" key={note}>{note}</small>)}
      {attempt.video_qa_result && <VideoQaCard result={attempt.video_qa_result} />}
      {attempt.screenshot_path && (
        <img className="attempt-shot" src={artifactUrl(runId, attempt.screenshot_path)} alt={`Attempt ${attempt.attempt} screenshot`} loading="lazy" />
      )}
    </div>
  )
}

function QaLedger({ run, levels }: { run: SagaRun; levels: LevelResult[] }) {
  const [expanded, setExpanded] = useState<number | null>(levels.length === 1 ? 0 : null)
  const systemBuilds = run.system_build_results || []
  if (!levels.length && !systemBuilds.length) {
    return <div className="empty-row">No completed level ledger yet — this run may still be in progress or was cancelled early.</div>
  }
  return (
    <div className="ledger detail-ledger">
      {systemBuilds.length > 0 && <SystemBuildLedger results={systemBuilds} />}
      {levels.map((level, index) => {
        const attempts = level.attempts || []
        const open = expanded === index
        return (
          <article key={level.level_index} className={open ? 'open' : ''}>
            <button className="ledger-row" onClick={() => setExpanded(open ? null : index)}>
              <span className={`ledger-marker ${level.status === 'passed' ? 'passed' : ''}`}>{level.status === 'passed' ? '✓' : '!'}</span>
              <div>
                <h3>Level {level.level_number ?? level.level_index + 1}{(level.name || level.level_name) ? ` · ${level.name || level.level_name}` : ''}</h3>
                <p>{statusLabel(level.status)} · {level.retry_count || 0} retries · {attempts.length || 1} attempt{attempts.length === 1 ? '' : 's'}</p>
              </div>
              <i className={`chevron ${open ? 'up' : ''}`} />
            </button>
            {open && (
              <div className="ledger-detail">
                {attempts.length
                  ? attempts.map((attempt) => <AttemptCard key={attempt.attempt} attempt={attempt} runId={run.id} />)
                  : <AttemptCard runId={run.id} attempt={{
                      attempt: 1, status: level.status, errors: level.qa_errors,
                      vision_notes: level.vision_notes, objective_result: level.objective_result,
                      vision_evaluated: level.vision_evaluated,
                      screenshot_path: level.screenshot_path,
                    }} />}
              </div>
            )}
          </article>
        )
      })}
      {run.video_qa_result
        && !levels.some((level) => level.attempts?.some((attempt) => attempt.video_qa_result))
        && <VideoQaCard result={run.video_qa_result} />}
    </div>
  )
}

function SystemBuildLedger({ results }: { results: SystemBuildResult[] }) {
  const active = results.filter((result) => result.status !== 'superseded')
  const confirmed = active.filter((result) => result.qa_confirmed).length
  const clean = active.every((result) => !result.status.startsWith('rejected') && !result.status.startsWith('blocked'))
  return (
    <article className="open">
      <div className="ledger-row">
        <span className={`ledger-marker ${clean ? 'passed' : ''}`}>B</span>
        <div>
          <h3>Protected system builds</h3>
          <p>{active.length} active records - {confirmed} behaviorally confirmed</p>
        </div>
      </div>
      <div className="ledger-detail">
        {active.map((result, index) => (
          <div className="attempt" key={`${result.level_index}-${result.system_id}-${index}`}>
            <div className="attempt-head">
              <span className={`ledger-marker small ${result.qa_confirmed ? 'passed' : ''}`}>{result.qa_confirmed ? 'OK' : 'i'}</span>
              <strong>Level {result.level_index + 1} - {result.system_id}</strong>
              <span className="attempt-stage">{statusLabel(result.status)} - {result.kind}</span>
              {result.executed_model && <span className="chip mono">{result.executed_model}</span>}
            </div>
            {result.recommended_model && result.recommended_model !== result.executed_model && <small className="note">Recommended specialist: {result.recommended_model}</small>}
            {(result.qa_evidence || []).map((evidence) => <small className="note" key={evidence}>{evidence}</small>)}
            {(result.errors || []).map((error) => <small className="note bad" key={error}>{error}</small>)}
          </div>
        ))}
      </div>
    </article>
  )
}

function AssetGallery({ runId, files, onZoom }: { runId: string; files: RunFiles | null; onZoom: (url: string) => void }) {
  if (!files) return <div className="empty-row">Scanning run workspace…</div>
  if (!files.images.length && !files.audio.length && !files.videos.length) {
    return <div className="empty-row">No media assets were found in this run.</div>
  }
  return (
    <div className="asset-gallery">
      {files.images.length > 0 && (
        <div className="asset-grid">
          {files.images.map((image) => {
            const url = artifactUrl(runId, image.path)!
            return (
              <button className="asset-tile" key={image.path} onClick={() => onZoom(url)} title={image.path}>
                <img src={url} alt={image.name} loading="lazy" />
                <span>{image.name}</span>
              </button>
            )
          })}
        </div>
      )}
      {files.audio.map((track) => (
        <div className="audio-row" key={track.path}>
          <Icon name="music" />
          <div><strong>{track.name}</strong><small>{formatBytes(track.size)}</small></div>
          <audio src={artifactUrl(runId, track.path)} controls preload="none" />
        </div>
      ))}
      {files.videos.map((video) => (
        <div className="audio-row" key={video.path}>
          <Icon name="film" />
          <div><strong>{video.name}</strong><small>{formatBytes(video.size)}</small></div>
          <a className="text-button" href={artifactUrl(runId, video.path)} target="_blank" rel="noreferrer">Open</a>
        </div>
      ))}
    </div>
  )
}

function DesignView({ design }: { design: DesignDoc }) {
  const facts = useMemo(() => ([
    ['Genre', design.genre],
    ['Template', design.mechanic_template],
    ['Art style', design.art_style],
    ['Audio mood', design.audio_mood],
    ['Win condition', design.win_condition],
    ['Lose condition', design.lose_condition],
  ] as const).filter(([, value]) => value), [design])
  return (
    <div className="design-view">
      {design.story_premise && <p className="design-premise">“{design.story_premise}”</p>}
      {design.hero_description && <p className="design-hero"><b>Hero</b> {design.hero_description}</p>}
      <div className="design-facts">
        {facts.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
      </div>
      {(design.core_mechanics?.length || 0) > 0 && (
        <div className="design-section">
          <p className="eyebrow">CORE MECHANICS</p>
          <ul>{design.core_mechanics!.map((mechanic) => <li key={mechanic}>{mechanic}</li>)}</ul>
        </div>
      )}
      {(design.levels?.length || 0) > 0 && (
        <div className="design-section">
          <p className="eyebrow">LEVEL ARC</p>
          {design.levels!.map((level, index) => (
            <div className="design-level" key={index}>
              <div className="design-level-head">
                <strong>{index + 1}. {level.name || 'Untitled level'}</strong>
                {level.intensity !== undefined && (
                  <span className="intensity" title={`Intensity ${level.intensity}/10`}>
                    {Array.from({ length: 5 }, (_, i) => <i key={i} className={i < (level.intensity || 0) ? 'on' : ''} />)}
                  </span>
                )}
              </div>
              {level.description && <p>{level.description}</p>}
              {level.pressure_notes && <small>Pressure: {level.pressure_notes}</small>}
              {level.outro_beat && <small>Outro: {level.outro_beat}</small>}
            </div>
          ))}
        </div>
      )}
      {(design.extra_sprites?.length || 0) > 0 && (
        <div className="design-section">
          <p className="eyebrow">EXTRA SPRITES</p>
          <ul>{design.extra_sprites!.map((sprite) => <li key={sprite.name}><b>{sprite.name}</b> — {sprite.description}</li>)}</ul>
        </div>
      )}
    </div>
  )
}
