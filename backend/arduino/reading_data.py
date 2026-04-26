import serial
import os
import csv
import time
import argparse
import numpy as np
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument("--port",   default="/dev/ttyUSB0")
parser.add_argument("--output", default=None)
parser.add_argument("--window", default=10, type=int, help="Seconds per median window")
parser.add_argument("--baud",   default=9600, type=int)
args = parser.parse_args()

output_file = args.output or os.path.join(os.path.dirname(__file__), "arduino_output.csv")
write_header = not os.path.exists(output_file)

print(f"Saving to {output_file}")
print(f"Collecting {args.window}s median windows...")

with serial.Serial(args.port, args.baud, timeout=2) as ser:
    time.sleep(2)  # let Arduino reset after connect
    with open(output_file, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "tds", "ph", "sample_count"])
        if write_header:
            writer.writeheader()

        while True:
            tds_readings, ph_readings = [], []
            deadline = time.time() + args.window
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Collecting {args.window}s...")

            while time.time() < deadline:
                try:
                    line = ser.readline().decode("utf-8").strip()
                    if not line:
                        continue
                    # Parse "TDS:420.5,PH:7.23"
                    parts = dict(p.split(":") for p in line.split(",") if ":" in p)
                    tds = float(parts.get("TDS") or parts.get("tds"))
                    ph  = float(parts.get("PH")  or parts.get("ph"))
                    tds_readings.append(tds)
                    ph_readings.append(ph)
                    print(f"  raw → TDS:{tds} pH:{ph}")
                except Exception:
                    continue

            if not tds_readings:
                print("  ⚠ No valid readings, skipping window.")
                continue

            row = {
                "timestamp":    datetime.now().isoformat(),
                "tds":          round(float(np.median(tds_readings)), 2),
                "ph":           round(float(np.median(ph_readings)),  3),
                "sample_count": len(tds_readings),
            }
            writer.writerow(row)
            f.flush()
            print(f"  ✅ median → TDS:{row['tds']} ppm | pH:{row['ph']} | samples:{row['sample_count']}")