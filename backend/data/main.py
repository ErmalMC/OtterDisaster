"""
AquaSense — openEO Data Extraction Pipeline
============================================
Changes in this version:
  + Adds Sentinel-3 SLSTR surface water temperature download (new)
    - Uses SENTINEL3_SLSTR collection, band S8 (thermal infrared, 10.85µm)
      which is the standard land/water surface temperature channel
    - Downloads separately from Sentinel-2 because SLSTR has 1km resolution
      and daily revisit vs Sentinel-2's 10m/5-day cadence — they cannot be
      merged in the same job
    - Saves per-year LST parquets then merges to lst_merged.parquet
  + Sentinel-2 WQ pipeline unchanged

Run:
    python main.py

Output:
    vardar_wq_results/
        vardar_wq_2022.nc / 2023 / 2024           (Sentinel-2 WQ)
        vardar_lst_2022.parquet / 2023 / 2024      (Sentinel-3 SLSTR LST)
        vardar_wq_merged.parquet                   (S2 WQ merged)
        vardar_lst_merged.parquet                  (S3 LST merged, daily)
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

# SLSTR S8 band: 10.85 µm thermal infrared — this is the standard channel
# for land/water surface temperature retrieval. S9 (12µm) is the second
# thermal channel used for split-window SST but S8 alone is fine for
# relative temperature anomaly detection in inland water.
# The raw values in openEO are brightness temperatures in Kelvin.
SLSTR_BAND        = "S8_BT_in"   # nadir-view brightness temperature
KELVIN_TO_CELSIUS = 273.15
LST_MIN_VALID_K   = 270.0        # < -3°C = likely cloud or invalid pixel
LST_MAX_VALID_K   = 320.0        # > 47°C = saturated / error pixel

# ─── Sentinel-2 UDF (unchanged) ──────────────────────────────────────────────
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


# ─── Sentinel-2 WQ pipeline (unchanged) ─────────────────────────────────────

def build_wq_cube(conn: openeo.Connection, year: str) -> openeo.DataCube:
    time_range = [f"{year}-01-01", f"{year}-12-31"]
    log.info(f"[S2] Building WQ process graph for {year}...")

    raw = conn.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=BBOX,
        temporal_extent=time_range,
        bands=["B01", "B02", "B03", "B04", "B05", "B06", "B08", "SCL"],
        max_cloud_cover=15
    )
    optical  = raw.filter_bands(["B01", "B02", "B03", "B04", "B05", "B06", "B08"])
    rescaled = optical.apply(lambda x: (x - 1000) / 10000)
    scl      = raw.band("SCL")
    cloud_mask = (scl == 4) | (scl == 5) | (scl == 6)
    masked   = rescaled.mask(~cloud_mask)
    monthly  = masked.aggregate_temporal_period(period="month", reducer="median")
    wq       = monthly.apply_neighborhood(
        process=lambda data: data.run_udf(udf=UDF_CODE, runtime="Python", version="3.11"),
        size=[{"dimension": "x", "value": 256, "unit": "px"},
              {"dimension": "y", "value": 256, "unit": "px"}],
        overlap=[]
    )
    return wq


def run_wq_year_job(conn: openeo.Connection, year: str) -> Path:
    final_path = OUTPUT_DIR / f"vardar_wq_{year}.nc"
    if final_path.exists():
        log.info(f"[S2] {year}: already downloaded, skipping.")
        return final_path

    wq_cube = build_wq_cube(conn, year)
    log.info(f"[S2] {year}: Submitting batch job...")
    job = wq_cube.save_result(format="NetCDF").create_job(title=f"AquaSense Vardar WQ {year}")
    job.start_and_wait(max_poll_interval=60, print=log.info)

    out_path = OUTPUT_DIR / f"vardar_wq_{year}"
    out_path.mkdir(exist_ok=True)
    job.get_results().download_files(str(out_path))
    nc_files = list(out_path.glob("*.nc"))
    if nc_files:
        nc_files[0].rename(final_path)
        log.info(f"[S2] {year}: Saved to {final_path}")
        return final_path
    log.error(f"[S2] {year}: No .nc file found")
    return None


# ─── NEW: Sentinel-3 SLSTR LST pipeline ─────────────────────────────────────

def build_lst_cube(conn: openeo.Connection, year: str) -> openeo.DataCube:
    """
    Build a Sentinel-3 SLSTR brightness-temperature datacube for one year.

    Why NOT aggregate to monthly here:
    SLSTR has daily coverage — that's its entire advantage over Sentinel-2.
    We keep daily observations and filter invalid pixels (clouds, saturated)
    so that in train.py we can compute the exact age of each reading in days.
    Monthly averaging would destroy the staleness signal entirely.

    Band S8_BT_in: nadir-view 10.85µm thermal infrared brightness temperature.
    Values are in Kelvin. We filter to [270K, 320K] to remove cloud pixels.
    1 km spatial resolution — coarser than Sentinel-2 but fine for river-reach
    average temperature.
    """
    time_range = [f"{year}-01-01", f"{year}-12-31"]
    log.info(f"[S3] Building LST process graph for {year}...")

    lst = conn.load_collection(
        "SENTINEL3_SLSTR",
        spatial_extent=BBOX,
        temporal_extent=time_range,
        bands=[SLSTR_BAND],
    )

    # Filter invalid pixels: keep only Kelvin values in physical range
    # This removes clouds (cold, < 270K) and saturated/error pixels (> 320K)
    lst_filtered = lst.apply(
        lambda x: x.linear_scale_range(LST_MIN_VALID_K, LST_MAX_VALID_K,
                                        LST_MIN_VALID_K, LST_MAX_VALID_K)
    )
    # Note: pixels outside [min, max] become NaN after linear_scale_range

    return lst_filtered


def run_lst_year_job(conn: openeo.Connection, year: str) -> Path:
    """
    Submit Sentinel-3 SLSTR job for one year and convert to a flat parquet.
    Returns path to the parquet or None on failure.
    """
    final_path = OUTPUT_DIR / f"vardar_lst_{year}.parquet"
    if final_path.exists():
        log.info(f"[S3] {year}: already downloaded, skipping.")
        return final_path

    lst_cube = build_lst_cube(conn, year)
    log.info(f"[S3] {year}: Submitting batch job...")
    job = lst_cube.save_result(format="NetCDF").create_job(
        title=f"AquaSense Vardar LST {year}"
    )
    job.start_and_wait(max_poll_interval=60, print=log.info)

    nc_dir = OUTPUT_DIR / f"vardar_lst_{year}"
    nc_dir.mkdir(exist_ok=True)
    job.get_results().download_files(str(nc_dir))

    nc_files = list(nc_dir.glob("*.nc"))
    if not nc_files:
        log.error(f"[S3] {year}: No .nc file downloaded")
        return None

    # Convert NetCDF → flat parquet: one row per day, spatial mean of valid pixels
    records = []
    ds = xr.open_dataset(nc_files[0], engine="netcdf4")
    timestamps = ds["t"].values if "t" in ds.dims else ds["time"].values

    band_var = SLSTR_BAND if SLSTR_BAND in ds.data_vars else list(ds.data_vars)[0]
    log.info(f"[S3] {year}: Processing {len(timestamps)} daily scenes, band={band_var}")

    for i, ts in enumerate(timestamps):
        arr = ds[band_var].isel(t=i).values if "t" in ds.dims else ds[band_var].isel(time=i).values
        arr = arr.astype(float)

        # Mask invalid range (cloud / saturated)
        arr[arr < LST_MIN_VALID_K] = np.nan
        arr[arr > LST_MAX_VALID_K] = np.nan

        valid_count = int(np.sum(~np.isnan(arr)))
        if valid_count == 0:
            # All pixels clouded — record as NaN so the merge knows it's missing
            records.append({
                "timestamp":            pd.Timestamp(ts),
                "lst_water_kelvin":     np.nan,
                "lst_water_celsius":    np.nan,
                "lst_valid_px_count":   0,
            })
        else:
            mean_k = float(np.nanmean(arr))
            records.append({
                "timestamp":            pd.Timestamp(ts),
                "lst_water_kelvin":     round(mean_k, 3),
                "lst_water_celsius":    round(mean_k - KELVIN_TO_CELSIUS, 3),
                "lst_valid_px_count":   valid_count,
            })

    ds.close()
    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
    df.to_parquet(final_path, index=False)
    valid_days = (df["lst_valid_px_count"] > 0).sum()
    log.info(f"[S3] {year}: {valid_days}/{len(df)} days with valid LST. Saved to {final_path}")
    return final_path


def merge_lst_parquets(lst_paths: list[Path]) -> Path:
    """Concatenate yearly LST parquets into one merged file."""
    dfs = [pd.read_parquet(p) for p in lst_paths if p and p.exists()]
    if not dfs:
        log.error("[S3] No LST parquets to merge")
        return None
    merged = pd.concat(dfs, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    out = OUTPUT_DIR / "vardar_lst_merged.parquet"
    merged.to_parquet(out, index=False)
    log.info(f"[S3] Merged LST: {len(merged)} daily rows → {out}")
    log.info(f"     Valid days (LST available): {(merged['lst_valid_px_count'] > 0).sum()}")
    return out


def merge_wq_to_parquet(nc_paths: list[Path]) -> Path:
    """Sentinel-2 WQ merge — unchanged from original main.py."""
    log.info("[S2] Merging yearly NetCDF files into parquet...")
    dfs = []

    for nc_path in nc_paths:
        if nc_path is None or not nc_path.exists():
            continue
        ds = xr.open_dataset(nc_path, engine="netcdf4")
        numeric_vars = [v for v in ds.data_vars if ds[v].dtype.kind in ("f", "i", "u")]
        ds = ds[numeric_vars]
        available_dims = list(ds.dims)
        spatial_dims = [d for d in ["x", "y"] if d in available_dims]
        ds_mean = ds.mean(dim=spatial_dims, skipna=True)
        df = ds_mean.to_dataframe().reset_index()
        for col in ["t", "time"]:
            if col in df.columns:
                df = df.rename(columns={col: "timestamp"})
                break
        dfs.append(df)
        log.info(f"  [S2] {nc_path.name}: {len(df)} monthly records")
        ds.close()

    if not dfs:
        return None

    merged = pd.concat(dfs, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    merged = merged.rename(columns={
        "Chl_a": "chl_a", "Cyanobacteria": "cyanobacteria",
        "Turbidity": "turbidity_sat", "CDOM": "cdom", "DOC": "doc",
    })
    out = OUTPUT_DIR / "vardar_wq_merged.parquet"
    merged.to_parquet(out, index=False)
    log.info(f"[S2] WQ merged parquet: {len(merged)} rows → {out}")
    return out


def main():
    log.info("Connecting to Copernicus openEO...")
    conn = openeo.connect("https://openeo.dataspace.copernicus.eu")
    conn.authenticate_oidc()
    log.info("Authenticated.\n")

    # ── Sentinel-2 WQ jobs ────────────────────────────────────────────────────
    nc_paths = []
    for year in YEARS:
        nc_path = run_wq_year_job(conn, year)
        nc_paths.append(nc_path)
        if year != YEARS[-1]:
            log.info("Waiting 10s before next S2 job...")
            time.sleep(10)

    wq_parquet = merge_wq_to_parquet(nc_paths)

    # ── Sentinel-3 SLSTR LST jobs ─────────────────────────────────────────────
    log.info("\n--- Starting Sentinel-3 SLSTR LST download ---")
    lst_paths = []
    for year in YEARS:
        lst_path = run_lst_year_job(conn, year)
        lst_paths.append(lst_path)
        if year != YEARS[-1]:
            log.info("Waiting 10s before next S3 job...")
            time.sleep(10)

    lst_parquet = merge_lst_parquets(lst_paths)

    if wq_parquet and lst_parquet:
        log.info(
            f"\nDone.\n"
            f"  S2 WQ data:  {wq_parquet}\n"
            f"  S3 LST data: {lst_parquet}\n"
            f"\nNext step:\n"
            f"  python train.py \\\n"
            f"    --satellite {wq_parquet} \\\n"
            f"    --lst       {lst_parquet} \\\n"
            f"    --sensor    <your_sensor.csv> \\\n"
            f"    --output    models/"
        )


if __name__ == "__main__":
    main()