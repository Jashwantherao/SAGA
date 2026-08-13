import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { EVENTS, elapsedBetween, formatDate, getJSON, runPreviewUrl, sendJSON, statusLabel } from './api'
import type { Health, Job, JobSummary, ManagedService, SagaRun, ServiceAction, View } from './types'
import Icon from './components/Icon'
import SystemMonitor from './components/SystemMonitor'
import RunDetail from './components/RunDetail'
import Toasts from './components/Toasts'
import type { Toast } from './components/Toasts'
import ModelsPanel from './ModelsPanel'
import ServicesPanel from './ServicesPanel'

const viewTitles: Record<View, string> = {
  studio: 'Studio overview',
  create: 'Create game',
  library: 'Game library',
  services: 'Services',
  models: 'Models & APIs',
}

const IDEA_POOL = [
  'A tiny lighthouse keeper redirects moonbeams to guide ghost ships through a storm',
  'A clockwork beekeeper herds luminous bees into a brass hive before dawn',
  'A shadow puppet escapes the theater by stitching itself to passing lanterns',
  'A librarian mouse re-shelves cursed books while the library rearranges itself',
  'A rain spirit waters a floating garden while dodging bottled lightning',
  'A tiny astronaut lassoes runaway constellations back into the night sky',
  'A sentient teapot brews courage potions for knights afraid of the dark',
  'A magnetic scrapyard robot builds a bridge home from falling stars',
]
const MAX_IDEA_LENGTH = 4000

let toastId = 0

function App() {
  const [view, setView] = useState<View>('studio')
  const [commandOpen, setCommandOpen] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [services, setServices] = useState<ManagedService[]>([])
  const [serviceBusy, setServiceBusy] = useState<string | null>(null)
  const [runs, setRuns] = useState<SagaRun[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [history, setHistory] = useState<JobSummary[]>([])
  const [selectedRun, setSelectedRun] = useState<SagaRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [apiDown, setApiDown] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const isRunning = job?.status === 'running' || job?.status === 'queued'

  const pushToast = useCallback((kind: Toast['kind'], text: string) => {
    const id = ++toastId
    setToasts((current) => [...current.slice(-3), { id, kind, text }])
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 5200)
  }, [])

  const loadRuns = useCallback(async () => {
    setRuns(await getJSON<SagaRun[]>('/runs'))
  }, [])

  const loadJob = useCallback(async () => {
    setJob(await getJSON<Job | null>('/generations/current'))
  }, [])

  const loadHistory = useCallback(async () => {
    setHistory(await getJSON<JobSummary[]>('/generations'))
  }, [])

  const loadStatus = useCallback(async () => {
    try {
      const [healthData, servicesData] = await Promise.all([
        getJSON<Health>('/health'),
        getJSON<ManagedService[]>('/services').catch(() => [] as ManagedService[]),
      ])
      setHealth(healthData)
      if (servicesData.length) setServices(servicesData)
      await Promise.all([loadRuns(), loadHistory().catch(() => undefined)])
      setApiDown(false)
    } catch {
      setApiDown(true)
    } finally {
      setLoading(false)
    }
  }, [loadRuns, loadHistory])

  useEffect(() => {
    void loadStatus()
    void loadJob().catch(() => undefined)
    let socket: WebSocket | null = null
    let reconnectTimer: number | undefined
    let disposed = false

    const connect = () => {
      socket = new WebSocket(EVENTS)
      socket.onopen = () => setApiDown(false)
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data)
        if (message.type === 'job') {
          setJob(message.job)
          if (['completed', 'failed', 'cancelled'].includes(message.job.status)) {
            void loadHistory().catch(() => undefined)
          }
        }
        if (message.type === 'log') {
          setJob((current) => current
            ? { ...current, status: 'running', logs: [...current.logs, message.line].slice(-300) }
            : current)
        }
        if (message.type === 'runs_changed') void loadRuns().catch(() => undefined)
      }
      socket.onclose = () => {
        if (!disposed) reconnectTimer = window.setTimeout(connect, 1200)
      }
    }
    connect()
    return () => {
      disposed = true
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [loadJob, loadRuns, loadStatus, loadHistory])

  useEffect(() => {
    if (!isRunning) return
    const poll = window.setInterval(() => void loadJob().catch(() => undefined), 1500)
    return () => window.clearInterval(poll)
  }, [isRunning, loadJob])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen((current) => !current)
      }
      if (event.key === 'Escape') setCommandOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  async function createGame(idea: string, levels: number, skipPreflight: boolean) {
    try {
      const payload = await sendJSON<Job>('/generations', 'POST', { idea, levels, skip_preflight: skipPreflight })
      setJob(payload)
      setView('studio')
      pushToast('success', 'Generation started — the studio is on it.')
      void loadHistory().catch(() => undefined)
    } catch (reason) {
      pushToast('error', reason instanceof Error ? reason.message : 'Could not start generation')
    }
  }

  async function cancelJob() {
    if (!job) return
    try {
      await sendJSON(`/generations/${job.id}/cancel`, 'POST')
      pushToast('info', 'Stop requested — the generator is shutting down.')
    } catch (reason) {
      pushToast('error', reason instanceof Error ? reason.message : 'Could not stop generation')
    }
  }

  async function openRun(run: SagaRun, target: 'folder' | 'godot' | 'play') {
    try {
      await sendJSON(`/runs/${encodeURIComponent(run.id)}/open`, 'POST', { target })
      if (target !== 'folder') pushToast('success', target === 'play' ? `Launching ${run.title || 'game'}…` : 'Opening the Godot editor…')
    } catch (reason) {
      pushToast('error', reason instanceof Error ? reason.message : `Could not open ${target}`)
    }
  }

  async function deleteRun(run: SagaRun) {
    try {
      await sendJSON(`/runs/${encodeURIComponent(run.id)}`, 'DELETE')
      setSelectedRun(null)
      pushToast('success', `Deleted run ${run.title || run.id}.`)
      void loadRuns().catch(() => undefined)
    } catch (reason) {
      pushToast('error', reason instanceof Error ? reason.message : 'Could not delete run')
    }
  }

  async function controlService(action: ServiceAction, service: ManagedService['name'] | 'all') {
    const operation = `${action}-${service}`
    setServiceBusy(operation)
    try {
      const payload = await sendJSON<{ results: { name: string; status: string; detail?: string }[] }>(
        '/services/actions', 'POST', { action, service })
      const failed = payload.results?.find((result) => result.status === 'not_configured')
      if (failed) pushToast('error', failed.detail || `${failed.name} is not configured`)
      else pushToast('success', `Service ${action} dispatched${service === 'all' ? ' for the full stack' : ` for ${service}`}.`)
      window.setTimeout(() => void loadStatus(), 1600)
    } catch (reason) {
      pushToast('error', reason instanceof Error ? reason.message : `Could not ${action} ${service}`)
    } finally {
      setServiceBusy(null)
    }
  }

  const completedRuns = runs.filter((run) => run.complete)
  const shippedRuns = completedRuns.filter((run) => run.ship_ready)
  const shipRate = completedRuns.length ? Math.round((shippedRuns.length / completedRuns.length) * 100) : 0
  const activeStage = useMemo(() => {
    const text = job?.logs.join('\n').toLowerCase() || ''
    if (!isRunning) return job?.status || 'idle'
    if (text.includes('gameplay video')) return 'Video QA'
    if (text.includes('qa:') || text.includes('screenshot')) return 'Gameplay QA'
    if (text.includes('godot project')) return 'Building game'
    if (text.includes('sprite') || text.includes('background')) return 'Creating assets'
    if (text.includes('design')) return 'Designing game'
    return 'Starting studio'
  }, [isRunning, job])

  return (
    <div className="app-shell">
      <div className="aurora" aria-hidden="true"><i /><i /><i /></div>
      <aside className="sidebar">
        <button className="brand" onClick={() => setView('studio')} aria-label="SAGA Studio home">
          <span className="brand-mark"><span>S</span></span>
          <span><strong>SAGA</strong><small>Autonomous game studio</small></span>
        </button>
        <nav>
          <span className="nav-caption">Workspace</span>
          <NavButton active={view === 'studio'} icon="grid" label="Studio" onClick={() => setView('studio')} />
          <NavButton active={view === 'create'} icon="spark" label="Create game" onClick={() => setView('create')} />
          <NavButton active={view === 'library'} icon="library" label="Game library" onClick={() => setView('library')} count={runs.length} />
          <span className="nav-divider" />
          <span className="nav-caption">Infrastructure</span>
          <NavButton active={view === 'services'} icon="services" label="Services" onClick={() => setView('services')} />
          <NavButton active={view === 'models'} icon="models" label="Models & APIs" onClick={() => setView('models')} />
        </nav>
        <div className="sidebar-bottom">
          <SystemMonitor />
          <div className={`system-pill ${health?.ready ? 'online' : 'attention'}`}>
            <span className="pulse" />
            <div>
              <strong>{health?.ready ? 'Studio ready' : loading ? 'Checking studio' : 'Needs attention'}</strong>
              <small>{health?.settings.coder_model || 'Local services'}</small>
            </div>
          </div>
          <button className="nav-button" onClick={() => void loadStatus()}><Icon name="refresh" /> Refresh health</button>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div className="breadcrumbs"><span>SAGA</span><b>/</b>{viewTitles[view]}</div>
          <div className="topbar-actions">
            {isRunning && view !== 'studio' && (
              <button className="running-chip" onClick={() => setView('studio')}>
                <span className="live-dot" /> {activeStage}{job?.started_at ? ` · ${elapsedBetween(job.started_at)}` : ''}
              </button>
            )}
            <button className="command-trigger" onClick={() => setCommandOpen(true)} aria-label="Open command palette">
              <Icon name="search" /><span>Jump to…</span><kbd>Ctrl K</kbd>
            </button>
            <span className={`topbar-health ${health?.ready ? 'ready' : ''}`} title="Current studio health">
              <i />{health?.ready ? 'Ready' : loading ? 'Checking' : 'Attention'}
            </span>
            <button className="primary compact" onClick={() => setView('create')}><span>＋</span> New game</button>
          </div>
        </header>

        {apiDown && (
          <div className="error-banner">
            <Icon name="warning" />
            <span>SAGA's local API is unreachable at 127.0.0.1:8765. Start it with <code>npm run dev:stack</code> or <code>saga-ui-api</code>.</span>
            <button onClick={() => void loadStatus()}>Retry</button>
          </div>
        )}

        {view === 'studio' && (
          <StudioView
            health={health} loading={loading} runs={runs} job={job} history={history}
            isRunning={isRunning} activeStage={activeStage}
            shipRate={shipRate} completedCount={completedRuns.length} shippedCount={shippedRuns.length}
            onCreate={() => setView('create')} onLibrary={() => setView('library')} onServices={() => setView('services')}
            onCancel={() => void cancelJob()} onRefresh={() => void loadStatus()}
            onSelect={setSelectedRun} onPlay={(run) => void openRun(run, 'play')}
            onToast={pushToast}
          />
        )}

        {view === 'create' && (
          <CreateView health={health} isRunning={isRunning} onSubmit={createGame} />
        )}

        {view === 'library' && (
          <LibraryView runs={runs} onSelect={setSelectedRun} onPlay={(run) => void openRun(run, 'play')} onCreate={() => setView('create')} />
        )}

        {view === 'services' && (
          <div className="page">
            <div className="page-heading">
              <div><p className="eyebrow">LOCAL RUNTIME</p><h1>Start, stop, and inspect services.</h1><p>One safe control surface for Ollama, ComfyUI, and MusicGen.</p></div>
            </div>
            <ServicesPanel services={services} busy={serviceBusy} locked={isRunning} onAction={(action, service) => void controlService(action, service)} />
          </div>
        )}

        {view === 'models' && (
          <div className="page">
            <div className="page-heading">
              <div><p className="eyebrow">MODEL ROUTING</p><h1>Choose the model for every role.</h1><p>Mix local models, DeepSeek, NVIDIA, Anthropic, and compatible APIs.</p></div>
            </div>
            <ModelsPanel />
          </div>
        )}
      </main>

      {selectedRun && (
        <RunDetail
          run={selectedRun}
          deletable={!isRunning}
          onClose={() => setSelectedRun(null)}
          onOpen={(target) => void openRun(selectedRun, target)}
          onDelete={() => void deleteRun(selectedRun)}
        />
      )}
      {commandOpen && (
        <CommandPalette
          current={view}
          onClose={() => setCommandOpen(false)}
          onNavigate={(target) => { setView(target); setCommandOpen(false) }}
          onRefresh={() => { void loadStatus(); setCommandOpen(false) }}
        />
      )}
      <Toasts toasts={toasts} onDismiss={(id) => setToasts((current) => current.filter((toast) => toast.id !== id))} />
    </div>
  )
}

function StudioView({ health, loading, runs, job, history, isRunning, activeStage, shipRate, completedCount, shippedCount, onCreate, onLibrary, onServices, onCancel, onRefresh, onSelect, onPlay, onToast }: {
  health: Health | null; loading: boolean; runs: SagaRun[]; job: Job | null; history: JobSummary[]
  isRunning: boolean; activeStage: string; shipRate: number; completedCount: number; shippedCount: number
  onCreate: () => void; onLibrary: () => void; onServices: () => void; onCancel: () => void; onRefresh: () => void
  onSelect: (run: SagaRun) => void; onPlay: (run: SagaRun) => void
  onToast: (kind: Toast['kind'], text: string) => void
}) {
  const [now, setNow] = useState(() => Date.now())
  const [follow, setFollow] = useState(true)
  const terminalRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (!isRunning) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [isRunning])

  useEffect(() => {
    if (follow && terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight
  }, [job?.logs, follow])

  async function copyLogs() {
    if (!job?.logs.length) return
    try {
      await navigator.clipboard.writeText(job.logs.join('\n'))
      onToast('success', 'Pipeline log copied to clipboard.')
    } catch {
      onToast('error', 'Clipboard is unavailable in this window.')
    }
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div><p className="eyebrow">CONTROL ROOM</p><h1>Good games, proven playable.</h1><p>Generate, observe, and ship from one studio.</p></div>
        <div className="date-chip"><span className="live-dot" /> Live workspace <strong>{health?.settings.output_root || 'D:\\SAGA'}</strong></div>
      </div>

      <section className="metrics">
        <Metric label="Studio health" value={health?.ready ? 'Ready' : loading ? 'Checking' : 'Attention'} detail={`${health?.checks.filter((check) => check.ok).length || 0}/${health?.checks.length || 0} systems available`} tone={health?.ready ? 'green' : 'amber'} />
        <Metric label="Games generated" value={String(completedCount)} detail={`${runs.length} total workspaces`} />
        <Metric label="Ship rate" value={`${shipRate}%`} detail={`${shippedCount} QA-approved games`} tone="violet" />
        <Metric label="Active stage" value={activeStage} detail={isRunning ? job?.idea || '' : 'Studio is available'} tone={isRunning ? 'blue' : undefined} />
      </section>

      <div className="dashboard-grid">
        <section className="panel production-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">PRODUCTION</p><h2>{isRunning ? job?.idea : 'No game in production'}</h2></div>
            {isRunning && <span className="status running">Running</span>}
          </div>
          {isRunning || job?.logs.length ? (
            <>
              <div className="stage-track">
                {['Design', 'Assets', 'Build', 'QA', 'Ship'].map((stage, index) => (
                  <div className={`stage ${index < stageIndex(activeStage) ? 'done' : ''} ${index === stageIndex(activeStage) ? 'active' : ''}`} key={stage}>
                    <span>{index < stageIndex(activeStage) ? '✓' : index + 1}</span><small>{stage}</small>
                  </div>
                ))}
              </div>
              <div className="terminal">
                <div className="terminal-bar">
                  <span><i /><i /><i /></span>
                  <b>LIVE PIPELINE</b>
                  <div className="terminal-tools">
                    <button className={follow ? 'on' : ''} onClick={() => setFollow((value) => !value)} title="Auto-scroll to newest output">follow</button>
                    <button onClick={() => void copyLogs()} title="Copy full log">copy</button>
                    <em>{job?.status}</em>
                  </div>
                </div>
                <pre ref={terminalRef}>{job?.logs.join('\n') || (job?.status === 'running' ? 'Generator process is active. Waiting for the current step to report progress…' : 'Preparing the studio…')}</pre>
              </div>
              <div className="panel-actions">
                <span>{job?.levels} level{job?.levels === 1 ? '' : 's'} · {job?.status}{job?.started_at ? ` · ${elapsedBetween(job.started_at, isRunning ? now : job.finished_at ? new Date(job.finished_at).getTime() : now)} elapsed` : ''}</span>
                {isRunning && <button className="danger-button" onClick={onCancel}><Icon name="stop" /> Stop generation</button>}
              </div>
            </>
          ) : (
            <div className="empty-production">
              <div className="orb"><span>✦</span></div>
              <h3>Your next game starts with one sentence.</h3>
              <p>SAGA designs it, creates the assets, builds it in Godot, and verifies every level.</p>
              <div className="empty-pipeline" aria-label="SAGA production pipeline">
                {['Design', 'Art + audio', 'Godot build', 'Playtest', 'Ship gate'].map((step, index) => (
                  <span key={step}><b>{String(index + 1).padStart(2, '0')}</b>{step}</span>
                ))}
              </div>
              <button className="primary" onClick={onCreate}>Create a game <span>→</span></button>
            </div>
          )}
        </section>

        <div className="side-stack">
          <section className="panel services-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">SYSTEMS</p><h2>Studio services</h2></div>
              <div className="heading-actions">
                <button className="text-button" onClick={onServices}>Manage</button>
                <button className="icon-button" onClick={onRefresh}><Icon name="refresh" /></button>
              </div>
            </div>
            <div className="service-list">
              {(health?.checks || []).map((check) => (
                <div className="service" key={check.name}>
                  <span className={`service-icon ${check.ok ? 'ok' : check.required ? 'fail' : 'warn'}`}>{check.ok ? '✓' : '!'}</span>
                  <div><strong>{check.name}</strong><small>{check.detail}</small></div>
                  <b className={check.ok ? 'ok-text' : check.required ? 'fail-text' : 'warn-text'}>{check.marker}</b>
                </div>
              ))}
              {!health && <div className="service-loading">Contacting the local studio…</div>}
            </div>
          </section>

          {history.length > 0 && (
            <section className="panel history-panel">
              <div className="panel-heading"><div><p className="eyebrow">SESSION HISTORY</p><h2>Recent generations</h2></div><Icon name="history" /></div>
              <div className="history-list">
                {history.slice(0, 5).map((entry) => (
                  <div className="history-row" key={entry.id}>
                    <span className={`dot ${entry.status}`} />
                    <div><strong>{entry.idea}</strong><small>{entry.levels} level{entry.levels === 1 ? '' : 's'} · {statusLabel(entry.status)}{entry.started_at && entry.finished_at ? ` · ${elapsedBetween(entry.started_at, new Date(entry.finished_at).getTime())}` : ''}</small></div>
                    {entry.run_id && <button className="text-button" onClick={() => { const match = runs.find((run) => run.id === entry.run_id); if (match) onSelect(match) }}>View</button>}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>

      <section className="recent-section">
        <div className="section-heading">
          <div><p className="eyebrow">RECENT BUILDS</p><h2>Game library</h2></div>
          <button className="text-button" onClick={onLibrary}>View all <span>→</span></button>
        </div>
        {runs.length
          ? <div className="run-grid">{runs.slice(0, 3).map((run) => <RunCard key={run.id} run={run} onSelect={() => onSelect(run)} onPlay={() => onPlay(run)} />)}</div>
          : <div className="empty-row">Generated games will appear here with their QA evidence.</div>}
      </section>
    </div>
  )
}

function CreateView({ health, isRunning, onSubmit }: {
  health: Health | null
  isRunning: boolean
  onSubmit: (idea: string, levels: number, skipPreflight: boolean) => Promise<void>
}) {
  const [idea, setIdea] = useState('')
  const [levels, setLevels] = useState(1)
  const [skipPreflight, setSkipPreflight] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    if (submitting || isRunning || idea.trim().length < 3) return
    setSubmitting(true)
    try {
      await onSubmit(idea.trim(), levels, skipPreflight)
    } finally {
      setSubmitting(false)
    }
  }

  function rollIdea() {
    const next = IDEA_POOL[Math.floor(Math.random() * IDEA_POOL.length)]
    setIdea(next === idea ? IDEA_POOL[(IDEA_POOL.indexOf(next) + 1) % IDEA_POOL.length] : next)
  }

  return (
    <div className="page create-page">
      <div className="page-heading">
        <div><p className="eyebrow">NEW PRODUCTION</p><h1>What should we build?</h1><p>Give the studio a strong premise. SAGA handles the production plan.</p></div>
      </div>
      <form className="create-layout" onSubmit={submit}>
        <section className="panel prompt-panel">
          <div className="prompt-label-row">
            <label htmlFor="idea">Game idea</label>
            <button type="button" className="text-button" onClick={rollIdea}><Icon name="dice" /> Surprise me</button>
          </div>
          <textarea
            id="idea" autoFocus value={idea}
            onChange={(event) => setIdea(event.target.value)}
            onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') void submit() }}
            placeholder="A tiny lighthouse keeper redirects moonbeams to guide ghost ships through a storm…"
            minLength={3} maxLength={MAX_IDEA_LENGTH} required
          />
          <div className="prompt-footer"><span>Describe the fantasy, player action, progression, and pressure. Ctrl+Enter to generate.</span><b className={idea.length > MAX_IDEA_LENGTH * .9 ? 'near-limit' : ''}>{idea.length.toLocaleString()}/{MAX_IDEA_LENGTH.toLocaleString()}</b></div>
          <div className="suggestions">
            <span>Try one:</span>
            {IDEA_POOL.slice(0, 3).map((sample) => (
              <button type="button" key={sample} onClick={() => setIdea(sample)}>{sample.split(' ').slice(1, 5).join(' ')}…</button>
            ))}
          </div>
        </section>
        <aside className="panel production-settings">
          <p className="eyebrow">PRODUCTION SETTINGS</p>
          <div className={`preflight-summary ${health?.ready ? 'ready' : ''}`}>
            <span><i />{health?.ready ? 'Studio preflight ready' : 'Preflight needs attention'}</span>
            <b>{health?.checks.filter((check) => check.ok).length || 0}/{health?.checks.length || 0}</b>
          </div>
          <label>Number of levels</label>
          <div className="level-picker">
            {[1, 2, 3, 4, 5].map((value) => (
              <button type="button" className={levels === value ? 'active' : ''} key={value} onClick={() => setLevels(value)}>{value}</button>
            ))}
          </div>
          <div className="setting-row"><span>Coder</span><strong>{health?.settings.coder_model || 'Configured model'}</strong></div>
          <div className="setting-row"><span>Video QA</span><strong>{health?.settings.video_qa ? 'Enabled' : 'Disabled'}</strong></div>
          <label className="toggle-row">
            <span><strong>Skip preflight</strong><small>Attempt a run when services are offline</small></span>
            <input type="checkbox" checked={skipPreflight} onChange={(event) => setSkipPreflight(event.target.checked)} />
          </label>
          {!health?.ready && !skipPreflight && <div className="preflight-note"><Icon name="warning" /> Required services must pass before generation.</div>}
          <button className="primary generate" disabled={isRunning || submitting || idea.trim().length < 3} type="submit">
            <span>✦</span>{isRunning ? 'Studio is busy' : submitting ? 'Starting…' : 'Generate game'}
          </button>
          <small className="estimate">One level usually takes several minutes.</small>
        </aside>
      </form>
    </div>
  )
}

type LibraryFilter = 'all' | 'shipped' | 'failed' | 'building'

function LibraryView({ runs, onSelect, onPlay, onCreate }: {
  runs: SagaRun[]
  onSelect: (run: SagaRun) => void
  onPlay: (run: SagaRun) => void
  onCreate: () => void
}) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<LibraryFilter>('all')

  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase()
    return runs.filter((run) => {
      if (filter === 'shipped' && !run.ship_ready) return false
      if (filter === 'failed' && (run.ship_ready || !run.complete)) return false
      if (filter === 'building' && run.complete) return false
      if (!text) return true
      return [run.title, run.idea, run.id, run.coder_model].some((field) => field?.toLowerCase().includes(text))
    })
  }, [runs, query, filter])

  const counts: Record<LibraryFilter, number> = useMemo(() => ({
    all: runs.length,
    shipped: runs.filter((run) => run.ship_ready).length,
    failed: runs.filter((run) => run.complete && !run.ship_ready).length,
    building: runs.filter((run) => !run.complete).length,
  }), [runs])

  return (
    <div className="page">
      <div className="page-heading">
        <div><p className="eyebrow">RUN ARCHIVE</p><h1>Game library</h1><p>Every workspace, artifact, and truthful QA decision.</p></div>
        <span className="library-count">{filtered.length} of {runs.length} runs</span>
      </div>
      {runs.length > 0 && (
        <div className="library-toolbar">
          <div className="search-box">
            <Icon name="search" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title, idea, model, or run id…" />
            {query && <button onClick={() => setQuery('')} aria-label="Clear search"><Icon name="close" /></button>}
          </div>
          <div className="filter-chips">
            {([['all', 'All'], ['shipped', 'Ship ready'], ['failed', 'Failed QA'], ['building', 'Incomplete']] as const).map(([value, label]) => (
              <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>
                {label} <b>{counts[value]}</b>
              </button>
            ))}
          </div>
        </div>
      )}
      {filtered.length ? (
        <div className="run-grid library-grid">
          {filtered.map((run) => <RunCard key={run.id} run={run} onSelect={() => onSelect(run)} onPlay={() => onPlay(run)} />)}
        </div>
      ) : runs.length ? (
        <div className="empty-row">No runs match this search.</div>
      ) : (
        <div className="panel empty-library">
          <div className="orb"><span>✦</span></div>
          <h2>No games yet</h2>
          <p>Create the first production and it will appear here.</p>
          <button className="primary" onClick={onCreate}>Create a game</button>
        </div>
      )}
    </div>
  )
}

function NavButton({ active, icon, label, onClick, count }: { active: boolean; icon: string; label: string; onClick: () => void; count?: number }) {
  return (
    <button className={`nav-button ${active ? 'active' : ''}`} onClick={onClick}>
      <Icon name={icon} /><span>{label}</span>{count !== undefined && <b>{count}</b>}
    </button>
  )
}

function CommandPalette({ current, onClose, onNavigate, onRefresh }: {
  current: View
  onClose: () => void
  onNavigate: (view: View) => void
  onRefresh: () => void
}) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const commands: { label: string; detail: string; icon: string; view?: View; action?: () => void }[] = [
    { label: 'Studio overview', detail: 'Production, health and recent builds', icon: 'grid', view: 'studio' },
    { label: 'Create a new game', detail: 'Start from a one-sentence premise', icon: 'spark', view: 'create' },
    { label: 'Open game library', detail: 'Browse runs and truthful QA evidence', icon: 'library', view: 'library' },
    { label: 'Manage services', detail: 'Ollama, ComfyUI and MusicGen', icon: 'services', view: 'services' },
    { label: 'Configure models & APIs', detail: 'Route each studio agent', icon: 'models', view: 'models' },
    { label: 'Refresh studio health', detail: 'Run local readiness checks again', icon: 'refresh', action: onRefresh },
  ]
  const visible = commands.filter((command) => `${command.label} ${command.detail}`.toLowerCase().includes(query.toLowerCase()))

  useEffect(() => inputRef.current?.focus(), [])

  function run(command: typeof commands[number]) {
    if (command.view) onNavigate(command.view)
    else command.action?.()
  }

  return (
    <div className="command-backdrop" onMouseDown={onClose}>
      <section className="command-palette" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={(event) => event.stopPropagation()}>
        <div className="command-search">
          <Icon name="search" />
          <input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && visible[0]) run(visible[0]) }} placeholder="Jump to a studio surface…" />
          <kbd>Esc</kbd>
        </div>
        <div className="command-list">
          {visible.map((command) => (
            <button key={command.label} className={command.view === current ? 'current' : ''} onClick={() => run(command)}>
              <span><Icon name={command.icon} /></span>
              <div><strong>{command.label}</strong><small>{command.detail}</small></div>
              {command.view === current && <em>Current</em>}
            </button>
          ))}
          {!visible.length && <p>No command matches “{query}”.</p>}
        </div>
        <footer><span><kbd>Enter</kbd> open</span><span><kbd>Ctrl K</kbd> toggle</span><b>SAGA COMMAND DECK</b></footer>
      </section>
    </div>
  )
}

function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: string }) {
  return <article className={`metric ${tone || ''}`}><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div><i /></article>
}

function RunCard({ run, onSelect, onPlay }: { run: SagaRun; onSelect: () => void; onPlay: () => void }) {
  const preview = runPreviewUrl(run)
  return (
    <article className="run-card" onClick={onSelect}>
      <div className="run-preview">
        {preview ? <img src={preview} alt={`${run.title || 'Generated game'} screenshot`} loading="lazy" /> : <div className="placeholder-art"><span>✦</span></div>}
        <span className={`status ${run.ship_ready ? 'passed' : run.complete ? 'failed' : 'building'}`}>{run.ship_ready ? 'Ship ready' : statusLabel(run.status)}</span>
        <button className="play-button" aria-label="Play game" onClick={(event) => { event.stopPropagation(); onPlay() }}>▶</button>
      </div>
      <div className="run-copy">
        <h3>{run.title || run.idea || 'Production in progress'}</h3>
        <p>
          {run.level_results?.length || 0} levels · {run.retry_count || 0} retries
          {run.quality_report ? ` · quality ${Math.round(run.quality_report.overall_score)}` : ''}
        </p>
        <div><span>{formatDate(run.updated_at)}</span><b>{run.coder_model || 'SAGA'}</b></div>
      </div>
    </article>
  )
}

function stageIndex(stage: string) {
  const normalized = stage.toLowerCase()
  if (normalized.includes('ship') || normalized.includes('complete')) return 4
  if (normalized.includes('qa')) return 3
  if (normalized.includes('build')) return 2
  if (normalized.includes('asset')) return 1
  return 0
}

export default App
