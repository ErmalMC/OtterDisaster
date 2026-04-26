const DEFAULT_API_BASE_URL = "/api";

function normalizeBaseUrl(baseUrl) {
  const value = (baseUrl ?? DEFAULT_API_BASE_URL).toString().trim();
  if (!value) {
    return DEFAULT_API_BASE_URL;
  }
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function buildApiUrl(path) {
  const baseUrl = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${suffix}`;
}

async function requestJson(path, { method = "GET", body } = {}) {
  const response = await fetch(buildApiUrl(path), {
    method,
    headers:
      body === undefined
        ? undefined
        : {
            "Content-Type": "application/json",
          },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const contentType = response.headers.get("content-type") || "";
  let payload = null;

  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else {
    const text = await response.text();
    payload = text.length > 0 ? text : null;
  }

  if (!response.ok) {
    const message =
      (payload && typeof payload === "object" && (payload.error || payload.message)) ||
      (typeof payload === "string" ? payload : `Request failed with status ${response.status}`);
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

export function getApiBaseUrl() {
  return normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);
}

export function fetchHealth() {
  return requestJson("/health");
}

export function predictWaterQuality(sensorReading) {
  return requestJson("/predict", {
    method: "POST",
    body: sensorReading,
  });
}

export function reloadSatelliteData() {
  return requestJson("/reload_satellite", {
    method: "POST",
  });
}

export function fetchArduinoReading() {
  return requestJson("/arduino", { method: "POST" });
}

export function fetchHistory(limit = 100) {
  return requestJson(`/history?limit=${limit}`);
}

export function createPredictionStream(onMessage, onError) {
  const es = new EventSource(buildApiUrl("/stream"));
  es.onmessage = (e) => onMessage(JSON.parse(e.data));
  es.onerror   = onError ?? (() => {});
  return es; // caller calls es.close() to disconnect
}

