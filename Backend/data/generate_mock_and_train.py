"""
generate_mock_and_train.py
==========================
Generates realistic mock data for ALL data sources, then trains the model.
Run this ONCE before touching the Arduino.

Generates:
    mock_data/satellite_features.parquet   — Sentinel-2 WQ indices (monthly)
    mock_data/lst_readings.parquet         — Sentinel-3 SLSTR temperature (daily, gaps included)
    mock_data/sensor_readings.csv          — Arduino pH + TDS (every 2 days)
    mock_data/expert_labels.csv            — Anomaly event labels

Then runs:
    python train.py --satellite ... --lst ... --sensor ... --labels ... --output models/

Usage:
    python generate_mock_and_train.py
"""

import numpy as np
import pandas as pd
from pathlib import Path
import subprocess
import sys

SEED = 42
rng  = np.random.default_rng(SEED)
Path("mock_data").mkdir(exist_ok=True)

print("=" * 60)
print("AquaSense — Mock Data Generator")
print("=" * 60)


# ── 1. Sentinel-2 WQ satellite data (monthly, 2022–2024) ─────────────────────
print("\n[1/4] Generating Sentinel-2 WQ satellite mock data...")

dates     = pd.date_range("2022-01-01", "2024-12-01", freq="MS")
n         = len(dates)
month_arr = dates.month.values
sin_m     = np.sin(2 * np.pi * month_arr / 12)

sat = pd.DataFrame({
    "timestamp":     dates,
    "ndwi":          0.20 + 0.10 * sin_m + rng.normal(0, 0.04, n),
    "ndti":          0.05 + 0.04 * np.abs(sin_m) + rng.normal(0, 0.03, n),
    "ndci":          0.02 + 0.06 * np.clip(sin_m, 0, 1) + rng.normal(0, 0.03, n),
    "chl_a":         8.0  + 5.0  * np.clip(sin_m, 0, 1) + rng.uniform(0, 3, n),
    "cyanobacteria": 2000 + 3000 * np.clip(sin_m, 0, 1) + rng.uniform(0, 1000, n),
    "turbidity_sat": 20.0 + 15.0 * np.abs(sin_m) + rng.uniform(0, 10, n),
    "cdom":          60.0 + 20.0 * sin_m + rng.uniform(0, 15, n),
    "doc":           50.0 + 15.0 * sin_m + rng.uniform(0, 10, n),
})

# 6 anomaly months spread across the 3 years, different seasons
anomaly_months = [4, 14, 18, 24, 29, 33]
for i in anomaly_months:
    sat.loc[i, "ndci"]          = rng.uniform(0.22, 0.42)
    sat.loc[i, "cyanobacteria"] = rng.uniform(30000, 90000)
    sat.loc[i, "turbidity_sat"] = rng.uniform(90, 200)
    sat.loc[i, "ndti"]          = rng.uniform(0.30, 0.50)
    sat.loc[i, "chl_a"]         = rng.uniform(28, 55)

sat.to_parquet("mock_data/satellite_features.parquet", index=False)
print(f"  Saved {len(sat)} monthly satellite rows")
print(f"  Anomaly months at indices: {anomaly_months}")
for i in anomaly_months:
    print(f"    {sat.loc[i, 'timestamp'].strftime('%Y-%m')}  "
          f"NDCI={sat.loc[i,'ndci']:.2f}  "
          f"Cyano={sat.loc[i,'cyanobacteria']:.0f}")


# ── 2. Sentinel-3 SLSTR LST data (daily, 2022–2024, with realistic cloud gaps) ──
print("\n[2/4] Generating Sentinel-3 SLSTR temperature mock data...")

daily_dates  = pd.date_range("2022-01-01", "2024-12-31", freq="D")
d            = len(daily_dates)
month_daily  = daily_dates.month.values

# Realistic Vardar river temp: ~4°C winter, ~26°C summer (peaks in July)
base_temp_c  = 15.0 + 11.0 * np.sin(2 * np.pi * (month_daily - 3) / 12)
daily_temp   = base_temp_c + rng.normal(0, 1.5, d)
daily_temp   = np.clip(daily_temp, 1.0, 35.0)

# Cloud probability: higher in winter (50%), lower in summer (20%)
sin_d        = np.sin(2 * np.pi * (month_daily - 3) / 12)
cloud_prob   = 0.35 - 0.15 * np.clip(sin_d, 0, 1)
is_cloudy    = rng.random(d) < cloud_prob

lst_celsius        = np.where(is_cloudy, np.nan, daily_temp)
lst_valid_px_count = np.where(is_cloudy, 0, rng.integers(15, 80, d))

# Inject temperature anomalies aligned with satellite anomaly months
anomaly_type_map = {
    4:  (2, "algal_bloom",          "hot"),    # summer — hot water → bloom
    14: (4, "industrial_discharge", "hot"),    # summer discharge
    18: (6, "acid_mine_drainage",   "cold"),   # mine drainage — cold upwelling
    24: (2, "algal_bloom",          "hot"),    # summer bloom
    29: (1, "turbidity_event",      "normal"), # no temp signal for turbidity
    33: (4, "industrial_discharge", "cold"),   # winter cold discharge
}

for i in anomaly_months:
    target  = sat.loc[i, "timestamp"]
    d_mask  = (daily_dates >= target) & (daily_dates < target + pd.Timedelta("30D"))
    _, _, temp_type = anomaly_type_map.get(i, (1, "", "normal"))
    valid_in_window = d_mask & ~is_cloudy
    if valid_in_window.sum() == 0:
        continue
    if temp_type == "hot":
        lst_celsius[valid_in_window] = rng.uniform(28, 33, valid_in_window.sum())
    elif temp_type == "cold":
        lst_celsius[valid_in_window] = rng.uniform(2, 7, valid_in_window.sum())
    # "normal" — leave temperature unchanged (turbidity doesn't have a temp signal)

lst_df = pd.DataFrame({
    "timestamp":            daily_dates,
    "lst_water_celsius":    lst_celsius,
    "lst_water_kelvin":     np.where(np.isnan(lst_celsius), np.nan, lst_celsius + 273.15),
    "lst_valid_px_count":   lst_valid_px_count.astype(int),
})

lst_df.to_parquet("mock_data/lst_readings.parquet", index=False)
valid_n = lst_df["lst_water_celsius"].notna().sum()
print(f"  Saved {len(lst_df)} daily LST rows")
print(f"  Cloud-free days: {valid_n}/{d} ({100*valid_n/d:.0f}% coverage)")
print(f"  Temperature range: {lst_df['lst_water_celsius'].min():.1f}°C "
      f"to {lst_df['lst_water_celsius'].max():.1f}°C")


# ── 3. Arduino sensor data (every 2 days, 2022–2024) ─────────────────────────
print("\n[3/4] Generating Arduino sensor mock data...")

sensor_dates = pd.date_range("2022-01-01", "2024-12-31", freq="2D")
m            = len(sensor_dates)
month_s      = sensor_dates.month.values
sin_s        = np.sin(2 * np.pi * month_s / 12)

# Realistic Vardar baselines
base_tds = 280.0 + 80.0 * np.abs(sin_s)
base_ph  = 7.6   - 0.2  * sin_s

sensor = pd.DataFrame({
    "timestamp": sensor_dates,
    "ph":        np.clip(base_ph  + rng.normal(0, 0.15, m), 6.5, 8.5),
    "tds_ppm":   np.clip(base_tds + rng.normal(0, 40,   m), 80,  600),
})

for i in anomaly_months:
    target = sat.loc[i, "timestamp"]
    mask   = (sensor_dates >= target) & (sensor_dates < target + pd.Timedelta("28D"))
    if mask.sum() == 0:
        continue
    sensor.loc[mask, "tds_ppm"] = rng.uniform(900, 2800, mask.sum())
    sensor.loc[mask, "ph"]      = rng.uniform(4.2, 5.8,  mask.sum())

# Add sensor-only anomaly events (no corresponding satellite signal)
# These teach the model that extreme pH or TDS alone is anomalous
sensor_only_anomaly_dates = pd.date_range("2022-03-01", "2024-10-01", freq="6MS")
for d in sensor_only_anomaly_dates:
    mask = (sensor_dates >= d) & (sensor_dates < d + pd.Timedelta("14D"))
    if mask.sum() == 0:
        continue
    event = rng.integers(0, 3)
    if event == 0:   # extreme acid (pH crash, moderate TDS)
        sensor.loc[mask, "ph"]      = rng.uniform(1.5, 4.0, mask.sum())
        sensor.loc[mask, "tds_ppm"] = rng.uniform(50, 300, mask.sum())
    elif event == 1: # industrial discharge (TDS spike, neutral pH)
        sensor.loc[mask, "tds_ppm"] = rng.uniform(1500, 3500, mask.sum())
        sensor.loc[mask, "ph"]      = rng.uniform(6.0, 7.5, mask.sum())
    else:            # combined acid mine drainage
        sensor.loc[mask, "tds_ppm"] = rng.uniform(900, 2500, mask.sum())
        sensor.loc[mask, "ph"]      = rng.uniform(2.5, 5.0, mask.sum())

sensor.to_csv("mock_data/sensor_readings.csv", index=False)
print(f"  Saved {len(sensor)} sensor readings (every 2 days)")
print(f"  Normal TDS: {sensor['tds_ppm'].quantile(0.05):.0f}–"
      f"{sensor['tds_ppm'].quantile(0.95):.0f} ppm")
print(f"  Normal pH:  {sensor['ph'].quantile(0.05):.2f}–"
      f"{sensor['ph'].quantile(0.95):.2f}")


# ── 4. Expert labels ──────────────────────────────────────────────────────────
print("\n[4/4] Generating expert labels...")

label_rows = []
for i in anomaly_months:
    d_start   = sat.loc[i, "timestamp"]
    d_end     = d_start + pd.Timedelta("27D")
    atype, label_name, _ = anomaly_type_map.get(i, (1, "turbidity_event", ""))
    label_rows.append({
        "date_start":   d_start.strftime("%Y-%m-%d"),
        "date_end":     d_end.strftime("%Y-%m-%d"),
        "anomaly":      1,
        "anomaly_type": atype,
        "notes":        f"mock — {label_name}",
    })

# Add sensor-only anomaly labels
sensor_only_anomaly_dates = pd.date_range("2022-03-01", "2024-10-01", freq="6MS")
for d in sensor_only_anomaly_dates:
    label_rows.append({
        "date_start":   d.strftime("%Y-%m-%d"),
        "date_end":     (d + pd.Timedelta("13D")).strftime("%Y-%m-%d"),
        "anomaly":      1,
        "anomaly_type": 4,
        "notes":        "mock — sensor_only_event",
    })

labels_df = pd.DataFrame(label_rows)
labels_df.to_csv("mock_data/expert_labels.csv", index=False)
print(f"  Saved {len(labels_df)} labeled events")
for _, row in labels_df.iterrows():
    print(f"    {row['date_start']} – {row['date_end']}  |  "
          f"type={row['anomaly_type']} ({row['notes']})")


# ── 5. Train ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Training RF model on mock data...")
print("=" * 60 + "\n")

result = subprocess.run([
    sys.executable, "train.py",
    "--satellite", "mock_data/satellite_features.parquet",
    "--lst",       "mock_data/lst_readings.parquet",
    "--sensor",    "mock_data/sensor_readings.csv",
    "--labels",    "mock_data/expert_labels.csv",
    "--output",    "models/",
], capture_output=False)

print("\n" + "=" * 60)
if result.returncode == 0:
    print("Model trained and saved.")
    print()
    print("Files created:")
    print("  models/rf_anomaly_model.pkl")
    print("  models/model_metadata.json")
    print("  models/feature_importance.csv")
    print()
    print("Run order from here:")
    print("  Test (no Arduino): python watch_arduino.py --demo")
    print("  Plug in Arduino")
    print("  Terminal 1:        python reading_data.py")
    print("  Terminal 2:        python watch_arduino.py")
else:
    print("Training FAILED — read the errors above.")
    print("Install missing packages:")
    print("  pip install scikit-learn pandas numpy pyarrow scipy joblib")