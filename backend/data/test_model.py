import logging
from inference import AquaSenseInference

# Suppress logs for a clean output
logging.basicConfig(level=logging.CRITICAL)

# 1. Initialize the engine (This handles the 33-feature engineering)
engine = AquaSenseInference(
    model_path="../models/rf_anomaly_model.pkl",
    satellite_parquet="mock_data/satellite_features.parquet", # or your real parquet
    water_body="river"
)

# 2. Test your "Distilled Water" scenario (Low TDS)
print("--- Testing Low TDS (Distilled Water) ---")
result = engine.predict({"tds": 10.0, "ph": 7.0})

print(f"Anomaly Score: {result['anomaly_score']:.4f}")
print(f"Severity:      {result['severity']}")
print(f"Type:          {result['anomaly_type']}")
print(f"Explanation:   {result['explanation']}")