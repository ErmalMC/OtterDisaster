"""
udf.py — RF anomaly scoring UDF for openEO
Loads the pre-trained Random Forest from /tmp/rf_model.pkl
(uploaded alongside the batch job) and scores every pixel.
"""

# FIX: same issue as main.py — the string was opened with "" instead of triple-quotes.
# Everything below is a Python string that gets sent to the openEO backend.

rf_udf_code = """
import numpy as np
import xarray as xr
import pickle
from openeo.udf import XarrayDataCube

def apply_datacube(cube: XarrayDataCube, context: dict) -> XarrayDataCube:
    arr = cube.get_array()  # dims: [t, bands, y, x]

    # Load pre-trained RF model uploaded alongside the batch job
    model_path = context.get("model_path", "/tmp/rf_model.pkl")
    with open(model_path, "rb") as f:
        model = pickle.load(f)

    t, b, y, x = arr.shape
    # reshape to (t, n_pixels, n_bands) for sklearn
    features = arr.values.reshape(t, b, -1).transpose(0, 2, 1)

    anomaly_scores = np.full((t, 1, y * x), np.nan)

    for i in range(t):
        pixel_features = features[i]                          # (n_pixels, n_bands)
        valid_mask = ~np.any(np.isnan(pixel_features), axis=1)
        if valid_mask.sum() > 0:
            probs = model.predict_proba(pixel_features[valid_mask])[:, 1]
            anomaly_scores[i, 0, valid_mask] = probs

    anomaly_scores = anomaly_scores.reshape(t, 1, y, x)

    result_array = xr.DataArray(
        anomaly_scores,
        dims=["t", "bands", "y", "x"],
        coords={
            **{k: arr.coords[k] for k in ["t", "y", "x"]},
            "bands": ["anomaly_score"],
        }
    )
    return XarrayDataCube(result_array)
"""