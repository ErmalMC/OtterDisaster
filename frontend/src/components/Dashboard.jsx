import { useEffect, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  Tooltip,
  ZoomControl,
} from "react-leaflet";
// import { Otter } from "./Otter.jsx";

const MAP_CENTER = [41.9973, 21.428];
const MAP_ZOOM = 12;

const SENSOR_POINTS = [
  {
    id: "otter-04",
    position: [41.9973, 21.428],
    active: false,
    label: "OTTER-04",
    reading: "WQI 94",
    status: "Optimal",
    depth: "3.2 m",
    note: "Primary telemetry unit",
  },
  {
    id: "sensor-2",
    position: [42.0038, 21.454],
    label: "OTTER-05",
    reading: "WQI 89",
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

const baseMetrics = [
  {
    key: "do",
    label: "Dissolved O₂",
    value: "8.42",
    unit: "mg/L",
    status: "good",
    hint: "+0.2 vs baseline",
    bar: 84,
  },
  {
    key: "turb",
    label: "Turbidity",
    value: "1.2",
    unit: "NTU",
    status: "good",
    hint: "Very clear",
    bar: 15,
  },
  {
    key: "ph",
    label: "pH Level",
    value: "7.42",
    unit: "pH",
    status: "good",
    hint: "Neutral range",
    bar: 60,
  },
  {
    key: "temp",
    label: "Temperature",
    value: "14.2",
    unit: "°C",
    status: "good",
    hint: "Optimal",
    bar: 50,
  },
];

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
      {/* Map background */}
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
          {SENSOR_POINTS.map((point) => {
            const color = point.idle
              ? "oklch(0.75 0.05 80)"
              : "var(--aqua-glow)";
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
                  <Tooltip
                    direction="top"
                    offset={[0, -8]}
                    permanent={point.active}
                  >
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
        {/* Scanline */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="w-full h-32 bg-gradient-to-b from-transparent via-[var(--aqua-glow)]/10 to-transparent animate-[scanline_9s_linear_infinite]" />
        </div>
      </div>
      {/* Top right status */}
      <div className="absolute top-6 right-6 z-20 flex gap-3">
        <button
          onClick={onReset}
          className="bg-white/80 backdrop-blur-xl border border-white shadow-[var(--shadow-glass)] rounded-full px-4 py-2 flex items-center gap-2 text-xs font-medium text-[var(--metal-700)] hover:bg-white transition-colors cursor-pointer"
        >
          <svg
            className="size-3.5"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path
              d="M19 12H5M12 5l-7 7 7 7"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Back to Manual
        </button>
        <div className="bg-white/80 backdrop-blur-xl border border-white shadow-[var(--shadow-glass)] rounded-full px-4 py-2 flex items-center gap-2.5">
          <div className="size-2 rounded-full bg-[var(--status-good)] shadow-[0_0_8px_var(--status-good)] animate-pulse" />
          <span className="font-data text-[10px] font-semibold tracking-[0.2em] text-[var(--metal-800)] uppercase">
            Live · GPS Linked
          </span>
        </div>
      </div>

      {/* Otter swimming - bottom right */}
      {/*<div className="absolute bottom-8 right-8 z-20 w-32 opacity-90 pointer-events-none animate-[swim_8s_ease-in-out_infinite]">*/}
      {/*  <Otter className="w-full drop-shadow-lg" />*/}
      {/*</div>*/}

      {/* Main panel */}
      <aside className="relative z-20 w-[440px] max-w-[92vw] h-[calc(100dvh-3rem)] m-6 flex flex-col gap-4 animate-[fade-up_0.6s_ease-out_0.1s_both]">
        {/* Header card */}
        <div className="bg-white/85 backdrop-blur-2xl border border-white/60 shadow-[var(--shadow-glass)] rounded-3xl p-6 shrink-0 relative overflow-hidden">
          <div className="absolute top-2 left-2 size-2 border-t border-l border-[var(--metal-300)]" />
          <div className="absolute top-2 right-2 size-2 border-t border-r border-[var(--metal-300)]" />
          <div className="absolute bottom-2 left-2 size-2 border-b border-l border-[var(--metal-300)]" />
          <div className="absolute bottom-2 right-2 size-2 border-b border-r border-[var(--metal-300)]" />

          <div className="flex justify-between items-start mb-5">
            <div>
              <p className="font-data text-[10px] font-semibold uppercase tracking-[0.25em] text-[var(--aqua-600)] mb-1">
                Sector Alpha-9
              </p>
              <h1 className="text-2xl font-medium tracking-tight text-[var(--metal-900)]">
                Clearwater Basin
              </h1>
              <p className="text-xs text-[var(--metal-500)] mt-1">
                41.9973° N · 21.4280° E
              </p>
            </div>
            <div className="size-10 rounded-xl bg-[var(--metal-900)] flex items-center justify-center shadow-inner">
              <div className="size-1.5 rounded-full bg-[var(--aqua-glow)] shadow-[0_0_8px_var(--aqua-glow)]" />
            </div>
          </div>

          {/* WQI badge */}
          <div className="bg-gradient-to-r from-[oklch(0.95_0.06_160)] to-[var(--aqua-100)] border border-[oklch(0.85_0.1_160)]/30 rounded-2xl p-4 flex items-center justify-between">
            <div>
              <p className="font-data text-[11px] uppercase tracking-widest text-[oklch(0.45_0.12_160)] font-semibold mb-0.5">
                Water Quality Index
              </p>
              <p className="text-[var(--metal-900)] font-medium text-sm">
                Optimal Conditions
              </p>
            </div>
            <div className="bg-white rounded-xl px-3.5 py-2 shadow-sm border border-white">
              <span className="font-data text-3xl font-bold text-[var(--status-good)] tabular-nums">
                94
              </span>
              <span className="font-data text-xs text-[var(--metal-500)] ml-1">
                /100
              </span>
            </div>
          </div>
        </div>

        {/* Metrics grid */}
        <div className="grid grid-cols-2 gap-3 shrink-0">
          {metrics.map((m) => (
            <div
              key={m.key}
              className="bg-white/85 backdrop-blur-2xl border border-white/60 shadow-[var(--shadow-glass)] rounded-2xl p-5 group hover:border-[var(--aqua-300)] transition-colors"
            >
              <div className="flex justify-between items-center mb-3">
                <span className="text-xs font-medium text-[var(--metal-500)]">
                  {m.label}
                </span>
                <span
                  className="size-1.5 rounded-full"
                  style={{ backgroundColor: statusColor[m.status] }}
                />
              </div>
              <div className="flex items-baseline gap-1">
                <span className="font-data text-3xl font-semibold tracking-tight text-[var(--metal-900)] tabular-nums">
                  {m.value}
                </span>
                <span className="font-data text-xs text-[var(--metal-500)]">
                  {m.unit}
                </span>
              </div>
              <div className="w-full h-1 bg-[var(--metal-100)] rounded-full mt-3 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${m.bar}%`,
                    backgroundColor: statusColor[m.status],
                  }}
                />
              </div>
              <p className="mt-2 text-[10px] text-[var(--metal-500)]">
                {m.hint}
              </p>
            </div>
          ))}
        </div>

        {/* Depth profile */}
        <div className="bg-white/85 backdrop-blur-2xl border border-white/60 shadow-[var(--shadow-glass)] rounded-3xl p-5 flex-1 flex flex-col min-h-0 overflow-hidden">
          <div className="flex justify-between items-center mb-3 shrink-0">
            <h3 className="text-xs font-semibold text-[var(--metal-800)]">
              Depth Profile · Last 12 min
            </h3>
            <span className="font-data text-[10px] text-[var(--aqua-600)] border border-[var(--aqua-300)]/40 bg-[var(--aqua-50)] px-2 py-0.5 rounded">
              LIVE
            </span>
          </div>
          <div className="flex-1 bg-[var(--metal-50)] rounded-2xl border border-[var(--metal-100)] relative overflow-hidden p-3 min-h-0">
            <div className="w-full border-t border-dashed border-[var(--metal-200)] absolute top-1/4 left-0" />
            <div className="w-full border-t border-dashed border-[var(--metal-200)] absolute top-2/4 left-0" />
            <div className="w-full border-t border-dashed border-[var(--metal-200)] absolute top-3/4 left-0" />
            <div className="relative w-full h-full flex items-end justify-between gap-1">
              {Array.from({ length: 18 }).map((_, i) => {
                const h = 30 + Math.sin(i * 0.6 + time.getSeconds() * 0.1) * 25;
                return (
                  <div
                    key={i}
                    className="flex-1 bg-gradient-to-t from-[var(--aqua-500)] to-[var(--aqua-300)] rounded-t-sm transition-all duration-700 opacity-80"
                    style={{ height: `${h}%` }}
                  />
                );
              })}
            </div>
          </div>
          <div className="flex justify-between items-center mt-3 shrink-0">
            <span className="font-data text-[10px] text-[var(--metal-500)]">
              Updated {time.toLocaleTimeString()}
            </span>
            <span className="font-data text-[10px] text-[var(--metal-500)]">
              Probe ID: 884-X
            </span>
          </div>
        </div>
      </aside>
    </div>
  );
}
