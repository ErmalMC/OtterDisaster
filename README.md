# OtterDisaster

OtterDisaster is a water-quality monitoring demo with:

- a Flask backend in `backend/` that serves anomaly inference endpoints
- a React + Vite frontend in `frontend/` that queries those endpoints

## Connected API flow

- Frontend calls `GET /api/health` and `POST /api/predict`
- During local dev, Vite proxies `/api/*` to `http://127.0.0.1:5000`
- Backend also keeps legacy routes (`/health`, `/predict`) for compatibility

## Run locally

### 1) Backend

```bash
cd /home/ermal/Files/Coding/Programming_Files/OtterDisaster
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python backend/api.py
```

Backend starts on `http://127.0.0.1:5000`.

### 2) Frontend (new terminal)

```bash
cd /home/ermal/Files/Coding/Programming_Files/OtterDisaster/frontend
npm install
npm run dev
```

Frontend starts on Vite's local URL (usually `http://127.0.0.1:5173`).

## Quick verification

### Backend health

```bash
curl -s http://127.0.0.1:5000/api/health
```

### Backend prediction

```bash
curl -s -X POST http://127.0.0.1:5000/api/predict \
  -H 'Content-Type: application/json' \
  -d '{"tds":420,"ph":7.2}'
```

### End-to-end via frontend

1. Open the frontend URL in your browser.
2. Confirm top status changes from "Connecting to API" to live status.
3. Submit TDS/pH values in the dashboard form.
4. Verify the "Backend verdict" cards update from the Flask response.
