"""
AquaSense — Water Quality Anomaly Detection Training Script
===========================================================
Changes in this version:
  + Sentinel-3 SLSTR surface water temperature integration
    - New --lst argument: path to vardar_lst_merged.parquet
    - Three new features added to FEATURE_COLUMNS:
        lst_water_celsius  — surface temperature in °C (NaN when no reading)
        lst_age_days       — days since last valid SLSTR reading (0–30+)
        lst_weight         — exp(-age / LST_DECAY_DAYS) staleness weight
    - The RF learns that a fresh temperature reading (weight ~1.0) is
      highly informative, while a 14-day-old reading (weight ~0.14) should
      be discounted. Feeding both the value AND the weight as features lets
      the RF figure out the correct interaction without us hard-coding it.
    - Temperature is important because cyanobacteria blooms require
      sustained water temp > 20°C, and acid mine drainage often shows
      anomalously cold surface readings (upwelling of deep mine water).
    - When no LST data exists at all, lst_weight=0 so the feature is
      effectively switched off — the model degrades gracefully.
  + z_cyano fix (from previous version): expm1 before rolling z-score
  + merge tolerance 14D (from previous version)

Usage:
    python train.py \
        --satellite vardar_wq_results/vardar_wq_merged.parquet \
        --lst       vardar_wq_results/vardar_lst_merged.parquet \
        --sensor    data/sensor_readings.csv \
        --labels    data/expert_labels.csv \
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
# ─────────────────────────────────────────────

THRESHOLDS = {
    # Satellite indices
    "ndwi_min":    0.10,
    "ndti_high":   0.25,
    "ndci_bloom":  0.20,
    "ndci_severe": 0.35,
    # UDF-derived WQ
    "chl_a_high":    25.0,
    "cyano_alert":   20.0,
    "turbidity_high": 100.0,
    "cdom_high":     160.0,
    "doc_high":      145.0,
    # Arduino sensor
    "tds_moderate": 800.0,
    "tds_severe":   2000.0,
    "ph_acid":      6.0,
    "ph_alkaline":  9.0,
    # Statistical
    "zscore_anomaly":        2.5,
    "zscore_rolling_window": 30,
    # Interaction
    "acid_mine_tds": 800.0,
    "acid_mine_ph":  6.5,
    # Temperature thresholds (Sentinel-3 SLSTR)
    # River Vardar: typical range 4°C (winter) to 28°C (summer)
    "lst_bloom_risk_celsius": 20.0,   # above this = bloom risk season
    "lst_cold_anomaly_celsius": 8.0,  # below this in summer = possible cold upwelling
    "lst_hot_anomaly_celsius": 30.0,  # above this = thermal stress / stagnation
}

ANOMALY_TYPES = {
    0: "normal",
    1: "turbidity_event",
    2: "algal_bloom",
    3: "toxic_cyanobacteria",
    4: "industrial_discharge",
    5: "organic_pollution",
    6: "acid_mine_drainage",
}

# ── LST staleness decay constant ─────────────────────────────────────────────
# exp(-age / LST_DECAY_DAYS) gives the weight:
#   0 days old  → weight = 1.00 (full trust)
#   7 days old  → weight = 0.37 (still useful)
#  14 days old  → weight = 0.14 (weak signal)
#  30 days old  → weight = 0.02 (near-zero, essentially ignored)
#
# Why 7 days? River surface temperature in temperate climates typically
# changes 0.5–2°C/day in spring/autumn, less in summer/winter.
# A 7-day reading might be 3–14°C off from the current value — still
# directionally informative but not precise enough to fully trust.
LST_DECAY_DAYS = 7.0

FEATURE_COLUMNS = [
    # Sentinel-2 derived
    "ndwi", "ndti", "ndci",
    "chl_a", "cyanobacteria", "turbidity_sat", "cdom", "doc",
    # Arduino sensor
    "tds", "ph",
    # Sentinel-3 SLSTR surface water temperature — NEW
    "lst_water_celsius",  # actual temperature value (NaN → filled to seasonal mean)
    "lst_age_days",       # how many days since this reading was taken
    "lst_weight",         # exp(-age/7) — staleness decay weight [0, 1]
    # Engineered
    "sin_month", "cos_month",
    "tds_ph_interaction",
    "ndci_chl_product",
    # Temperature interaction terms — NEW
    "lst_cyano_risk",     # lst_weight * (lst_celsius > 20°C flag) * ndci
    "lst_tds_interaction",# hot water + high TDS = evaporation/industrial signature
    # Rolling Z-scores
    "z_ndti", "z_ndci", "z_chl_a", "z_cyano", "z_tds", "z_ph",
    "z_lst",              # rolling Z-score of temperature — NEW
    "multi_feature_z_count",
    # Lag features
    "tds_lag1", "ph_lag1", "ndti_lag1",
    "tds_delta", "ph_delta",
    "lst_delta",          # temperature change from previous valid reading — NEW
]


# ─────────────────────────────────────────────
# 2. DATA LOADING
# ─────────────────────────────────────────────

def load_satellite_data(path: Path) -> pd.DataFrame:
    """Load Sentinel-2 WQ features (unchanged from previous version)."""
    log.info(f"[S2] Loading satellite data from {path}")
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=["timestamp"])

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    log.info(f"[S2] Loaded {len(df)} monthly observations")

    # Expand monthly → weekly via linear interpolation
    df = df.set_index("timestamp")
    weekly_index = pd.date_range(df.index.min(), df.index.max(), freq="W")
    df = df.reindex(df.index.union(weekly_index))
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].interpolate(method="time")
    df = df.loc[weekly_index].reset_index().rename(columns={"index": "timestamp"})
    log.info(f"[S2] Expanded to {len(df)} weekly observations")

    if "cyanobacteria" in df.columns:
        df["cyanobacteria"] = np.log1p(df["cyanobacteria"].clip(lower=0))

    return df


def load_lst_data(path: Path) -> pd.DataFrame:
    """
    Load Sentinel-3 SLSTR surface temperature data produced by main.py.

    The raw parquet has one row per day with:
        timestamp            — observation date
        lst_water_celsius    — spatially averaged surface temp (NaN = cloudy)
        lst_valid_px_count   — how many pixels were valid that day

    This function:
    1. Keeps all days (including NaN days — we need the gaps to compute age)
    2. Does NOT interpolate — we want to know exactly when data was missing
       because that gap length is what becomes lst_age_days
    3. Forward-fills lst_age_days to carry forward the staleness counter

    Returns a daily DataFrame with columns:
        timestamp, lst_water_celsius, lst_age_days, lst_weight
    """
    log.info(f"[S3] Loading LST data from {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    total_days  = len(df)
    valid_days  = (df["lst_water_celsius"].notna()).sum()
    log.info(f"[S3] {total_days} days total | {valid_days} with valid LST readings "
             f"({100 * valid_days / max(total_days, 1):.0f}% coverage)")

    # Compute age: how many days since the last valid reading
    # This is the staleness clock — resets to 0 on each valid observation
    last_valid_date = None
    ages = []
    for _, row in df.iterrows():
        if pd.notna(row["lst_water_celsius"]):
            last_valid_date = row["timestamp"]
            ages.append(0)
        else:
            if last_valid_date is None:
                ages.append(999)  # no data yet at all — use max staleness
            else:
                ages.append((row["timestamp"] - last_valid_date).days)

    df["lst_age_days"] = ages

    # Staleness weight: exponential decay
    # Fresh reading (age=0): weight=1.0
    # 7-day-old reading:     weight=0.37
    # 14-day-old reading:    weight=0.14
    df["lst_weight"] = np.exp(-df["lst_age_days"] / LST_DECAY_DAYS)

    # When we have no temperature value, forward-fill the LAST KNOWN temperature
    # but DO NOT change lst_age_days or lst_weight — those correctly reflect staleness
    df["lst_water_celsius"] = df["lst_water_celsius"].ffill()

    # If there's still NaN (no prior data at all), use the dataset mean
    global_mean_lst = df["lst_water_celsius"].mean()
    df["lst_water_celsius"] = df["lst_water_celsius"].fillna(global_mean_lst)

    log.info(f"[S3] LST range: {df['lst_water_celsius'].min():.1f}°C – "
             f"{df['lst_water_celsius'].max():.1f}°C | "
             f"mean age {df['lst_age_days'].mean():.1f} days")
    return df


def load_sensor_data(path: Path) -> pd.DataFrame:
    """Load Arduino sensor CSV (unchanged)."""
    log.info(f"Loading sensor data from {path}")
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp")
    df = df[(df["ph"] >= 0) & (df["ph"] <= 14)]
    df = df[(df["tds_ppm"] >= 0) & (df["tds_ppm"] <= 10000)]
    df = df.rename(columns={"tds_ppm": "tds"})
    df = df.set_index("timestamp")
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df = df[numeric_cols].resample("D").median().reset_index()
    df.columns.name = None
    log.info(f"Sensor: {len(df)} daily records after resampling")
    return df


def merge_satellite_sensor(sat_df: pd.DataFrame, sensor_df: pd.DataFrame) -> pd.DataFrame:
    """Merge Sentinel-2 WQ with Arduino sensor (unchanged, 14D tolerance)."""
    log.info("Merging S2 WQ + sensor (nearest join, ±14 days)")
    merged = pd.merge_asof(
        sat_df.sort_values("timestamp"),
        sensor_df[["timestamp", "tds", "ph"]].sort_values("timestamp"),
        on="timestamp",
        tolerance=pd.Timedelta("14D"),
        direction="nearest"
    )
    n_matched = merged[["tds", "ph"]].notna().all(axis=1).sum()
    log.info(f"Sensor match: {n_matched}/{len(merged)} rows have sensor data")
    return merged


def merge_lst(main_df: pd.DataFrame, lst_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge the LST data into the main training dataframe.

    Strategy: merge_asof with NO tolerance limit — we always want a temperature
    value, but lst_age_days + lst_weight tell the model how fresh that value is.
    The RF will learn to discount old readings automatically via lst_weight.

    This is intentionally different from the sensor merge (which uses 14D tolerance
    and leaves NaN when no match). Here we never leave NaN because even a 30-day-old
    temperature reading provides seasonal context — we just weight it near zero.
    """
    log.info("Merging LST data (forward-fill, no tolerance limit)")

    # lst_df has daily rows; main_df has weekly rows after S2 expansion
    lst_merge = lst_df[["timestamp", "lst_water_celsius", "lst_age_days", "lst_weight"]].copy()

    merged = pd.merge_asof(
        main_df.sort_values("timestamp"),
        lst_merge.sort_values("timestamp"),
        on="timestamp",
        direction="backward",    # use the most recent past LST reading
        tolerance=None,          # no cutoff — age/weight encode staleness
    )

    valid_lst = merged["lst_water_celsius"].notna().sum()
    log.info(f"LST merge: {valid_lst}/{len(merged)} rows have LST value "
             f"| mean age {merged['lst_age_days'].mean():.1f} days "
             f"| mean weight {merged['lst_weight'].mean():.2f}")
    return merged


# ─────────────────────────────────────────────
# 3. FEATURE ENGINEERING
# ─────────────────────────────────────────────

def add_seasonal_features(df: pd.DataFrame) -> pd.DataFrame:
    df["month"] = df["timestamp"].dt.month
    df["sin_month"] = np.sin(2 * np.pi * df["month"] / 12)
    df["cos_month"] = np.cos(2 * np.pi * df["month"] / 12)
    return df


def add_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    df["tds_ph_interaction"] = df["tds"] * (14 - df["ph"])
    df["ndci_chl_product"]   = df["ndci"] * df["chl_a"].clip(lower=0)

    # ── NEW: Temperature interaction features ─────────────────────────────────
    if "lst_water_celsius" in df.columns:
        lst_c      = df["lst_water_celsius"].fillna(0)
        lst_weight = df["lst_weight"].fillna(0)

        # Bloom risk = temperature above 20°C AND NDCI elevated.
        # Weighted by freshness so a stale hot reading doesn't falsely trigger.
        # This encodes the ecological fact that cyanobacteria need warm AND
        # nutrient-rich conditions simultaneously.
        bloom_flag = (lst_c > THRESHOLDS["lst_bloom_risk_celsius"]).astype(float)
        df["lst_cyano_risk"] = lst_weight * bloom_flag * df["ndci"].fillna(0).clip(lower=0)

        # TDS × temperature interaction: evaporation concentrates dissolved solids
        # in hot, slow-moving water (salt signature in summer). Also catches
        # industrial discharge which often raises both temperature and TDS.
        df["lst_tds_interaction"] = lst_weight * lst_c * df["tds"].fillna(0) / 1000.0
        # Divide by 1000 to keep the product in a similar scale to other features

    else:
        df["lst_cyano_risk"]    = 0.0
        df["lst_tds_interaction"] = 0.0

    return df


def add_rolling_zscores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rolling Z-scores. Includes z_lst for temperature anomaly.
    z_cyano fix retained: expm1 before rolling so we work in real units.
    """
    window    = THRESHOLDS["zscore_rolling_window"]
    z_features = ["ndti", "ndci", "chl_a", "cyanobacteria", "tds", "ph"]

    cyano_real = None
    if "cyanobacteria" in df.columns:
        cyano_real = np.expm1(df["cyanobacteria"].clip(lower=0))

    for feat in z_features:
        if feat not in df.columns:
            continue
        series   = cyano_real if feat == "cyanobacteria" else df[feat]
        roll     = series.rolling(window=window, min_periods=5)
        roll_mean = roll.mean()
        roll_std  = roll.std().replace(0, np.nan)
        df[f"z_{feat}"] = (series - roll_mean) / roll_std

    # ── NEW: Temperature rolling Z-score ─────────────────────────────────────
    # z_lst tells the model if TODAY'S temperature is anomalous relative to
    # the recent seasonal baseline — e.g. July that is 8°C colder than normal
    # could indicate upwelling from mining activity above the sampling point.
    # We only compute z_lst when we have a fresh reading (weight > 0.1) so that
    # stale, forward-filled temperatures don't generate false Z-score signals.
    if "lst_water_celsius" in df.columns and "lst_weight" in df.columns:
        lst_series = df["lst_water_celsius"].copy()
        # Mask stale values so they don't pull the rolling window
        lst_series_fresh = lst_series.where(df["lst_weight"] > 0.1, other=np.nan)
        roll_lst     = lst_series_fresh.rolling(window=window, min_periods=3)
        roll_lst_mean = roll_lst.mean()
        roll_lst_std  = roll_lst.std().replace(0, np.nan)
        df["z_lst"] = (lst_series - roll_lst_mean) / roll_lst_std
        # Weight the Z-score by freshness: stale readings get near-zero z_lst
        df["z_lst"] = df["z_lst"] * df["lst_weight"]
    else:
        df["z_lst"] = 0.0

    # Multi-feature anomaly count (now includes z_lst)
    z_cols_base = [f"z_{f}" for f in z_features if f"z_{f}" in df.columns]
    z_cols_all  = z_cols_base + (["z_lst"] if "z_lst" in df.columns else [])
    df["multi_feature_z_count"] = (
        df[z_cols_all].abs() > THRESHOLDS["zscore_anomaly"]
    ).sum(axis=1)

    return df


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """Lag features. Adds lst_delta — temperature change from last valid reading."""
    for feat in ["tds", "ph", "ndti"]:
        if feat in df.columns:
            df[f"{feat}_lag1"] = df[feat].shift(1)
            df[f"{feat}_delta"] = df[feat] - df[feat].shift(1)

    # ── NEW: Temperature delta ────────────────────────────────────────────────
    # A sudden temperature drop in summer (e.g. -5°C over a week) can signal
    # cold industrial effluent or mine drainage before chemical sensors respond.
    if "lst_water_celsius" in df.columns:
        df["lst_delta"] = df["lst_water_celsius"].diff()
        # Weight by freshness of BOTH current and previous reading
        # (if either is stale, the delta is unreliable)
        prev_weight = df["lst_weight"].shift(1).fillna(0)
        curr_weight = df["lst_weight"].fillna(0)
        combined_weight = np.minimum(prev_weight, curr_weight)
        df["lst_delta"] = df["lst_delta"] * combined_weight
    else:
        df["lst_delta"] = 0.0

    return df


def engineer_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    log.info("Engineering features...")
    df = add_seasonal_features(df)
    df = add_interaction_features(df)
    df = add_rolling_zscores(df)
    df = add_lag_features(df)

    available = [c for c in FEATURE_COLUMNS if c in df.columns]
    missing   = [c for c in FEATURE_COLUMNS if c not in df.columns]
    if missing:
        log.warning(f"Missing features (zeroed): {missing}")
        for c in missing:
            df[c] = 0.0

    return df, FEATURE_COLUMNS


# ─────────────────────────────────────────────
# 4. LABELING
# ─────────────────────────────────────────────

def rule_based_labels(df: pd.DataFrame) -> pd.Series:
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
        # Temperature-based rules — only fire when reading is fresh (weight > 0.5)
        (df.get("lst_water_celsius", pd.Series(0, index=df.index)) > t["lst_hot_anomaly_celsius"])
        & (df.get("lst_weight", pd.Series(0, index=df.index)) > 0.5),
    ]
    return pd.Series(
        np.where(np.any([c.fillna(False) for c in conditions], axis=0), 1, 0),
        index=df.index
    )


def classify_anomaly_type(row: pd.Series) -> int:
    t = THRESHOLDS

    if row.get("cyanobacteria", 0) > t["cyano_alert"]:
        return 3  # toxic cyanobacteria

    if (row.get("tds", 0) > t["acid_mine_tds"] and
            row.get("ph", 7) < t["acid_mine_ph"]):
        return 6  # acid mine drainage

    # ── NEW: Warm + high TDS → industrial signature ───────────────────────────
    # A cold temperature anomaly combined with high TDS suggests cold mine
    # effluent mixing into warmer river water — reinforces acid_mine classification.
    lst_c      = row.get("lst_water_celsius", 15.0)
    lst_weight = row.get("lst_weight", 0.0)
    if (row.get("tds", 0) > t["tds_moderate"] and
            lst_weight > 0.3 and lst_c > t["lst_hot_anomaly_celsius"]):
        return 4  # industrial discharge (hot + high TDS)

    if row.get("tds", 0) > t["tds_moderate"]:
        return 4  # industrial discharge

    # ── NEW: Warm + NDCI bloom ────────────────────────────────────────────────
    # Upgrade from algal_bloom to toxic_cyanobacteria confidence when temperature
    # exceeds the bloom risk threshold AND NDCI is in bloom territory.
    if ((row.get("ndci", 0) > t["ndci_bloom"] or row.get("chl_a", 0) > t["chl_a_high"])
            and lst_weight > 0.3 and lst_c > t["lst_bloom_risk_celsius"]):
        return 2  # algal bloom, with temperature-supported confidence

    if (row.get("ndci", 0) > t["ndci_bloom"] or row.get("chl_a", 0) > t["chl_a_high"]):
        return 2

    if (row.get("cdom", 0) > t["cdom_high"] or row.get("doc", 0) > t["doc_high"]):
        return 5  # organic pollution

    if row.get("ndti", 0) > t["ndti_high"]:
        return 1  # turbidity event

    return 1


def merge_expert_labels(df: pd.DataFrame, labels_path: Path) -> pd.Series:
    log.info(f"Loading expert labels from {labels_path}")
    labels = pd.read_csv(labels_path, parse_dates=["date_start", "date_end"])
    y = rule_based_labels(df)
    for _, event in labels.iterrows():
        mask = (df["timestamp"] >= event["date_start"]) & \
               (df["timestamp"] <= event["date_end"])
        y[mask] = int(event["anomaly"])
        log.info(f"  Expert: {event['date_start'].date()} – {event['date_end'].date()} "
                 f"→ {'ANOMALY' if event['anomaly'] else 'normal'}")
    return y


# ─────────────────────────────────────────────
# 5. UNSUPERVISED PRE-SCREENING
# ─────────────────────────────────────────────

def run_isolation_forest(X: np.ndarray, feature_names: list) -> np.ndarray:
    log.info("Running Isolation Forest for unsupervised pre-screening...")
    iso = IsolationForest(n_estimators=200, contamination=0.05,
                          random_state=42, n_jobs=-1)
    iso.fit(X)
    raw_scores = iso.decision_function(X)
    scores = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())
    log.info(f"Isolation Forest: top score = {scores.max():.3f}, "
             f"flagged {(scores > 0.7).sum()} observations")
    return scores


# ─────────────────────────────────────────────
# 6. RANDOM FOREST TRAINING
# ─────────────────────────────────────────────

def train_random_forest(X: np.ndarray, y: np.ndarray, feature_names: list) -> dict:
    log.info("Training Random Forest classifier...")
    log.info(f"  Dataset: {len(y)} obs | {y.sum()} anomalies ({100*y.mean():.1f}%)")

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("rf", RandomForestClassifier(
            n_estimators=300,
            max_depth=12,
            min_samples_leaf=5,
            class_weight="balanced",
            n_jobs=-1,
            random_state=42,
            oob_score=True,
        ))
    ])

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    log.info("Running 5-fold cross-validation...")
    roc_scores = cross_val_score(pipeline, X, y, cv=cv, scoring="roc_auc", n_jobs=-1)
    ap_scores  = cross_val_score(pipeline, X, y, cv=cv, scoring="average_precision", n_jobs=-1)
    log.info(f"  ROC-AUC:  {roc_scores.mean():.3f} ± {roc_scores.std():.3f}")
    log.info(f"  Avg Prec: {ap_scores.mean():.3f} ± {ap_scores.std():.3f}")

    pipeline.fit(X, y)
    rf = pipeline.named_steps["rf"]
    log.info(f"  OOB score: {rf.oob_score_:.3f}")

    importance_df = pd.DataFrame({
        "feature":    feature_names,
        "importance": rf.feature_importances_
    }).sort_values("importance", ascending=False)

    log.info("Top 15 most important features:")
    for _, row in importance_df.head(15).iterrows():
        lst_tag = " ← temperature" if "lst" in row["feature"] else ""
        log.info(f"  {row['feature']:35s}  {row['importance']:.4f}{lst_tag}")

    return {
        "pipeline":           pipeline,
        "cv_roc_auc":         float(roc_scores.mean()),
        "cv_avg_precision":   float(ap_scores.mean()),
        "feature_importance": importance_df,
        "feature_names":      feature_names,
    }


# ─────────────────────────────────────────────
# 7. INFERENCE
# ─────────────────────────────────────────────

def predict_single(pipeline, feature_names: list, observation: dict) -> dict:
    X = pd.DataFrame([observation])[feature_names].fillna(0).values
    proba_matrix = pipeline.predict_proba(X)
    if proba_matrix.shape[1] == 1:
        trained_class = pipeline.named_steps["rf"].classes_[0]
        proba = float(trained_class)
    else:
        proba = proba_matrix[0, 1]
    is_anomaly   = proba > 0.5
    anomaly_type = 0
    explanation  = "All parameters within normal range."

    if is_anomaly:
        obs          = pd.Series(observation)
        anomaly_type = classify_anomaly_type(obs)
        explanation  = build_explanation(obs, anomaly_type, proba)

    return {
        "anomaly_score": round(float(proba), 4),
        "is_anomaly":    bool(is_anomaly),
        "anomaly_type":  ANOMALY_TYPES[anomaly_type],
        "severity":      severity_level(proba),
        "explanation":   explanation,
    }


def severity_level(score: float) -> str:
    if score < 0.4: return "normal"
    if score < 0.6: return "watch"
    if score < 0.8: return "warning"
    return "critical"


def build_explanation(obs: pd.Series, anomaly_type: int, score: float) -> str:
    type_name = ANOMALY_TYPES[anomaly_type]
    parts = [f"Anomaly detected ({type_name}, confidence {score:.0%})."]

    if obs.get("cyanobacteria", 0) > THRESHOLDS["cyano_alert"]:
        parts.append(f"Cyanobacteria at {obs['cyanobacteria']:.0f}k cells/ml. Potential health hazard.")

    if obs.get("tds", 0) > THRESHOLDS["tds_moderate"]:
        parts.append(f"TDS elevated at {obs['tds']:.0f} ppm. Possible industrial/mining discharge.")

    if obs.get("ph", 7) < THRESHOLDS["ph_acid"]:
        parts.append(f"pH at {obs['ph']:.1f} — acidic event. Check upstream mining activity.")

    if obs.get("ndci", 0) > THRESHOLDS["ndci_bloom"]:
        parts.append(f"NDCI at {obs['ndci']:.2f} — algal bloom forming.")

    # ── NEW: Temperature explanation ──────────────────────────────────────────
    lst_c      = obs.get("lst_water_celsius")
    lst_weight = obs.get("lst_weight", 0)
    lst_age    = obs.get("lst_age_days", 999)
    if lst_c is not None and lst_weight > 0.2:
        freshness = f"({int(lst_age)}d old reading)" if lst_age > 0 else "(today's reading)"
        if lst_c > THRESHOLDS["lst_hot_anomaly_celsius"]:
            parts.append(f"Surface water temperature {lst_c:.1f}°C {freshness} — "
                         f"thermal stress threshold exceeded ({THRESHOLDS['lst_hot_anomaly_celsius']}°C). "
                         f"Stagnant warm water increases bloom risk and dissolved oxygen depletion.")
        elif lst_c > THRESHOLDS["lst_bloom_risk_celsius"]:
            parts.append(f"Surface water at {lst_c:.1f}°C {freshness} — "
                         f"bloom risk season (>{THRESHOLDS['lst_bloom_risk_celsius']}°C). "
                         f"Temperature favours cyanobacteria over eukaryotic algae.")
        elif (obs.get("z_lst", 0) or 0) < -2.0:
            parts.append(f"Surface water {lst_c:.1f}°C {freshness} — anomalously cold for this season. "
                         f"Possible cold effluent or mine water mixing.")
    elif lst_weight <= 0.2 and lst_c is not None:
        parts.append(f"Temperature data is {int(lst_age)} days old (weight={lst_weight:.2f}) — "
                     f"too stale to use as diagnostic. Last reading: {lst_c:.1f}°C.")

    if obs.get("multi_feature_z_count", 0) >= 3:
        parts.append(f"{int(obs['multi_feature_z_count'])} parameters simultaneously "
                     f"outside normal range — high confidence multi-parameter event.")

    return " ".join(parts)


# ─────────────────────────────────────────────
# 8. MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AquaSense training pipeline")
    parser.add_argument("--satellite", type=Path, required=True,
                        help="Path to Sentinel-2 WQ merged parquet")
    parser.add_argument("--lst", type=Path, default=None,
                        help="Path to Sentinel-3 SLSTR LST merged parquet (optional)")
    parser.add_argument("--sensor", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("models/"))
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    # ── Load & merge ──────────────────────────────────────────────────────────
    sat_df    = load_satellite_data(args.satellite)
    sensor_df = load_sensor_data(args.sensor)
    df        = merge_satellite_sensor(sat_df, sensor_df)

    # ── Merge LST if provided ─────────────────────────────────────────────────
    if args.lst and args.lst.exists():
        lst_df = load_lst_data(args.lst)
        df = merge_lst(df, lst_df)
        log.info(f"LST merged. Mean lst_weight = {df['lst_weight'].mean():.2f} "
                 f"(1.0 = always fresh, 0.0 = always stale)")
    else:
        log.warning("No --lst path provided. Temperature features will be zeroed.")
        log.warning("Run main.py to download Sentinel-3 SLSTR data, then retrain.")
        df["lst_water_celsius"] = np.nan
        df["lst_age_days"]      = 999
        df["lst_weight"]        = 0.0

    # ── Feature engineering ───────────────────────────────────────────────────
    df, feature_names = engineer_features(df)
    X = df[feature_names].fillna(0).values

    # ── Isolation Forest discovery mode ───────────────────────────────────────
    if args.discover:
        iso_scores = run_isolation_forest(X, feature_names)
        df["iso_anomaly_score"] = iso_scores
        discovery_path = args.output / "discovery_candidates.csv"
        display_cols   = ["timestamp", "iso_anomaly_score"] + feature_names[:8]
        if "lst_water_celsius" in df.columns:
            display_cols.insert(3, "lst_water_celsius")
            display_cols.insert(4, "lst_age_days")
        top = df.nlargest(50, "iso_anomaly_score")[display_cols]
        top.to_csv(discovery_path, index=False)
        log.info(f"Discovery: top 50 candidates → {discovery_path}")
        return

    # ── Labels ────────────────────────────────────────────────────────────────
    if args.labels and args.labels.exists():
        y = merge_expert_labels(df, args.labels)
    else:
        log.warning("No expert labels — using rule-based labels.")
        y = rule_based_labels(df)

    # ── Train ─────────────────────────────────────────────────────────────────
    results  = train_random_forest(X, y.values, feature_names)
    pipeline = results["pipeline"]

    # ── Save ──────────────────────────────────────────────────────────────────
    model_path = args.output / "rf_anomaly_model.pkl"
    joblib.dump(pipeline, model_path)
    log.info(f"Model saved → {model_path}")

    meta = {
        "feature_names":    feature_names,
        "thresholds":       THRESHOLDS,
        "anomaly_types":    ANOMALY_TYPES,
        "lst_decay_days":   LST_DECAY_DAYS,
        "lst_enabled":      args.lst is not None and args.lst.exists(),
        "cv_roc_auc":       results["cv_roc_auc"],
        "cv_avg_precision": results["cv_avg_precision"],
        "n_train":          int(len(y)),
        "n_anomalies":      int(y.sum()),
        "anomaly_rate":     float(y.mean()),
    }
    with open(args.output / "model_metadata.json", "w") as f:
        json.dump(meta, f, indent=2)

    results["feature_importance"].to_csv(args.output / "feature_importance.csv", index=False)

    log.info(f"\nTraining complete. ROC-AUC: {results['cv_roc_auc']:.3f} | "
             f"Avg Precision: {results['cv_avg_precision']:.3f}")

    # Demo prediction
    log.info("\n--- Demo prediction on last observation ---")
    demo_obs = df.iloc[-1][feature_names].to_dict()
    result   = predict_single(pipeline, feature_names, demo_obs)
    log.info(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()