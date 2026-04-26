import { useState } from "react";
import { Otter } from "./Otter";
import otterLogo from '../../public/otter-logo.svg';

export function InstructionManual({ onDeploy, onGoToMap }) {
  const [deploying, setDeploying] = useState(false);

  const handleDeploy = () => {
    setDeploying(true);
    setTimeout(onDeploy, 1400);
  };

  const handleGoToMap = () => {
    if (onGoToMap) {
      onGoToMap();
      return;
    }
    onDeploy();
  };

  const steps = [
    {
      n: "01",
      title: "Calibrate the probe",
      body: "Rinse the OTTER-04 sensor array with distilled water and confirm the status LED pulses cyan.",
    },
    {
      n: "02",
      title: "Position above water",
      body: "Hold the device 30 cm above the surface, away from direct sunlight and surface debris.",
    },
    {
      n: "03",
      title: "Submerge for 10 seconds",
      body: "Lower the probe vertically until fully submerged. Hold steady — readings stabilize within 10 seconds.",
    },
    {
      n: "04",
      title: "Begin telemetry",
      body: "Press Deploy below. Live readings will stream to the dashboard once the device is in the water.",
    },
  ];

  return (
    <div className="min-h-dvh w-full bg-[var(--metal-100)] text-[var(--metal-800)] font-sans antialiased relative overflow-hidden">
      {/* Background grain + grid */}
      <div className="absolute inset-0 bg-[linear-gradient(rgba(14,165,233,0.06)_1px,transparent_1px),linear-gradient(90deg,rgba(14,165,233,0.06)_1px,transparent_1px)] bg-[size:64px_64px] pointer-events-none" />
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-[var(--aqua-100)] rounded-full blur-3xl opacity-50 -translate-y-1/3 translate-x-1/4 pointer-events-none" />

      <div className="relative max-w-5xl mx-auto px-6 py-12 md:py-16">
        {/* Header */}
        <div className="flex items-center justify-between mb-12 animate-[fade-in_0.6s_ease-out]">
          <div className="flex items-center gap-3">
{/*                logo on instruction page - the logo is made from html elements*/}
             <div className="size-9 rounded-xl bg-[var(--metal-900)] flex items-center justify-center shadow-[var(--shadow-glass)]">
               <img src={otterLogo} alt="icon" />
             </div>
            <div>
              <h1 className="font-data text-[10px] font-semibold uppercase tracking-[0.25em] text-[var(--aqua-600)]">
                Otterware · v1.0
              </h1>
              <p className="text-sm font-medium text-[var(--metal-800)]">
                Water Quality Monitor
              </p>
            </div>
          </div>
          <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-white/70 backdrop-blur-md border border-[var(--metal-200)] rounded-full">
            <div className="size-1.5 rounded-full bg-[var(--status-fair)]" />
            <span className="font-data text-[10px] uppercase tracking-widest text-[var(--metal-500)]">
              Awaiting Deployment
            </span>
          </div>
        </div>

        {/* Title */}
        <div className="mb-12 animate-[fade-up_0.6s_ease-out_0.1s_both]">
          <p className="font-data text-xs uppercase tracking-[0.3em] text-[var(--aqua-600)] mb-3">
            Instruction Manual
          </p>
          <h2 className="text-4xl md:text-5xl font-medium tracking-tight text-[var(--metal-900)] text-balance max-w-2xl">
            Deploy the OTTER probe to begin measuring water quality.
          </h2>
          <p className="mt-4 text-[var(--metal-500)] max-w-xl text-pretty">
            Follow the four-step procedure below. The dashboard will activate
            once the sensor confirms it is submerged.
          </p>
        </div>

        {/* Steps */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-12">
          {steps.map((s, i) => (
            <div
              key={s.n}
              className="bg-white/80 backdrop-blur-xl border border-[var(--metal-200)] rounded-2xl p-6 shadow-[var(--shadow-glass)] animate-[fade-up_0.5s_ease-out_both] hover:border-[var(--aqua-300)] transition-colors"
              style={{ animationDelay: `${0.15 + i * 0.08}s` }}
            >
              <div className="flex items-start gap-4">
                <div className="font-data text-2xl font-semibold text-[var(--aqua-500)] tabular-nums">
                  {s.n}
                </div>
                <div className="flex-1">
                  <h3 className="font-medium text-[var(--metal-900)] mb-1.5">
                    {s.title}
                  </h3>
                  <p className="text-sm text-[var(--metal-500)] leading-relaxed">
                    {s.body}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Otter illustration + CTA */}
        <div className="bg-gradient-to-br from-[var(--aqua-100)] via-white to-[var(--metal-100)] border border-[var(--metal-200)] rounded-3xl p-8 md:p-10 shadow-[var(--shadow-glass)] flex flex-col md:flex-row items-center justify-between gap-8 animate-[fade-up_0.6s_ease-out_0.5s_both] relative overflow-hidden">
          <div className="absolute -bottom-2 -right-2 w-48 opacity-90 pointer-events-none">
            <Otter className="w-full animate-[swim_8s_ease-in-out_infinite]" />
          </div>
          <div className="relative z-10 max-w-md">
            <p className="font-data text-[10px] uppercase tracking-[0.25em] text-[var(--aqua-600)] mb-2">
              Ready when you are
            </p>
            <h3 className="text-2xl font-medium text-[var(--metal-900)] mb-2">
              Insert the device into the water.
            </h3>
            <p className="text-sm text-[var(--metal-500)]">
              Ollie, our field unit, is standing by. Press Deploy to confirm the
              probe has been submerged, or just view the map.
            </p>
          </div>
          <div className="relative z-10 flex items-center gap-3">
            <button
              onClick={handleDeploy}
              disabled={deploying}
              className="group px-7 py-4 bg-[var(--metal-900)] text-white font-medium rounded-2xl shadow-lg hover:shadow-xl transition-all hover:-translate-y-0.5 disabled:opacity-70 disabled:cursor-wait flex items-center gap-3 cursor-pointer"
            >
              <span>{deploying ? "Deploying probe..." : "Deploy probe"}</span>
              {!deploying && (
                <svg
                  className="size-4 transition-transform group-hover:translate-x-0.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              )}
              {deploying && (
                <div className="size-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              )}
            </button>
            <button
              onClick={handleGoToMap}
              disabled={deploying}
              className="px-6 py-4 bg-white/85 text-[var(--metal-800)] font-medium rounded-2xl border border-[var(--metal-200)] shadow-[var(--shadow-glass)] hover:shadow-xl transition-all hover:-translate-y-0.5 disabled:opacity-70 hover:bg-white transition-colors disabled:opacity-70 disabled:cursor-not-allowed cursor-pointer"
            >
              Go to map
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
