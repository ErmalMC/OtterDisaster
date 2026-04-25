import { useState } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, useMapEvents } from 'react-leaflet'

const SEVERITY_COLOR = {
  OK: '#3fb950',
  LOW: '#7ee787',
  MEDIUM: '#ffa726',
  HIGH: '#ff6b6b',
  CRITICAL: '#ef5350',
}

const MAP_CENTER = [42.0014, 21.4343]
const MAP_BOUNDS = {
  north: 42.013,
  south: 41.992,
  west: 21.383,
  east: 21.486,
}

const VARDAR_PATH = [
  [42.01, 21.385],
  [42.008, 21.398],
  [42.006, 21.41],
  [42.004, 21.422],
  [42.002, 21.433],
  [42.001, 21.443],
  [41.999, 21.455],
  [41.997, 21.468],
  [41.996, 21.48],
]

function seededOffset(seed, span) {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  const normalized = (hash % 1000) / 1000
  return (normalized - 0.5) * span
}

function toSiteLatLng(site) {
  if (typeof site.lat === 'number' && typeof site.lon === 'number') {
    return [site.lat, site.lon]
  }
  const x = Number(site.x || 50) / 100
  const y = Number(site.y || 50) / 100
  const lat = MAP_BOUNDS.north - y * (MAP_BOUNDS.north - MAP_BOUNDS.south)
  const lon = MAP_BOUNDS.west + x * (MAP_BOUNDS.east - MAP_BOUNDS.west)
  return [lat, lon]
}

function MapClearSelection({ onClear }) {
  useMapEvents({
    click() {
      onClear()
    },
  })
  return null
}

export default function RiverMap({ sites, liveFeed, currentSeverity, onPointSelect }) {
  const [selected, setSelected] = useState(null)

  const mapPoints = liveFeed.slice(-14).map((point) => ({
    ...point,
    lat: MAP_CENTER[0] + seededOffset(`${point.id}-lat`, 0.006),
    lon: MAP_CENTER[1] + seededOffset(`${point.id}-lon`, 0.01),
  }))

  function formatDate(iso) {
    return new Date(iso).toLocaleString()
  }

  function buildSitePayload(site) {
    return {
      kind: 'site',
      id: site.name,
      title: site.name,
      subtitle: site.active ? 'Online monitoring node' : 'Offline planned node',
      details: ['Type: Sensor point', `Status: ${site.active ? 'Active' : 'Offline'}`],
      raw: site,
    }
  }

  function buildReadingPayload(point) {
    return {
      kind: 'reading',
      id: point.id,
      title: `${point.severity || 'OK'} reading`,
      subtitle: point.diagnosis,
      details: [
        `Time: ${formatDate(point.timestamp)}`,
        `Source: ${point.dataSource || 'SIMULATED'}`,
        `pH: ${Number(point.ardPh).toFixed(2)}`,
        `Conductivity: ${Number(point.ardConductivity).toFixed(0)} uS/cm`,
        `Turbidity: ${Number(point.satTurbidity).toFixed(1)}`,
      ],
      raw: point,
    }
  }

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-4">
      <div>
        <h2 className="text-base font-semibold">Vardar River Map</h2>
        <p className="text-sm text-slate-400">Sensor coverage and anomaly hotspots</p>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-slate-700">
        <MapContainer center={MAP_CENTER} zoom={13} className="h-[360px] w-full" scrollWheelZoom>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MapClearSelection
            onClear={() => {
              setSelected(null)
              if (typeof onPointSelect === 'function') {
                onPointSelect(null)
              }
            }}
          />

          <Polyline positions={VARDAR_PATH} pathOptions={{ color: '#4fc3f7', weight: 4, opacity: 0.75 }} />

          {sites.map((site) => {
            const [lat, lon] = toSiteLatLng(site)
            const isSelected = selected?.kind === 'site' && selected?.id === site.name
            return (
              <CircleMarker
                key={site.name}
                center={[lat, lon]}
                radius={isSelected ? 9 : 7}
                bubblingMouseEvents={false}
                eventHandlers={{
                  click: () => {
                    const isSame = selected?.kind === 'site' && selected?.id === site.name
                    const payload = isSame ? null : buildSitePayload(site)
                    setSelected(payload)
                    if (typeof onPointSelect === 'function') {
                      onPointSelect(payload)
                    }
                  },
                }}
                pathOptions={{
                  color: site.active ? '#10b981' : '#94a3b8',
                  fillColor: site.active ? '#34d399' : '#94a3b8',
                  fillOpacity: 0.9,
                  weight: 2,
                }}
              />
            )
          })}

          {mapPoints.map((point) => {
            const isSelected = selected?.kind === 'reading' && selected?.id === point.id
            return (
              <CircleMarker
                key={point.id}
                center={[point.lat, point.lon]}
                radius={isSelected ? 8 : point.isAnomaly ? 7 : 5}
                bubblingMouseEvents={false}
                eventHandlers={{
                  click: () => {
                    const isSame = selected?.kind === 'reading' && selected?.id === point.id
                    const payload = isSame ? null : buildReadingPayload(point)
                    setSelected(payload)
                    if (typeof onPointSelect === 'function') {
                      onPointSelect(payload)
                    }
                  },
                }}
                pathOptions={{
                  color: SEVERITY_COLOR[point.severity] || SEVERITY_COLOR.OK,
                  fillColor: SEVERITY_COLOR[point.severity] || SEVERITY_COLOR.OK,
                  fillOpacity: point.isAnomaly ? 0.95 : 0.75,
                  weight: 2,
                }}
              />
            )
          })}
        </MapContainer>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-slate-400">
        <span>
          Current status:{' '}
          <strong style={{ color: SEVERITY_COLOR[currentSeverity] || '#3fb950' }}>{currentSeverity}</strong>
        </span>
        <span className="text-xs">Click a dot to send its data to the top message area.</span>
      </div>
    </section>
  )
}

