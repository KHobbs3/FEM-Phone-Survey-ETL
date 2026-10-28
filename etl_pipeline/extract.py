"""
Extract: load raw survey data.

Preference order:
  1. The round's SurveyCTO wide export (config.RAW_XLSX), else the single .xlsx
     file in the data directory — primary real data source
  2. All .csv files concatenated — used for mock/test data when no Excel is present
"""

import pandas as pd
from pathlib import Path
from config import RAW_DATA_DIR, RAW_XLSX


def _find_xlsx(data_dir: Path) -> Path | None:
    xlsx_files = [f for f in data_dir.glob("*.xlsx") if not f.name.startswith("~$")]
    return xlsx_files[0] if len(xlsx_files) == 1 else None


def load_raw_data(data_dir: Path = RAW_DATA_DIR, xlsx: Path | None = RAW_XLSX) -> pd.DataFrame:
    """
    Load the raw survey data.  Reads the Excel wide export if present,
    otherwise falls back to concatenating all CSVs in the directory.
    """
    if xlsx is None or not xlsx.exists():
        xlsx = _find_xlsx(data_dir)

    if xlsx:
        print(f"  Reading Excel file: {xlsx.name}")
        df = pd.read_excel(xlsx, sheet_name="data", dtype=str, keep_default_na=False)
        df["_source_file"] = xlsx.name
        print(f"  Loaded {len(df)} rows, {len(df.columns)} columns")
        return df

    # Fallback: CSV files (mock / test data)
    csv_files = sorted(f for f in data_dir.glob("*.csv") if not f.name.startswith("["))
    if not csv_files:
        raise FileNotFoundError(
            f"No usable data files found in {data_dir}. "
            "Expected one .xlsx file or one or more .csv files."
        )

    frames = []
    for path in csv_files:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df["_source_file"] = path.name
        frames.append(df)
        print(f"  Loaded {len(df)} rows from {path.name}")

    combined = pd.concat(frames, ignore_index=True)
    print(f"  Total: {len(combined)} rows across {len(csv_files)} file(s)")
    return combined
