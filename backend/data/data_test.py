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
    print(f"\n--- {nc_path.name} ---")
    ds = xr.open_dataset(nc_path, engine="netcdf4")
    print(ds)  # shows all dims, vars, dtypes

    numeric_vars = [v for v in ds.data_vars if ds[v].dtype.kind in ("f", "i", "u")]
    print(f"Numeric vars: {numeric_vars}")

    if not numeric_vars:
        print("WARNING: no numeric vars found, skipping.")
        continue

    spatial_dims = [d for d in ["x", "y"] if d in ds.dims]
    print(f"Spatial dims: {spatial_dims}")

    ds_mean = ds[numeric_vars].mean(dim=spatial_dims, skipna=True)
    df = ds_mean.to_dataframe().reset_index()
    print(df.head())
    dfs.append(df)

print(f"\nTotal dataframes collected: {len(dfs)}")