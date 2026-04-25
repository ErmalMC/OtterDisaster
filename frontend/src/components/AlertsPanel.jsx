function formatTime(iso) {
  return new Date(iso).toLocaleString()
}

function SourceTag({ source }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
        source === 'REAL' ? 'border-emerald-500 text-emerald-300' : 'border-amber-500 text-amber-300'
      }`}
    >
      {source === 'REAL' ? 'REAL S2' : 'SIM'}
    </span>
  )
}

function severityStyle(severity) {
  if (severity === 'CRITICAL') return 'border-l-rose-500'
  if (severity === 'HIGH') return 'border-l-orange-400'
  if (severity === 'MEDIUM') return 'border-l-amber-400'
  if (severity === 'LOW') return 'border-l-lime-400'
  return 'border-l-emerald-500'
}

export default function AlertsPanel({ liveFeed, historical }) {
  const liveItems = [...liveFeed].reverse()
  const histItems = [...historical].filter((row) => row.isAnomaly).slice(-6).reverse()
  const items = [...liveItems, ...histItems].slice(0, 10)

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-4">
      <div>
        <h2 className="text-base font-semibold">Alert Feed</h2>
        <p className="text-sm text-slate-400">Newest live and historical detections</p>
      </div>

      <div className="mt-3 grid max-h-[330px] gap-2 overflow-auto">
        {!items.length && <p className="text-sm text-slate-400">No anomalies detected yet.</p>}

        {items.map((item) => (
          <article
            className={`rounded-lg border border-slate-700 border-l-4 bg-slate-950/60 p-3 text-sm ${severityStyle(item.severity || 'OK')}`}
            key={item.id}
          >
            <header className="flex flex-wrap items-center gap-2">
              <strong>{formatTime(item.timestamp)}</strong>
              <span className="rounded-full border border-slate-600 px-2 py-0.5 text-[10px] font-semibold">
                {item.severity || 'OK'}
              </span>
              <SourceTag source={item.dataSource || 'SIMULATED'} />
            </header>
            <p className="my-2">{item.diagnosis}</p>
            <small className="text-slate-400">
              pH {Number(item.ardPh).toFixed(2)} | Cond {Number(item.ardConductivity).toFixed(0)} uS/cm
            </small>
          </article>
        ))}
      </div>
    </section>
  )
}

