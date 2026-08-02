import { useEffect, useId, useState } from 'react'

const API = 'http://127.0.0.1:8765/api'

type Settings = {
  designer_backend: string; designer_model: string; designer_remote_model: string
  director_backend: string; director_model: string; director_remote_model: string
  architect_backend: string; architect_model: string; architect_base_url: string
  coder_backend: string; coder_model: string; coder_remote_model: string; dotmaze_model: string
  vision_backend: string; vision_model: string; vision_remote_model: string
  feedback_backend: string; feedback_model: string
  video_qa_enabled: boolean; video_model: string
  openai_base_url: string; vision_base_url: string; stop_gpu_services: boolean; incremental_build: boolean; incremental_max_systems: number
  api_keys: { deepseek: boolean; nvidia: boolean; anthropic: boolean }
  deepseek_api_key?: string; nvidia_api_key?: string; anthropic_api_key?: string
}

type Catalog = { local: string[]; deepseek: string[]; nvidia: string[]; claude: string[] }

const backendOptions: Record<string, { value: string; label: string }[]> = {
  standard: [
    { value: 'local', label: 'Local · Ollama' },
    { value: 'deepseek', label: 'DeepSeek API' },
    { value: 'openai', label: 'Custom OpenAI API' },
    { value: 'claude', label: 'Anthropic Claude' },
  ],
  coder: [
    { value: 'ollama', label: 'Local · Ollama' },
    { value: 'deepseek', label: 'DeepSeek API' },
    { value: 'openai', label: 'Custom OpenAI API' },
  ],
  vision: [
    { value: 'local', label: 'Local · Ollama' },
    { value: 'nvidia', label: 'NVIDIA API' },
    { value: 'openai', label: 'Custom OpenAI API' },
  ],
  architect: [
    { value: 'nvidia', label: 'NVIDIA API' },
    { value: 'local', label: 'Local · Ollama' },
    { value: 'deterministic', label: 'Deterministic fallback' },
  ],
}

export default function ModelsPanel() {
  const [settings, setSettings] = useState<Settings | null>(null)
  const [catalog, setCatalog] = useState<Catalog>({ local: [], deepseek: [], nvidia: [], claude: [] })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    void Promise.all([fetch(`${API}/settings`), fetch(`${API}/models`)]).then(async ([settingsResponse, modelsResponse]) => {
      setSettings(await settingsResponse.json())
      setCatalog(await modelsResponse.json())
    }).catch(() => setMessage('Could not load model settings.'))
  }, [])

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings((current) => current ? { ...current, [key]: value } : current)
  }

  function modelsFor(backend: string) {
    if (backend === 'local' || backend === 'ollama') return catalog.local
    if (backend === 'nvidia') return catalog.nvidia
    if (backend === 'claude') return catalog.claude
    return catalog.deepseek
  }

  async function save() {
    if (!settings) return
    setSaving(true)
    setMessage(null)
    try {
      const payload = { ...settings }
      delete (payload as Partial<Settings>).api_keys
      const response = await fetch(`${API}/settings`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Could not save settings')
      setSettings(result)
      setMessage('Saved. New generations will use this model configuration.')
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Could not save settings')
    } finally {
      setSaving(false)
    }
  }

  if (!settings) return <div className="panel settings-loading">Loading configured providers and models…</div>

  return <div className="models-layout">
    <section className="agent-settings">
      <div className="settings-section-title"><p className="eyebrow">AGENT ROUTING</p><h2>Choose the right brain for each job</h2><p>Local for cost and privacy; hosted models where quality matters most.</p></div>
      <AgentModel title="Game Designer" description="Design document, mechanics and level arc" backend={settings.designer_backend} options={backendOptions.standard} model={settings.designer_backend === 'local' ? settings.designer_model : settings.designer_remote_model} models={modelsFor(settings.designer_backend)} onBackend={(value) => update('designer_backend', value)} onModel={(value) => update(settings.designer_backend === 'local' ? 'designer_model' : 'designer_remote_model', value)} />
      <AgentModel title="Studio Director" description="QA triage and repair routing" backend={settings.director_backend} options={backendOptions.standard} model={settings.director_backend === 'local' ? settings.director_model : settings.director_remote_model} models={modelsFor(settings.director_backend)} modelPlaceholder={settings.director_backend === 'local' ? 'Inherit Coder model' : undefined} onBackend={(value) => update('director_backend', value)} onModel={(value) => update(settings.director_backend === 'local' ? 'director_model' : 'director_remote_model', value)} />
      <AgentModel title="Systems Architect" description="Blueprint, dependencies and acceptance contracts" backend={settings.architect_backend} options={backendOptions.architect} model={settings.architect_model} models={modelsFor(settings.architect_backend)} onBackend={(value) => update('architect_backend', value)} onModel={(value) => update('architect_model', value)} featured />
      <AgentModel title="Coder" description="Godot gameplay implementation" backend={settings.coder_backend} options={backendOptions.coder} model={settings.coder_backend === 'ollama' ? settings.coder_model : settings.coder_remote_model} models={modelsFor(settings.coder_backend)} onBackend={(value) => update('coder_backend', value)} onModel={(value) => update(settings.coder_backend === 'ollama' ? 'coder_model' : 'coder_remote_model', value)} featured />
      <AgentModel title="Vision QA" description="Screenshot and visual defect review" backend={settings.vision_backend} options={backendOptions.vision} model={settings.vision_backend === 'local' ? settings.vision_model : settings.vision_remote_model} models={modelsFor(settings.vision_backend)} onBackend={(value) => update('vision_backend', value)} onModel={(value) => update(settings.vision_backend === 'local' ? 'vision_model' : 'vision_remote_model', value)} />
      <AgentModel title="Feedback Interpreter" description="Turns playtest notes into revisions" backend={settings.feedback_backend} options={backendOptions.standard} model={settings.feedback_model} models={modelsFor(settings.feedback_backend)} onBackend={(value) => update('feedback_backend', value)} onModel={(value) => update('feedback_model', value)} />
    </section>

    <aside className="provider-settings">
      <section className="panel provider-card">
        <p className="eyebrow">PROVIDERS</p><h2>API connections</h2>
        <label>OpenAI-compatible base URL<input value={settings.openai_base_url} onChange={(event) => update('openai_base_url', event.target.value)} /></label>
        <SecretField label="DeepSeek API key" configured={settings.api_keys.deepseek} value={settings.deepseek_api_key || ''} onChange={(value) => update('deepseek_api_key', value)} />
        <SecretField label="NVIDIA API key" configured={settings.api_keys.nvidia} value={settings.nvidia_api_key || ''} onChange={(value) => update('nvidia_api_key', value)} />
        <SecretField label="Anthropic API key" configured={settings.api_keys.anthropic} value={settings.anthropic_api_key || ''} onChange={(value) => update('anthropic_api_key', value)} />
      </section>
      <section className="panel provider-card">
        <p className="eyebrow">SPECIALIZED MODELS</p><h2>QA and heavy templates</h2>
        <label>Dot-maze local model<ModelInput value={settings.dotmaze_model} models={catalog.local} onChange={(value) => update('dotmaze_model', value)} /></label>
        <label>NVIDIA base URL<input value={settings.vision_base_url} onChange={(event) => update('vision_base_url', event.target.value)} /></label>
        <label>Systems Architect base URL<input value={settings.architect_base_url} onChange={(event) => update('architect_base_url', event.target.value)} /></label>
        <label>Video QA model<ModelInput value={settings.video_model} models={catalog.nvidia} onChange={(value) => update('video_model', value)} /></label>
        <Toggle label="Require gameplay video QA" detail="Capture and review every generated level" checked={settings.video_qa_enabled} onChange={(value) => update('video_qa_enabled', value)} />
        <Toggle label="Release GPU services for Coder" detail="Stops art/audio services before loading large local code models" checked={settings.stop_gpu_services} onChange={(value) => update('stop_gpu_services', value)} />
        <Toggle label="Protected incremental build" detail="Refine each blueprint system separately; every candidate must pass the transactional Godot gate" checked={settings.incremental_build} onChange={(value) => update('incremental_build', value)} />
        <label>Maximum system-builder passes<input type="number" min="1" max="12" value={settings.incremental_max_systems} onChange={(event) => update('incremental_max_systems', Number(event.target.value))} /></label>
      </section>
      <button className="primary settings-save" onClick={() => void save()} disabled={saving}>{saving ? 'Saving…' : 'Save model configuration'}</button>
      {message && <div className="settings-message">{message}</div>}
      <p className="secret-note">Keys are written to the local `.env` file and are never returned to this interface.</p>
    </aside>
  </div>
}

function AgentModel({ title, description, backend, options, model, models, onBackend, onModel, modelPlaceholder, featured }: { title: string; description: string; backend: string; options: { value: string; label: string }[]; model: string; models: string[]; onBackend: (value: string) => void; onModel: (value: string) => void; modelPlaceholder?: string; featured?: boolean }) {
  return <article className={`agent-model-card ${featured ? 'featured' : ''}`}><div className="agent-identity"><span>{title.slice(0, 1)}</span><div><h3>{title}{featured && <b>PRIMARY</b>}</h3><p>{description}</p></div></div><label><small>Backend</small><select value={backend} onChange={(event) => onBackend(event.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label><label><small>Model</small><ModelInput value={model} models={models} placeholder={modelPlaceholder} onChange={onModel} /></label></article>
}

function ModelInput({ value, models, onChange, placeholder }: { value: string; models: string[]; onChange: (value: string) => void; placeholder?: string }) {
  const id = useId()
  return <><input list={id} value={value} placeholder={placeholder || 'Model identifier'} onChange={(event) => onChange(event.target.value)} /><datalist id={id}>{models.map((model) => <option key={model} value={model} />)}</datalist></>
}

function SecretField({ label, configured, value, onChange }: { label: string; configured: boolean; value: string; onChange: (value: string) => void }) {
  return <label>{label}<span className={`key-state ${configured ? 'configured' : ''}`}>{configured ? 'Configured' : 'Missing'}</span><input type="password" autoComplete="off" value={value} placeholder={configured ? 'Leave blank to keep existing key' : 'Paste key'} onChange={(event) => onChange(event.target.value)} /></label>
}

function Toggle({ label, detail, checked, onChange }: { label: string; detail: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="toggle-row settings-toggle"><span><strong>{label}</strong><small>{detail}</small></span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /></label>
}
