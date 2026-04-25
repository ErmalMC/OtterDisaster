"""
convert_output.py
=================
One-time converter: turns your existing output.csv (the multi-line
human-readable format your Arduino sketch currently produces) into
arduino_output.csv (the clean timestamp,ph,tds_ppm format the
pipeline needs).

Also prints a summary so you can verify the values look right.

Usage:
    python convert_output.py
    python convert_output.py --input output.csv --output arduino_output.csv
"""

import argparse
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path

_RE_PH  = re.compile(r"pH\s*:\s*([\-\d.]+)")
_RE_PPM = re.compile(r"PPM\s*:\s*([\-\d.]+)")

PH_MIN,  PH_MAX  = 0.0,  14.0
TDS_MIN, TDS_MAX = 0.0, 10000.0


def convert(input_path: Path, output_path: Path):
    lines = input_path.read_text(errors="ignore").splitlines()

    rows         = []
    skipped_ph   = 0
    skipped_tds  = 0
    buf_ph  = None
    buf_ppm = None

    # We'll assign synthetic timestamps spaced 2 s apart starting from now
    # so the inference engine has something to work with.
    base_ts = datetime(2025, 4, 25, 10, 0, 0)
    idx     = 0

    for line in lines:
        line = line.strip()

        m_ph = _RE_PH.match(line)
        if m_ph:
            buf_ph = float(m_ph.group(1))

        m_ppm = _RE_PPM.match(line)
        if m_ppm:
            buf_ppm = float(m_ppm.group(1))

        # Once we have both, emit a row
        if buf_ph is not None and buf_ppm is not None:
            ph  = buf_ph
            tds = buf_ppm
            buf_ph = buf_ppm = None

            # Validate — skip impossible values
            if not (PH_MIN <= ph <= PH_MAX):
                skipped_ph += 1
                continue
            if not (TDS_MIN <= tds <= TDS_MAX):
                skipped_tds += 1
                continue

            ts = (base_ts + timedelta(seconds=2 * idx)).isoformat(timespec="seconds")
            rows.append([ts, round(ph, 4), round(tds, 4)])
            idx += 1

    if not rows:
        print("ERROR: No valid rows found. Check your input file.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "ph", "tds_ppm"])
        writer.writerows(rows)

    ph_vals  = [r[1] for r in rows]
    tds_vals = [r[2] for r in rows]

    print(f"\nConversion complete")
    print(f"  Input:           {input_path}")
    print(f"  Output:          {output_path}")
    print(f"  Valid rows:      {len(rows)}")
    print(f"  Skipped (pH):    {skipped_ph}  (pH outside 0–14, e.g. sensor in air)")
    print(f"  Skipped (TDS):   {skipped_tds}")
    print(f"\n  pH  range:  {min(ph_vals):.2f} – {max(ph_vals):.2f}  "
          f"  (mean {sum(ph_vals)/len(ph_vals):.2f})")
    print(f"  TDS range:  {min(tds_vals):.2f} – {max(tds_vals):.2f} ppm  "
          f"  (mean {sum(tds_vals)/len(tds_vals):.2f})")
    print(f"\n  First row:  {rows[0]}")
    print(f"  Last row:   {rows[-1]}")
    print(f"\nNow run:  python demo.py --csv {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  default="output.csv",
                        help="Your raw Arduino log (default: output.csv)")
    parser.add_argument("--output", default="arduino_output.csv",
                        help="Clean CSV output (default: arduino_output.csv)")
    args = parser.parse_args()
    convert(Path(args.input), Path(args.output))