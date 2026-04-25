"""
demo.py
=======
Terminal live demo — NO frontend, NO Arduino required.

Runs inference on every row of arduino_output.csv (your real converted
data) and prints a full formatted result to the terminal.

Can also replay LIVE as if the Arduino is plugged in right now.

Modes:
  --csv arduino_output.csv       replay converted real data (default)
  --live arduino_output.csv      watch file for NEW rows (real-time, Arduino plugged in)
  --single ph=6.87 tds=120       predict a single manual reading

Usage:
    # Replay your converted real data:
    python demo.py

    # Replay with a delay (simulate live):
    python demo.py --delay 1.5

    # Watch file live (Arduino plugged in + reading_data.py running):
    python demo.py --live

    # Single manual reading:
    python demo.py --single --ph 6.87 --tds 120.0
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import logging
logging.disable(logging.CRITICAL)  # suppress noisy INFO/WARNING logs in demo


# ── ANSI colours ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
MAGENTA= "\033[95m"
DIM    = "\033[2m"

SEV_COLOR = {
    "normal":   GREEN,
    "watch":    YELLOW,
    "warning":  MAGENTA,
    "critical": RED,
}

def color(text, c): return f"{c}{text}{RESET}"
def bold(text):     return f"{BOLD}{text}{RESET}"


# ── Pretty printer ────────────────────────────────────────────────────────────

def print_banner():
    print()
    print(color("╔══════════════════════════════════════════════════════╗", CYAN))
    print(color("║        AquaSense — Live Demo (Terminal Mode)         ║", CYAN))
    print(color("╚══════════════════════════════════════════════════════╝", CYAN))
    print()


def print_result(result: dict, row_num: int, total: int | None = None):
    sev   = result.get("severity", "normal")
    sc    = SEV_COLOR.get(sev, RESET)
    prog  = f"[{row_num}/{total}]" if total else f"[{row_num}]"

    print(color("─" * 56, DIM))
    print(f"{bold(prog)}  {color(result['timestamp'], DIM)}")
    print()

    # Sensor readings
    sensor = result.get("sensor", {})
    ph     = sensor.get("ph",      result.get("ph",  "?"))
    tds    = sensor.get("tds_ppm", result.get("tds", "?"))
    print(f"  {bold('Sensor')}   pH = {color(str(ph), CYAN)}   "
          f"TDS = {color(str(tds) + ' ppm', CYAN)}")

    # Anomaly result
    is_anom = result.get("is_anomaly", False)
    label   = "⚠  ANOMALY" if is_anom else "✓  Normal"
    print(f"  {bold('Status')}   {color(label, sc)}")

    if is_anom:
        atype = result.get("anomaly_type", "").replace("_", " ").title()
        print(f"  {bold('Type')}     {color(atype, sc)}")

    print(f"  {bold('Severity')} {color(sev.upper(), sc)}")

    # Scores
    raw_score = result.get("anomaly_score",  result.get("adjusted_score", 0))
    adj_score = result.get("adjusted_score", raw_score)
    conf      = result.get("confidence_pct", 100)
    mode      = result.get("data_mode", "full")

    print(f"  {bold('Score')}    raw={raw_score:.3f}  adjusted={adj_score:.3f}  "
          f"confidence={color(str(conf)+'%', YELLOW)}  mode={mode}")

    # Satellite freshness
    sat_age  = result.get("satellite_age_days", "?")
    sat_date = result.get("satellite_date", "?")
    print(f"  {bold('Satellite')} {sat_date}  ({sat_age}d old)")

    # Weather
    wx = result.get("weather", {})
    if wx.get("total_rain_7d_mm") is not None:
        rain = wx["total_rain_7d_mm"]
        pen  = wx.get("rain_penalty_pct", 0)
        rain_str = f"{rain} mm / 7d"
        if pen > 0:
            rain_str += color(f"  (penalty -{pen}%)", YELLOW)
        print(f"  {bold('Weather')}  {rain_str}")

    # Low confidence warning
    if result.get("low_confidence_warning"):
        print(f"\n  {color('⚠  Low confidence — satellite data stale or heavy rain.', YELLOW)}")

    # Explanation
    expl = result.get("explanation") or result.get("message", "")
    if expl:
        # Wrap at 54 chars
        words  = expl.split()
        line   = "  "
        lines  = []
        for w in words:
            if len(line) + len(w) + 1 > 56:
                lines.append(line)
                line = "  " + w + " "
            else:
                line += w + " "
        if line.strip():
            lines.append(line)
        print()
        for l in lines:
            print(color(l, DIM))

    print()


def print_summary(results: list):
    anomalies = [r for r in results if r.get("is_anomaly")]
    types     = {}
    for r in anomalies:
        t = r.get("anomaly_type", "unknown")
        types[t] = types.get(t, 0) + 1

    print(color("═" * 56, CYAN))
    print(bold(f"  SUMMARY  —  {len(results)} readings processed"))
    print(color("═" * 56, CYAN))
    print(f"  Normal readings:  {len(results) - len(anomalies)}")
    print(f"  Anomalies:        {color(str(len(anomalies)), RED if anomalies else GREEN)}")
    if types:
        print(f"  Anomaly types:")
        for t, n in sorted(types.items(), key=lambda x: -x[1]):
            print(f"    {t.replace('_',' ').title():<30} {n}")
    ph_vals  = [r["sensor"]["ph"]      for r in results if "sensor" in r]
    tds_vals = [r["sensor"]["tds_ppm"] for r in results if "sensor" in r]
    if ph_vals:
        print(f"\n  pH  range:  {min(ph_vals):.2f} – {max(ph_vals):.2f}  "
              f"(mean {sum(ph_vals)/len(ph_vals):.2f})")
    if tds_vals:
        print(f"  TDS range:  {min(tds_vals):.1f} – {max(tds_vals):.1f} ppm  "
              f"(mean {sum(tds_vals)/len(tds_vals):.1f})")
    print()


# ── Inference bootstrap ───────────────────────────────────────────────────────

def load_engine(model_path: str, sat_path: str, water_body: str):
    """Load AquaSenseInference. Raises clear errors if files are missing."""
    model_p = Path(model_path)
    sat_p   = Path(sat_path)

    if not model_p.exists():
        print(color(f"\nERROR: Model not found at {model_p}", RED))
        print("  Run:  python generate_mock_and_train.py")
        sys.exit(1)

    if not sat_p.exists():
        print(color(f"\nERROR: Satellite parquet not found at {sat_p}", RED))
        print("  Run:  python generate_mock_and_train.py")
        sys.exit(1)

    from inference import AquaSenseInference
    engine = AquaSenseInference(
        model_path=str(model_p),
        satellite_parquet=str(sat_p),
        lat=41.99, lon=21.43,
        water_body=water_body,
    )
    return engine


# ── Replay mode ───────────────────────────────────────────────────────────────

def replay_csv(engine, csv_path: Path, delay: float):
    if not csv_path.exists():
        print(color(f"\nERROR: CSV not found: {csv_path}", RED))
        print("  Run first:  python convert_output.py")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    df.columns = [c.lower().strip() for c in df.columns]

    # Map column names flexibly
    ph_col  = next((c for c in df.columns if c == "ph"), None)
    tds_col = next((c for c in df.columns if "tds" in c or "ppm" in c), None)
    ts_col  = next((c for c in df.columns if "time" in c or "date" in c), None)

    if not ph_col or not tds_col:
        print(color(f"ERROR: Could not find ph/tds columns in {csv_path}", RED))
        print(f"  Columns found: {list(df.columns)}")
        sys.exit(1)

    # Filter sane rows
    df = df[(df[ph_col] >= 0) & (df[ph_col] <= 14)]
    df = df[(df[tds_col] >= 0) & (df[tds_col] <= 10000)]
    df = df.reset_index(drop=True)

    print(color(f"  Loaded {len(df)} valid rows from {csv_path}", DIM))
    if delay > 0:
        print(color(f"  Replaying with {delay}s delay between readings", DIM))
    print()

    results = []
    try:
        for i, row in df.iterrows():
            ph  = float(row[ph_col])
            tds = float(row[tds_col])
            ts  = str(row[ts_col]) if ts_col else None

            result = engine.predict(
                sensor_reading={"tds": tds, "ph": ph},
                timestamp=ts,
            )
            print_result(result, i + 1, len(df))
            results.append(result)

            if delay > 0 and i < len(df) - 1:
                time.sleep(delay)

    except KeyboardInterrupt:
        print(color("\n  Interrupted by user.", YELLOW))

    if results:
        print_summary(results)


# ── Live-watch mode ───────────────────────────────────────────────────────────

def live_watch(engine, csv_path: Path):
    """Watch arduino_output.csv for new rows and predict each one."""
    if not csv_path.exists():
        print(color(f"Waiting for {csv_path} to appear...", DIM))

    last_size = 0
    last_row  = -1
    row_num   = 0

    print(color(f"  Watching {csv_path} for new Arduino readings...", DIM))
    print(color("  Press Ctrl+C to stop.\n", DIM))

    try:
        while True:
            if not csv_path.exists():
                time.sleep(1)
                continue

            cur_size = csv_path.stat().st_size
            if cur_size == last_size:
                time.sleep(0.5)
                continue
            last_size = cur_size

            try:
                df = pd.read_csv(csv_path)
                df.columns = [c.lower().strip() for c in df.columns]
            except Exception:
                time.sleep(0.5)
                continue

            if len(df) <= last_row + 1:
                continue

            ph_col  = next((c for c in df.columns if c == "ph"), None)
            tds_col = next((c for c in df.columns if "tds" in c or "ppm" in c), None)
            ts_col  = next((c for c in df.columns if "time" in c or "date" in c), None)

            for i in range(last_row + 1, len(df)):
                row = df.iloc[i]
                try:
                    ph  = float(row[ph_col])
                    tds = float(row[tds_col])
                except Exception:
                    continue

                if not (0 <= ph <= 14) or not (0 <= tds <= 10000):
                    continue

                ts = str(row[ts_col]) if ts_col else None
                result = engine.predict(
                    sensor_reading={"tds": tds, "ph": ph},
                    timestamp=ts,
                )
                row_num += 1
                print_result(result, row_num)
                last_row = i

    except KeyboardInterrupt:
        print(color("\n  Live watch stopped.", YELLOW))


# ── Single reading mode ───────────────────────────────────────────────────────

def single_reading(engine, ph: float, tds: float):
    print(color(f"  Single reading — pH={ph}  TDS={tds} ppm", DIM))
    print()
    result = engine.predict(sensor_reading={"tds": tds, "ph": ph})
    print_result(result, 1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AquaSense terminal demo — no frontend needed"
    )
    parser.add_argument("--csv",  default="arduino_output.csv",
                        help="Converted Arduino CSV (default: arduino_output.csv)")
    parser.add_argument("--live", action="store_true",
                        help="Watch CSV for new rows in real-time (Arduino plugged in)")
    parser.add_argument("--single", action="store_true",
                        help="Run a single manual prediction")
    parser.add_argument("--ph",  type=float, default=7.0,
                        help="pH value for --single mode")
    parser.add_argument("--tds", type=float, default=300.0,
                        help="TDS ppm for --single mode")
    parser.add_argument("--delay", type=float, default=0.3,
                        help="Seconds between rows in replay mode (default 0.3)")
    parser.add_argument("--model", default="models/rf_anomaly_model.pkl",
                        help="Path to trained model")
    parser.add_argument("--satellite", default="mock_data/satellite_features.parquet",
                        help="Path to satellite parquet")
    parser.add_argument("--water-body", default="river",
                        choices=["river", "lake", "spring"])
    args = parser.parse_args()

    print_banner()

    print(color("  Loading model and satellite data...", DIM))
    engine = load_engine(args.model, args.satellite, args.water_body)
    print(color("  Ready.\n", GREEN))

    if args.single:
        single_reading(engine, args.ph, args.tds)
    elif args.live:
        live_watch(engine, Path(args.csv))
    else:
        replay_csv(engine, Path(args.csv), args.delay)


if __name__ == "__main__":
    main()