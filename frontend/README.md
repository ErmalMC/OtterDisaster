# Frontend

React + Vite dashboard for the OtterDisaster backend.

## API integration

- Uses `src/utils/aquaSenseApi.js`
- Calls `/api/health`, `/api/predict`, and `/api/reload_satellite`
- In local development, Vite proxies `/api/*` to `http://127.0.0.1:5000`

## Run

```bash
npm install
npm run dev
```

## Optional environment variables

Copy `.env.example` to `.env` and edit if needed.

- `VITE_API_BASE_URL` (default: `/api`)
- `VITE_BACKEND_ORIGIN` (default: `http://127.0.0.1:5000`)

## Scripts

```bash
npm run dev
npm run lint
npm run build
npm run preview
```

