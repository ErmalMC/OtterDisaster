function getColor(kind, value) {
  if (kind === 'ph') return value > 6.5 && value < 8 ? 'text-emerald-400' : value > 5.5 ? 'text-amber-400' : 'text-rose-400'
  if (kind === 'cond') return value < 500 ? 'text-emerald-400' : value < 800 ? 'text-amber-400' : 'text-rose-400'
  if (kind === 'turb') return value < 8 ? 'text-emerald-400' : value < 15 ? 'text-amber-400' : 'text-rose-400'
  if (kind === 'ndwi') return value > 0.2 ? 'text-emerald-400' : 'text-amber-400'
  return 'text-emerald-400'
}

function Card({ label, value, unit, detail, tone }) {
  return (
    <article className="rounded-xl border border-slate-700 bg-slate-900 p-4">
      <p className="text-xs uppercase tracking-wider text-slate-400">{label}</p>
      <h3 className={`mt-1 text-3xl font-bold ${tone}`}>{value}</h3>
      <small className="text-xs text-slate-500">{unit}</small>
      <p className={`mt-1 text-sm font-medium ${tone}`}>{detail}</p>
    </article>
  )
}

export default function MetricCards({ current }) {
  const ph = Number(current.ardPh || 0)
  const cond = Number(current.ardConductivity || 0)
  const turbidity = Number(current.satTurbidity || 0)
  const ndwi = Number(current.satNdwi || 0)

  return (
    <section className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">
      <Card
        label="Arduino pH"
        value={ph.toFixed(2)}
        unit="pH units"
        detail={ph > 6.5 && ph < 8 ? 'Normal' : 'Abnormal'}
        tone={getColor('ph', ph)}
      />
      <Card
        label="Conductivity"
        value={cond.toFixed(0)}
        unit="uS/cm"
        detail={cond < 500 ? 'Normal' : 'Elevated'}
        tone={getColor('cond', cond)}
      />
      <Card
        label="Sat. Turbidity"
        value={turbidity.toFixed(1)}
        unit="NTU proxy"
        detail={turbidity < 8 ? 'Clear' : 'Turbid'}
        tone={getColor('turb', turbidity)}
      />
      <Card
        label="NDWI"
        value={ndwi.toFixed(3)}
        unit="index"
        detail={ndwi > 0.2 ? 'Water present' : 'Anomalous'}
        tone={getColor('ndwi', ndwi)}
      />
    </section>
  )
}

