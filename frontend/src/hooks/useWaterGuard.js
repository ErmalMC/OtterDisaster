import { useEffect, useMemo, useState } from 'react'
import { SAT_STATUS, fetchSatelliteData, getCachedSatellite } from '../services/satelliteService'
import { SENSOR_SITES, generateReading, seedHistorical } from '../services/simulatorService'
import { scoreReading } from '../utils/anomalyDetection'

const LIVE_KEY = 'waterguard:live-feed'
const MAX_LIVE = 120

function enrichReading(reading, baselineRows) {
  const score = scoreReading(reading, baselineRows)
  return {
    ...reading,
    anomalyScore: score.anomalyScore,
    isAnomaly: score.isAnomaly,
    severity: score.severity,
    diagnosis: score.diagnosis,
  }
}

function readStoredLive() {
  try {
    const raw = localStorage.getItem(LIVE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function useWaterGuard() {
  const historical = useMemo(() => {
    const base = seedHistorical(55)
    const scored = []
    base.forEach((row) => {
      const enriched = enrichReading(row, scored.length ? scored : base.slice(0, 12))
      scored.push(enriched)
    })
    return scored
  }, [])

  const [satellite, setSatellite] = useState(() => getCachedSatellite())

  const [liveFeed, setLiveFeed] = useState(() => readStoredLive())
  const [isFetchingSatellite, setIsFetchingSatellite] = useState(false)


  useEffect(() => {
    localStorage.setItem(LIVE_KEY, JSON.stringify(liveFeed))
  }, [liveFeed])

  async function connectSatellite() {
    setIsFetchingSatellite(true)
    const result = await fetchSatelliteData()
    setSatellite(result)
    setIsFetchingSatellite(false)
    return result
  }

  function injectReading({ scenario, rain, temp }) {
    if (satellite.status === SAT_STATUS.NO_DATA) {
      return { ok: false, message: 'No clear satellite image available right now.' }
    }

    const useReal = satellite.status === SAT_STATUS.OK || satellite.status === SAT_STATUS.CACHED
    const reading = generateReading({
      scenario,
      rain,
      temp,
      realBands: useReal ? satellite.data : null,
    })

    const baseline = [...historical, ...liveFeed]
    const enriched = enrichReading(reading, baseline)

    setLiveFeed((prev) => [...prev, enriched].slice(-MAX_LIVE))
    return {
      ok: true,
      reading: enriched,
      dataSourceLabel: useReal ? 'REAL S2' : 'SIMULATED',
    }
  }

  function clearLiveFeed() {
    setLiveFeed([])
  }

  const current = liveFeed.length ? liveFeed[liveFeed.length - 1] : historical[historical.length - 1]
  const liveAlerts = liveFeed.filter((item) => item.isAnomaly)

  return {
    SENSOR_SITES,
    SAT_STATUS,
    historical,
    liveFeed,
    liveAlerts,
    current,
    satellite,
    isFetchingSatellite,
    connectSatellite,
    injectReading,
    clearLiveFeed,
  }
}

