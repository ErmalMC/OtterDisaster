const FDI_RATIO = (842 - 665) / (1610 - 665)

export const SENSOR_SITES = [
  { name: 'Sensor Alpha - Stone Bridge', x: 46, y: 52, active: true },
  { name: 'Sensor Beta - Matka Canyon', x: 18, y: 70, active: false },
  { name: 'Sensor Gamma - Downstream East', x: 84, y: 40, active: false },
]

const BAND_PROFILES = {
  clean: [
    [0.045, 0.004],
    [0.025, 0.003],
    [0.018, 0.002],
    [0.012, 0.002],
    [0.008, 0.001],
  ],
  sewage: [
    [0.06, 0.006],
    [0.022, 0.003],
    [0.055, 0.008],
    [0.04, 0.005],
    [0.012, 0.002],
  ],
  debris: [
    [0.05, 0.005],
    [0.03, 0.004],
    [0.025, 0.003],
    [0.08, 0.015],
    [0.055, 0.01],
  ],
  runoff: [
    [0.08, 0.01],
    [0.075, 0.01],
    [0.035, 0.005],
    [0.045, 0.008],
    [0.02, 0.003],
  ],
  industrial: [
    [0.12, 0.015],
    [0.15, 0.02],
    [0.06, 0.01],
    [0.055, 0.01],
    [0.03, 0.005],
  ],
}

const ARDUINO_PROFILES = {
  clean: [7.2, 0.15, 320, 24],
  sewage: [8.3, 0.3, 650, 62],
  debris: [7.1, 0.2, 360, 30],
  runoff: [6.8, 0.3, 780, 84],
  industrial: [4.2, 0.8, 1100, 120],
}

function randNormal(mean, std) {
  const u = 1 - Math.random()
  const v = Math.random()
  const z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v)
  return mean + std * z
}

function computeIndices(B3, B4, B7, B8, B11) {
  const eps = 1e-9
  const ndwi = (B3 - B8) / (B3 + B8 + eps)
  const ndci = (B7 - B4) / (B7 + B4 + eps)
  const cdom = B3 / (B4 + eps)
  const fdi = B8 - (B4 + (B11 - B4) * FDI_RATIO)
  const turbidity = (B4 / (B3 + eps)) * 100
  return { ndwi, ndci, cdom, fdi, turbidity }
}

function getBandValues(scenario, realBands) {
  if (realBands) {
    return {
      B3: Math.max(0.001, Number(realBands.B03 || 0.045) + randNormal(0, 0.001)),
      B4: Math.max(0.001, Number(realBands.B04 || 0.025) + randNormal(0, 0.001)),
      B7: Math.max(0.001, Number(realBands.B07 || 0.018) + randNormal(0, 0.001)),
      B8: Math.max(0.001, Number(realBands.B08 || 0.012) + randNormal(0, 0.001)),
      B11: Math.max(0.001, Number(realBands.B11 || 0.008) + randNormal(0, 0.001)),
      dataSource: 'REAL',
    }
  }

  const [[b3m, b3s], [b4m, b4s], [b7m, b7s], [b8m, b8s], [b11m, b11s]] = BAND_PROFILES[scenario]
  return {
    B3: randNormal(b3m, b3s),
    B4: randNormal(b4m, b4s),
    B7: randNormal(b7m, b7s),
    B8: randNormal(b8m, b8s),
    B11: randNormal(b11m, b11s),
    dataSource: 'SIMULATED',
  }
}

export function generateReading({ scenario, rain, temp, realBands, timestamp }) {
  const sat = getBandValues(scenario, realBands)
  const indices = computeIndices(sat.B3, sat.B4, sat.B7, sat.B8, sat.B11)
  const [phMean, phStd, condMean, condStd] = ARDUINO_PROFILES[scenario]

  const ardPh = randNormal(phMean, phStd)
  const conductivity = randNormal(condMean, condStd) + rain * 3
  const lst = temp + randNormal(0, 1.5) + (scenario === 'industrial' ? 5 : 0)

  return {
    id: crypto.randomUUID(),
    timestamp: timestamp || new Date().toISOString(),
    scenario,
    dataSource: sat.dataSource,
    satNdwi: indices.ndwi,
    satNdci: indices.ndci,
    satCdom: indices.cdom,
    satFdi: indices.fdi,
    satTurbidity: indices.turbidity,
    satLst: lst,
    rainfallMm: rain,
    ardPh,
    ardConductivity: conductivity,
  }
}

export function seedHistorical(weeks = 55) {
  const points = []
  const now = Date.now()
  const weekMs = 7 * 24 * 60 * 60 * 1000

  for (let i = 0; i < weeks; i += 1) {
    const idx = i / Math.max(1, weeks - 1)
    const seasonal = Math.sin(idx * Math.PI * 2)
    const rain = Math.max(0, 3 + Math.abs(seasonal) * 6 + randNormal(0, 1.2))
    const temp = 12 + 14 * seasonal + randNormal(0, 1.4)

    let scenario = 'clean'
    if (i >= 14 && i <= 16) scenario = 'runoff'
    if (i >= 24 && i <= 27) scenario = 'sewage'
    if (i >= 31 && i <= 33) scenario = 'debris'
    if (i >= 50 && i <= 54) scenario = 'industrial'

    points.push(
      generateReading({
        scenario,
        rain,
        temp,
        timestamp: new Date(now - (weeks - i) * weekMs).toISOString(),
      }),
    )
  }

  return points
}

