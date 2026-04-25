const SEVERITY_COLOR = {
  OK: '#3fb950',
  LOW: '#7ee787',
  MEDIUM: '#ffa726',
  HIGH: '#ff6b6b',
  CRITICAL: '#ef5350',
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
  const alertPoints = liveFeed.filter((row) => row.isAnomaly).slice(-8)

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
          <div
            key={site.name}
            className={`absolute grid h-6 w-6 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border-2 text-[10px] font-bold ${
              site.active
                ? 'border-emerald-500 bg-emerald-900/40 text-emerald-300'
                : 'border-slate-500 bg-slate-800 text-slate-400'
            }`}
            style={{ left: `${site.x}%`, top: `${site.y}%` }}
            title={site.name}
          >
            <span>{site.active ? 'S' : 'O'}</span>
          </div>
        ))}

        {alertPoints.map((point) => (
          <div
            key={point.id}
            className="absolute h-11 w-11 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 shadow-[0_0_0_8px_rgba(255,255,255,0.07)]"
            style={{
              left: `${46 + seededOffset(`${point.id}-x`, 20)}%`,
              top: `${52 + seededOffset(`${point.id}-y`, 26)}%`,
              borderColor: SEVERITY_COLOR[point.severity] || '#ef5350',
            }}
            title={point.diagnosis}
          />
        ))}
      </div>

      <div className="mt-2 text-sm text-slate-400">
        <span>
          Current status:{' '}
          <strong style={{ color: SEVERITY_COLOR[currentSeverity] || '#3fb950' }}>{currentSeverity}</strong>
        </span>
      </div>
    </section>
  )
}

