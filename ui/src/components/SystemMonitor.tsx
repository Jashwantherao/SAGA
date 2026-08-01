import { useEffect, useState } from 'react'
import { getJSON } from '../api'
import type { SystemStats } from '../types'

function Meter({ label, value, max, display, hot }: { label: string; value: number; max: number; display: string; hot?: boolean }) {
  const percent = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="meter">
      <div className="meter-head"><span>{label}</span><b className={hot ? 'hot' : ''}>{display}</b></div>
      <div className="meter-track"><i style={{ width: `${percent}%` }} className={hot ? 'hot' : ''} /></div>
    </div>
  )
}

export default function SystemMonitor() {
  const [stats, setStats] = useState<SystemStats | null>(null)

  useEffect(() => {
    let disposed = false
    const load = () =>
      getJSON<SystemStats>('/system')
        .then((data) => { if (!disposed) setStats(data) })
        .catch(() => undefined)
    void load()
    const timer = window.setInterval(load, 5000)
    return () => { disposed = true; window.clearInterval(timer) }
  }, [])

  if (!stats) return null
  const gpu = stats.gpu
  const vramUsed = gpu?.memory_used_mb ?? 0
  const vramTotal = gpu?.memory_total_mb ?? 0
  return (
    <div className="system-monitor" title={gpu?.name || 'System monitor'}>
      <div className="system-monitor-title">
        <span>{gpu ? gpu.name.replace('NVIDIA GeForce ', '') : 'System'}</span>
        {gpu?.temperature != null && <b className={gpu.temperature >= 80 ? 'hot' : ''}>{Math.round(gpu.temperature)}°C</b>}
      </div>
      {gpu && vramTotal > 0 && (
        <Meter
          label="VRAM"
          value={vramUsed}
          max={vramTotal}
          display={`${(vramUsed / 1024).toFixed(1)}/${(vramTotal / 1024).toFixed(0)} GB`}
          hot={vramUsed / vramTotal > 0.92}
        />
      )}
      {gpu?.utilization != null && <Meter label="GPU" value={gpu.utilization} max={100} display={`${Math.round(gpu.utilization)}%`} />}
      <Meter label="CPU" value={stats.cpu_percent} max={100} display={`${Math.round(stats.cpu_percent)}%`} />
      <Meter
        label="RAM"
        value={stats.memory_used}
        max={stats.memory_total}
        display={`${(stats.memory_used / 1_073_741_824).toFixed(0)}/${(stats.memory_total / 1_073_741_824).toFixed(0)} GB`}
        hot={stats.memory_percent > 92}
      />
    </div>
  )
}
