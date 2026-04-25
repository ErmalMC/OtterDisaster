import { useState } from 'react'
import SidebarControls from './components/SidebarControls'
import RiverMap from './components/RiverMap'
import { useWaterGuard } from './hooks/useWaterGuard'

function App() {
  const {
    SENSOR_SITES,
    liveFeed,
    liveAlerts,
    current,
    satellite,
    isFetchingSatellite,
    connectSatellite,
    injectReading,
    clearLiveFeed,
  } = useWaterGuard()
  const [mapMessage, setMapMessage] = useState(null)

  function handleInject(params) {
    injectReading(params)
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 lg:grid lg:grid-cols-[320px_1fr]">
      <SidebarControls
        satellite={satellite.data}
        satStatus={satellite.status}
        isFetchingSatellite={isFetchingSatellite}
        onConnectSatellite={connectSatellite}
        onInject={handleInject}
        onClear={clearLiveFeed}
        liveCount={liveFeed.length}
        alertCount={liveAlerts.length}
      />

      <main className="hidden min-h-screen border-l border-slate-800/80 bg-slate-950 p-4 lg:block">
        <section className="mb-4 rounded-xl border border-slate-700 bg-slate-900 p-4">
          <p className="text-xs uppercase tracking-wider text-slate-400">Message Area</p>
          <div className="mt-2 min-h-16 rounded-lg border border-dashed border-slate-700 bg-slate-950/70 p-3 text-sm text-slate-400">
            {mapMessage ? (
              <div>
                <p className="font-semibold text-slate-100">{mapMessage.title}</p>
                <p className="mt-1 text-slate-300">{mapMessage.subtitle}</p>
                <ul className="mt-2 space-y-1 text-xs text-slate-400">
                  {mapMessage.details.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : (
              'Click a dot on the map to show its data here.'
            )}
          </div>
        </section>

        <RiverMap
          sites={SENSOR_SITES}
          liveFeed={liveFeed}
          currentSeverity={current?.severity || 'OK'}
          onPointSelect={setMapMessage}
        />
      </main>
    </div>
  )
}

export default App
