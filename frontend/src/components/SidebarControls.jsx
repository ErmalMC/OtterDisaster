import { useMemo, useState } from 'react'

const STATUS_LABELS = {
  ok: 'Live real Sentinel-2 data',
  cached: 'Cached real Sentinel-2 data',
  no_data: 'No clear image - readings blocked',
  error: 'Satellite fetch failed',
  unauthenticated: 'Not connected - simulated data',
}

const STATUS_CLASS = {
  ok: 'border-emerald-700 bg-emerald-950/30 text-emerald-200',
  cached: 'border-sky-700 bg-sky-950/30 text-sky-200',
  no_data: 'border-rose-700 bg-rose-950/30 text-rose-200',
  error: 'border-rose-700 bg-rose-950/30 text-rose-200',
  unauthenticated: 'border-amber-700 bg-amber-950/30 text-amber-200',
}

const SCENARIOS = [
  ['clean', 'Normal river flow'],
  ['sewage', 'Household sewage / canalization'],
  ['debris', 'Floating plastic / litter'],
  ['runoff', 'Urban stormwater runoff'],
  ['industrial', 'Industrial discharge'],
]

function formatStatus(status) {
  return STATUS_LABELS[status] || status
}

export default function SidebarControls({
  satellite,
  satStatus,
  isFetchingSatellite,
  onConnectSatellite,
  onInject,
  onClear,
  liveCount,
  alertCount,
}) {
  const [scenario, setScenario] = useState('clean')
  const [rain, setRain] = useState(2)
  const [temp, setTemp] = useState(18)

  const isInjectBlocked = satStatus === 'no_data'

  const dataSourceBanner = useMemo(() => {
    if (satStatus === 'ok' || satStatus === 'cached') {
      return {
        className: 'source-banner real',
        text: `Next reading will use real Sentinel-2 data from ${satellite.imageDate || 'latest image'}`,
      }
    }
    if (satStatus === 'no_data') {
      return {
        className: 'source-banner blocked',
        text: 'No clear image available. Reading injection is blocked.',
      }
    }
    return {
      className: 'source-banner sim',
      text: 'Satellite not connected. Simulated band values will be used.',
    }
  }, [satStatus, satellite.imageDate])

  function submitInject() {
    onInject({ scenario, rain: Number(rain), temp: Number(temp) })
  }

  return (
    <aside className="space-y-4 border-b border-slate-700 bg-slate-900 p-4 lg:min-h-screen lg:border-b-0 lg:border-r">
      <div>
        <p className="inline-flex rounded border border-sky-500 px-2 py-1 text-xs font-semibold text-sky-300">SAT</p>
        <h1 className="mt-2 text-xl font-semibold">WaterGuard AI</h1>
        <p className="text-sm text-slate-400">Vardar River Monitor</p>
      </div>

      <section className="rounded-xl border border-slate-700 bg-slate-950/40 p-3">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-sky-400">Satellite Connection</h2>
        <div className={`rounded-lg border p-3 text-sm ${STATUS_CLASS[satStatus] || STATUS_CLASS.unauthenticated}`}>
          <strong>{formatStatus(satStatus)}</strong>
          {satellite.imageDate && <p className="mt-1 text-xs text-slate-300">Image: {satellite.imageDate}</p>}
          {(satStatus === 'ok' || satStatus === 'cached') && (
            <p className="mt-1 font-mono text-xs text-slate-300">
              B03={Number(satellite.B03 || 0).toFixed(4)} B04={Number(satellite.B04 || 0).toFixed(4)} B08=
              {Number(satellite.B08 || 0).toFixed(4)}
            </p>
          )}
          {satellite.reason && <p className="mt-1 text-xs text-slate-200">{satellite.reason}</p>}
        </div>
        <button
          type="button"
          onClick={onConnectSatellite}
          disabled={isFetchingSatellite}
          className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm font-medium transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isFetchingSatellite ? 'Fetching satellite data...' : 'Connect & Fetch Real Data'}
        </button>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-950/40 p-3 text-sm text-slate-300">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-sky-400">Live Stats</h2>
        <p>{liveCount} injected readings</p>
        <p>{alertCount} active alerts</p>
      </section>

      <section className="rounded-xl border border-slate-700 bg-slate-950/40 p-3">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-widest text-sky-400">Demo Controls</h2>
        <div
          className={`mb-3 rounded-lg border-l-4 px-3 py-2 text-xs ${
            dataSourceBanner.className.includes('real')
              ? 'border-emerald-500 bg-emerald-950/30 text-emerald-200'
              : dataSourceBanner.className.includes('blocked')
                ? 'border-rose-500 bg-rose-950/30 text-rose-200'
                : 'border-amber-500 bg-amber-950/30 text-amber-200'
          }`}
        >
          {dataSourceBanner.text}
        </div>
        <label className="mb-3 block text-sm text-slate-300">
          Pollution Scenario
          <select
            value={scenario}
            onChange={(event) => setScenario(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"
          >
            {SCENARIOS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="mb-3 block text-sm text-slate-300">
          Rainfall (mm)
          <input
            type="range"
            min="0"
            max="30"
            step="0.5"
            value={rain}
            onChange={(event) => setRain(event.target.value)}
            className="mt-1 w-full accent-sky-500"
          />
          <span className="text-xs text-slate-400">{Number(rain).toFixed(1)}</span>
        </label>
        <label className="mb-3 block text-sm text-slate-300">
          Air Temperature (C)
          <input
            type="range"
            min="0"
            max="40"
            step="1"
            value={temp}
            onChange={(event) => setTemp(event.target.value)}
            className="mt-1 w-full accent-sky-500"
          />
          <span className="text-xs text-slate-400">{Number(temp).toFixed(0)}</span>
        </label>
        <button
          type="button"
          onClick={submitInject}
          disabled={isInjectBlocked}
          className="mb-2 w-full rounded-lg bg-sky-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          Inject Reading
        </button>
        <button
          type="button"
          onClick={onClear}
          className="w-full rounded-lg border border-rose-700 bg-rose-950/40 px-3 py-2 text-sm font-medium text-rose-200 transition hover:bg-rose-900/50"
        >
          Clear Live Feed
        </button>
      </section>
    </aside>
  )
}

