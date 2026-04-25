const FEATURE_KEYS = ['satTurbidity', 'ardPh', 'ardConductivity', 'satNdci', 'satCdom', 'satFdi']

function mean(values) {
  if (!values.length) return 0
  return values.reduce((acc, cur) => acc + cur, 0) / values.length
}

function stdDev(values, avg) {
  if (values.length < 2) return 1
  const variance =
    values.reduce((acc, cur) => {
      const d = cur - avg
      return acc + d * d
    }, 0) / (values.length - 1)
  return Math.sqrt(Math.max(variance, 1e-8))
}

function zScore(value, values) {
  const avg = mean(values)
  const std = stdDev(values, avg)
  return (value - avg) / std
}

function mapSeverity(score, reading) {
  if (score >= 10 || (reading.satTurbidity > 14 && reading.ardConductivity > 850)) {
    return 'CRITICAL'
  }
  if (score >= 7.5) return 'HIGH'
  if (score >= 6) return 'MEDIUM'
  if (score >= 4.5) return 'LOW'
  return 'OK'
}

export function diagnose(reading, severity) {
  if (severity === 'OK') return 'Normal river conditions'
  if (reading.satTurbidity > 12 && (reading.ardPh < 5.5 || reading.ardPh > 9.5) && reading.ardConductivity > 800) {
    return 'CRITICAL: Verified industrial discharge'
  }
  if (reading.satNdci > 0.25 && reading.ardPh > 7.8 && reading.ardConductivity > 500) {
    return 'ALERT: Household sewage or canalization spill'
  }
  if (reading.satCdom > 2.2 && reading.ardPh < 7) {
    return 'ALERT: Organic waste or rotting debris'
  }
  if (reading.satFdi > 0.025 && reading.ardPh > 6.8 && reading.ardPh < 7.6) {
    return 'NOTICE: Floating plastic or litter signal'
  }
  if (reading.rainfallMm > 8 && reading.satTurbidity > 8 && reading.ardConductivity > 600) {
    return 'NOTICE: Urban stormwater runoff pattern'
  }
  return 'Possible seasonal or atmospheric false positive'
}

export function scoreReading(reading, baselineRows) {
  const baseline = baselineRows.slice(-30)
  if (baseline.length < 8) {
    return {
      anomalyScore: 0,
      isAnomaly: false,
      severity: 'OK',
      diagnosis: 'Not enough baseline data yet',
    }
  }

  const score = FEATURE_KEYS.reduce((acc, key) => {
    const values = baseline.map((row) => Number(row[key] || 0))
    return acc + Math.abs(zScore(Number(reading[key] || 0), values))
  }, 0)

  const severity = mapSeverity(score, reading)
  const isAnomaly = severity !== 'OK'

  return {
    anomalyScore: score,
    isAnomaly,
    severity,
    diagnosis: diagnose(reading, severity),
  }
}

