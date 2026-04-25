/*
  AquaSense Sensor Node
  =====================
  Reads TDS (Total Dissolved Solids) and pH from analog sensors.
  Outputs a single line per reading over Serial (USB) in the format:
    TDS:342.5,PH:7.23

  Wiring:
    TDS module (e.g. DFRobot Gravity TDS):
      VCC  → 5V
      GND  → GND
      AOUT → A0

    pH module (e.g. DFRobot SEN0161):
      VCC  → 5V
      GND  → GND
      AOUT → A1

  Tested on: Arduino Uno, Nano, ESP32 (change analog pins if needed)
*/

const int TDS_PIN = A0;
const int PH_PIN  = A1;

// TDS calibration
// The DFRobot TDS module outputs 0-2.3V for 0-1000 ppm.
// Adjust VREF and AREF_VOLTAGE for your board.
const float AREF_VOLTAGE  = 5.0;   // 3.3 for ESP32 / 3.3V boards
const float TDS_FACTOR    = 0.5;   // calibration factor — adjust with known TDS solution
const int   NUM_SAMPLES   = 30;    // averaging samples

// pH calibration
// pH 4.0 → ~3.0V,  pH 7.0 → ~2.5V,  pH 10.0 → ~2.0V (varies by module)
// These offsets should be calibrated with pH buffer solutions.
const float PH_VOLTAGE_AT_7 = 2.50;    // volts when pH = 7
const float PH_SLOPE        = -0.18;   // volts per pH unit (negative = inverse)

const unsigned long INTERVAL_MS = 10000;  // read every 10 seconds

unsigned long lastRead = 0;


float readTDS() {
  // Average over NUM_SAMPLES to reduce noise
  long sum = 0;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    sum += analogRead(TDS_PIN);
    delay(10);
  }
  float avgADC = sum / (float)NUM_SAMPLES;
  float voltage = avgADC * AREF_VOLTAGE / 1023.0;

  // Temperature compensation (assume 25°C for demo; add thermistor for production)
  float tempCoeff = 1.0 + 0.02 * (25.0 - 25.0);  // placeholder

  // Convert voltage to TDS ppm
  float tds = (133.42 * voltage * voltage * voltage
              - 255.86 * voltage * voltage
              + 857.39 * voltage) * TDS_FACTOR * tempCoeff;

  return max(0.0f, tds);
}


float readPH() {
  long sum = 0;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    sum += analogRead(PH_PIN);
    delay(10);
  }
  float avgADC = sum / (float)NUM_SAMPLES;
  float voltage = avgADC * AREF_VOLTAGE / 1023.0;

  // Linear conversion from voltage to pH
  float ph = 7.0 + (PH_VOLTAGE_AT_7 - voltage) / PH_SLOPE;

  // Clamp to realistic range
  ph = constrain(ph, 0.0, 14.0);
  return ph;
}


void setup() {
  Serial.begin(9600);
  analogReference(DEFAULT);  // use EXTERNAL if you have a 3.3V ref

  // Startup message
  Serial.println("AquaSense sensor node ready.");
  delay(1000);
}


void loop() {
  unsigned long now = millis();
  if (now - lastRead >= INTERVAL_MS) {
    lastRead = now;

    float tds = readTDS();
    float ph  = readPH();

    // Output format: TDS:342.5,PH:7.23
    Serial.print("TDS:");
    Serial.print(tds, 1);
    Serial.print(",PH:");
    Serial.println(ph, 2);
  }
}
