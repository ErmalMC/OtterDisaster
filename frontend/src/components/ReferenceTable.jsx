const ROWS = [
  {
    source: 'Household Sewage',
    satellite: 'NDCI > 0.25 (algae bloom)',
    arduino: 'pH > 7.8',
    conductivity: '> 500 uS/cm',
  },
  {
    source: 'Organic Waste',
    satellite: 'CDOM > 2.2 (brown water)',
    arduino: 'pH < 7.0',
    conductivity: 'Moderate',
  },
  {
    source: 'Floating Plastic',
    satellite: 'FDI > 0.025 (NIR anomaly)',
    arduino: 'pH near normal',
    conductivity: 'Normal',
  },
  {
    source: 'Urban Runoff',
    satellite: 'High turbidity',
    arduino: 'Slightly low pH',
    conductivity: '> 600 uS/cm + rain',
  },
  {
    source: 'Industrial',
    satellite: 'Turbidity > 12 and high LST',
    arduino: 'pH < 5.5 or > 9.5',
    conductivity: '> 800 uS/cm',
  },
]

export default function ReferenceTable() {
  return (
    <section className="rounded-xl border border-slate-700 bg-slate-900 p-4">
      <div>
        <h2 className="text-base font-semibold">Diagnosis Reference Table</h2>
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="border-b border-slate-700 px-2 py-2 text-left font-semibold text-slate-400">Source</th>
              <th className="border-b border-slate-700 px-2 py-2 text-left font-semibold text-slate-400">Satellite Signal</th>
              <th className="border-b border-slate-700 px-2 py-2 text-left font-semibold text-slate-400">Arduino Signal</th>
              <th className="border-b border-slate-700 px-2 py-2 text-left font-semibold text-slate-400">Conductivity</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr key={row.source}>
                <td className="border-b border-slate-800 px-2 py-2">{row.source}</td>
                <td className="border-b border-slate-800 px-2 py-2">{row.satellite}</td>
                <td className="border-b border-slate-800 px-2 py-2">{row.arduino}</td>
                <td className="border-b border-slate-800 px-2 py-2">{row.conductivity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

