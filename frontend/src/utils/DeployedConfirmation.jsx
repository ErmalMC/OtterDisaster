import { useEffect } from "react";

export function DeployedConfirmation({ onContinue }) {
  useEffect(() => {
    const t = setTimeout(onContinue, 2400);
    return () => clearTimeout(t);
  }, [onContinue]);

  return (
    <div className="min-h-dvh w-full bg-[var(--metal-100)] text-[var(--metal-800)] font-sans antialiased relative overflow-hidden flex items-center justify-center">
      {/* Ripples */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="size-64 rounded-full border border-[var(--aqua-300)] animate-[pulse-ring_2.5s_ease-out_infinite]" />
        <div
          className="absolute size-64 rounded-full border border-[var(--aqua-300)] animate-[pulse-ring_2.5s_ease-out_infinite]"
          style={{ animationDelay: "0.8s" }}
        />
        <div
          className="absolute size-64 rounded-full border border-[var(--aqua-300)] animate-[pulse-ring_2.5s_ease-out_infinite]"
          style={{ animationDelay: "1.6s" }}
        />
      </div>

      <div className="relative z-10 flex flex-col items-center text-center px-6">
        {/* Check badge */}
        <div className="relative mb-8 animate-[check-pop_0.6s_cubic-bezier(0.34,1.56,0.64,1)_both]">
          <div className="absolute inset-0 bg-[var(--status-good)] blur-2xl opacity-40 rounded-full" />
          <div className="relative size-24 rounded-full bg-gradient-to-br from-[var(--status-good)] to-[oklch(0.55_0.15_160)] flex items-center justify-center shadow-2xl ring-8 ring-white/80">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="white"
              strokeWidth="3"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="size-12"
            >
              <path d="M5 13l4 4L19 7" />
            </svg>
          </div>
        </div>

        <p className="font-data text-xs uppercase tracking-[0.3em] text-[var(--status-good)] mb-3 animate-[fade-up_0.5s_ease-out_0.3s_both]">
          Probe submerged
        </p>
        <h1 className="text-3xl md:text-4xl font-medium text-[var(--metal-900)] tracking-tight mb-3 animate-[fade-up_0.5s_ease-out_0.4s_both]">
          Device successfully inserted into the water.
        </h1>
        <p className="text-[var(--metal-500)] max-w-md animate-[fade-up_0.5s_ease-out_0.5s_both]">
          Telemetry stream initiated. Calibrating sensors and streaming readings
          to the dashboard…
        </p>

        <div className="mt-8 flex items-center gap-2 animate-[fade-up_0.5s_ease-out_0.6s_both]">
          <div className="size-1.5 rounded-full bg-[var(--aqua-500)] animate-pulse" />
          <div
            className="size-1.5 rounded-full bg-[var(--aqua-500)] animate-pulse"
            style={{ animationDelay: "0.2s" }}
          />
          <div
            className="size-1.5 rounded-full bg-[var(--aqua-500)] animate-pulse"
            style={{ animationDelay: "0.4s" }}
          />
        </div>
      </div>
    </div>
  );
}
