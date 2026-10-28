"""
Transform: parse types, handle sentinel values, remove PII, compute QA columns.
"""

import pandas as pd
import numpy as np
from config import (
    PII_COLUMNS, SENTINEL_MAP, COL_RESPONDENT_ID,
    BINARY_COLUMNS, LIKERT_COLUMNS, NUMERIC_CONTINUOUS_COLUMNS, ORDINAL_COLUMNS,
)


# ── Sentinel handling ──────────────────────────────────────────────────────────

def _is_sentinel(val: str) -> bool:
    try:
        return int(float(val)) in SENTINEL_MAP
    except (ValueError, TypeError):
        return False


def replace_sentinels(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Replace sentinel codes (-99, -88) with NaN in numeric columns.
    Returns (cleaned_df, sentinel_log_df) where sentinel_log records every
    cell that was replaced so we can audit response patterns.
    """
    sentinel_keys = {str(k): v for k, v in SENTINEL_MAP.items()}
    numeric_cols = BINARY_COLUMNS + LIKERT_COLUMNS + NUMERIC_CONTINUOUS_COLUMNS + ORDINAL_COLUMNS

    log_rows = []
    df = df.copy()

    for col in numeric_cols:
        if col not in df.columns:
            continue
        mask = df[col].isin(sentinel_keys.keys())
        for idx in df.index[mask]:
            raw_val = df.at[idx, col]
            log_rows.append({
                "respondent_id": df.at[idx, COL_RESPONDENT_ID] if COL_RESPONDENT_ID in df.columns else idx,
                "column": col,
                "sentinel_code": int(float(raw_val)),
                "sentinel_meaning": SENTINEL_MAP.get(int(float(raw_val)), "unknown"),
            })
        df.loc[mask, col] = np.nan

    sentinel_log = pd.DataFrame(log_rows)
    return df, sentinel_log


# ── Type coercion ──────────────────────────────────────────────────────────────

def coerce_types(df: pd.DataFrame) -> pd.DataFrame:
    """Cast columns to appropriate dtypes after sentinels have been replaced."""
    df = df.copy()

    numeric_cols = BINARY_COLUMNS + LIKERT_COLUMNS + NUMERIC_CONTINUOUS_COLUMNS + ORDINAL_COLUMNS
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for ts_col in ["starttime", "endtime", "SubmissionDate"]:
        if ts_col in df.columns:
            df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")

    for date_col in ["interview_date", "edd"]:
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    return df


# ── Duration cross-check ───────────────────────────────────────────────────────

def add_computed_duration(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive actual call duration from endtime - starttime.
    Add columns:
      computed_duration_seconds  – derived from timestamps
      duration_discrepancy_seconds – |reported - computed|
    """
    df = df.copy()
    if "starttime" in df.columns and "endtime" in df.columns:
        elapsed = (df["endtime"] - df["starttime"]).dt.total_seconds()
        df["computed_duration_seconds"] = elapsed
        if "duration" in df.columns:
            df["duration_discrepancy_seconds"] = (df["duration"] - elapsed).abs()
    return df


# ── PII removal ────────────────────────────────────────────────────────────────

def drop_pii(df: pd.DataFrame) -> pd.DataFrame:
    """Drop all PII columns. Silently skips columns that don't exist."""
    cols_to_drop = [c for c in PII_COLUMNS if c in df.columns]
    return df.drop(columns=cols_to_drop)


# ── Standardise empty / whitespace strings ────────────────────────────────────

def standardise_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Replace blank / whitespace-only strings with NaN."""
    df = df.copy()
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        df[col] = df[col].where(~df[col].str.fullmatch(r"\s*", na=False), other=np.nan)
    return df


# ── Main transform entry point ─────────────────────────────────────────────────

def transform(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Full transform pass.
    Returns:
      (cleaned_df, sentinel_log_df)
    cleaned_df has no PII, sentinel codes replaced by NaN, types coerced,
    and QA columns appended.
    """
    df = standardise_strings(raw_df)
    df, sentinel_log = replace_sentinels(df)
    df = coerce_types(df)
    df = add_computed_duration(df)
    df = drop_pii(df)
    return df, sentinel_log
