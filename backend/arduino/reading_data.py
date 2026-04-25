import serial
import os

ino_folder = r"C:\Users\Ole\OneDrive\Documents\Arduino\cassini26_ph_tds_code" # path do foldero so ino kodo
output_file = os.path.join(ino_folder, "output.csv")

with serial.Serial("COM3", 9600) as ser, open(output_file, "w") as f:  # tuka se stava porto so e povrzan so arduinoto
    print(f"Saving to {output_file}")
    while True:
        line = ser.readline().decode().strip()
        print(line)
        f.write(line + "\n")
        f.flush()