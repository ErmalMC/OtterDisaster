import numpy as np
import xarray as xr
import pandas as pd
from pathlib import Path

OUTPUT_DIR = Path("vardar_wq_results")
nc_paths = [
    OUTPUT_DIR / "vardar_wq_2022.nc",
    OUTPUT_DIR / "vardar_wq_2023.nc",
    OUTPUT_DIR / "vardar_wq_2024.nc",
]

dfs = []

for nc_path in nc_paths:
    print(f"\nProcessing {nc_path.name}...")
    ds = xr.open_dataset(nc_path, engine="netcdf4")
    timestamps = ds["t"].values
    records = []

    for i, ts in enumerate(timestamps):
        print(f"  {ts} ...", flush=True)

        # Load only bands confirmed to have valid data (B06, B08 are all-NaN in downloads)
        B01 = ds["B01"].isel(t=i).values
        B02 = ds["B02"].isel(t=i).values
        B03 = ds["B03"].isel(t=i).values
        B04 = ds["B04"].isel(t=i).values
        B05 = ds["B05"].isel(t=i).values  # used as NIR proxy for NDWI

        # Clip to valid reflectance range [0, 1]
        B01 = np.clip(B01, 0, 1)
        B02 = np.clip(B02, 0, 1)
        B03 = np.clip(B03, 0, 1)
        B04 = np.clip(B04, 0, 1)
        B05 = np.clip(B05, 0, 1)

        # Replace zeros with nan to avoid division by zero
        B01 = np.where(B01 == 0, np.nan, B01)
        B02 = np.where(B02 == 0, np.nan, B02)
        B04 = np.where(B04 == 0, np.nan, B04)
        B05 = np.where(B05 == 0, np.nan, B05)

        with np.errstate(divide="ignore", invalid="ignore"):
            chl_a         = 4.26      * np.power(B03 / B01,          3.94)
            cyanobacteria = 115530.31 * np.power((B03 * B04) / B02,  2.38)
            turbidity     = 8.93 * (B03 / B01) - 6.39
            cdom          = 537  * np.exp(-2.93 * B03 / B04)
            doc           = 432  * np.exp(-2.24 * B03 / B04)

            # B05 (705nm red-edge) used as NIR proxy since B06/B08 are missing
            ndwi = (B03 - B05) / (B03 + B05)  # water index
            ndti = (B04 - B03) / (B04 + B03)  # turbidity index
            ndci = (B05 - B04) / (B05 + B04)  # chlorophyll index

        records.append({
            "timestamp":     ts,
            "ndwi":          np.nanmean(ndwi),
            "ndti":          np.nanmean(ndti),
            "ndci":          np.nanmean(ndci),
            "chl_a":         np.nanmean(chl_a),
            "cyanobacteria": np.nanmean(cyanobacteria),
            "turbidity_sat": np.nanmean(turbidity),
            "cdom":          np.nanmean(cdom),
            "doc":           np.nanmean(doc),
        })

        # Free memory before next slice
        del B01, B02, B03, B04, B05
        del chl_a, cyanobacteria, turbidity, cdom, doc
        del ndwi, ndti, ndci

    df = pd.DataFrame(records)
    print(df)
    dfs.append(df)
    ds.close()

merged = pd.concat(dfs, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
out = OUTPUT_DIR / "vardar_wq_merged.parquet"
merged.to_parquet(out, index=False)
print(f"\nDone. Saved {len(merged)} rows to {out}")
print(merged)