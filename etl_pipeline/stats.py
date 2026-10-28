"""
Stats: generate descriptive statistics for each survey question.
Outputs a single summary CSV plus per-section tabs / CSVs.
"""

import pandas as pd
import numpy as np
from config import (
    BINARY_COLUMNS, LIKERT_COLUMNS, NUMERIC_CONTINUOUS_COLUMNS,
    ORDINAL_COLUMNS, MULTISELECT_COLUMNS, SKIP_STATS_COLUMNS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_counts(series: pd.Series) -> dict:
    """Return n, n_missing, pct_missing for any series."""
    n_total = len(series)
    n_missing = series.isna().sum()
    return {
        "n_total": n_total,
        "n_valid": n_total - n_missing,
        "n_missing": n_missing,
        "pct_missing": round(100 * n_missing / n_total, 1) if n_total else np.nan,
    }


# ── Per-type stat functions ───────────────────────────────────────────────────

def numeric_summary(col: str, series: pd.Series) -> pd.DataFrame:
    """Mean, median, SD, min/max, percentiles for a continuous series."""
    base = _base_counts(series)
    s = series.dropna()
    if s.empty:
        stats = {k: np.nan for k in ["mean", "median", "std", "min", "p25", "p75", "max"]}
    else:
        stats = {
            "mean":   round(s.mean(), 3),
            "median": round(s.median(), 3),
            "std":    round(s.std(), 3),
            "min":    round(s.min(), 3),
            "p25":    round(s.quantile(0.25), 3),
            "p75":    round(s.quantile(0.75), 3),
            "max":    round(s.max(), 3),
        }
    row = {"column": col, "stat_type": "numeric", **base, **stats}
    return pd.DataFrame([row])


def likert_summary(col: str, series: pd.Series) -> pd.DataFrame:
    """Numeric summary + value distribution for 1–5 Likert items."""
    num_df = numeric_summary(col, series)
    num_df["stat_type"] = "likert"

    s = series.dropna()
    dist_rows = []
    for val in sorted([1, 2, 3, 4, 5]):
        n = (s == val).sum()
        dist_rows.append({
            "column": col, "stat_type": "likert_distribution",
            "value": val, "n": int(n),
            "pct_of_valid": round(100 * n / len(s), 1) if len(s) else np.nan,
        })
    dist_df = pd.DataFrame(dist_rows)
    return pd.concat([num_df, dist_df], ignore_index=True)


def binary_summary(col: str, series: pd.Series) -> pd.DataFrame:
    """Frequency table for 0/1 binary columns."""
    base = _base_counts(series)
    s = series.dropna()
    rows = []
    for val, label in [(1, "yes/true"), (0, "no/false")]:
        n = (s == val).sum()
        rows.append({
            "column": col, "stat_type": "binary",
            **base,
            "value": val, "label": label,
            "n": int(n),
            "pct_of_valid": round(100 * n / len(s), 1) if len(s) else np.nan,
        })
    return pd.DataFrame(rows)


def categorical_summary(col: str, series: pd.Series) -> pd.DataFrame:
    """Value counts for ordinal / categorical columns."""
    base = _base_counts(series)
    s = series.dropna().astype(str)
    counts = s.value_counts().sort_index()
    rows = []
    for val, n in counts.items():
        rows.append({
            "column": col, "stat_type": "categorical",
            **base,
            "value": val,
            "n": int(n),
            "pct_of_valid": round(100 * n / len(s), 1) if len(s) else np.nan,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        [{"column": col, "stat_type": "categorical", **base, "value": np.nan, "n": 0}]
    )


def multiselect_summary(col: str, series: pd.Series) -> pd.DataFrame:
    """Explode space-separated multi-select values and count each option."""
    base = _base_counts(series)
    s = series.dropna().astype(str)
    n_valid_responses = len(s)

    # Explode
    options = s.str.split().explode()
    counts = options.value_counts().sort_values(ascending=False)

    rows = []
    for opt, n in counts.items():
        rows.append({
            "column": col, "stat_type": "multiselect",
            **base,
            "option": opt,
            "n_selected": int(n),
            "pct_of_responses": round(100 * n / n_valid_responses, 1) if n_valid_responses else np.nan,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        [{"column": col, "stat_type": "multiselect", **base, "option": np.nan, "n_selected": 0}]
    )


# ── Column classifier ─────────────────────────────────────────────────────────

def _classify_column(col: str, series: pd.Series) -> str:
    """Infer stat type for columns not in the explicit registries."""
    if col in MULTISELECT_COLUMNS:
        return "multiselect"
    if col in LIKERT_COLUMNS:
        return "likert"
    if col in BINARY_COLUMNS:
        return "binary"
    if col in NUMERIC_CONTINUOUS_COLUMNS:
        return "numeric"
    if col in ORDINAL_COLUMNS:
        return "categorical"

    # Heuristic fallback
    s = series.dropna()
    if s.empty:
        return "skip"
    # Datetime columns can't be treated as numeric
    if pd.api.types.is_datetime64_any_dtype(series):
        return "skip"
    # Multi-select: string column with spaces in values
    if series.dtype == object:
        sample = s.head(20).astype(str)
        if sample.str.contains(r" ").any():
            return "multiselect"
        return "categorical"
    # Numeric with only 0/1 → binary
    if not pd.api.types.is_numeric_dtype(series):
        return "categorical"
    unique_vals = set(s.unique()) - {np.nan}
    if unique_vals <= {0, 1}:
        return "binary"
    # Small integer range → likely ordinal
    if s.between(1, 10).all() and (s % 1 == 0).all():
        return "categorical"
    return "numeric"


# ── Master stats generator ─────────────────────────────────────────────────────

def generate_all_stats(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """
    Compute descriptive statistics for every survey column.

    Returns a dict of DataFrames keyed by stat type:
      "numeric"     – continuous numeric columns
      "likert"      – 1-5 attitude scales
      "binary"      – yes/no columns
      "categorical" – ordinal / single-choice columns
      "multiselect" – multi-select option columns
    """
    # Also skip SurveyCTO sentinel-indicator sub-columns (end in __99, __88, __22)
    # and "other specify" text sub-columns (end in __22 or _oth suffix pattern).
    def _is_sentinel_subcol(col: str) -> bool:
        return col.endswith("__99") or col.endswith("__88") or col.endswith("__22")

    skip = set(SKIP_STATS_COLUMNS) | {"_source_file"}
    results: dict[str, list[pd.DataFrame]] = {
        "numeric": [], "likert": [], "binary": [],
        "categorical": [], "multiselect": [],
    }

    for col in df.columns:
        if col in skip or _is_sentinel_subcol(col):
            continue

        series = df[col]
        kind = _classify_column(col, series)

        if kind == "numeric":
            results["numeric"].append(numeric_summary(col, series))
        elif kind == "likert":
            results["likert"].append(likert_summary(col, series))
        elif kind == "binary":
            results["binary"].append(binary_summary(col, series))
        elif kind == "categorical":
            results["categorical"].append(categorical_summary(col, series))
        elif kind == "multiselect":
            results["multiselect"].append(multiselect_summary(col, series))
        # "skip" → do nothing

    return {k: pd.concat(v, ignore_index=True) if v else pd.DataFrame()
            for k, v in results.items()}


def sentinel_rate_summary(sentinel_log: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise sentinel codes per column:
    how many responses per code, so analysts can see patterns.
    """
    if sentinel_log.empty:
        return pd.DataFrame()
    summary = (
        sentinel_log
        .groupby(["column", "sentinel_code", "sentinel_meaning"])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return summary
