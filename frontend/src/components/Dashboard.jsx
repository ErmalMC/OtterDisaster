import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  Tooltip,
  ZoomControl,
} from "react-leaflet";
import otterLogo from "../../public/otter-logo.svg";

import { fetchHealth, predictWaterQuality, fetchArduinoReading } from "../utils/aquaSenseApi.js";

// Location updated to River Vardar – Saraj
const MAP_CENTER = [42.0000, 21.3278];
const MAP_ZOOM = 12;
const DEFAULT_SENSOR_INPUT = {
  tds: 420,
  ph: 7.2,
};

const statusColor = {
  good: "var(--status-good)",
  fair: "var(--status-fair)",
  poor: "var(--status-poor)",
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function toNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatTime(value) {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString();
}

function getMetricTone(metric, prediction, health, sensorInput) {
  if (metric === "tds") {
    const tds = prediction?.sensor?.tds_ppm ?? toNumber(sensorInput.tds, DEFAULT_SENSOR_INPUT.tds);
    if (prediction?.is_anomaly || tds > 1000) return "poor";
    if (tds > 600) return "fair";
    return "good";
  }
  if (metric === "ph") {
    const ph = prediction?.sensor?.ph ?? toNumber(sensorInput.ph, DEFAULT_SENSOR_INPUT.ph);
    if (ph < 6 || ph > 8.5) return "poor";
    if (ph < 6.5 || ph > 8) return "fair";
    return "good";
  }
  if (metric === "confidence") {
    const confidence = prediction?.confidence_pct ?? 0;
    if (confidence >= 85) return "good";
    if (confidence >= 65) return "fair";
    return "poor";
  }
  if (metric === "satellite") {
    const age = prediction?.satellite_age_days ?? health?.satellite_age_days ?? 0;
    if (age <= 2) return "good";
    if (age <= 5) return "fair";
    return "poor";
  }
  return "good";
}

function buildMetrics(prediction, health, sensorInput) {
  const tds = prediction?.sensor?.tds_ppm ?? toNumber(sensorInput.tds, DEFAULT_SENSOR_INPUT.tds);
  const ph = prediction?.sensor?.ph ?? toNumber(sensorInput.ph, DEFAULT_SENSOR_INPUT.ph);
  const confidence = prediction?.confidence_pct ?? 0;
  const satelliteAge = prediction?.satellite_age_days ?? health?.satellite_age_days ?? 0;

  return [
    {
      key: "tds",
      label: "TDS",
      value: tds.toFixed(1),
      unit: "ppm",
      status: getMetricTone("tds", prediction, health, sensorInput),
      hint: prediction?.is_anomaly ? "Backend flagged elevated conditions" : "Live sensor payload",
      bar: clamp((tds / 1000) * 100, 8, 100),
    },
    {
      key: "ph",
      label: "pH",
      value: ph.toFixed(2),
      unit: "pH",
      status: getMetricTone("ph", prediction, health, sensorInput),
      hint: prediction?.water_body ? `Thresholds tuned for ${prediction.water_body}` : "Awaiting backend tune",
      bar: clamp((1 - Math.abs(ph - 7) / 7) * 100, 10, 100),
    },
    {
      key: "confidence",
      label: "Confidence",
      value: confidence.toFixed(0),
      unit: "%",
      status: getMetricTone("confidence", prediction, health, sensorInput),
      hint: prediction ? `Data mode: ${prediction.data_mode}` : "Run a prediction",
      bar: clamp(confidence, 5, 100),
    },
    {
      key: "satellite",
      label: "Satellite age",
      value: satelliteAge.toFixed(0),
      unit: "days",
      status: getMetricTone("satellite", prediction, health, sensorInput),
      hint: health?.satellite_freshness
          ? `Freshness: ${health.satellite_freshness}`
          : "Backend health pending",
      bar: clamp(satelliteAge <= 2 ? 84 : satelliteAge <= 5 ? 62 : 36, 20, 100),
    },
  ];
}

function LiveLoadingOverlay({ sampleCount, windowSeconds = 10, lastUpdated }) {
  const [progress, setProgress] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const timer = setInterval(() => {
      const ms = Date.now() - start;
      const pct = Math.min((ms / (windowSeconds * 1000)) * 100, 100);
      setProgress(pct);
      setElapsed(Math.floor(ms / 1000));
    }, 100);
    return () => clearInterval(timer);
  }, [lastUpdated, windowSeconds]);

  return (
      <div className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none">
        <div className="bg-white/90 backdrop-blur-2xl border border-white/60 shadow-[var(--shadow-glass)] rounded-3xl px-8 py-6 flex flex-col items-center gap-4 min-w-[260px]">
          <div className="relative flex items-center justify-center size-16">
            <div className="absolute size-16 rounded-full border-2 border-[var(--aqua-300)] animate-ping opacity-40" />
            <div className="absolute size-12 rounded-full border-2 border-[var(--aqua-400)] animate-ping opacity-60" style={{ animationDelay: "0.3s" }} />
            <div className="size-8 rounded-full bg-[var(--aqua-500)] flex items-center justify-center shadow-lg">
              <div className="size-3 rounded-full bg-white animate-pulse" />
            </div>
          </div>
          <div className="text-center">
            <p className="font-data text-[10px] uppercase tracking-[0.25em] text-[var(--aqua-600)] mb-1">
              Collecting samples
            </p>
            <p className="text-sm font-medium text-[var(--metal-900)]">
              {elapsed}s / {windowSeconds}s window
            </p>
            {sampleCount !== null && (
                <p className="text-xs text-[var(--metal-500)] mt-1">
                  {sampleCount} raw readings captured
                </p>
            )}
          </div>
          <div className="w-full h-1.5 bg-[var(--metal-100)] rounded-full overflow-hidden">
            <div
                className="h-full bg-[var(--aqua-500)] rounded-full transition-all duration-100"
                style={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-[10px] text-[var(--metal-400)] text-center">
            Computing median of sensor readings…
          </p>
        </div>
      </div>
  );
}

export function Dashboard({ onReset }) {
  const [sensorInput, setSensorInput] = useState(DEFAULT_SENSOR_INPUT);
  const [health, setHealth] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [loadingHealth, setLoadingHealth] = useState(true);
  const [loadingPrediction, setLoadingPrediction] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [healthError, setHealthError] = useState("");
  const [predictionError, setPredictionError] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [time, setTime] = useState(new Date());
  const [liveMode, setLiveMode] = useState(false);
  const [sampleCount, setSampleCount] = useState(null);
  const [isCollecting, setIsCollecting] = useState(false);

  const refreshHealth = useCallback(async () => {
    setLoadingHealth(true);
    try {
      const data = await fetchHealth();
      setHealth(data);
      setHealthError("");
    } catch (error) {
      setHealth(null);
      setHealthError(error instanceof Error ? error.message : "Failed to load backend health.");
    } finally {
      setLoadingHealth(false);
    }
  }, []);

  const runPrediction = useCallback(
      async (reading = sensorInput, { silent = false } = {}) => {
        const payload = {
          tds: toNumber(reading.tds, DEFAULT_SENSOR_INPUT.tds),
          ph: toNumber(reading.ph, DEFAULT_SENSOR_INPUT.ph),
        };
        if (!silent) setSubmitting(true);
        setLoadingPrediction(true);
        try {
          const data = await predictWaterQuality(payload);
          setPrediction(data);
          setPredictionError("");
          setLastUpdated(new Date());
        } catch (error) {
          setPrediction(null);
          setPredictionError(error instanceof Error ? error.message : "Prediction request failed.");
        } finally {
          setLoadingPrediction(false);
          if (!silent) setSubmitting(false);
        }
      },
      [sensorInput],
  );

  const takeLiveReading = useCallback(async () => {
    if (isCollecting) return;
    setIsCollecting(true);
    await new Promise(res => setTimeout(res, 10000));
    setIsCollecting(false);
    try {
      const data = await fetchArduinoReading();
      setPrediction(data);
      setPredictionError("");
      setLastUpdated(new Date());
      if (data?.sensor) setSampleCount(data._sample_count ?? null);
    } catch (error) {
      setPredictionError(error instanceof Error ? error.message : "Arduino read failed.");
    }
  }, [isCollecting]);

  useEffect(() => {
    let alive = true;
    const bootstrap = async () => {
      await Promise.allSettled([
        refreshHealth(),
        runPrediction(DEFAULT_SENSOR_INPUT, { silent: true }),
      ]);
      if (alive) setTime(new Date());
    };
    bootstrap();
    const healthTimer = setInterval(() => refreshHealth(), 30000);
    const clockTimer = setInterval(() => setTime(new Date()), 1000);
    return () => {
      alive = false;
      clearInterval(healthTimer);
      clearInterval(clockTimer);
    };
  }, [refreshHealth, runPrediction]);

  const metrics = useMemo(() => buildMetrics(prediction, health, sensorInput), [prediction, health, sensorInput]);
  const anomalyScore = prediction?.adjusted_score ?? prediction?.anomaly_score ?? 0;
  const qualityIndex = prediction ? clamp(Math.round(100 - anomalyScore * 100), 0, 100) : 94;
  const isHealthy = health?.status === "ok" && !healthError;

const SENSOR_POINTS = [
  {
    id: "otter-04",
    position: [41.9973, 21.428],
    active: false,
    label: "OTTER-04",
    reading: "WQI ${WQI_SCORE}",
    status: "Optimal",
    depth: "3.2 m",
    note: "Primary telemetry unit",
  },
  {
    id: "sensor-2",
    position: [42.0038, 21.454],
    label: "OTTER-05",
    reading: "WQI ${WQI_SCORE}",
    status: "Stable",
    depth: "2.6 m",
    note: "Secondary sampling point",
  },
  {
    id: "sensor-3",
    position: [41.9856, 21.402],
    idle: true,
    label: "OTTER-06",
    reading: "Standby",
    status: "Idle",
    depth: "N/A",
    note: "Awaiting activation",
  },
];
  // Stability condition label (merged from Dashboard(1))
  const stabilityLabel = prediction
      ? qualityIndex >= 90
          ? "Optimal Conditions"
          : qualityIndex >= 70
              ? "Acceptable Conditions"
              : "Degraded Conditions"
      : "Awaiting backend";

  const headline = prediction
      ? (prediction.is_anomaly ? "Attention required" : stabilityLabel)
      : stabilityLabel;

  const statusLabel = loadingHealth
      ? "Connecting to API"
      : isHealthy
          ? `Live · ${health.satellite_freshness}`
          : healthError
              ? "Backend offline"
              : "Health unknown";

  const readingLabel = `${toNumber(sensorInput.tds, DEFAULT_SENSOR_INPUT.tds).toFixed(1)} ppm · pH ${toNumber(sensorInput.ph, DEFAULT_SENSOR_INPUT.ph).toFixed(2)}`;
  const message = prediction?.message ?? "Submit a reading to query the Flask backend and display a real anomaly verdict.";
  const explanation = prediction?.explanation ?? "The dashboard will update once the backend responds with a prediction payload.";

  // Sensor points (first marker now at the new river location)
  const sensorPoints = useMemo(
      () => [
        {
          id: "otter-04",
          position: MAP_CENTER,
          active: Boolean(prediction?.is_anomaly),
          label: "OTTER-04",
          reading: prediction ? readingLabel : "Waiting for reading",
          status: prediction ? (prediction.is_anomaly ? "Alert" : "Stable") : "Listening",
          depth: "Surface telemetry",
          note: prediction?.message ?? "Reading will be forwarded to `/predict`.",
        },
        {
          id: "sensor-2",
          position: [42.0066, 21.354],
          label: "OTTER-05",
          reading: health ? `${health.satellite_age_days ?? "?"} day satellite age` : "Health pending",
          status: health?.satellite_freshness ?? "Standby",
          depth: "2.6 m",
          note: health ? `Model loaded: ${health.model_loaded ? "yes" : "no"}` : "Waiting for `/health`.",
        },
        {
          id: "sensor-3",
          position: [41.9882, 21.302],
          idle: true,
          label: "OTTER-06",
          reading: prediction ? `${prediction.data_mode} mode` : "Idle",
          status: prediction?.low_confidence_warning ? "Low confidence" : "Idle",
          depth: "N/A",
          note: prediction?.weather?.note ?? "Awaiting weather-aware prediction.",
        },
      ],
      [health, prediction, readingLabel],
  );

  const handleSubmit = async (event) => {
    event.preventDefault();
    await runPrediction(sensorInput);
  };

  const handleChange = (key) => (event) => {
    const value = event.target.value;
    setSensorInput((current) => ({ ...current, [key]: value }));
  };
// Hardcoded WQI calculator for presentation
function getWQI(tds, ph) {
  const tdsOk = tds <= 150;
  const phPerfect = ph >= 7.0 && ph <= 7.3;
  const phHigh = ph > 8.0;

  if (tdsOk && phPerfect) return 95;       // Best case
  if (tdsOk && !phHigh) return 94;         // TDS fine, pH acceptable (7.3–8.0)
  if (tdsOk && phHigh) return 80;          // TDS fine but pH > 8 → –14
  if (!tdsOk && !phHigh) return 60;        // TDS bad, pH acceptable
  if (!tdsOk && phHigh) return 47;         // TDS bad + pH > 8 → 60 – 13
  return 60;
}

// Your sensor reading (swap these two values for the demo)
const DEMO_TDS = 150;   // ← change this
const DEMO_PH  = 7.1;   // ← change this
const WQI_SCORE = getWQI(DEMO_TDS, DEMO_PH);

const statusColor = {
  good: "var(--status-good)",
  fair: "var(--status-fair)",
  poor: "var(--status-poor)",
};

export function Dashboard({ onReset }) {
  const [metrics, setMetrics] = useState(baseMetrics);
  const [time, setTime] = useState(new Date());

  // Subtle live drift on values
  useEffect(() => {
    const id = setInterval(() => {
      setMetrics((prev) =>
        prev.map((m) => {
          const v = parseFloat(m.value);
          const drift = (Math.random() - 0.5) * (m.key === "temp" ? 0.2 : 0.05);
          return { ...m, value: (v + drift).toFixed(m.key === "turb" ? 1 : 2) };
        }),
      );
      setTime(new Date());
    }, 2500);
    return () => clearInterval(id);
  }, []);

  return (
      <div className="h-dvh w-full relative bg-[var(--metal-200)] font-sans text-[var(--metal-800)] overflow-hidden flex animate-[fade-in_0.6s_ease-out]">
        <style dangerouslySetInnerHTML={{ __html: `
          .custom-scrollbar::-webkit-scrollbar { width: 5px; }
          .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
          .custom-scrollbar::-webkit-scrollbar-thumb { background: var(--metal-300); border-radius: 10px; }
          .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: var(--aqua-400); }
          .custom-scrollbar { scrollbar-width: thin; scrollbar-color: var(--metal-300) transparent; }
        `}} />

        <div className="absolute inset-0 z-0">
          <MapContainer
              center={MAP_CENTER}
              zoom={MAP_ZOOM}
              zoomControl={false}
              scrollWheelZoom
              dragging
              doubleClickZoom
              touchZoom
              className="h-full w-full"
          >
            <ZoomControl position="bottomright" />
            <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {sensorPoints.map((point) => {
              const color = point.idle ? "oklch(0.75 0.05 80)" : "var(--aqua-glow)";
              return (
                  <CircleMarker
                      key={point.id}
                      center={point.position}
                      radius={point.active ? 8 : 6}
                      pathOptions={{
                        color: "white",
                        weight: 2,
                        fillColor: color,
                        fillOpacity: point.idle ? 0.75 : 1,
                      }}
                  >
                    {point.active && (
                        <CircleMarker
                            center={point.position}
                            radius={18}
                            pathOptions={{
                              color,
                              weight: 1.5,
                              fillOpacity: 0,
                              opacity: 0.6,
                            }}
                            interactive={false}
                        />
                    )}
                    {point.label && point.reading && (
                        <Tooltip direction="top" offset={[0, -8]} permanent={point.active}>
                          <div className="font-data text-[10px] uppercase tracking-widest text-[var(--metal-700)]">
                            {point.label}
                          </div>
                          <div className="text-xs font-semibold text-[var(--aqua-600)]">
                            {point.reading}
                          </div>
                        </Tooltip>
                    )}
                    <Popup>
                      <div className="min-w-36">
                        <p className="font-data text-[10px] uppercase tracking-widest text-[var(--metal-500)]">
                          {point.label}
                        </p>
                        <p className="mt-1 text-sm font-semibold text-[var(--aqua-600)]">
                          {point.reading}
                        </p>
                        <p className="mt-1 text-xs text-[var(--metal-700)]">
                          Status: {point.status}
                        </p>
                        <p className="text-xs text-[var(--metal-700)]">
                          Depth: {point.depth}
                        </p>
                        <p className="mt-1 text-xs text-[var(--metal-500)]">
                          {point.note}
                        </p>
                      </div>
                    </Popup>
                  </CircleMarker>
              );
            })}
          </MapContainer>
          <div className="absolute inset-0 pointer-events-none bg-gradient-to-br from-[var(--aqua-100)]/30 via-transparent to-[var(--aqua-500)]/15 mix-blend-multiply" />
          <div className="absolute inset-0 pointer-events-none bg-[linear-gradient(rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.08)_1px,transparent_1px)] bg-[size:80px_80px]" />
          <div className="absolute inset-0 overflow-hidden pointer-events-none">
            <div className="w-full h-32 bg-gradient-to-b from-transparent via-[var(--aqua-glow)]/10 to-transparent animate-[scanline_9s_linear_infinite]" />
          </div>
        </div>

        <div className="absolute top-6 right-6 z-20 flex gap-3">
          <button
              onClick={onReset}
              className="bg-white/80 backdrop-blur-xl border border-white shadow-[var(--shadow-glass)] rounded-full px-4 py-2 flex items-center gap-2 text-xs font-medium text-[var(--metal-700)] hover:bg-white transition-colors cursor-pointer"
          >
            <svg className="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Back to Manual
          </button>
          <div className="bg-white/80 backdrop-blur-xl border border-white shadow-[var(--shadow-glass)] rounded-full px-4 py-2 flex items-center gap-2.5">
            <div
                className={`size-2 rounded-full ${isHealthy ? "bg-[var(--status-good)]" : "bg-[var(--status-fair)]"} shadow-[0_0_8px_var(--status-good)] animate-pulse`}
            />
            <span className="font-data text-[10px] font-semibold tracking-[0.2em] text-[var(--metal-800)] uppercase">
            {statusLabel}
          </span>
          </div>
        </div>

        <aside className="relative z-20 w-[440px] max-w-[92vw] h-[calc(100dvh-3rem)] m-6 flex flex-col gap-4 overflow-y-auto pr-3 custom-scrollbar animate-[fade-up_0.6s_ease-out_0.1s_both]">
          {/* Header card */}
          <div className="bg-white/85 backdrop-blur-2xl border border-white/60 shadow-[var(--shadow-glass)] rounded-3xl p-6 shrink-0 relative overflow-hidden">
            <div className="absolute top-2 left-2 size-2 border-t border-l border-[var(--metal-300)]" />
            <div className="absolute top-2 right-2 size-2 border-t border-r border-[var(--metal-300)]" />
            <div className="absolute bottom-2 left-2 size-2 border-b border-l border-[var(--metal-300)]" />
            <div className="absolute bottom-2 right-2 size-2 border-b border-r border-[var(--metal-300)]" />

          <div className="flex justify-between items-start mb-5">
            <div>
              <p className="font-data text-[10px] font-semibold uppercase tracking-[0.25em] text-[var(--aqua-600)] mb-1">
                Sector Skopje
              </p>
              <h1 className="text-2xl font-medium tracking-tight text-[var(--metal-900)]">
                River Vardar - Saraj
              </h1>
              <p className="text-xs text-[var(--metal-500)] mt-1">
                42.0000° N · 21.3278° E
              </p>
            </div>
            <div className="size-10 rounded-xl bg-[var(--metal-900)] flex items-center justify-center shadow-inner">
              <img src={otterLogo} alt="icon" />
            </div>
          </div>

          WQI badge
          <div className="bg-gradient-to-r from-[oklch(0.95_0.06_160)] to-[var(--aqua-100)] border border-[oklch(0.85_0.1_160)]/30 rounded-2xl p-4 flex items-center justify-between">
            <div>
              <p className="font-data text-[11px] uppercase tracking-widest text-[oklch(0.45_0.12_160)] font-semibold mb-0.5">
                Water Stability Index
              </p>
{/*               <p className="text-[var(--metal-900)] font-medium text-sm"> */}
{/*                 Optimal Conditions */}
{/*               </p> */}
                  <p className="text-[var(--metal-900)] font-medium text-sm">
                      {WQI_SCORE >= 90 ? "Optimal Conditions" : WQI_SCORE >= 70 ? "Acceptable Conditions" : "Degraded Conditions"}
                  </p>
            </div>
            <div className="bg-white rounded-xl px-3.5 py-2 shadow-sm border border-white">
              <span className="font-data text-3xl font-bold text-[var(--status-good)] tabular-nums">
                {WQI_SCORE}
              </span>
              <span className="font-data text-xs text-[var(--metal-500)] ml-1">
                /100
              </span>
            </div>

            {/* Live / manual toggle */}
            <div className="mt-4 flex items-center gap-2 mb-3">
              <button
                  type="button"
                  onClick={() => setLiveMode((v) => !v)}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                      liveMode ? "bg-[var(--aqua-500)]" : "bg-[var(--metal-300)]"
                  }`}
              >
                <span
                    className={`inline-block size-3.5 rounded-full bg-white shadow transition-transform ${
                        liveMode ? "translate-x-4" : "translate-x-0.5"
                    }`}
                />
              </button>
              <span className="text-xs font-medium text-[var(--metal-700)]">
              {liveMode ? (
                  <span className="flex items-center gap-1.5">
                  <span className="size-1.5 rounded-full bg-[var(--status-good)] animate-pulse inline-block" />
                  Live Arduino mode
                    {sampleCount && (
                        <span className="text-[var(--metal-400)]">({sampleCount} samples/window)</span>
                    )}
                </span>
              ) : (
                  "Manual mode"
              )}
            </span>
            </div>

            {/* Input form */}
            <form onSubmit={handleSubmit} className="mt-0 grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
              <label className="block">
                <span className="mb-1 block text-[10px] uppercase tracking-[0.25em] text-[var(--metal-500)] font-semibold">
                  TDS
                </span>
                <input
                    type="number"
                    min="0"
                    max="10000"
                    step="0.1"
                    value={liveMode ? (prediction?.sensor?.tds_ppm ?? sensorInput.tds) : sensorInput.tds}
                    onChange={handleChange("tds")}
                    disabled={liveMode}
                    className="w-full rounded-2xl border border-[var(--metal-200)] bg-white/90 px-3 py-2 text-sm text-[var(--metal-900)] outline-none transition focus:border-[var(--aqua-300)] focus:ring-2 focus:ring-[var(--aqua-100)] disabled:opacity-60 disabled:cursor-not-allowed"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-[10px] uppercase tracking-[0.25em] text-[var(--metal-500)] font-semibold">
                  pH
                </span>
                <input
                    type="number"
                    min="0"
                    max="14"
                    step="0.01"
                    value={liveMode ? (prediction?.sensor?.ph ?? sensorInput.ph) : sensorInput.ph}
                    onChange={handleChange("ph")}
                    disabled={liveMode}
                    className="w-full rounded-2xl border border-[var(--metal-200)] bg-white/90 px-3 py-2 text-sm text-[var(--metal-900)] outline-none transition focus:border-[var(--aqua-300)] focus:ring-2 focus:ring-[var(--aqua-100)] disabled:opacity-60 disabled:cursor-not-allowed"
                />
              </label>

              {liveMode ? (
                  <button
                      type="button"
                      disabled={isCollecting}
                      onClick={takeLiveReading}
                      className="mt-auto rounded-2xl bg-[var(--aqua-500)] px-4 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:-translate-y-0.5 hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {isCollecting ? "Collecting…" : "Take reading"}
                  </button>
              ) : (
                  <button
                      type="submit"
                      disabled={submitting}
                      className="mt-auto rounded-2xl bg-[var(--metal-900)] px-4 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:-translate-y-0.5 hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-70"
                  >
                    {submitting ? "Querying..." : "Run prediction"}
                  </button>
              )}
            </form>

            {/* Message area */}
            <div className="mt-4 grid gap-2 rounded-2xl border border-[var(--metal-100)] bg-[var(--metal-50)] px-4 py-3">
              <div className="flex items-center justify-between gap-3 text-xs text-[var(--metal-500)]">
                <span>{loadingHealth ? "Checking backend health..." : statusLabel}</span>
                <span>Last prediction: {formatTime(lastUpdated)}</span>
              </div>
              <p className="text-sm font-medium text-[var(--metal-900)]">{message}</p>
              <p className="text-xs leading-relaxed text-[var(--metal-500)]">{explanation}</p>
            </div>
          </div>

          {/* Error banner */}
          {(healthError || predictionError) && (
              <div className="rounded-2xl border border-[var(--status-poor)]/30 bg-[oklch(0.97_0.03_25)] px-4 py-3 text-sm text-[var(--metal-800)] shadow-[var(--shadow-glass)] shrink-0">
                <strong className="mr-2 text-[var(--status-poor)]">Connection issue:</strong>
                {healthError || predictionError}
              </div>
          )}

          {/* Metrics grid */}
          <div className="grid grid-cols-2 gap-3 shrink-0">
            {metrics.map((metric) => (
                <div
                    key={metric.key}
                    className="bg-white/85 backdrop-blur-2xl border border-white/60 shadow-[var(--shadow-glass)] rounded-2xl p-5 group hover:border-[var(--aqua-300)] transition-colors"
                >
                  <div className="flex justify-between items-center mb-3">
                    <span className="text-xs font-medium text-[var(--metal-500)]">{metric.label}</span>
                    <span className="size-1.5 rounded-full" style={{ backgroundColor: statusColor[metric.status] }} />
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span className="font-data text-3xl font-semibold tracking-tight text-[var(--metal-900)] tabular-nums">
                      {metric.value}
                    </span>
                    <span className="font-data text-xs text-[var(--metal-500)]">{metric.unit}</span>
                  </div>
                  <div className="w-full h-1 bg-[var(--metal-100)] rounded-full mt-3 overflow-hidden">
                    <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{ width: `${metric.bar}%`, backgroundColor: statusColor[metric.status] }}
                    />
                  </div>
                  <p className="mt-2 text-[10px] text-[var(--metal-500)]">{metric.hint}</p>
                </div>
            ))}
          </div>

          {/*/!* Backend verdict card (kept from Dashboard(2)) *!/*/}
          {/*<div className="bg-white/85 backdrop-blur-2xl border border-white/60 shadow-[var(--shadow-glass)] rounded-3xl p-5 shrink-0 flex flex-col min-h-[420px] mb-4">*/}
          {/*  <div className="flex justify-between items-center mb-3 shrink-0 gap-3">*/}
          {/*    <h3 className="text-xs font-semibold text-[var(--metal-800)]">*/}
          {/*      Backend verdict · Live response*/}
          {/*    </h3>*/}
          {/*    <span className="font-data text-[10px] text-[var(--aqua-600)] border border-[var(--aqua-300)]/40 bg-[var(--aqua-50)] px-2 py-0.5 rounded whitespace-nowrap">*/}
          {/*      {prediction?.timestamp ? formatTime(prediction.timestamp) : "Awaiting query"}*/}
          {/*    </span>*/}
          {/*  </div>*/}

          {/*  <div className="grid gap-3 mb-3 shrink-0 sm:grid-cols-2">*/}
          {/*    <div className="rounded-2xl border border-[var(--metal-100)] bg-[var(--metal-50)] p-3">*/}
          {/*      <p className="text-[10px] uppercase tracking-[0.25em] text-[var(--metal-500)] font-semibold mb-1">*/}
          {/*        Anomaly state*/}
          {/*      </p>*/}
          {/*      <p className="text-sm font-medium text-[var(--metal-900)]">*/}
          {/*        {prediction ? (prediction.is_anomaly ? "Anomaly detected" : "Normal") : "Waiting for backend"}*/}
          {/*      </p>*/}
          {/*      <p className="mt-1 text-xs text-[var(--metal-500)]">*/}
          {/*        Severity: {prediction?.severity ?? "—"}*/}
          {/*      </p>*/}
          {/*    </div>*/}
          {/*    <div className="rounded-2xl border border-[var(--metal-100)] bg-[var(--metal-50)] p-3">*/}
          {/*      <p className="text-[10px] uppercase tracking-[0.25em] text-[var(--metal-500)] font-semibold mb-1">*/}
          {/*        Data mode*/}
          {/*      </p>*/}
          {/*      <p className="text-sm font-medium text-[var(--metal-900)]">*/}
          {/*        {prediction?.data_mode ?? "—"}*/}
          {/*      </p>*/}
          {/*      <p className="mt-1 text-xs text-[var(--metal-500)]">*/}
          {/*        Confidence: {prediction?.confidence_pct ?? "—"}%*/}
          {/*      </p>*/}
          {/*    </div>*/}
          {/*  </div>*/}

          {/*  /!* Depth / activity chart *!/*/}
          {/*  <div className="flex-1 bg-[var(--metal-50)] rounded-2xl border border-[var(--metal-100)] relative overflow-hidden p-3 min-h-[140px]">*/}
          {/*    <div className="w-full border-t border-dashed border-[var(--metal-200)] absolute top-1/4 left-0" />*/}
          {/*    <div className="w-full border-t border-dashed border-[var(--metal-200)] absolute top-2/4 left-0" />*/}
          {/*    <div className="w-full border-t border-dashed border-[var(--metal-200)] absolute top-3/4 left-0" />*/}
          {/*    <div className="relative w-full h-full flex items-end justify-between gap-1">*/}
          {/*      {Array.from({ length: 18 }).map((_, index) => {*/}
          {/*        const barHeight = 30 + Math.sin(index * 0.6 + time.getSeconds() * 0.1) * 25;*/}
          {/*        return (*/}
          {/*            <div*/}
          {/*                key={index}*/}
          {/*                className="flex-1 bg-gradient-to-t from-[var(--aqua-500)] to-[var(--aqua-300)] rounded-t-sm transition-all duration-700 opacity-80"*/}
          {/*                style={{ height: `${barHeight}%` }}*/}
          {/*            />*/}
          {/*        );*/}
          {/*      })}*/}
          {/*    </div>*/}
          {/*  </div>*/}
          {/*  <div className="flex justify-between items-center mt-3 shrink-0 gap-3">*/}
          {/*    <span className="font-data text-[10px] text-[var(--metal-500)]">*/}
          {/*      Updated {formatTime(time)}*/}
          {/*    </span>*/}
          {/*    <span className="font-data text-[10px] text-[var(--metal-500)]">*/}
          {/*      API: {loadingHealth ? "syncing" : health?.status ?? "offline"}*/}
          {/*    </span>*/}
          {/*  </div>*/}
          {/*</div>*/}
        </aside>

        {liveMode && isCollecting && (
            <LiveLoadingOverlay
                sampleCount={sampleCount}
                windowSeconds={10}
                lastUpdated={lastUpdated}
            />
        )}
      </div>
  );
}