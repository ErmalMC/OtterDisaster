"""
AquaSense — Water Quality Anomaly Detection Training Script
===========================================================
Trains a Random Forest anomaly detector that fuses:
  - Satellite-derived features (NDWI, NDTI, NDCI, Chl-a, Cyanobacteria, Turbidity, CDOM, DOC)
  - In-situ Arduino sensor readings (TDS, pH)
  - Engineered features (rolling Z-scores, seasonal encoding, interaction terms)

The model outputs an anomaly_score [0, 1] per observation.
Anomaly type classification uses a rule-based layer on top of RF score.

Usage:
    python train.py --satellite data/satellite_features.parquet \
                    --sensor    data/sensor_readings.csv \
                    --labels    data/expert_labels.csv \       # optional — see labeling section
                    --output    models/
"""

import argparse
import json
import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import (
    classification_report, roc_auc_score,
    average_precision_score, confusion_matrix
)
from sklearn.inspection import permutation_importance
import joblib

warnings.filterwarnings("ignore", category=UserWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 1. CONFIGURATION & THRESHOLDS
#    (Review with your domain expert)
# ─────────────────────────────────────────────

THRESHOLDS = {
    # Satellite indices
    "ndwi_min": 0.10,  # below = not water pixel, skip
    "ndti_high": 0.25,  # turbidity anomaly
    "ndci_bloom": 0.20,  # algal bloom forming
    "ndci_severe": 0.35,  # severe bloom
    # UDF-derived WQ
    "chl_a_high": 25.0,  # mg/m³ — EU WFD threshold
    "cyano_alert": 20.0, # 10³ cells/ml — WHO bathing ban
    "turbidity_high": 100.0,  # NTU
    "cdom_high": 160.0,  # adjusted for satellite-derived scale
    "doc_high": 145.0, # mg/l — adjusted for satellite-derived scale
    # Arduino sensor
    "tds_moderate": 800.0,  # ppm
    "tds_severe": 2000.0,  # ppm
    "ph_acid": 6.0,  # acid event
    "ph_alkaline": 9.0,  # alkaline event
    # Statistical
    "zscore_anomaly": 2.5,  # |Z| > 2.5 = anomaly candidate
    "zscore_rolling_window": 30,  # days for rolling baseline
    # Interaction
    "acid_mine_tds": 800.0,  # TDS threshold for acid mine detection
    "acid_mine_ph": 6.5,  # pH threshold for acid mine detection
}

# Anomaly type labels — shown to users on the dashboard
ANOMALY_TYPES = {
    0: "normal",
    1: "turbidity_event",  # sediment, runoff, mining
    2: "algal_bloom",  # nutrient enrichment, eutrophication
    3: "toxic_cyanobacteria",  # worst case — health emergency
    4: "industrial_discharge",  # factory/chemical — TDS + pH combo
    5: "organic_pollution",  # wastewater, decomposition
    6: "acid_mine_drainage",  # pH crash + TDS spike
}

FEATURE_COLUMNS = [
    # Satellite indices
    "ndwi", "ndti", "ndci",
    # UDF-derived WQ params
    "chl_a", "cyanobacteria", "turbidity_sat", "cdom", "doc",
    # Arduino
    "tds", "ph",
    # Engineered
    "sin_month", "cos_month",
    "tds_ph_interaction",
    "ndci_chl_product",
    "z_ndti", "z_ndci", "z_chl_a", "z_cyano", "z_tds", "z_ph",
    "multi_feature_z_count",  # how many features are anomalous simultaneously
    # Lag features
    "tds_lag1", "ph_lag1", "ndti_lag1",
    "tds_delta", "ph_delta",  # change from previous observation
]


# ─────────────────────────────────────────────
# 2. DATA LOADING
# ─────────────────────────────────────────────

def load_satellite_data(path: Path) -> pd.DataFrame:
    """
    Load openEO-exported satellite features.
    Expected columns: timestamp, ndwi, ndti, ndci,
                      chl_a, cyanobacteria, turbidity_sat, cdom, doc

    NOTE: NDWI water-pixel filter is skipped because spatial averaging over
    the full bounding box (river + surrounding land) produces negative NDWI
    even for valid river observations. The RF learns from all available pixels.

    Monthly satellite rows are interpolated to weekly frequency to give the
    model enough observations to align with the dense Arduino sensor data.
    """
    log.info(f"Loading satellite data from {path}")
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=["timestamp"])

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    log.info(f"Satellite data loaded: {len(df)} monthly observations")

    # ── Expand monthly → weekly via linear interpolation ──────────────────
    # This gives ~4x more rows for the RF to train on and improves
    # alignment with the Arduino sensor data (which is every 2 days).
    df = df.set_index("timestamp")
    weekly_index = pd.date_range(df.index.min(), df.index.max(), freq="W")
    df = df.reindex(df.index.union(weekly_index))
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].interpolate(method="time")
    df = df.loc[weekly_index].reset_index().rename(columns={"index": "timestamp"})
    log.info(f"Expanded to {len(df)} weekly observations via interpolation")

    if "cyanobacteria" in df.columns:
        df["cyanobacteria"] = np.log1p(df["cyanobacteria"].clip(lower=0))

    return df


def load_sensor_data(path: Path) -> pd.DataFrame:
    """
    Load Arduino sensor CSV.
    Expected columns: timestamp, tds_ppm, ph
    Arduino sends data every N minutes — we resample to daily median for satellite fusion.
    """
    log.info(f"Loading sensor data from {path}")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp")

    # Basic quality filters
    df = df[(df["ph"] >= 0) & (df["ph"] <= 14)]
    df = df[(df["tds_ppm"] >= 0) & (df["tds_ppm"] <= 10000)]

    # Rename to standard names
    df = df.rename(columns={"tds_ppm": "tds"})

    # Resample to daily median to align with satellite pass (~5 day frequency)
    df = df.set_index("timestamp")
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df = df[numeric_cols].resample("D").median().reset_index()
    df.columns.name = None

    log.info(f"Sensor data: {len(df)} daily records after resampling")
    return df


def merge_satellite_sensor(sat_df: pd.DataFrame, sensor_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge satellite observations with nearest sensor reading.
    Satellite passes ~every 5 days; sensor is daily.
    We use merge_asof (time-nearest join) with a 3-day tolerance.
    """
    log.info("Merging satellite + sensor data on timestamp (nearest join, ±3 days)")

    sat_df = sat_df.sort_values("timestamp")
    sensor_df = sensor_df.sort_values("timestamp")

    merged = pd.merge_asof(
        sat_df,
        sensor_df[["timestamp", "tds", "ph"]],
        on="timestamp",
        tolerance=pd.Timedelta("7D"),  # widened to match weekly satellite cadence
        direction="nearest"
    )

    n_matched = merged[["tds", "ph"]].notna().all(axis=1).sum()
    log.info(f"Sensor match: {n_matched}/{len(merged)} satellite obs have sensor data")

    return merged


# ─────────────────────────────────────────────
# 3. FEATURE ENGINEERING
# ─────────────────────────────────────────────

def add_seasonal_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cyclical encoding of month — critical for separating seasonal from anomalous."""
    df["month"] = df["timestamp"].dt.month
    df["sin_month"] = np.sin(2 * np.pi * df["month"] / 12)
    df["cos_month"] = np.cos(2 * np.pi * df["month"] / 12)
    return df


def add_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Domain-informed interaction terms.
    These capture multi-parameter pollution signatures.
    """
    # Acid mine drainage signature: high TDS + low pH
    df["tds_ph_interaction"] = df["tds"] * (14 - df["ph"])

    # Algal pressure: both chlorophyll and spectral index elevated
    df["ndci_chl_product"] = df["ndci"] * df["chl_a"].clip(lower=0)

    return df


def add_rolling_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rolling Z-scores per feature over a 30-day window.
    This computes how far each observation is from its own recent baseline.
    This IS the median baseline comparison the RF will learn from.
    """
    window = THRESHOLDS["zscore_rolling_window"]
    z_features = ["ndti", "ndci", "chl_a", "cyanobacteria", "tds", "ph"]

    for feat in z_features:
        if feat not in df.columns:
            continue
        roll = df[feat].rolling(window=window, min_periods=5)
        roll_mean = roll.mean()
        roll_std = roll.std().replace(0, np.nan)
        df[f"z_{feat}"] = (df[feat] - roll_mean) / roll_std

    # Count of features simultaneously anomalous — very powerful signal
    z_cols = [f"z_{f}" for f in z_features if f"z_{f}" in df.columns]
    df["multi_feature_z_count"] = (df[z_cols].abs() > THRESHOLDS["zscore_anomaly"]).sum(axis=1)

    return df


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Previous-observation values and deltas.
    A sudden change is often more diagnostic than the absolute value.
    """
    for feat in ["tds", "ph", "ndti"]:
        if feat in df.columns:
            df[f"{feat}_lag1"] = df[feat].shift(1)
            df[f"{feat}_delta"] = df[feat] - df[feat].shift(1)
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Engineering features...")
    df = add_seasonal_features(df)
    df = add_interaction_features(df)
    df = add_rolling_zscores(df)
    df = add_lag_features(df)

    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    missing = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        log.warning(f"Missing features (will use zeros): {missing}")
        for c in missing:
            df[c] = 0.0

    return df, available


# ─────────────────────────────────────────────
# 4. LABELING
#    Two strategies — with or without expert labels
# ─────────────────────────────────────────────

def rule_based_labels(df: pd.DataFrame) -> pd.Series:
    """
    Generate binary anomaly labels using domain thresholds.
    Use this BEFORE you have expert labels — it bootstraps training.
    Your domain expert should REVIEW and CORRECT these labels.
    Returns: pd.Series of int (0=normal, 1=anomaly)
    """
    t = THRESHOLDS
    conditions = [
        df["ndti"] > t["ndti_high"],
        df["ndci"] > t["ndci_bloom"],
        df["chl_a"] > t["chl_a_high"],
        df["cyanobacteria"] > t["cyano_alert"],
        df["turbidity_sat"] > t["turbidity_high"],
        df["cdom"] > t["cdom_high"],
        df["doc"] > t["doc_high"],
        df["tds"] > t["tds_moderate"],
        df["ph"] < t["ph_acid"],
        df["ph"] > t["ph_alkaline"],
        df["multi_feature_z_count"] >= 2,
    ]
    return pd.Series(
        np.where(np.any([c.fillna(False) for c in conditions], axis=0), 1, 0),
        index=df.index
    )


def classify_anomaly_type(row: pd.Series) -> int:
    """
    Rule-based anomaly type classification.
    Applied AFTER the RF flags an anomaly to tell the user WHAT happened.
    Returns: int key into ANOMALY_TYPES dict
    """
    t = THRESHOLDS

    # Highest priority first
    if row.get("cyanobacteria", 0) > t["cyano_alert"]:
        return 3  # toxic cyanobacteria — health emergency

    if (row.get("tds", 0) > t["acid_mine_tds"] and
            row.get("ph", 7) < t["acid_mine_ph"]):
        return 6  # acid mine drainage

    if row.get("tds", 0) > t["tds_moderate"]:
        return 4  # industrial discharge

    if (row.get("ndci", 0) > t["ndci_bloom"] or
            row.get("chl_a", 0) > t["chl_a_high"]):
        return 2  # algal bloom

    if (row.get("cdom", 0) > t["cdom_high"] or
            row.get("doc", 0) > t["doc_high"]):
        return 5  # organic pollution

    if row.get("ndti", 0) > t["ndti_high"]:
        return 1  # turbidity event

    return 1  # default: turbidity/general


def merge_expert_labels(df: pd.DataFrame, labels_path: Path) -> pd.Series:
    """
    Load expert-labeled events and override rule-based labels.
    Expert label CSV format:
        date_start, date_end, anomaly (0/1), anomaly_type (int), notes
    """
    log.info(f"Loading expert labels from {labels_path}")
    labels = pd.read_csv(labels_path, parse_dates=["date_start", "date_end"])
    y = rule_based_labels(df)

    for _, event in labels.iterrows():
        mask = (df["timestamp"] >= event["date_start"]) & \
               (df["timestamp"] <= event["date_end"])
        y[mask] = int(event["anomaly"])
        log.info(f"  Expert label: {event['date_start'].date()} – {event['date_end'].date()} "
                 f"→ {'ANOMALY' if event['anomaly'] else 'normal'} | {event.get('notes', '')}")

    return y


# ─────────────────────────────────────────────
# 5. UNSUPERVISED PRE-SCREENING (Isolation Forest)
#    Finds anomalies with NO labels at all
#    Use this first to discover events for expert review
# ─────────────────────────────────────────────

def run_isolation_forest(X: np.ndarray, feature_names: list) -> np.ndarray:
    """
    Isolation Forest for zero-label anomaly discovery.
    Returns anomaly scores (higher = more anomalous).
    Use the output to prioritize which dates to show your domain expert.
    """
    log.info("Running Isolation Forest for unsupervised pre-screening...")
    iso = IsolationForest(
        n_estimators=200,
        contamination=0.05,  # assume ~5% of river observations are anomalous
        random_state=42,
        n_jobs=-1
    )
    iso.fit(X)
    # decision_function: lower = more anomalous → negate and normalize to [0,1]
    raw_scores = iso.decision_function(X)
    scores = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())
    log.info(f"Isolation Forest: top anomaly score = {scores.max():.3f}, "
             f"flagged {(scores > 0.7).sum()} observations (score > 0.7)")
    return scores


# ─────────────────────────────────────────────
# 6. RANDOM FOREST TRAINING
# ─────────────────────────────────────────────

def train_random_forest(X: np.ndarray, y: np.ndarray, feature_names: list) -> dict:
    """
    Train the main RF anomaly classifier.
    Handles class imbalance (anomalies are rare) with class_weight='balanced'.
    Returns trained pipeline + metrics.
    """
    log.info("Training Random Forest classifier...")
    log.info(f"  Dataset: {len(y)} observations | {y.sum()} anomalies ({100 * y.mean():.1f}%)")

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("rf", RandomForestClassifier(
            n_estimators=300,
            max_depth=12,
            min_samples_leaf=5,
            class_weight="balanced",  # critical for rare anomaly class
            n_jobs=-1,
            random_state=42,
            oob_score=True,
        ))
    ])

    # Cross-validated performance
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    log.info("Running 5-fold cross-validation...")
    roc_scores = cross_val_score(pipeline, X, y, cv=cv, scoring="roc_auc", n_jobs=-1)
    ap_scores = cross_val_score(pipeline, X, y, cv=cv, scoring="average_precision", n_jobs=-1)

    log.info(f"  ROC-AUC:  {roc_scores.mean():.3f} ± {roc_scores.std():.3f}")
    log.info(f"  Avg Precision: {ap_scores.mean():.3f} ± {ap_scores.std():.3f}")

    # Final fit on all data
    pipeline.fit(X, y)
    rf = pipeline.named_steps["rf"]

    log.info(f"  OOB score (accuracy proxy): {rf.oob_score_:.3f}")

    # Feature importance
    importance_df = pd.DataFrame({
        "feature": feature_names,
        "importance": rf.feature_importances_
    }).sort_values("importance", ascending=False)

    log.info("Top 10 most important features:")
    for _, row in importance_df.head(10).iterrows():
        log.info(f"  {row['feature']:30s}  {row['importance']:.4f}")

    return {
        "pipeline": pipeline,
        "cv_roc_auc": float(roc_scores.mean()),
        "cv_avg_precision": float(ap_scores.mean()),
        "feature_importance": importance_df,
        "feature_names": feature_names,
    }


# ─────────────────────────────────────────────
# 7. INFERENCE (single observation → alert)
# ─────────────────────────────────────────────

def predict_single(pipeline, feature_names: list, observation: dict) -> dict:
    """
    Given a single observation dict (from satellite + sensor),
    returns: anomaly_score, is_anomaly, anomaly_type, explanation

    This is what the web app calls in real-time.
    """
    X = pd.DataFrame([observation])[feature_names].fillna(0).values
    proba_matrix = pipeline.predict_proba(X)
    # If only one class was seen during training, proba_matrix has 1 column
    if proba_matrix.shape[1] == 1:
        trained_class = pipeline.named_steps["rf"].classes_[0]
        proba = float(trained_class)  # 1.0 if all anomaly, 0.0 if all normal
    else:
        proba = proba_matrix[0, 1]
    is_anomaly = proba > 0.5

    anomaly_type = 0
    explanation = "All parameters within normal range."

    if is_anomaly:
        obs = pd.Series(observation)
        anomaly_type = classify_anomaly_type(obs)
        explanation = build_explanation(obs, anomaly_type, proba)

    return {
        "anomaly_score": round(float(proba), 4),
        "is_anomaly": bool(is_anomaly),
        "anomaly_type": ANOMALY_TYPES[anomaly_type],
        "severity": severity_level(proba),
        "explanation": explanation,
    }


def severity_level(score: float) -> str:
    if score < 0.4:   return "normal"
    if score < 0.6:   return "watch"
    if score < 0.8:   return "warning"
    return "critical"


def build_explanation(obs: pd.Series, anomaly_type: int, score: float) -> str:
    """
    Human-readable explanation of what triggered the anomaly.
    This is what the dashboard shows to the end user.
    """
    type_name = ANOMALY_TYPES[anomaly_type]
    parts = [f"Anomaly detected ({type_name}, confidence {score:.0%})."]

    if obs.get("cyanobacteria", 0) > THRESHOLDS["cyano_alert"]:
        parts.append(f"Cyanobacteria at {obs['cyanobacteria']:.0f}k cells/ml "
                     f"(WHO limit: 100k). Potential health hazard — avoid water contact.")

    if obs.get("tds", 0) > THRESHOLDS["tds_moderate"]:
        parts.append(f"TDS elevated at {obs['tds']:.0f} ppm "
                     f"(normal: 200–500 ppm). Possible industrial or mining discharge.")

    if obs.get("ph", 7) < THRESHOLDS["ph_acid"]:
        parts.append(f"pH at {obs['ph']:.1f} — acidic event detected. "
                     f"Check upstream mining or industrial activity.")

    if obs.get("ndci", 0) > THRESHOLDS["ndci_bloom"]:
        parts.append(f"NDCI at {obs['ndci']:.2f} — algal bloom forming. "
                     f"Likely elevated nutrients from agricultural runoff.")

    if obs.get("multi_feature_z_count", 0) >= 3:
        parts.append(f"{int(obs['multi_feature_z_count'])} parameters simultaneously "
                     f"outside normal range — high confidence event.")

    return " ".join(parts)


# ─────────────────────────────────────────────
# 8. MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AquaSense training pipeline")
    parser.add_argument("--satellite", type=Path, required=True)
    parser.add_argument("--sensor", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=None,
                        help="Optional expert labels CSV. If omitted, uses rule-based labels.")
    parser.add_argument("--output", type=Path, default=Path("models/"))
    parser.add_argument("--discover", action="store_true",
                        help="Run Isolation Forest to discover events for expert labeling")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # --- Load & merge ---
    sat_df = load_satellite_data(args.satellite)
    sensor_df = load_sensor_data(args.sensor)
    df = merge_satellite_sensor(sat_df, sensor_df)

    # --- Feature engineering ---
    df, feature_names = engineer_features(df)
    X = df[feature_names].fillna(0).values

    # --- Isolation Forest discovery mode ---
    if args.discover:
        iso_scores = run_isolation_forest(X, feature_names)
        df["iso_anomaly_score"] = iso_scores
        discovery_path = args.output / "discovery_candidates.csv"
        top = df.nlargest(50, "iso_anomaly_score")[
            ["timestamp", "iso_anomaly_score"] + feature_names[:8]
            ]
        top.to_csv(discovery_path, index=False)
        log.info(f"Discovery mode: top 50 anomaly candidates saved to {discovery_path}")
        log.info("Share this file with your domain expert for labeling.")
        return

    # --- Labels ---
    if args.labels and args.labels.exists():
        y = merge_expert_labels(df, args.labels)
    else:
        log.warning("No expert labels provided — using rule-based labels for bootstrapping.")
        log.warning("Run with --discover first, get expert labels, then retrain.")
        y = rule_based_labels(df)

    # --- Train RF ---
    results = train_random_forest(X, y.values, feature_names)
    pipeline = results["pipeline"]

    # --- Save model artifacts ---
    model_path = args.output / "rf_anomaly_model.pkl"
    joblib.dump(pipeline, model_path)
    log.info(f"Model saved to {model_path}")

    # Save metadata
    meta = {
        "feature_names": feature_names,
        "thresholds": THRESHOLDS,
        "anomaly_types": ANOMALY_TYPES,
        "cv_roc_auc": results["cv_roc_auc"],
        "cv_avg_precision": results["cv_avg_precision"],
        "n_train": int(len(y)),
        "n_anomalies": int(y.sum()),
        "anomaly_rate": float(y.mean()),
    }
    meta_path = args.output / "model_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Save feature importance
    fi_path = args.output / "feature_importance.csv"
    results["feature_importance"].to_csv(fi_path, index=False)

    log.info(f"Training complete. Artifacts saved to {args.output}/")
    log.info(f"  ROC-AUC: {results['cv_roc_auc']:.3f}  |  Avg Precision: {results['cv_avg_precision']:.3f}")

    # Demo: show what a single prediction looks like
    log.info("\n--- Demo prediction on last observation ---")
    demo_obs = df.iloc[-1][feature_names].to_dict()
    result = predict_single(pipeline, feature_names, demo_obs)
    log.info(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()