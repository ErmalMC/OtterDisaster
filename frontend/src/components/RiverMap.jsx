import { useState } from 'react'
import { CircleMarker, MapContainer, TileLayer, useMapEvents } from 'react-leaflet'

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

export default function RiverMap({ sites, liveFeed, onPointSelect }) {
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
    <MapContainer center={MAP_CENTER} zoom={13} className="h-[500px] w-full" scrollWheelZoom>
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
  )
}

