# WaterGuard Frontend Demo

This Vite + React app now runs a **WaterGuard-style real-time river monitoring dashboard** for the Vardar River demo scenario.

It includes:
- TailwindCSS-driven dashboard UI (no custom component stylesheet required)
- historical seed data generation (55 weeks)
- live reading injection controls for scenario, rainfall, and temperature
- mock satellite band integration (B03/B04/B07/B08/B11) with local cache
- browser-side anomaly scoring + severity classification
- map panel, alert feed, metric cards, trend charts, and diagnosis reference table

## Quick start

```bash
npm install
npm run dev
```

Then open the local URL Vite prints in the terminal.

## Current data mode

For now, the frontend uses **mock satellite fetches only** and stores results in browser local storage to mimic caching.

When your Python backend is ready, we can wire the fetch service to your API in a small follow-up change.

## Scripts

```bash
npm run dev
npm run lint
npm run build
npm run preview
```

## Project structure

- `src/hooks/useWaterGuard.js` app orchestration state and actions
- `src/services/simulatorService.js` telemetry generation and historical seed
- `src/services/satelliteService.js` mock satellite fetch + local cache
- `src/utils/anomalyDetection.js` in-browser anomaly scoring and diagnosis
- `src/components/*` dashboard UI panels
- `src/App.jsx` shell composition
