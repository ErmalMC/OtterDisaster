"""
AquaSense Arduino Bridge — Hackathon Demo Mode
===============================================
For the demo: Arduino sends TDS + pH via Serial (USB).
This script reads from Serial, timestamps each reading,
passes it directly to the trained RF model, and emits
a JSON alert that the web app can consume via WebSocket.

Hardware setup:
  - Arduino Uno/Nano/ESP32
  - TDS sensor → Analog pin A0 (via TDS module, e.g. DFRobot Gravity)
  - pH sensor  → Analog pin A1 (via pH module, e.g. DFRobot SEN0161)
  - USB → laptop running this script

Arduino sketch is in arduino/sensor_sketch.ino
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import serial
import joblib
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

MODEL_PATH   = Path("models/rf_anomaly_model.pkl")
META_PATH    = Path("models/model_metadata.json")
SERIAL_PORT  = "/dev/ttyUSB0"   # Windows: "COM3", Mac: "/dev/tty.usbserial-*"
BAUD_RATE    = 9600

# Fallback satellite values for demo (replace with latest openEO fetch)
DEMO_SATELLITE_CONTEXT = {
    "ndwi": 0.45,
    "ndti": 0.08,
    "ndci": 0.05,
    "chl_a": 6.2,
    "cyanobacteria": 18.0,
    "turbidity_sat": 22.0,
    "cdom": 5.1,
    "doc": 8.3,
    "sin_month": np.sin(2 * np.pi * datetime.now().month / 12),
    "cos_month": np.cos(2 * np.pi * datetime.now().month / 12),
}

ANOMALY_TYPES = {
    "normal": "All parameters within normal range.",
    "turbidity_event": "Elevated sediment or suspended particles detected.",
    "algal_bloom": "Algal bloom forming — elevated chlorophyll and nutrients.",
    "toxic_cyanobacteria": "TOXIC BLOOM — cyanobacteria at health-hazard levels.",
    "industrial_discharge": "Industrial discharge signature — high dissolved solids.",
    "organic_pollution": "Organic pollution — possible wastewater or decomposition.",
    "acid_mine_drainage": "Acid mine drainage — pH crash and high TDS combined.",
}


class SensorBridge:
    def __init__(self):
        log.info(f"Loading model from {MODEL_PATH}")
        self.pipeline = joblib.load(MODEL_PATH)
        with open(META_PATH) as f:
            self.meta = json.load(f)
        self.feature_names = self.meta["feature_names"]
        self.history = []   # rolling window for Z-score computation
        self._serial_buf: dict = {}  # accumulator for multi-line serial format

    def read_loop(self, port: str = SERIAL_PORT):
        """Main loop: read serial → predict → emit alert JSON."""
        log.info(f"Connecting to Arduino on {port} @ {BAUD_RATE} baud...")
        with serial.Serial(port, BAUD_RATE, timeout=5) as ser:
            log.info("Connected. Waiting for sensor data...")
            while True:
                raw = ser.readline().decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                reading = self.parse_arduino_line(raw)
                if reading is None:
                    continue

                observation = self.build_observation(reading)
                alert = self.predict(observation)

                # Emit to stdout (web app reads this via subprocess pipe or websocket)
                print(json.dumps(alert), flush=True)

                if alert["is_anomaly"]:
                    log.warning(f"ANOMALY: {alert['anomaly_type']} | score={alert['anomaly_score']:.3f}")
                    log.warning(f"  {alert['explanation']}")

    def parse_arduino_line(self, line: str) -> dict | None:
        """
        Parse Arduino serial output.

        Supports three formats automatically:

        Format A — multi-line (current sketch):
            Buffer lines until both pH and PPM seen, then emit one reading.
            pH: 6.87
            PPM: 93.44

        Format B — single-line key:value pairs:
            TDS:342.5,PH:7.23

        Format C — bare comma-separated:
            7.23,342.5
        """
        import re
        _re_ph  = re.compile(r"pH\s*:\s*([\-\d.]+)", re.IGNORECASE)
        _re_ppm = re.compile(r"PPM\s*:\s*([\-\d.]+)", re.IGNORECASE)

        # Multi-line format — accumulate in instance buffer
        m_ph = _re_ph.match(line)
        if m_ph:
            self._serial_buf["ph"] = float(m_ph.group(1))

        m_ppm = _re_ppm.match(line)
        if m_ppm:
            self._serial_buf["ppm"] = float(m_ppm.group(1))

        if "ph" in self._serial_buf and "ppm" in self._serial_buf:
            ph  = self._serial_buf.pop("ph")
            tds = self._serial_buf.pop("ppm")
            if 0 <= ph <= 14 and 0 <= tds <= 10000:
                return {"tds": tds, "ph": ph, "timestamp": datetime.now(timezone.utc).isoformat()}
            return None

        # Single-line key:value  TDS:342.5,PH:7.23
        try:
            parts = dict(kv.split(":") for kv in line.split(","))
            if "TDS" in parts and "PH" in parts:
                return {
                    "tds": float(parts["TDS"]),
                    "ph":  float(parts["PH"]),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception:
            pass

        # Bare comma  ph,tds
        try:
            vals = [v.strip() for v in line.split(",")]
            if len(vals) == 2:
                ph, tds = float(vals[0]), float(vals[1])
                if 0 <= ph <= 14 and 0 <= tds <= 10000:
                    return {"tds": tds, "ph": ph, "timestamp": datetime.now(timezone.utc).isoformat()}
        except Exception:
            pass

        log.debug(f"Could not parse: {line!r}")
        return None

    def build_observation(self, reading: dict) -> dict:
        """
        Combine live sensor reading with satellite context + engineered features.
        For demo: satellite values are the latest known context.
        In production: fetch latest openEO result for this pixel/date.
        """
        self.history.append(reading)
        if len(self.history) > 30:
            self.history.pop(0)

        tds_vals = [r["tds"] for r in self.history]
        ph_vals  = [r["ph"]  for r in self.history]

        obs = {**DEMO_SATELLITE_CONTEXT, **reading}

        # Z-scores (rolling window from history)
        def zscore(val, series):
            if len(series) < 3:
                return 0.0
            m, s = np.mean(series), np.std(series)
            return float((val - m) / s) if s > 0 else 0.0

        obs["z_tds"] = zscore(reading["tds"], tds_vals)
        obs["z_ph"]  = zscore(reading["ph"],  ph_vals)
        obs["z_ndti"] = 0.0
        obs["z_ndci"] = 0.0
        obs["z_chl_a"] = 0.0
        obs["z_cyano"] = 0.0  # key: z_cyanobacteria

        # Interaction features
        obs["tds_ph_interaction"] = reading["tds"] * (14 - reading["ph"])
        obs["ndci_chl_product"]   = obs["ndci"] * obs["chl_a"]

        # Multi-feature Z count
        obs["multi_feature_z_count"] = sum(
            1 for z in [obs["z_tds"], obs["z_ph"]] if abs(z) > 2.5
        )

        # Lag features (from history)
        if len(self.history) >= 2:
            prev = self.history[-2]
            obs["tds_lag1"]   = prev["tds"]
            obs["ph_lag1"]    = prev["ph"]
            obs["ndti_lag1"]  = DEMO_SATELLITE_CONTEXT["ndti"]
            obs["tds_delta"]  = reading["tds"] - prev["tds"]
            obs["ph_delta"]   = reading["ph"]  - prev["ph"]
        else:
            obs["tds_lag1"] = obs["ph_lag1"] = obs["ndti_lag1"] = 0.0
            obs["tds_delta"] = obs["ph_delta"] = 0.0

        return obs

    def predict(self, observation: dict) -> dict:
        X = pd.DataFrame([observation])[self.feature_names].fillna(0).values
        proba = float(self.pipeline.predict_proba(X)[0, 1])
        is_anomaly = proba > 0.5

        from backend.data.train import classify_anomaly_type, build_explanation, severity_level, ANOMALY_TYPES
        obs_series = pd.Series(observation)
        anomaly_type_id = classify_anomaly_type(obs_series) if is_anomaly else 0
        anomaly_type = ANOMALY_TYPES[anomaly_type_id]
        explanation = build_explanation(obs_series, anomaly_type_id, proba) if is_anomaly else "Normal."

        return {
            "timestamp":     observation["timestamp"],
            "tds":           round(observation["tds"], 1),
            "ph":            round(observation["ph"], 2),
            "anomaly_score": round(proba, 4),
            "is_anomaly":    is_anomaly,
            "anomaly_type":  anomaly_type,
            "severity":      severity_level(proba),
            "explanation":   explanation,
        }


def simulate_mode():
    """
    Demo without physical Arduino — injects synthetic readings.
    Simulates a normal period, then an acid mine drainage event.
    """
    log.info("SIMULATION MODE — no Arduino required")
    bridge = SensorBridge()

    scenarios = [
        *[{"tds": np.random.normal(350, 30), "ph": np.random.normal(7.4, 0.2)} for _ in range(15)],
        # Acid mine drainage event
        *[{"tds": np.random.normal(1800, 100), "ph": np.random.normal(5.1, 0.3)} for _ in range(5)],
        # Recovery
        *[{"tds": np.random.normal(400, 40), "ph": np.random.normal(7.2, 0.2)} for _ in range(5)],
    ]

    for reading in scenarios:
        reading["timestamp"] = datetime.now(timezone.utc).isoformat()
        obs = bridge.build_observation(reading)
        alert = bridge.predict(obs)
        print(json.dumps(alert), flush=True)
        if alert["is_anomaly"]:
            log.warning(f"ANOMALY [{alert['severity'].upper()}]: {alert['anomaly_type']}")
            log.warning(f"  TDS={alert['tds']} ppm | pH={alert['ph']}")
            log.warning(f"  {alert['explanation']}")
        else:
            log.info(f"Normal | TDS={alert['tds']} ppm | pH={alert['ph']} | score={alert['anomaly_score']:.3f}")
        time.sleep(0.5)


if __name__ == "__main__":
    import sys
    if "--simulate" in sys.argv:
        simulate_mode()
    else:
        bridge = SensorBridge()
        bridge.read_loop()