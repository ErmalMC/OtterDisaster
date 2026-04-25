function toSeries(hist, live, key) {
  return [...hist.slice(-40), ...live.slice(-20)].map((row) => Number(row[key] || 0))
}

function minMax(values) {
  if (!values.length) return { min: 0, max: 1 }
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) return { min: min - 1, max: max + 1 }
  return { min, max }
}

function linePath(values, width, height, padding = 12) {
  if (!values.length) return ''
  const { min, max } = minMax(values)
  return values
    .map((value, index) => {
      const x = padding + (index / Math.max(values.length - 1, 1)) * (width - padding * 2)
      const y = height - padding - ((value - min) / (max - min)) * (height - padding * 2)
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}

export default function TimelineChart({ historical, liveFeed }) {
  const turb = toSeries(historical, liveFeed, 'satTurbidity')
  const ph = toSeries(historical, liveFeed, 'ardPh')
  const ndci = toSeries(historical, liveFeed, 'satNdci')
  const cdom = toSeries(historical, liveFeed, 'satCdom')

  return (
    <section className="grid gap-4 xl:grid-cols-2">
      <article className="rounded-xl border border-slate-700 bg-slate-900 p-4">
        <div>
          <h2 className="text-base font-semibold">Turbidity and pH Timeline</h2>
          <p className="text-sm text-slate-400">Historical baseline with live injections</p>
        </div>
        <svg
          viewBox="0 0 640 220"
          role="img"
          aria-label="Turbidity and pH timeline"
          className="mt-3 h-[220px] w-full rounded-lg border border-slate-700 bg-slate-950"
        >
          <path d={linePath(turb, 640, 220)} className="fill-none stroke-sky-400 [stroke-width:2.4]" />
          <path d={linePath(ph, 640, 220)} className="fill-none stroke-emerald-400 [stroke-width:2.4]" />
        </svg>
        <div className="mt-2 flex gap-4 text-sm">
          <span className="text-sky-400">Turbidity</span>
          <span className="text-emerald-400">pH</span>
        </div>
      </article>

      <article className="rounded-xl border border-slate-700 bg-slate-900 p-4">
        <div>
          <h2 className="text-base font-semibold">Satellite Indices</h2>
          <p className="text-sm text-slate-400">NDCI and CDOM trend view</p>
        </div>
        <svg
          viewBox="0 0 640 220"
          role="img"
          aria-label="Satellite indices timeline"
          className="mt-3 h-[220px] w-full rounded-lg border border-slate-700 bg-slate-950"
        >
          <path d={linePath(ndci, 640, 220)} className="fill-none stroke-lime-300 [stroke-width:2.4]" />
          <path d={linePath(cdom, 640, 220)} className="fill-none stroke-amber-300 [stroke-width:2.4]" />
        </svg>
        <div className="mt-2 flex gap-4 text-sm">
          <span className="text-lime-300">NDCI</span>
          <span className="text-amber-300">CDOM</span>
        </div>
      </article>
    </section>
  )
}

