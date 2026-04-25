"""
AquaSense Expert Labeling Guide
================================
This script helps your domain expert label anomaly events.
It shows the top anomaly candidates from Isolation Forest discovery,
lets the expert accept/reject/reclassify each one, and saves a
labels CSV that the training script can consume.

Usage:
    python label_tool.py --candidates models/discovery_candidates.csv \
                         --output     data/expert_labels.csv
"""

import json
from pathlib import Path
import pandas as pd
import argparse

ANOMALY_TYPES = {
    0: "normal — not an anomaly",
    1: "turbidity_event — sediment, runoff, silt",
    2: "algal_bloom — nutrient enrichment, eutrophication",
    3: "toxic_cyanobacteria — health emergency level bloom",
    4: "industrial_discharge — factory/chemical, high TDS",
    5: "organic_pollution — wastewater, agricultural runoff",
    6: "acid_mine_drainage — pH crash + TDS spike (check upstream mines)",
}

ANOMALY_QUESTIONS = """
When classifying, consider:
  - Is there a known event near this date? (heavy rain, factory incident, agricultural season?)
  - Are multiple parameters elevated simultaneously?
  - Is the NDTI high but pH/TDS normal? → turbidity from rain, not chemical
  - Is TDS > 800 ppm AND pH < 6.5? → strong acid mine drainage signature
  - Is NDCI > 0.2 in summer? → possibly seasonal bloom, not anomaly
  - Is NDCI > 0.2 in winter? → anomaly — nutrient discharge
"""


def label_interactively(candidates_path: Path, output_path: Path):
    df = pd.read_csv(candidates_path)
    print(f"\nLoaded {len(df)} anomaly candidates for expert review.")
    print(ANOMALY_QUESTIONS)

    labels = []

    for idx, row in df.iterrows():
        print(f"\n{'='*60}")
        print(f"Candidate {idx+1}/{len(df)}")
        print(f"  Date:           {row['timestamp']}")
        print(f"  Anomaly score:  {row['iso_anomaly_score']:.3f}")
        print()

        # Show all available parameters
        params = {k: v for k, v in row.items()
                  if k not in ['timestamp', 'iso_anomaly_score']
                  and not pd.isna(v)}
        for k, v in params.items():
            print(f"  {k:25s}  {v:.4f}" if isinstance(v, float) else f"  {k:25s}  {v}")

        print()
        print("Is this an anomaly? [y/n/s=skip]:", end=" ")
        ans = input().strip().lower()

        if ans == "s":
            continue
        elif ans == "n":
            labels.append({
                "date_start": row["timestamp"],
                "date_end": row["timestamp"],
                "anomaly": 0,
                "anomaly_type": 0,
                "notes": "Expert: normal observation"
            })
        elif ans == "y":
            print("\nAnomaly type:")
            for k, v in ANOMALY_TYPES.items():
                print(f"  {k}: {v}")
            print("Enter type number:", end=" ")
            try:
                atype = int(input().strip())
            except ValueError:
                atype = 1

            print("Notes (optional):", end=" ")
            notes = input().strip()

            labels.append({
                "date_start": row["timestamp"],
                "date_end": row["timestamp"],
                "anomaly": 1,
                "anomaly_type": atype,
                "notes": notes,
            })

    out_df = pd.DataFrame(labels)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_path, index=False)
    print(f"\nSaved {len(out_df)} labels to {output_path}")
    print(f"  Anomalies: {out_df['anomaly'].sum()} / {len(out_df)}")
    print(f"\nNow run: python train.py --satellite ... --sensor ... --labels {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("OtterDisaster/data/expert_labels.csv"))
    args = parser.parse_args()
    label_interactively(args.candidates, args.output)