"""
AquaSense — Flask API Server
=============================
Exposes the inference engine over HTTP so the UI can call it.

Endpoints:
  POST /predict           — live Arduino reading → anomaly result
  GET  /health            — health check + satellite age
  POST /reload_satellite  — call after a new OpenEO download completes

Run:
    pip install flask
    python api.py

Environment variables:
    MODEL_PATH      path to rf_anomaly_model.pkl   (default: models/rf_anomaly_model.pkl)
    SAT_PARQUET     path to vardar_wq_merged.parquet (default: vardar_wq_results/vardar_wq_merged.parquet)
    LAT             latitude  (default: 41.99)
    LON             longitude (default: 21.43)
    PORT            port      (default: 5000)
"""

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, Response, stream_with_context
from flask_cors import CORS

from backend.data.inference import AquaSenseInference

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)   # allow the UI (different port) to call the API

# ── Initialise engine at startup ─────────────────────────────────────────────
MODEL_PATH    = os.environ.get("MODEL_PATH",    "models/rf_anomaly_model.pkl")
SAT_PARQUET   = os.environ.get("SAT_PARQUET",   "vardar_wq_results/vardar_wq_merged.parquet")
LAT           = float(os.environ.get("LAT", 41.99))
LON           = float(os.environ.get("LON", 21.43))
ARDUINO_CSV   = os.environ.get("ARDUINO_CSV",   "data/arduino_output.csv")
PREDICTIONS_LOG = Path(os.environ.get("PREDICTIONS_LOG", "data/predictions_log.jsonl"))

# SSE subscribers — each connected frontend client gets a queue
_sse_subscribers: list[queue.Queue] = []
_sse_lock = threading.Lock()

engine: AquaSenseInference | None = None

def get_engine() -> AquaSenseInference:
    global engine
    if engine is None:
        engine = AquaSenseInference(
            model_path=MODEL_PATH,
            satellite_parquet=SAT_PARQUET,
            lat=LAT,
            lon=LON,
        )
    return engine


def _log_prediction(result: dict):
    """Append prediction result to JSONL log file and broadcast to SSE subscribers."""
    try:
        PREDICTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PREDICTIONS_LOG, "a") as f:
            f.write(json.dumps(result) + "\n")
    except Exception as e:
        log.warning(f"Could not write prediction log: {e}")

    # Broadcast to all connected SSE clients
    payload = json.dumps(result)
    with _sse_lock:
        dead = []
        for q in _sse_subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_subscribers.remove(q)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/predict", methods=["POST"])
def predict():
    """
    POST /predict
    Body (JSON):
        {
          "tds": 420.0,          # TDS in ppm  (required)
          "ph": 7.2,             # pH value    (required)
          "timestamp": "2024-11-15T10:30:00"  # optional, defaults to now
        }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Request body must be JSON"}), 400

        tds = data.get("tds")
        ph  = data.get("ph")

        if tds is None or ph is None:
            return jsonify({"error": "Both 'tds' and 'ph' fields are required"}), 400

        # Validate ranges
        if not (0 <= ph <= 14):
            return jsonify({"error": f"pH value {ph} is out of valid range [0, 14]"}), 400
        if not (0 <= tds <= 10000):
            return jsonify({"error": f"TDS value {tds} is out of valid range [0, 10000]"}), 400

        ts = data.get("timestamp")   # string or None

        result = get_engine().predict(
            sensor_reading={"tds": float(tds), "ph": float(ph)},
            timestamp=ts,
        )

        _log_prediction(result)
        return jsonify(result), 200

    except FileNotFoundError as e:
        log.error(f"Missing file: {e}")
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        log.exception("Prediction failed")
        return jsonify({"error": str(e)}), 500


@app.route("/arduino", methods=["POST"])
def arduino():
    """
    POST /arduino
    Reads the latest row from arduino_output.csv, runs inference,
    logs the result, and returns it as JSON to the frontend.
    Optional body: { "csv_path": "/custom/path/arduino_output.csv" }
    """
    try:
        body     = request.get_json(force=True, silent=True) or {}
        csv_path = body.get("csv_path", ARDUINO_CSV)
        result   = get_engine().predict_from_arduino(csv_path)
        _log_prediction(result)
        return jsonify(result), 200
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        log.exception("Arduino prediction failed")
        return jsonify({"error": str(e)}), 500


@app.route("/history", methods=["GET"])
def history():
    """
    GET /history?limit=100
    Returns the last N predictions from the log as a JSON array.
    The frontend uses this to populate charts and history tables.
    """
    try:
        limit = int(request.args.get("limit", 100))
        if not PREDICTIONS_LOG.exists():
            return jsonify([]), 200

        lines = PREDICTIONS_LOG.read_text().strip().splitlines()
        # Return the most recent `limit` entries
        recent = lines[-limit:]
        results = [json.loads(line) for line in recent if line.strip()]
        return jsonify(results), 200
    except Exception as e:
        log.exception("History fetch failed")
        return jsonify({"error": str(e)}), 500


@app.route("/stream", methods=["GET"])
def stream():
    """
    GET /stream
    Server-Sent Events endpoint. The frontend connects once and receives
    every new prediction in real time as it happens — no polling needed.

    Frontend usage (JavaScript):
        const es = new EventSource("http://localhost:5000/stream");
        es.onmessage = (e) => {
            const result = JSON.parse(e.data);
            updateDashboard(result);
        };
    """
    q: queue.Queue = queue.Queue(maxsize=50)
    with _sse_lock:
        _sse_subscribers.append(q)

    def event_generator():
        # Send a connected ping immediately so the frontend knows it's live
        yield "event: connected\ndata: {\"status\": \"connected\"}\n\n"
        try:
            while True:
                try:
                    payload = q.get(timeout=25)
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    # Keepalive comment so the connection doesn't time out
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_subscribers:
                    _sse_subscribers.remove(q)

    return Response(
        stream_with_context(event_generator()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # Nginx: disable buffering for SSE
        },
    )


@app.route("/health", methods=["GET"])
def health():
    """Returns model status and satellite freshness."""
    try:
        eng = get_engine()
        sat_df  = eng._sat_df
        latest  = sat_df["timestamp"].max()
        age     = (datetime.now() - latest).days

        return jsonify({
            "status":               "ok",
            "satellite_latest":     latest.isoformat(),
            "satellite_age_days":   age,
            "satellite_freshness":  "fresh" if age <= 2 else "usable" if age <= 5 else "stale",
            "model_loaded":         eng._pipeline is not None,
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/reload_satellite", methods=["POST"])
def reload_satellite():
    """Hot-reload satellite data after a new OpenEO download."""
    try:
        get_engine().reload_satellite()
        sat_df = engine._sat_df
        return jsonify({
            "status":  "reloaded",
            "rows":    len(sat_df),
            "latest":  sat_df["timestamp"].max().isoformat(),
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting AquaSense API on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)