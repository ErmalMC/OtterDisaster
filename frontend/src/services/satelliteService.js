export const SAT_STATUS = {
  OK: 'ok',
  CACHED: 'cached',
  NO_DATA: 'no_data',
  ERROR: 'error',
  UNAUTH: 'unauthenticated',
}

const CACHE_KEY = 'waterguard:satellite-cache'
const CACHE_HOURS = 24

const mockBands = {
  B03: 0.0475,
  B04: 0.0312,
  B07: 0.0211,
  B08: 0.0154,
  B11: 0.0098,
}

function toIsoDate(date) {
  return date.toISOString().slice(0, 10)
}

function readCache() {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed.fetchedAt || !parsed.status) return null
    return parsed
  } catch {
    return null
  }
}

function writeCache(status, payload) {
  localStorage.setItem(
    CACHE_KEY,
    JSON.stringify({
      fetchedAt: new Date().toISOString(),
      status,
      payload,
    }),
  )
}

export function getCachedSatellite() {
  const cached = readCache()
  if (!cached) {
    return { status: SAT_STATUS.UNAUTH, data: {} }
  }

  const ageMs = Date.now() - new Date(cached.fetchedAt).getTime()
  const fresh = ageMs < CACHE_HOURS * 60 * 60 * 1000

  if (cached.status === SAT_STATUS.OK && fresh) {
    return { status: SAT_STATUS.CACHED, data: cached.payload }
  }

  if (cached.status === SAT_STATUS.OK && !fresh) {
    return { status: SAT_STATUS.CACHED, data: cached.payload }
  }

  return { status: cached.status, data: cached.payload ?? {} }
}

export async function fetchSatelliteData() {
  try {
    // Mock-only source for the frontend phase.
    await new Promise((resolve) => {
      setTimeout(resolve, 700)
    })

    const noDataChance = Math.random() < 0.14
    if (noDataChance) {
      const reason = 'Cloud cover above threshold in the last 30 days.'
      writeCache(SAT_STATUS.NO_DATA, { reason })
      return { status: SAT_STATUS.NO_DATA, data: { reason } }
    }

    const payload = {
      imageDate: toIsoDate(new Date(Date.now() - 1000 * 60 * 60 * 24 * 2)),
      B03: mockBands.B03 + (Math.random() - 0.5) * 0.004,
      B04: mockBands.B04 + (Math.random() - 0.5) * 0.004,
      B07: mockBands.B07 + (Math.random() - 0.5) * 0.003,
      B08: mockBands.B08 + (Math.random() - 0.5) * 0.003,
      B11: mockBands.B11 + (Math.random() - 0.5) * 0.002,
    }

    writeCache(SAT_STATUS.OK, payload)
    return { status: SAT_STATUS.OK, data: payload }
  } catch (error) {
    const reason = error instanceof Error ? error.message : 'Unexpected satellite error'
    writeCache(SAT_STATUS.ERROR, { reason })
    return { status: SAT_STATUS.ERROR, data: { reason } }
  }
}

