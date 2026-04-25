import { useMemo, useState } from 'react'
import SidebarControls from './components/SidebarControls'
import MetricCards from './components/MetricCards'
import RiverMap from './components/RiverMap'
import AlertsPanel from './components/AlertsPanel'
import TimelineChart from './components/TimelineChart'
import ReferenceTable from './components/ReferenceTable'
import { useWaterGuard } from './hooks/useWaterGuard'

function severityBadge(severity) {
  const styles = {
    OK: 'border-emerald-500/60 text-emerald-300 bg-emerald-900/20',
    LOW: 'border-lime-500/60 text-lime-300 bg-lime-900/20',
    MEDIUM: 'border-amber-500/60 text-amber-300 bg-amber-900/20',
    HIGH: 'border-orange-500/60 text-orange-300 bg-orange-900/20',
    CRITICAL: 'border-rose-500/60 text-rose-300 bg-rose-900/20',
  }
  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-semibold tracking-wide ${styles[severity] || styles.OK}`}
    >
      {severity}
    </span>
  )
}

function satelliteBanner(satellite) {
  if (satellite.status === 'no_data') {
    return { tone: 'error', text: `No clear Sentinel-2 imagery available. ${satellite.data.reason || ''}` }
  }
  if (satellite.status === 'error') {
    return { tone: 'error', text: `Satellite API error. ${satellite.data.reason || ''}` }
  }
  if (satellite.status === 'ok' || satellite.status === 'cached') {
    const note = satellite.status === 'ok' ? 'freshly fetched' : 'served from cache'
    return {
      tone: 'success',
      text: `Real Sentinel-2 data active (${note}) - image ${satellite.data.imageDate || '?'} | B03 ${Number(
        satellite.data.B03 || 0,
      ).toFixed(4)} | B04 ${Number(satellite.data.B04 || 0).toFixed(4)} | B08 ${Number(satellite.data.B08 || 0).toFixed(4)}`,
    }
  }
  return {
    tone: 'warn',
    text: 'Satellite not connected. Live injections use simulated satellite band values.',
  }
}

function App() {
  const {
    SENSOR_SITES,
    historical,
    liveFeed,
    liveAlerts,
    current,
    satellite,
    isFetchingSatellite,
    connectSatellite,
    injectReading,
    clearLiveFeed,
  } = useWaterGuard()

  const [notice, setNotice] = useState('')

  const banner = useMemo(() => satelliteBanner(satellite), [satellite])

  function handleInject(params) {
    const result = injectReading(params)
    if (!result.ok) {
      setNotice(result.message)
      return
    }
    setNotice(`${result.dataSourceLabel}: ${result.reading.diagnosis}`)
  }

  function handleSatelliteConnect() {
    connectSatellite()
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 lg:grid lg:grid-cols-[320px_1fr]">
      <SidebarControls
        satellite={satellite.data}
        satStatus={satellite.status}
        isFetchingSatellite={isFetchingSatellite}
        onConnectSatellite={handleSatelliteConnect}
        onInject={handleInject}
        onClear={clearLiveFeed}
        liveCount={liveFeed.length}
        alertCount={liveAlerts.length}
      />

      <main className="space-y-4 p-4">
        <header className="rounded-xl border border-slate-700 bg-slate-900 p-4 md:flex md:items-start md:justify-between">
          <div>
            <h1 className="text-xl font-semibold md:text-2xl">Vardar River - Real-Time Water Quality</h1>
            <p className="mt-1 text-sm text-slate-400">Skopje, North Macedonia | Sentinel-2 + IoT simulation fusion</p>
          </div>
          <div className="mt-3 flex gap-6 md:mt-0">
            <div className="flex flex-col items-end gap-1">
              <small className="text-xs uppercase tracking-wider text-slate-400">Current Status</small>
              {severityBadge(current.severity || 'OK')}
            </div>
            <div className="flex flex-col items-end gap-1">
              <small className="text-xs uppercase tracking-wider text-slate-400">Last Update</small>
              <strong className="text-sm">{new Date().toLocaleTimeString()}</strong>
            </div>
          </div>
        </header>

        <section
          className={`rounded-xl border px-4 py-3 text-sm ${
            banner.tone === 'success'
              ? 'border-emerald-700 bg-emerald-950/30 text-emerald-200'
              : banner.tone === 'warn'
                ? 'border-amber-700 bg-amber-950/30 text-amber-200'
                : 'border-rose-700 bg-rose-950/30 text-rose-200'
          }`}
        >
          {banner.text}
        </section>
        {notice && (
          <section className="rounded-xl border border-sky-700 bg-sky-950/30 px-4 py-3 text-sm text-sky-200">
            {notice}
          </section>
        )}

        <MetricCards current={current} />

        <section className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <RiverMap sites={SENSOR_SITES} liveFeed={liveFeed} currentSeverity={current.severity || 'OK'} />
          <AlertsPanel liveFeed={liveFeed} historical={historical} />
        </section>

        <section className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm">
          <strong>{current.diagnosis}</strong>
          <span className="text-slate-300">
            pH {Number(current.ardPh).toFixed(2)} | Conductivity {Number(current.ardConductivity).toFixed(0)} uS/cm | Turbidity{' '}
            {Number(current.satTurbidity).toFixed(1)}
          </span>
        </section>

        <TimelineChart historical={historical} liveFeed={liveFeed} />
        <ReferenceTable />
      </main>
    </div>
  )
}

export default App
