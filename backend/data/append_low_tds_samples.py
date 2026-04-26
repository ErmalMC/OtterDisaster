"""
append_low_tds_samples.py
=========================
Appends realistic low-TDS and varied normal training samples to
sensor_readings.csv so the model stops treating clean/soft water
as anomalous.

Run BEFORE retraining:
    python append_low_tds_samples.py --sensor data/sensor_readings.csv

Then retrain as normal:
    python train.py --satellite mock_data/satellite_features.parquet \
                    --sensor data/sensor_readings.csv \
                    --output models/
"""

import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

rng = np.random.default_rng(42)


def generate_samples() -> pd.DataFrame:
    rows = []
    base = datetime(2024, 1, 1)

    # ── 1. Soft / mountain water (50–120 ppm, pH 6.8–7.6) ────────────────────
    # Natural rainwater-fed streams, upland rivers, glacial meltwater.
    # Completely normal — model must NOT flag these.
    n = 120
    rows.append(pd.DataFrame({
        "timestamp": [base + timedelta(hours=i*2) for i in range(n)],
        "ph":        rng.uniform(6.8, 7.6, n).round(2),
        "tds_ppm":   rng.uniform(50, 120, n).round(1),
        "label":     0,   # normal
        "note":      "soft_water_normal",
    }))

    # ── 2. Your actual tap-water readings (150–200 ppm, pH 6.9–7.5) ──────────
    # Matches what the probes are actually seeing right now in tap water.
    n = 80
    rows.append(pd.DataFrame({
        "timestamp": [base + timedelta(hours=200 + i*2) for i in range(n)],
        "ph":        rng.uniform(6.9, 7.5, n).round(2),
        "tds_ppm":   rng.uniform(150, 200, n).round(1),
        "label":     0,
        "note":      "tap_water_normal",
    }))

    # ── 3. Very soft upland river (20–50 ppm, pH 6.5–7.4) ────────────────────
    # Borderline — below tds_too_low=50 threshold so correctly anomalous,
    # but we add a handful so the model has seen this region.
    n = 30
    rows.append(pd.DataFrame({
        "timestamp": [base + timedelta(hours=400 + i*3) for i in range(n)],
        "ph":        rng.uniform(6.5, 7.4, n).round(2),
        "tds_ppm":   rng.uniform(20, 49, n).round(1),
        "label":     1,   # anomaly — pure_water / extreme dilution
        "note":      "ultra_soft_anomaly",
    }))

    # ── 4. Distilled / probe-in-air (0–10 ppm, pH 5.5–7.2) ──────────────────
    # Sensor disconnect or distilled water — always anomalous.
    n = 40
    rows.append(pd.DataFrame({
        "timestamp": [base + timedelta(hours=500 + i*2) for i in range(n)],
        "ph":        rng.uniform(5.5, 7.2, n).round(2),
        "tds_ppm":   rng.uniform(0, 10, n).round(1),
        "label":     1,   # anomaly
        "note":      "distilled_anomaly",
    }))

    # ── 5. Normal river range with seasonal spread (200–450 ppm) ─────────────
    # More density in the range the model already knows, just to keep
    # the class balance healthy after adding the low-TDS rows.
    n = 100
    rows.append(pd.DataFrame({
        "timestamp": [base + timedelta(hours=700 + i*2) for i in range(n)],
        "ph":        rng.uniform(7.0, 8.2, n).round(2),
        "tds_ppm":   rng.uniform(200, 450, n).round(1),
        "label":     0,
        "note":      "normal_river_extra",
    }))

    return pd.concat(rows, ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sensor",
        default="data/sensor_readings.csv",
        help="Path to sensor_readings.csv (will be appended to)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be added without writing",
    )
    args = parser.parse_args()

    sensor_path = Path(args.sensor)

    new_df = generate_samples()

    print(f"\nNew samples to add: {len(new_df)}")
    print(new_df.groupby(["note", "label"]).size().to_string())
    print(f"\nTDS range: {new_df['tds_ppm'].min():.1f} – {new_df['tds_ppm'].max():.1f} ppm")
    print(f"pH range:  {new_df['ph'].min():.2f} – {new_df['ph'].max():.2f}")

    if args.dry_run:
        print("\n[dry-run] Nothing written.")
        return

    if sensor_path.exists():
        existing = pd.read_csv(sensor_path)
        print(f"\nExisting rows: {len(existing)}")

        # Align columns — drop 'note' and 'label' if existing file doesn't have them
        existing_cols = set(existing.columns)
        new_cols      = set(new_df.columns)
        shared_cols   = list(existing_cols & new_cols)

        # Always keep at minimum: timestamp, ph, tds_ppm
        must_have = {"timestamp", "ph", "tds_ppm"}
        if not must_have.issubset(existing_cols):
            print(f"ERROR: sensor CSV must have columns: {must_have}")
            print(f"  Found: {list(existing_cols)}")
            return

        combined = pd.concat(
            [existing[shared_cols], new_df[shared_cols]],
            ignore_index=True
        )
        combined["timestamp"] = pd.to_datetime(combined["timestamp"])
        combined = combined.sort_values("timestamp").reset_index(drop=True)

    else:
        print(f"\nNo existing file at {sensor_path} — creating new.")
        combined = new_df[["timestamp", "ph", "tds_ppm", "label", "note"]]

    # Backup original
    if sensor_path.exists():
        backup = sensor_path.with_suffix(".csv.bak")
        sensor_path.rename(backup)
        print(f"Backup saved → {backup}")

    combined.to_csv(sensor_path, index=False)
    print(f"Written {len(combined)} rows → {sensor_path}")
    print("\nNext step — retrain the model:")
    print(f"  python train.py --satellite mock_data/satellite_features.parquet \\")
    print(f"                  --sensor {sensor_path} \\")
    print(f"                  --output models/")


if __name__ == "__main__":
    main()