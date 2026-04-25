"""
reading_data.py
===============
Reads TDS (PPM) + pH from Arduino over USB and writes every reading
to arduino_output.csv.

Supports TWO serial formats automatically:

  FORMAT A — Multi-line (your current Arduino sketch output):
      pH: 6.87
      PPM: 93.44
      Conductivity [uS/cm]: 93.44

  FORMAT B — Single-line comma-separated (simpler sketch):
      7.21,420.5
      2024-11-15T10:30:00,7.21,420.5

The script buffers incoming lines and flushes a row to CSV each time
it has collected both a pH and a PPM value.

Output CSV  (arduino_output.csv):
    timestamp,ph,tds_ppm
    2024-11-15T10:30:00,7.21,420.5

Usage:
    pip install pyserial
    python reading_data.py

    # Override port if auto-detection fails:
    python reading_data.py --port COM3           (Windows)
    python reading_data.py --port /dev/ttyUSB0   (Linux)
    python reading_data.py --port /dev/tty.usbmodem14101  (Mac)
"""

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("ERROR: pyserial not installed.")
    print("  Run: pip install pyserial")
    sys.exit(1)

OUTPUT_CSV   = Path("arduino_output.csv")
BAUD_RATE    = 9600
STARTUP_WAIT = 2

# Regex patterns for multi-line format
_RE_PH  = re.compile(r"pH\s*:\s*([\-\d.]+)", re.IGNORECASE)
_RE_PPM = re.compile(r"PPM\s*:\s*([\-\d.]+)", re.IGNORECASE)


def find_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    arduino_keywords = ["arduino", "ch340", "ch341", "cp210", "usbserial",
                        "usbmodem", "ftdi", "genuino"]
    for p in ports:
        desc         = (p.description   or "").lower()
        manufacturer = (p.manufacturer  or "").lower()
        if any(kw in desc or kw in manufacturer for kw in arduino_keywords):
            print(f"  Auto-detected Arduino on: {p.device}  ({p.description})")
            return p.device
    if ports:
        print("  No Arduino-labelled port found. Available ports:")
        for p in ports:
            print(f"    {p.device}  —  {p.description}")
        print(f"\n  Trying first port: {ports[0].device}")
        return ports[0].device
    return None


def parse_line(raw: str, buf: dict):
    """
    Parse one raw line.
    Multi-line mode: accumulate pH and PPM in buf, return tuple only when both present.
    Single-line mode: parse immediately.
    Returns (timestamp_str, ph, tds_ppm) or None.
    """
    # Multi-line format
    m_ph = _RE_PH.match(raw)
    if m_ph:
        buf["ph"] = float(m_ph.group(1))
        buf.setdefault("ts", datetime.now().isoformat(timespec="seconds"))

    m_ppm = _RE_PPM.match(raw)
    if m_ppm:
        buf["ppm"] = float(m_ppm.group(1))
        buf.setdefault("ts", datetime.now().isoformat(timespec="seconds"))

    if "ph" in buf and "ppm" in buf:
        ts, ph, tds = buf["ts"], buf["ph"], buf["ppm"]
        buf.clear()
        if not (0 <= ph <= 14):
            raise ValueError(f"pH {ph:.2f} out of range [0, 14]")
        if not (0 <= tds <= 10000):
            raise ValueError(f"TDS {tds:.1f} out of range [0, 10000]")
        return ts, ph, tds

    # Single-line comma format (fallback)
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) == 2:
        try:
            ph  = float(parts[0])
            tds = float(parts[1])
            if 0 <= ph <= 14 and 0 <= tds <= 10000:
                return datetime.now().isoformat(timespec="seconds"), ph, tds
        except ValueError:
            pass
    elif len(parts) == 3:
        try:
            ts  = parts[0]
            ph  = float(parts[1])
            tds = float(parts[2])
            if 0 <= ph <= 14 and 0 <= tds <= 10000:
                return ts, ph, tds
        except ValueError:
            pass

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",   default=None)
    parser.add_argument("--baud",   type=int, default=BAUD_RATE)
    parser.add_argument("--output", default=str(OUTPUT_CSV))
    args = parser.parse_args()

    out_path = Path(args.output)
    port     = args.port or find_arduino_port()

    if not port:
        print("ERROR: No serial port found. Is the Arduino plugged in?")
        sys.exit(1)

    print(f"\nConnecting to {port} at {args.baud} baud...")
    try:
        ser = serial.Serial(port, args.baud, timeout=2)
    except serial.SerialException as e:
        print(f"ERROR: Could not open {port}: {e}")
        sys.exit(1)

    print(f"Waiting {STARTUP_WAIT}s for Arduino to boot...")
    time.sleep(STARTUP_WAIT)
    ser.reset_input_buffer()

    write_header = not out_path.exists()
    f      = open(out_path, "a", newline="")
    writer = csv.writer(f)
    if write_header:
        writer.writerow(["timestamp", "ph", "tds_ppm"])
        f.flush()

    print(f"Writing to {out_path}")
    print("Listening for pH and PPM lines from Arduino...")
    print("Press Ctrl+C to stop.\n")

    total  = 0
    errors = 0
    buf    = {}

    try:
        while True:
            try:
                raw = ser.readline().decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue

                result = parse_line(raw, buf)
                if result is None:
                    continue

                ts, ph, tds = result
                writer.writerow([ts, ph, tds])
                f.flush()
                total += 1
                print(f"  [{total:4d}]  {ts}  pH={ph:.2f}  TDS={tds:.1f} ppm")

            except ValueError as e:
                errors += 1
                buf.clear()
                print(f"  [skip] Bad reading: {e}")

            except serial.SerialException as e:
                print(f"\nSerial error: {e}. Reconnecting in 5s...")
                time.sleep(5)
                try:
                    ser.close()
                    ser = serial.Serial(port, args.baud, timeout=2)
                    print("Reconnected.")
                except Exception as e2:
                    print(f"Reconnect failed: {e2}")
                    break

    except KeyboardInterrupt:
        print(f"\nStopped. Wrote {total} readings to {out_path}")
    finally:
        f.close()
        ser.close()


if __name__ == "__main__":
    main()