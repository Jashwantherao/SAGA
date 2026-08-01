import { useCallback, useEffect, useState } from 'react'
import { getJSON } from './api'
import type { ManagedService, ServiceAction } from './types'
import Icon from './components/Icon'

export type { ManagedService }

const GLYPHS: Record<ManagedService['name'], string> = { ollama: 'O', comfyui: 'C', musicgen: 'M' }

export default function ServicesPanel({ services, busy, locked, onAction }: {
  services: ManagedService[]
  busy: string | null
  locked: boolean
  onAction: (action: ServiceAction, service: ManagedService['name'] | 'all') => void
}) {
  const [logService, setLogService] = useState<ManagedService['name'] | null>(null)

  if (!services.length) return <div className="panel settings-loading">Inspecting local services…</div>
  const online = services.filter((service) => service.running).length
  return <>
    <div className="service-actions-bar panel">
      <div>
        <span className={`pulse ${online === services.length ? 'online' : ''}`} />
        <div>
          <strong>{online}/{services.length} services online</strong>
          <small>{locked ? 'Lifecycle controls are locked while a game is generating' : 'Manage the local inference and asset stack'}</small>
        </div>
      </div>
      <div>
        <button onClick={() => onAction('start', 'all')} disabled={!!busy}>{busy === 'start-all' ? 'Starting…' : 'Start all'}</button>
        <button onClick={() => onAction('stop', 'all')} disabled={!!busy || locked}>{busy === 'stop-all' ? 'Stopping…' : 'Stop all'}</button>
        <button className="primary compact" onClick={() => onAction('restart', 'all')} disabled={!!busy || locked}>{busy === 'restart-all' ? 'Restarting…' : 'Restart all'}</button>
      </div>
    </div>
    <div className="managed-service-grid">
      {services.map((service) => (
        <article className="panel managed-service" key={service.name}>
          <div className="managed-service-top">
            <span className={`service-glyph ${service.running ? 'online' : ''}`}>{GLYPHS[service.name]}</span>
            <span className={`status ${service.running ? 'passed' : service.configured ? 'failed' : 'building'}`}>
              {service.running ? 'Online' : service.configured ? 'Offline' : 'Setup needed'}
            </span>
          </div>
          <h2>{service.label}</h2>
          <p>{service.detail}</p>
          <div className="service-meta">
            <span>Port</span><code>{service.port}</code>
            <span>Requirement</span><strong>{service.optional ? 'Optional' : 'Required'}</strong>
          </div>
          {!service.configured && <div className="config-hint">{service.command_hint}</div>}
          <div className="managed-actions">
            <button onClick={() => onAction('start', service.name)} disabled={!!busy || service.running}>{busy === `start-${service.name}` ? 'Starting…' : 'Start'}</button>
            <button onClick={() => onAction('stop', service.name)} disabled={!!busy || locked || !service.running}>{busy === `stop-${service.name}` ? 'Stopping…' : 'Stop'}</button>
            <button className="restart" onClick={() => onAction('restart', service.name)} disabled={!!busy || locked}>{busy === `restart-${service.name}` ? 'Restarting…' : 'Restart'}</button>
            <button onClick={() => setLogService(service.name)}><Icon name="terminal" /> Logs</button>
          </div>
        </article>
      ))}
    </div>
    <div className="service-guidance panel">
      <p className="eyebrow">SAFE LIFECYCLE</p>
      <h2>What these controls do</h2>
      <div>
        <p><strong>Start</strong> launches only services that are offline; output is captured to a per-service log.</p>
        <p><strong>Stop / Restart</strong> only terminate a process verified to own the service's configured port and command.</p>
        <p><strong>Protection</strong> locks stop and restart while a game is being generated.</p>
      </div>
    </div>
    {logService && <ServiceLogModal name={logService} onClose={() => setLogService(null)} />}
  </>
}

function ServiceLogModal({ name, onClose }: { name: ManagedService['name']; onClose: () => void }) {
  const [lines, setLines] = useState<string[] | null>(null)
  const [logPath, setLogPath] = useState('')

  const load = useCallback(() => {
    getJSON<{ lines: string[]; log_path: string }>(`/services/${name}/logs?lines=200`)
      .then((data) => { setLines(data.lines); setLogPath(data.log_path) })
      .catch(() => setLines([]))
  }, [name])

  useEffect(() => {
    load()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [load, onClose])

  return (
    <div className="detail-backdrop" onMouseDown={onClose}>
      <section className="log-modal" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><p className="eyebrow">SERVICE LOG</p><h2>{name}</h2>{logPath && <small className="mono">{logPath}</small>}</div>
          <div className="heading-actions">
            <button className="icon-button" onClick={load} title="Refresh"><Icon name="refresh" /></button>
            <button className="close-button" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
          </div>
        </header>
        <pre>{lines === null ? 'Reading log…' : lines.length ? lines.join('\n') : 'No log output yet. Start the service from this screen to begin capturing output.'}</pre>
      </section>
    </div>
  )
}
