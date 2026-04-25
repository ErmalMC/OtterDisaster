"""
AquaSense — Live Inference Engine
===================================
Imports everything from train.py (predict_single, THRESHOLDS, FEATURE_COLUMNS,
ANOMALY_TYPES, classify_anomaly_type, severity_level, engineer_features, etc.)
so there is zero duplicated logic.

Adds on top:
  - Satellite staleness detection (how old is the last parquet row?)
  - Open-Meteo weather pull (free, no API key)
  - Confidence penalty = staleness penalty + rain penalty
  - Sensor-only fallback when satellite is > 5 days stale
  - Water body type thresholds (river / lake / spring)
  - z_cyano fix: un-log before z-score so the rolling window sees real units
  - Live Arduino pipeline: predict_from_arduino(csv_path) -> result dict

Usage:
    from inference import AquaSenseInference

    engine = AquaSenseInference(
        model_path="models/rf_anomaly_model.pkl",
        satellite_parquet="vardar_wq_results/vardar_wq_merged.parquet",
        lat=41.99, lon=21.43,
        water_body="river",   # "river" | "lake" | "spring"
    )

    result = engine.predict_from_arduino("path/to/output.csv")
    # or
    result = engine.predict({"tds": 420.0, "ph": 7.2})
    print(result)
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import requests

# ── Import everything already written in train.py ────────────────────────────
from train import (
    predict_single,
    THRESHOLDS,
    FEATURE_COLUMNS,
    ANOMALY_TYPES,
    classify_anomaly_type,
    severity_level,
    load_satellite_data,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# WATER BODY THRESHOLD OVERRIDES
# River: fast-changing, runoff risk — moderate thresholds
# Lake: still water, bloom risk higher, turbidity lower
# Spring: naturally clean — any deviation is significant
# ─────────────────────────────────────────────────────────────────────────────

WATER_BODY_THRESHOLDS = {
    "river": {
        "tds_moderate": 800.0,
        "tds_severe": 2000.0,
        "ph_acid": 6.0,
        "ph_alkaline": 9.0,
        "ndti_high": 0.25,
        "ndci_bloom": 0.20,
        "turbidity_high": 100.0,
    },
    "lake": {
        "tds_moderate": 600.0,
        "tds_severe": 1500.0,
        "ph_acid": 6.5,
        "ph_alkaline": 8.5,
        "ndti_high": 0.18,
        "ndci_bloom": 0.15,
        "turbidity_high": 60.0,
    },
    "spring": {
        "tds_moderate": 300.0,
        "tds_severe": 800.0,
        "ph_acid": 6.8,
        "ph_alkaline": 8.0,
        "ndti_high": 0.10,
        "ndci_bloom": 0.10,
        "turbidity_high": 20.0,
    },
}

SATELLITE_FRESH_DAYS  = 2
SATELLITE_USABLE_DAYS = 5
RAIN_PENALTY_MAX      = 0.35
RAIN_THRESHOLD_MM     = 5.0
RAIN_HEAVY_MM         = 20.0

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&daily=precipitation_sum"
    "&past_days=7&forecast_days=1"
    "&timezone=auto"
)


# ─────────────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_weather(lat: float, lon: float, observation_date: datetime) -> dict:
    try:
        url  = OPEN_METEO_URL.format(lat=lat, lon=lon)
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        dates     = data["daily"]["time"]
        rain_vals = data["daily"]["precipitation_sum"]
        rain_dict = dict(zip(dates, rain_vals))

        window_dates = [
            (observation_date - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(7)
        ]
        total_rain  = sum(rain_dict.get(d, 0) or 0 for d in window_dates)
        rain_on_day = rain_dict.get(observation_date.strftime("%Y-%m-%d"), 0) or 0

        if total_rain <= RAIN_THRESHOLD_MM:
            penalty = 0.0
        elif total_rain >= RAIN_HEAVY_MM:
            penalty = RAIN_PENALTY_MAX
        else:
            frac    = (total_rain - RAIN_THRESHOLD_MM) / (RAIN_HEAVY_MM - RAIN_THRESHOLD_MM)
            penalty = round(frac * RAIN_PENALTY_MAX, 3)

        if total_rain > RAIN_HEAVY_MM:
            note = f"Heavy rainfall ({total_rain:.0f} mm over 7 days). Satellite turbidity baseline unreliable."
        elif total_rain > RAIN_THRESHOLD_MM:
            note = f"Moderate rainfall ({total_rain:.0f} mm over 7 days). Slight turbidity increase expected."
        else:
            note = "Dry conditions. Weather has minimal effect on readings."

        return {
            "total_rain_7d_mm": round(total_rain, 1),
            "rain_on_day_mm":   round(rain_on_day, 1),
            "rain_penalty":     penalty,
            "weather_note":     note,
            "weather_ok":       True,
        }

    except Exception as e:
        log.warning(f"Weather fetch failed: {e}")
        return {
            "total_rain_7d_mm": None,
            "rain_on_day_mm":   None,
            "rain_penalty":     0.05,
            "weather_note":     "Weather data unavailable.",
            "weather_ok":       False,
        }


def _get_satellite_context(sat_df: pd.DataFrame, observation_date: datetime) -> dict:
    past = sat_df[sat_df["timestamp"] <= observation_date]
    if past.empty:
        past = sat_df
    nearest  = past.iloc[-1]
    age_days = (observation_date - nearest["timestamp"]).days

    sat_features = {
        col: float(nearest[col])
        for col in ["ndwi", "ndti", "ndci", "chl_a", "cyanobacteria",
                    "turbidity_sat", "cdom", "doc"]
        if col in nearest.index and not pd.isna(nearest[col])
    }
    return {
        "sat_features":       sat_features,
        "satellite_date":     nearest["timestamp"].strftime("%Y-%m-%d"),
        "satellite_age_days": int(age_days),
    }


def _compute_confidence(satellite_age_days: int, rain_penalty: float, base_score: float) -> dict:
    if satellite_age_days <= SATELLITE_FRESH_DAYS:
        staleness_penalty = 0.0
        data_mode         = "full"
    elif satellite_age_days <= SATELLITE_USABLE_DAYS:
        frac              = (satellite_age_days - SATELLITE_FRESH_DAYS) / (SATELLITE_USABLE_DAYS - SATELLITE_FRESH_DAYS)
        staleness_penalty = round(frac * 0.20, 3)
        data_mode         = "partial"
    else:
        staleness_penalty = 0.25
        data_mode         = "sensor_only"

    total_penalty  = staleness_penalty + rain_penalty
    adj_score      = round(max(0.0, base_score - total_penalty * base_score), 4)
    confidence_pct = max(30, round((1.0 - total_penalty) * 100))

    return {
        "adjusted_anomaly_score": adj_score,
        "confidence_pct":         confidence_pct,
        "data_mode":              data_mode,
        "staleness_penalty":      staleness_penalty,
        "rain_penalty":           rain_penalty,
        "total_penalty":          round(total_penalty, 3),
    }


def _build_feature_vector(
    sensor: dict,
    sat_features: dict,
    ts: datetime,
    history_df: Optional[pd.DataFrame],
    water_body: str,
) -> dict:
    """
    Assembles the full FEATURE_COLUMNS vector from live sensor + satellite.

    z_cyano fix: cyanobacteria is stored as log1p in the parquet.
    We expm1() it before computing the rolling z-score so the window
    sees real units. Without this, z_cyano is always near zero.
    """
    obs = {}
    obs.update(sat_features)

    obs["tds"] = float(sensor.get("tds", 0))
    obs["ph"]  = float(sensor.get("ph", 7.0))

    obs["sin_month"]          = float(np.sin(2 * np.pi * ts.month / 12))
    obs["cos_month"]          = float(np.cos(2 * np.pi * ts.month / 12))
    obs["tds_ph_interaction"] = obs["tds"] * (14 - obs["ph"])
    obs["ndci_chl_product"]   = obs.get("ndci", 0) * max(obs.get("chl_a", 0), 0)

    z_features = ["ndti", "ndci", "chl_a", "cyanobacteria", "tds", "ph"]
    for feat in z_features:
        obs[f"z_{feat}"] = 0.0

    if history_df is not None and len(history_df) >= 5:
        window = THRESHOLDS["zscore_rolling_window"]
        recent = history_df.tail(window).copy()

        if "cyanobacteria" in recent.columns:
            recent["cyanobacteria"] = np.expm1(recent["cyanobacteria"].clip(lower=0))

        for feat in z_features:
            if feat in recent.columns:
                mu  = recent[feat].mean()
                std = recent[feat].std()
                val = obs.get(feat, 0)
                if feat == "cyanobacteria":
                    val = float(np.expm1(max(val, 0)))
                obs[f"z_{feat}"] = float((val - mu) / std) if std and std > 0 else 0.0

    z_cols = [f"z_{f}" for f in z_features]
    obs["multi_feature_z_count"] = int(
        sum(abs(obs.get(c, 0)) > THRESHOLDS["zscore_anomaly"] for c in z_cols)
    )

    for feat in ["tds", "ph", "ndti"]:
        obs[f"{feat}_lag1"]  = 0.0
        obs[f"{feat}_delta"] = 0.0

    if history_df is not None and len(history_df) >= 1:
        last             = history_df.iloc[-1]
        obs["tds_lag1"]  = float(last.get("tds", 0))
        obs["ph_lag1"]   = float(last.get("ph", 7.0))
        obs["ndti_lag1"] = float(last.get("ndti", 0))
        obs["tds_delta"] = obs["tds"] - obs["tds_lag1"]
        obs["ph_delta"]  = obs["ph"]  - obs["ph_lag1"]

    return obs


def _build_message(
    is_anomaly: bool,
    anomaly_type_int: int,
    conf: dict,
    weather: dict,
    sensor: dict,
    satellite_age_days: int,
    water_body: str,
) -> str:
    """
    Honest UI message. Never gives satellite-derived root cause when stale.
    """
    wbt   = WATER_BODY_THRESHOLDS.get(water_body, WATER_BODY_THRESHOLDS["river"])
    lines = []

    if not is_anomaly:
        lines.append(f"Water quality is within normal parameters for a {water_body}.")
    else:
        type_name = ANOMALY_TYPES[anomaly_type_int].replace("_", " ").title()
        lines.append(f"Anomaly detected — {type_name}.")

        tds = sensor.get("tds", 0)
        ph  = sensor.get("ph", 7)
        if tds > wbt["tds_moderate"]:
            lines.append(f"TDS at {tds:.0f} ppm (threshold for {water_body}: {wbt['tds_moderate']:.0f} ppm).")
        if ph < wbt["ph_acid"]:
            lines.append(f"pH at {ph:.1f} — acidic for a {water_body} (limit: {wbt['ph_acid']}).")
        if ph > wbt["ph_alkaline"]:
            lines.append(f"pH at {ph:.1f} — alkaline for a {water_body} (limit: {wbt['ph_alkaline']}).")

    if conf["data_mode"] == "sensor_only":
        lines.append(
            f"Satellite data is {satellite_age_days} days old — result based on live sensor readings only."
        )
    elif conf["data_mode"] == "partial":
        lines.append(f"Satellite data is {satellite_age_days} days old. Confidence slightly reduced.")

    if weather.get("rain_penalty", 0) > 0.1:
        lines.append(weather["weather_note"])

    if conf["confidence_pct"] < 65:
        days_to_fresh = max(0, 5 - satellite_age_days)
        lines.append(
            f"Confidence: {conf['confidence_pct']}%. "
            f"Re-test when fresh satellite data arrives (~{days_to_fresh} days)."
        )

    return " ".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class AquaSenseInference:
    """
    Wraps train.py's predict_single() with staleness-aware confidence
    and a live Arduino CSV reader. This is the only class your API needs.
    """

    def __init__(
        self,
        model_path: str | Path,
        satellite_parquet: str | Path,
        lat: float = 41.99,
        lon: float = 21.43,
        water_body: str = "river",
    ):
        self.lat        = lat
        self.lon        = lon
        self.water_body = water_body.lower()

        if self.water_body not in WATER_BODY_THRESHOLDS:
            raise ValueError(f"water_body must be one of: {list(WATER_BODY_THRESHOLDS.keys())}")

        # Apply water body overrides to the global THRESHOLDS so classify_anomaly_type
        # (imported from train.py) automatically uses the right thresholds
        THRESHOLDS.update(WATER_BODY_THRESHOLDS[self.water_body])

        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        self._pipeline = joblib.load(model_path)
        log.info(f"Model loaded from {model_path}")

        self._sat_path = Path(satellite_parquet)
        self._load_satellite()

        self._history: list[dict] = []   # rolling buffer, max 60

    def _load_satellite(self):
        if not self._sat_path.exists():
            raise FileNotFoundError(f"Satellite parquet not found: {self._sat_path}")
        # load_satellite_data() from train.py handles interpolation + log1p
        df = load_satellite_data(self._sat_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        self._sat_df = df.sort_values("timestamp").reset_index(drop=True)
        log.info(
            f"Satellite loaded: {len(self._sat_df)} rows, "
            f"latest: {self._sat_df['timestamp'].max().date()}"
        )

    def reload_satellite(self):
        """Hot-reload parquet after a new OpenEO download — no restart needed."""
        self._load_satellite()

    def read_arduino_csv(self, csv_path: str | Path) -> dict:
        """
        Reads the latest row from the Arduino output.csv produced by reading_data.py.
        Handles both headered and raw-line CSV formats.
        Returns {"tds": float, "ph": float, "timestamp": datetime}
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"Arduino CSV not found: {csv_path}")

        try:
            df = pd.read_csv(csv_path)
            df.columns = [c.lower().strip() for c in df.columns]
            last    = df.iloc[-1]
            ts_col  = next((c for c in df.columns if "time" in c or "date" in c), None)
            tds_col = next((c for c in df.columns if "tds" in c), None)
            ph_col  = next((c for c in df.columns if c == "ph"), None)

            return {
                "tds":       float(last[tds_col]) if tds_col else 0.0,
                "ph":        float(last[ph_col])  if ph_col  else 7.0,
                "timestamp": pd.to_datetime(last[ts_col]).to_pydatetime() if ts_col else datetime.now(),
            }
        except Exception:
            # Fallback: raw lines "timestamp,ph,tds_ppm"
            lines = csv_path.read_text().strip().splitlines()
            parts = lines[-1].split(",")
            return {
                "timestamp": pd.to_datetime(parts[0]).to_pydatetime(),
                "ph":        float(parts[1]),
                "tds":       float(parts[2]),
            }

    def predict_from_arduino(self, csv_path: str | Path) -> dict:
        """
        Full pipeline: read latest Arduino row -> predict -> return alert dict.
        This is what api.py calls on every user measurement.
        """
        sensor = self.read_arduino_csv(csv_path)
        return self.predict(
            sensor_reading={"tds": sensor["tds"], "ph": sensor["ph"]},
            timestamp=sensor.get("timestamp"),
        )

    def predict(
        self,
        sensor_reading: dict,
        timestamp: Optional[str | datetime] = None,
        history_df: Optional[pd.DataFrame] = None,
    ) -> dict:
        """
        Core prediction. Calls predict_single() from train.py then wraps
        the result with confidence adjustment.

        Args:
            sensor_reading: {"tds": float, "ph": float}
            timestamp:      ISO string or datetime (default: now)
            history_df:     Recent observations for rolling z-scores.
                            Falls back to internal _history buffer if None.
        """
        if timestamp is None:
            ts = datetime.now()
        elif isinstance(timestamp, str):
            ts = pd.to_datetime(timestamp).to_pydatetime()
        else:
            ts = timestamp

        # Satellite context
        sat_ctx = _get_satellite_context(self._sat_df, ts)
        age     = sat_ctx["satellite_age_days"]

        # Weather
        weather = _fetch_weather(self.lat, self.lon, ts)

        # Zero satellite features when stale
        sat_feat = sat_ctx["sat_features"].copy()
        if age > SATELLITE_USABLE_DAYS:
            log.info(f"Satellite {age}d old — sensor-only mode")
            sat_feat = {k: 0.0 for k in sat_feat}

        # History for rolling stats
        hist = history_df if history_df is not None else (
            pd.DataFrame(self._history) if self._history else None
        )

        # Build feature vector
        obs = _build_feature_vector(sensor_reading, sat_feat, ts, hist, self.water_body)

        # ── Call train.py predict_single — the actual RF ──────────────────────
        train_result  = predict_single(self._pipeline, FEATURE_COLUMNS, obs)
        base_score    = train_result["anomaly_score"]

        # Confidence adjustment layer
        conf          = _compute_confidence(age, weather["rain_penalty"], base_score)
        adj_score     = conf["adjusted_anomaly_score"]
        is_anomaly    = adj_score > 0.5
        sev           = severity_level(adj_score)
        low_conf_warn = conf["confidence_pct"] < 65 or conf["data_mode"] == "sensor_only"

        # Anomaly type — integer needed for message builder
        anom_type_str = train_result["anomaly_type"] if is_anomaly else "normal"
        anom_type_int = next(
            (k for k, v in ANOMALY_TYPES.items() if v == anom_type_str), 0
        )

        # Explanation — suppress satellite-derived root cause when confidence low
        if not is_anomaly:
            explanation = f"All parameters within normal range for a {self.water_body}."
        elif low_conf_warn:
            explanation = (
                f"Anomaly detected (confidence {conf['confidence_pct']}%). "
                "Root cause withheld — satellite data is stale or heavy rainfall "
                "may be influencing satellite-derived features. Verify with updated data."
            )
        else:
            explanation = train_result["explanation"]

        message = _build_message(
            is_anomaly, anom_type_int, conf, weather,
            sensor_reading, age, self.water_body
        )

        # Update internal history
        self._history.append({**obs, "timestamp": ts})
        if len(self._history) > 60:
            self._history = self._history[-60:]

        return {
            "timestamp":              ts.isoformat(),
            "is_anomaly":             is_anomaly,
            "anomaly_type":           anom_type_str,
            "severity":               sev,
            "anomaly_score":          round(base_score, 4),
            "adjusted_score":         adj_score,
            "confidence_pct":         conf["confidence_pct"],
            "data_mode":              conf["data_mode"],
            "satellite_date":         sat_ctx["satellite_date"],
            "satellite_age_days":     age,
            "water_body":             self.water_body,
            "weather": {
                "total_rain_7d_mm":   weather["total_rain_7d_mm"],
                "rain_on_day_mm":     weather["rain_on_day_mm"],
                "rain_penalty_pct":   round(weather["rain_penalty"] * 100),
                "note":               weather["weather_note"],
            },
            "sensor": {
                "tds_ppm": round(sensor_reading.get("tds", 0), 1),
                "ph":      round(sensor_reading.get("ph", 0), 2),
            },
            "explanation":            explanation,
            "message":                message,
            "low_confidence_warning": low_conf_warn,
        }


# ─────────────────────────────────────────────────────────────────────────────
# CLI quick-test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")

    engine = AquaSenseInference(
        model_path="models/rf_anomaly_model.pkl",
        satellite_parquet="vardar_wq_results/vardar_wq_merged.parquet",
        lat=41.99, lon=21.43,
        water_body="river",
    )

    result = engine.predict({"tds": 650.0, "ph": 6.8})
    print(json.dumps(result, indent=2))