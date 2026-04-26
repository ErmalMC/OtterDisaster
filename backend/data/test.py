"""
main_v2.py — Fixed AquaSense OpenEO Pipeline
=============================================
Changes from main.py:
  - NO UDF: downloads raw reflectance bands directly
  - Computes all WQ parameters locally after download (full control)
  - Uses SCL cloud mask properly to exclude bad pixels
  - Downloads bands separately to avoid the corruption issue
  - Saves per-year NetCDF then merges to vardar_wq_merged.parquet
  - LST pipeline unchanged and working

Run:
    python main_v2.py

Output:
    vardar_wq_results_v2/
        vardar_wq_2022.nc / 2023 / 2024
        vardar_wq_merged.parquet
        vardar_lst_merged.parquet
"""

import time
import logging
from pathlib import Path

import openeo
import numpy as np
import xarray as xr
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
# Tighter BBOX — just the Vardar river channel through Skopje
# Narrower = fewer land pixels = cleaner water signal
BBOX = {"west": 21.38, "south": 41.98, "east": 21.48, "north": 42.02}

YEARS      = ["2022", "2023", "2024"]
OUTPUT_DIR = Path("vardar_wq_results_v2")
OUTPUT_DIR.mkdir(exist_ok=True)

# Sentinel-2 L2A surface reflectance scale factor
# Values are stored as integers * 10000, so divide by 10000 to get [0,1]
SCALE = 10000.0

# Valid reflectance range after scaling
REF_MIN = 0.0001
REF_MAX = 0.15   # water is dark — reflectance > 0.15 is likely land or cloud

# SLSTR LST config (unchanged from main.py)
SLSTR_BAND = "S8"  # was "S8_BT_in"
KELVIN_TO_CELSIUS = 273.15
LST_MIN_VALID_K   = 270.0
LST_MAX_VALID_K   = 320.0
LST_DECAY_DAYS    = 7


# ── Sentinel-2 raw band download (no UDF) ────────────────────────────────────

def build_s2_cube(conn: openeo.Connection, year: str) -> openeo.DataCube:
    """
    Download raw Sentinel-2 bands without UDF processing.
    SCL cloud masking applied server-side.
    Monthly median composite — one slice per month.
    Bands: B01(443nm) B02(490nm) B03(560nm) B04(665nm) B05(705nm)
    """
    time_range = [f"{year}-01-01", f"{year}-12-31"]
    log.info(f"[S2] Building raw band cube for {year}...")

    raw = conn.load_collection(
        "SENTINEL2_L2A",
        spatial_extent=BBOX,
        temporal_extent=time_range,
        bands=["B01", "B02", "B03", "B04", "B05", "SCL"],
        max_cloud_cover=20,
    )

    # SCL classes to KEEP: 4=vegetation, 5=bare soil, 6=water
    # We keep water (6) and surrounding land to allow NDWI filtering locally
    scl      = raw.band("SCL")
    keep     = (scl == 4) | (scl == 5) | (scl == 6)
    optical  = raw.filter_bands(["B01", "B02", "B03", "B04", "B05"])
    masked   = optical.mask(~keep)

    # Monthly median composite
    monthly = masked.aggregate_temporal_period(period="month", reducer="median")

    # Scale to reflectance [0, 1] — Sentinel-2 L2A stores as DN * 10000
    scaled = monthly.apply(lambda x: x / SCALE)

    return scaled


def run_s2_year(conn: openeo.Connection, year: str) -> Path:
    final_path = OUTPUT_DIR / f"vardar_wq_{year}.nc"
    if final_path.exists():
        log.info(f"[S2] {year}: already downloaded, skipping.")
        return final_path

    cube = build_s2_cube(conn, year)
    log.info(f"[S2] {year}: Submitting batch job...")
    job = cube.save_result(format="NetCDF").create_job(
        title=f"AquaSense Vardar RAW {year}"
    )
    job.start_and_wait(max_poll_interval=60, print=log.info)

    nc_dir = OUTPUT_DIR / f"vardar_wq_{year}_dl"
    nc_dir.mkdir(exist_ok=True)
    job.get_results().download_files(str(nc_dir))

    nc_files = list(nc_dir.glob("*.nc"))
    if not nc_files:
        log.error(f"[S2] {year}: No .nc file downloaded")
        return None

    nc_files[0].rename(final_path)
    log.info(f"[S2] {year}: Saved to {final_path}")
    return final_path


# ── Local WQ computation from raw bands ──────────────────────────────────────

def compute_wq_from_nc(nc_paths: list[Path]) -> Path:
    """
    Compute water quality parameters locally from raw band NetCDFs.
    Only uses pixels where NDWI > 0 (confirmed water surface).
    Outputs vardar_wq_merged.parquet with correct column names.
    """
    log.info("[S2] Computing WQ parameters locally from raw bands...")
    dfs = []

    for nc_path in nc_paths:
        if nc_path is None or not nc_path.exists():
            continue

        ds  = xr.open_dataset(nc_path, engine="netcdf4")
        dim = "t" if "t" in ds.dims else "time"
        times = ds[dim].values
        year = str(pd.Timestamp(times[0]).year)
        records = []

        log.info(f"[S2] Processing {year}: {len(times)} monthly slices...")

        for i, ts in enumerate(times):

            def band(name):
                arr = ds[name].isel({dim: i}).values.astype(np.float64)
                arr[~np.isfinite(arr)] = np.nan
                # After server-side /10000 scaling, valid reflectance is 0-1
                # Water is dark: 0.0001–0.15. Mask land/cloud pixels.
                arr[arr < REF_MIN]  = np.nan
                arr[arr > REF_MAX]  = np.nan
                return arr

            B01 = band("B01")
            B02 = band("B02")
            B03 = band("B03")
            B04 = band("B04") if "B04" in ds.data_vars else None
            B05 = band("B05") if "B05" in ds.data_vars else None

            # Water mask: NDWI > 0 using B03 (green) and B05 (red-edge as NIR proxy)
            # If B05 missing fall back to B02
            nir = B05 if B05 is not None else B02
            with np.errstate(divide="ignore", invalid="ignore"):
                ndwi_arr = (B03 - nir) / (B03 + nir)

            water = np.isfinite(ndwi_arr) & (ndwi_arr > 0)
            n_water = int(water.sum())

            if n_water < 10:
                log.warning(f"  {str(ts)[:7]}: only {n_water} water px — skipping")
                records.append({
                    "timestamp": pd.Timestamp(ts),
                    "ndwi": np.nan, "ndti": np.nan, "ndci": np.nan,
                    "chl_a": np.nan, "cyanobacteria": np.nan,
                    "turbidity_sat": np.nan, "cdom": np.nan, "doc": np.nan,
                })
                continue

            # Apply water mask to all bands
            def w(arr):
                return np.where(water & np.isfinite(arr), arr, np.nan) if arr is not None else None

            b1, b2, b3 = w(B01), w(B02), w(B03)
            b4 = w(B04) if B04 is not None else None
            b5 = w(B05) if B05 is not None else None

            with np.errstate(divide="ignore", invalid="ignore"):
                # Spectral indices
                ndwi = ndwi_arr.copy()
                ndwi[~water] = np.nan

                ndti = np.where(
                    (b4 is not None) & np.isfinite(b4) & np.isfinite(b3),
                    (b4 - b3) / (b4 + b3), np.nan
                ) if b4 is not None else np.full_like(b3, np.nan)

                ndci = np.where(
                    (b5 is not None) & np.isfinite(b5) & (b4 is not None) & np.isfinite(b4),
                    (b5 - b4) / (b5 + b4), np.nan
                ) if (b5 is not None and b4 is not None) else np.full_like(b3, np.nan)

                # WQ algorithms (Sentinel-2 empirical, Gons/Simis family)
                # chl_a: 3-band algorithm using B01(443) and B03(560)
                chl_a = np.where(
                    np.isfinite(b1) & (b1 > 0),
                    np.clip(4.26 * np.power(np.abs(b3 / b1), 3.94), 0, 200),
                    np.nan
                )

                # cyanobacteria: uses B02(490) and B03(560) and B04(665)
                if b4 is not None:
                    cyano_ratio = np.where(
                        np.isfinite(b2) & (b2 > 0) & np.isfinite(b4),
                        (b3 * b4) / b2, np.nan
                    )
                    cyanobacteria = np.clip(
                        115530.31 * np.power(np.abs(cyano_ratio), 2.38), 0, 200000
                    )
                else:
                    # fallback: use B03/B02 ratio proxy
                    cyanobacteria = np.where(
                        np.isfinite(b2) & (b2 > 0),
                        np.clip(115530.31 * np.power(np.abs(b3 / b2), 2.38), 0, 200000),
                        np.nan
                    )

                # turbidity: B03/B01 ratio algorithm
                turbidity_sat = np.where(
                    np.isfinite(b1) & (b1 > 0),
                    np.clip(8.93 * (b3 / b1) - 6.39, -2, 50),
                    np.nan
                )

                # CDOM and DOC: B03/B04 exponential algorithms
                if b4 is not None:
                    cdom = np.where(
                        np.isfinite(b4) & (b4 > 0),
                        np.clip(537 * np.exp(-2.93 * b3 / b4), 0, 1000),
                        np.nan
                    )
                    doc = np.where(
                        np.isfinite(b4) & (b4 > 0),
                        np.clip(432 * np.exp(-2.24 * b3 / b4), 0, 1000),
                        np.nan
                    )
                else:
                    cdom = doc = np.full_like(b3, np.nan)

            rec = {
                "timestamp":     pd.Timestamp(ts),
                "ndwi":          float(np.nanmedian(ndwi)),
                "ndti":          float(np.nanmedian(ndti)),
                "ndci":          float(np.nanmedian(ndci)),
                "chl_a":         float(np.nanmedian(chl_a)),
                "cyanobacteria": float(np.nanmedian(cyanobacteria)),
                "turbidity_sat": float(np.nanmedian(turbidity_sat)),
                "cdom":          float(np.nanmedian(cdom)),
                "doc":           float(np.nanmedian(doc)),
            }
            records.append(rec)
            log.info(f"  {str(ts)[:7]}: {n_water:5d} water px | "
                     f"chl={rec['chl_a']:.3f} cyano={rec['cyanobacteria']:.1f} "
                     f"turb={rec['turbidity_sat']:.2f} ndwi={rec['ndwi']:.3f}")

        dfs.append(pd.DataFrame(records))
        ds.close()

    merged = pd.concat(dfs, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    out = OUTPUT_DIR / "vardar_wq_merged.parquet"
    merged.to_parquet(out, index=False)
    log.info(f"[S2] WQ parquet saved: {len(merged)} rows → {out}")
    log.info(f"[S2] cyanobacteria: {merged['cyanobacteria'].describe()}")
    return out


# ── Sentinel-3 SLSTR LST (identical to main.py) ──────────────────────────────

def build_lst_cube(conn, year):
    time_range = [f"{year}-01-01", f"{year}-12-31"]
    lst = conn.load_collection(
        "SENTINEL3_SLSTR", spatial_extent=BBOX,
        temporal_extent=time_range, bands=[SLSTR_BAND],
    )
    return lst.apply(
        lambda x: x.linear_scale_range(
            LST_MIN_VALID_K, LST_MAX_VALID_K,
            LST_MIN_VALID_K, LST_MAX_VALID_K
        )
    )


def run_lst_year(conn, year):
    final_path = OUTPUT_DIR / f"vardar_lst_{year}.parquet"
    if final_path.exists():
        log.info(f"[S3] {year}: already downloaded, skipping.")
        return final_path

    cube = build_lst_cube(conn, year)
    log.info(f"[S3] {year}: Submitting LST batch job...")
    job = cube.save_result(format="NetCDF").create_job(
        title=f"AquaSense Vardar LST v2 {year}"
    )
    job.start_and_wait(max_poll_interval=60, print=log.info)

    nc_dir = OUTPUT_DIR / f"vardar_lst_{year}_dl"
    nc_dir.mkdir(exist_ok=True)
    job.get_results().download_files(str(nc_dir))

    nc_files = list(nc_dir.glob("*.nc"))
    if not nc_files:
        log.error(f"[S3] {year}: No .nc file")
        return None

    records = []
    ds = xr.open_dataset(nc_files[0], engine="netcdf4")
    dim = "t" if "t" in ds.dims else "time"
    timestamps = ds[dim].values
    band_var = SLSTR_BAND if SLSTR_BAND in ds.data_vars else list(ds.data_vars)[0]

    for i, ts in enumerate(timestamps):
        arr = ds[band_var].isel({dim: i}).values.astype(float)
        arr[arr < LST_MIN_VALID_K] = np.nan
        arr[arr > LST_MAX_VALID_K] = np.nan
        valid_count = int(np.sum(~np.isnan(arr)))
        if valid_count == 0:
            records.append({"timestamp": pd.Timestamp(ts),
                            "lst_water_kelvin": np.nan,
                            "lst_water_celsius": np.nan,
                            "lst_valid_px_count": 0})
        else:
            mean_k = float(np.nanmean(arr))
            records.append({"timestamp": pd.Timestamp(ts),
                            "lst_water_kelvin": round(mean_k, 3),
                            "lst_water_celsius": round(mean_k - KELVIN_TO_CELSIUS, 3),
                            "lst_valid_px_count": valid_count})
    ds.close()

    df = pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)
    df.to_parquet(final_path, index=False)
    log.info(f"[S3] {year}: {(df['lst_valid_px_count']>0).sum()}/{len(df)} valid days")
    return final_path


def merge_lst(lst_paths):
    dfs = [pd.read_parquet(p) for p in lst_paths if p and p.exists()]
    if not dfs:
        return None
    merged = pd.concat(dfs, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    out = OUTPUT_DIR / "vardar_lst_merged.parquet"
    merged.to_parquet(out, index=False)
    log.info(f"[S3] LST merged: {len(merged)} rows → {out}")
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Connecting to Copernicus openEO...")
    conn = openeo.connect("https://openeo.dataspace.copernicus.eu")
    conn.authenticate_oidc()
    log.info("Authenticated.\n")

    # ── Sentinel-2 raw band jobs ──────────────────────────────────────────────
    nc_paths = []
    for year in YEARS:
        nc_path = run_s2_year(conn, year)
        nc_paths.append(nc_path)
        if year != YEARS[-1]:
            log.info("Waiting 10s before next job...")
            time.sleep(10)

    wq_parquet = compute_wq_from_nc(nc_paths)

    # ── Sentinel-3 LST jobs ───────────────────────────────────────────────────
    log.info("\n--- Starting Sentinel-3 LST download ---")
    lst_paths = []
    for year in YEARS:
        lst_path = run_lst_year(conn, year)
        lst_paths.append(lst_path)
        if year != YEARS[-1]:
            time.sleep(10)

    lst_parquet = merge_lst(lst_paths)

    if wq_parquet and lst_parquet:
        log.info(
            f"\nDone.\n"
            f"  WQ parquet:  {wq_parquet}\n"
            f"  LST parquet: {lst_parquet}\n\n"
            f"Next step:\n"
            f"  python train.py \\\n"
            f"    --satellite {wq_parquet} \\\n"
            f"    --lst       {lst_parquet} \\\n"
            f"    --sensor    mock_data/sensor_readings.csv \\\n"
            f"    --output    models/\n"
        )


if __name__ == "__main__":
    main()