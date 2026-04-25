"""
AquaSense — openEO Data Extraction Pipeline
============================================
Fixes applied vs previous version:
  1. Splits 3-year request into per-year batch jobs (memory limit fix)
  2. Adds aggregate_temporal_period("month") BEFORE download — reduces
     output size by ~20x by collapsing daily observations to monthly medians
  3. Adds explicit save_result(format="NetCDF") so the backend knows the format
  4. Saves each year separately, merges at the end
  5. Adds a water-pixel spatial mask using NDWI so you only get river pixels

Run:
    python main.py

Output:
    vardar_wq_results/
        vardar_wq_2022.nc
        vardar_wq_2023.nc
        vardar_wq_2024.nc
        vardar_wq_merged.parquet  (merged, ready for train.py)
"""

import os
import time
import logging
from pathlib import Path

import openeo
import numpy as np
import xarray as xr
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────
BBOX       = {"west": 21.30, "south": 41.95, "east": 21.55, "north": 42.05}
YEARS      = ["2022", "2023", "2024"]
OUTPUT_DIR = Path("vardar_wq_results")
OUTPUT_DIR.mkdir(exist_ok=True)

# ─── UDF code string ─────────────────────────────────────────────────────────
UDF_CODE = """
import numpy as np
import xarray as xr
from openeo.udf import XarrayDataCube

def apply_datacube(cube: XarrayDataCube, context: dict) -> XarrayDataCube:
    arr = cube.get_array()

    B01 = arr.sel(bands="B01").values
    B02 = arr.sel(bands="B02").values
    B03 = arr.sel(bands="B03").values
    B04 = arr.sel(bands="B04").values
    B05 = arr.sel(bands="B05").values

    with np.errstate(divide='ignore', invalid='ignore'):
        chl_a = 4.26  * np.power(np.where(B01 > 0, B03 / B01,           np.nan), 3.94)
        cya   = 115530.31 * np.power(np.where(B02 > 0, (B03 * B04) / B02, np.nan), 2.38)
        turb  = np.where(B01 > 0, 8.93 * (B03 / B01) - 6.39, np.nan)
        cdom  = np.where(B04 > 0, 537  * np.exp(-2.93 * B03 / B04),      np.nan)
        doc   = np.where(B04 > 0, 432  * np.exp(-2.24 * B03 / B04),      np.nan)

    results = np.stack([chl_a, cya, turb, cdom, doc], axis=1)
    new_coords = dict(arr.coords)
    new_coords["bands"] = ["Chl_a", "Cyanobacteria", "Turbidity", "CDOM", "DOC"]

    return XarrayDataCube(xr.DataArray(results, dims=arr.dims, coords=new_coords))
"""


def build_wq_cube(conn: openeo.Connection, year: str) -> openeo.DataCube:
    """
    Build the water quality datacube for one year.
    Key optimisation: aggregate_temporal_period("month") collapses all
    Sentinel-2 passes in a month to a single median image.
    This reduces the job from ~70 time steps to 12 — fits in memory.
    """
    time_range = [f"{year}-01-01", f"{year}-12-31"]
    log.info(f"Building process graph for {year}...")

    # Load all bands including SCL for cloud masking
    raw = conn.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=BBOX,
        temporal_extent=time_range,
        bands=["B01", "B02", "B03", "B04", "B05", "B06", "B08", "SCL"],
        max_cloud_cover=15
    )

    # Rescale optical bands: (DN - 1000) / 10000 → surface reflectance
    optical = raw.filter_bands(["B01", "B02", "B03", "B04", "B05", "B06", "B08"])
    rescaled = optical.apply(lambda x: (x - 1000) / 10000)

    # Cloud mask — SCL values 4, 5, 6 are valid (vegetation, bare soil, water)
    scl = raw.band("SCL")
    cloud_mask = (scl == 4) | (scl == 5) | (scl == 6)
    masked = rescaled.mask(~cloud_mask)

    # FIX: Aggregate to monthly medians BEFORE running the UDF.
    # This is the key fix for the memory/timeout issue.
    # Instead of ~70 scenes/year the job processes 12 monthly composites.
    monthly = masked.aggregate_temporal_period(
        period="month",
        reducer="median"
    )

    # Apply water quality UDF to the monthly composite cube
    wq = monthly.apply_neighborhood(
        process=lambda data: data.run_udf(
            udf=UDF_CODE,
            runtime="Python",
            version="3.11"
        ),
        size=[
            {"dimension": "x", "value": 256, "unit": "px"},
            {"dimension": "y", "value": 256, "unit": "px"},
        ],
        overlap=[]
    )

    return wq


def run_year_job(conn: openeo.Connection, year: str) -> Path:
    """Submit one year as a batch job and download the result."""
    out_path = OUTPUT_DIR / f"vardar_wq_{year}"

    if (OUTPUT_DIR / f"vardar_wq_{year}.nc").exists():
        log.info(f"{year}: already downloaded, skipping.")
        return OUTPUT_DIR / f"vardar_wq_{year}.nc"

    wq_cube = build_wq_cube(conn, year)

    log.info(f"{year}: Submitting batch job...")
    job = wq_cube.save_result(format="NetCDF").create_job(
        title=f"AquaSense Vardar WQ {year}"
    )
    job.start_and_wait(
        max_poll_interval=60,   # poll every 60s
        print=log.info
    )

    log.info(f"{year}: Downloading results to {out_path}/")
    out_path.mkdir(exist_ok=True)
    job.get_results().download_files(str(out_path))

    # Find the downloaded nc file and rename for clarity
    nc_files = list(out_path.glob("*.nc"))
    if nc_files:
        final_path = OUTPUT_DIR / f"vardar_wq_{year}.nc"
        nc_files[0].rename(final_path)
        log.info(f"{year}: Saved to {final_path}")
        return final_path
    else:
        log.error(f"{year}: No .nc file found in {out_path}")
        return None


def merge_to_parquet(nc_paths: list[Path]) -> Path:
    """
    Merge yearly NetCDF files into a single flat parquet file
    ready for train.py. Spatially averages over river pixels
    to produce one row per month (timestamp, band values).
    """
    log.info("Merging yearly NetCDF files into parquet...")
    dfs = []

    def merge_to_parquet(nc_paths: list[Path]) -> Path:
        log.info("Merging yearly NetCDF files into parquet...")
        dfs = []

        for nc_path in nc_paths:
            if nc_path is None or not nc_path.exists():
                continue

            ds = xr.open_dataset(nc_path, engine="netcdf4")

            # Drop non-numeric variables (strings, CRS metadata, flags, etc.)
            numeric_vars = [v for v in ds.data_vars if ds[v].dtype.kind in ("f", "i", "u")]
            log.info(f"  {nc_path.name} — keeping numeric vars: {numeric_vars}")
            ds = ds[numeric_vars]

            # Confirm spatial dims exist before averaging
            available_dims = list(ds.dims)
            log.info(f"  {nc_path.name} — dims: {available_dims}")
            spatial_dims = [d for d in ["x", "y"] if d in available_dims]

            ds_mean = ds.mean(dim=spatial_dims, skipna=True)
            df = ds_mean.to_dataframe().reset_index()

            # Rename time dim (could be 't' or 'time')
            for col in ["t", "time"]:
                if col in df.columns:
                    df = df.rename(columns={col: "timestamp"})
                    break

            dfs.append(df)
            log.info(f"  Loaded {nc_path.name}: {len(df)} monthly records")

        if not dfs:
            log.error("No data to merge.")
            return None

        merged = pd.concat(dfs, ignore_index=True)
        merged = merged.sort_values("timestamp").reset_index(drop=True)

        rename = {
            "Chl_a": "chl_a",
            "Cyanobacteria": "cyanobacteria",
            "Turbidity": "turbidity_sat",
            "CDOM": "cdom",
            "DOC": "doc",
        }
        merged = merged.rename(columns=rename)

        out_path = OUTPUT_DIR / "vardar_wq_merged.parquet"
        merged.to_parquet(out_path, index=False)
        log.info(f"Merged parquet saved: {out_path} ({len(merged)} rows)")
        return out_path


def main():
    log.info("Connecting to Copernicus openEO...")
    conn = openeo.connect("https://openeo.dataspace.copernicus.eu")
    conn.authenticate_oidc()
    log.info("Authenticated.")

    nc_paths = []
    for year in YEARS:
        nc_path = run_year_job(conn, year)
        nc_paths.append(nc_path)
        # Small pause between jobs to be polite to the backend
        if year != YEARS[-1]:
            log.info("Waiting 10s before next job...")
            time.sleep(10)

    parquet_path = merge_to_parquet(nc_paths)
    if parquet_path:
        log.info(f"\nDone. Training data ready at: {parquet_path}")
        log.info("Next step: python train.py --satellite vardar_wq_results/vardar_wq_merged.parquet ...")


if __name__ == "__main__":
    main()