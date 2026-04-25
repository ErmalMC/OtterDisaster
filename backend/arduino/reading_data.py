import serial
import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="/dev/ttyUSB0")
parser.add_argument("--output", default=None)
args = parser.parse_args()

output_file = args.output or os.path.join(os.path.dirname(__file__), "output.csv")

with serial.Serial(args.port, 9600) as ser, open(output_file, "w") as f:
    print(f"Saving to {output_file}")
    while True:
        line = ser.readline().decode().strip()
        print(line)
        f.write(line + "\n")
        f.flush()