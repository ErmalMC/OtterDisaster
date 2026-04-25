import { useState } from 'react'

const SEVERITY_COLOR = {
  OK: '#3fb950',
  LOW: '#7ee787',
  MEDIUM: '#ffa726',
  HIGH: '#ff6b6b',
  CRITICAL: '#ef5350',
}

const SEVERITY_DOT = {
  OK: 'bg-emerald-400 ring-emerald-400/30',
  LOW: 'bg-lime-300 ring-lime-300/30',
  MEDIUM: 'bg-amber-300 ring-amber-300/30',
  HIGH: 'bg-orange-300 ring-orange-300/30',
  CRITICAL: 'bg-rose-400 ring-rose-400/40',
}

function seededOffset(seed, span) {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  }
  const normalized = (hash % 1000) / 1000
  return (normalized - 0.5) * span
}

export default function RiverMap({ sites, liveFeed, currentSeverity }) {
  const [hovered, setHovered] = useState(null)

  const mapPoints = liveFeed.slice(-14).map((point) => ({
    ...point,
    left: 46 + seededOffset(`${point.id}-x`, 20),
    top: 52 + seededOffset(`${point.id}-y`, 26),
  }))

  const tooltipLeft = hovered ? Math.min(88, Math.max(12, hovered.left)) : 50
  const tooltipTop = hovered ? (hovered.top > 24 ? hovered.top - 4 : hovered.top + 8) : 50
  const tooltipFromTop = hovered ? hovered.top <= 24 : false

  function formatDate(iso) {
    return new Date(iso).toLocaleString()
  }

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-4">
      <div>
        <h2 className="text-base font-semibold">Vardar River Map</h2>
        <p className="text-sm text-slate-400">Sensor coverage and anomaly hotspots</p>
      </div>

      <div className="relative mt-3 min-h-[280px] overflow-hidden rounded-xl border border-slate-700 bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
        <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full" aria-hidden="true">
          <path
            d="M2,22 C18,25 28,34 42,38 C57,43 64,59 82,65 C90,67 97,76 99,88"
            fill="none"
            stroke="#4fc3f7"
            strokeWidth="4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>

        {sites.map((site) => (
          <button
            key={site.name}
            type="button"
            className={`absolute h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-4 transition ${
              site.active
                ? 'bg-emerald-400 ring-emerald-400/25'
                : 'bg-slate-400 ring-slate-400/20'
            }`}
            style={{ left: `${site.x}%`, top: `${site.y}%` }}
            onMouseEnter={() =>
              setHovered({
                type: 'site',
                left: site.x,
                top: site.y,
                title: site.name,
                subtitle: site.active ? 'Online monitoring node' : 'Offline planned node',
                details: ['Type: Sensor point', `Status: ${site.active ? 'Active' : 'Offline'}`],
              })
            }
            onMouseLeave={() => setHovered(null)}
            onFocus={() =>
              setHovered({
                type: 'site',
                left: site.x,
                top: site.y,
                title: site.name,
                subtitle: site.active ? 'Online monitoring node' : 'Offline planned node',
                details: ['Type: Sensor point', `Status: ${site.active ? 'Active' : 'Offline'}`],
              })
            }
            onBlur={() => setHovered(null)}
            aria-label={site.name}
          >
            <span className="sr-only">{site.name}</span>
          </button>
        ))}

        {mapPoints.map((point) => (
          <button
            key={point.id}
            type="button"
            className={`absolute -translate-x-1/2 -translate-y-1/2 rounded-full ring-8 transition ${
              SEVERITY_DOT[point.severity] || SEVERITY_DOT.OK
            } ${point.isAnomaly ? 'h-4 w-4 shadow-[0_0_0_2px_rgba(255,255,255,0.3)]' : 'h-3 w-3 opacity-80'}`}
            style={{
              left: `${point.left}%`,
              top: `${point.top}%`,
            }}
            onMouseEnter={() =>
              setHovered({
                type: 'reading',
                left: point.left,
                top: point.top,
                title: `${point.severity || 'OK'} reading`,
                subtitle: point.diagnosis,
                details: [
                  `Time: ${formatDate(point.timestamp)}`,
                  `Source: ${point.dataSource || 'SIMULATED'}`,
                  `pH: ${Number(point.ardPh).toFixed(2)}`,
                  `Conductivity: ${Number(point.ardConductivity).toFixed(0)} uS/cm`,
                  `Turbidity: ${Number(point.satTurbidity).toFixed(1)}`,
                ],
              })
            }
            onMouseLeave={() => setHovered(null)}
            onFocus={() =>
              setHovered({
                type: 'reading',
                left: point.left,
                top: point.top,
                title: `${point.severity || 'OK'} reading`,
                subtitle: point.diagnosis,
                details: [
                  `Time: ${formatDate(point.timestamp)}`,
                  `Source: ${point.dataSource || 'SIMULATED'}`,
                  `pH: ${Number(point.ardPh).toFixed(2)}`,
                  `Conductivity: ${Number(point.ardConductivity).toFixed(0)} uS/cm`,
                  `Turbidity: ${Number(point.satTurbidity).toFixed(1)}`,
                ],
              })
            }
            onBlur={() => setHovered(null)}
            aria-label={`${point.severity || 'OK'} reading`}
          />
        ))}

        {hovered && (
          <div
            className="pointer-events-none absolute z-20 w-64 -translate-x-1/2 rounded-lg border border-slate-600 bg-slate-900/95 p-3 text-xs shadow-xl"
            style={{
              left: `${tooltipLeft}%`,
              top: `${tooltipTop}%`,
              transform: tooltipFromTop ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
            }}
          >
            <p className="font-semibold text-slate-100">{hovered.title}</p>
            <p className="mt-1 text-slate-300">{hovered.subtitle}</p>
            <ul className="mt-2 space-y-1 text-slate-400">
              {hovered.details.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-slate-400">
        <span>
          Current status:{' '}
          <strong style={{ color: SEVERITY_COLOR[currentSeverity] || '#3fb950' }}>{currentSeverity}</strong>
        </span>
        <span className="text-xs">Hover a dot to inspect site or reading data.</span>
      </div>
    </section>
  )
}

