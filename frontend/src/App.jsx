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
  const selectedReading = mapMessage?.kind === 'reading' ? mapMessage.raw : null
  const sidebarCurrent = selectedReading || current

  function handleInject(params) {
    injectReading(params)
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 lg:grid lg:grid-cols-[320px_1fr]">
      <SidebarControls
        satellite={satellite.data}
        satStatus={satellite.status}
        isFetchingSatellite={isFetchingSatellite}
        onConnectSatellite={connectSatellite}
        onInject={handleInject}
        onClear={clearLiveFeed}
        liveCount={liveFeed.length}
        alertCount={liveAlerts.length}
        current={sidebarCurrent}
      />

      <main className="hidden min-h-screen border-l border-slate-200 bg-slate-50 p-4 lg:block">
        <section className="mb-4 px-1 py-2">
          <p className="text-xs uppercase tracking-wider text-slate-500">Message Area</p>
          <div className="mt-2 min-h-16 text-sm text-slate-700">
            {mapMessage ? (
              <div>
                <p className="font-semibold text-slate-900">{mapMessage.title}</p>
                <p className="mt-1 text-slate-700">{mapMessage.subtitle}</p>
                {mapMessage.kind === 'reading' && Number(mapMessage.raw?.ardPh) < 6.5 && (
                  <p className="mt-2 rounded border border-rose-300 bg-rose-50 px-2 py-1 text-rose-700">
                    The water is toxic.
                  </p>
                )}
                <ul className="mt-2 space-y-1 text-xs text-slate-600">
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
