"""
Entry point for the Niger Phone Pulse ETL pipeline.

Usage:
    cd etl_pipeline
    python run.py                          # all submissions
    python run.py --keep-list <path>       # filter to KEYs listed in a CSV
    python run.py --no-recode-refresh      # apply the "Other" recodes file as it is

Before anything else, "Other (specify)" write-ins are recoded (other_recodes.py):
the recodes file is refreshed with fuzzy-matched codes for any new write-ins,
then applied to the raw export. For other rounds, use run_round.py.

The keep-list CSV must have a "KEY" column.  Any row whose KEY is NOT in
that list is dropped before processing.  Pass the q_a/reference_data/keep_list.csv
to run only on the high-quality, non-flagged submissions.

Outputs (all under etl_pipeline/outputs/):
  cleaned_data.csv           – PII-free, sentinel-replaced, type-coerced survey data
  validation_report.csv      – per-respondent quality issues
  sentinel_log.csv           – every cell where a sentinel code (-88/-99) was replaced
  stats/numeric.csv          – continuous variable summaries
  stats/likert.csv           – Likert attitude scale summaries
  stats/binary.csv           – yes/no question summaries
  stats/categorical.csv      – ordinal / single-choice summaries
  stats/multiselect.csv      – multi-select option frequencies
  stats/sentinel_rates.csv   – sentinel code frequencies per column
"""

import sys
import argparse
import pandas as pd
from pathlib import Path

# Allow running from either the project root or the etl_pipeline directory.
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, STATS_DIR, COL_KEY, FORM_PATH
from extract import load_raw_data
import other_recodes
from transform import transform
from validate import run_validation
from stats import generate_all_stats, sentinel_rate_summary


def confirm_no_pii(df: pd.DataFrame) -> None:
    """Hard assertion: known PII column names must not appear in the output."""
    from config import PII_COLUMNS
    leaked = [c for c in PII_COLUMNS if c in df.columns]
    if leaked:
        raise RuntimeError(
            f"PII LEAK DETECTED — the following columns are still present: {leaked}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Niger Phone Pulse ETL Pipeline")
    parser.add_argument(
        "--keep-list", metavar="CSV",
        help="Path to a CSV with a KEY column. Only rows whose KEY appears in "
             "this file will be processed. Omit to process all submissions.",
    )
    parser.add_argument(
        "--no-recode-refresh", action="store_true",
        help="apply the 'Other' recodes file as it is, without the fuzzy refresh of other_recodes.py",
    )
    return parser.parse_args()


def _apply_keep_list(df: pd.DataFrame, keep_list_path: str) -> tuple[pd.DataFrame, int]:
    path = Path(keep_list_path)
    if not path.exists():
        raise FileNotFoundError(f"Keep-list file not found: {path}")
    keep_df = pd.read_csv(path, usecols=["KEY"], dtype=str)
    keep_keys = set(keep_df["KEY"].dropna().str.strip())
    before = len(df)
    df = df[df[COL_KEY].isin(keep_keys)].copy()
    excluded = before - len(df)
    print(f"  Keep-list filter: {before} → {len(df)} rows "
          f"({excluded} excluded, {len(keep_keys) - len(df)} listed keys not found in data)")
    return df, excluded


def main() -> None:
    args = _parse_args()

    print("=" * 60)
    print("Niger Phone Pulse ETL Pipeline")
    print("=" * 60)

    # ── 1. Extract ─────────────────────────────────────────────────────────────
    print("\n[1/4] Extracting data ...")
    raw_df = load_raw_data()
    n_raw = len(raw_df)
    n_quality_excluded = 0

    # Refresh adds new write-ins with fuzzy-matched codes (codes already in the
    # file are kept); apply swaps "Other" for the coded choice. Runs on every
    # submission, before the keep-list and the sentinel handling in transform.
    print("\n  Recoding 'Other (specify)' write-ins ...")
    if not args.no_recode_refresh:
        other_recodes.export_writeins(raw_df, form_path=FORM_PATH)
    raw_df = other_recodes.apply_other_recodes(raw_df, form_path=FORM_PATH)

    if args.keep_list:
        print(f"  Applying keep-list: {args.keep_list}")
        raw_df, n_quality_excluded = _apply_keep_list(raw_df, args.keep_list)

    # ── 2. Transform ───────────────────────────────────────────────────────────
    print("\n[2/4] Transforming data ...")
    cleaned_df, sentinel_log = transform(raw_df)
    print(f"  Rows: {len(cleaned_df)}  |  Columns after PII removal: {len(cleaned_df.columns)}")
    print(f"  Sentinel replacements logged: {len(sentinel_log)}")

    # Safety check before writing any output
    confirm_no_pii(cleaned_df)
    print("  PII check passed — no PII columns in output.")

    # ── 3. Validate ────────────────────────────────────────────────────────────
    print("\n[3/4] Running validation checks ...")
    validation_report = run_validation(cleaned_df)

    sev_counts = validation_report["severity"].value_counts().to_dict() if not validation_report.empty else {}
    for sev in ("error", "warning", "info"):
        print(f"  {sev.upper():>8}: {sev_counts.get(sev, 0)} issue(s)")

    # ── 4. Generate statistics ─────────────────────────────────────────────────
    print("\n[4/4] Generating descriptive statistics ...")
    stat_tables = generate_all_stats(cleaned_df)
    for name, tbl in stat_tables.items():
        print(f"  {name:>12}: {len(tbl)} rows")

    sentinel_rates = sentinel_rate_summary(sentinel_log)

    # ── 5. Write outputs ───────────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATS_DIR.mkdir(parents=True, exist_ok=True)

    cleaned_df.to_csv(OUTPUT_DIR / "cleaned_data.csv", index=False)
    validation_report.to_csv(OUTPUT_DIR / "validation_report.csv", index=False)
    sentinel_log.to_csv(OUTPUT_DIR / "sentinel_log.csv", index=False)

    population_summary = pd.DataFrame([
        {"metric": "n_raw", "count": n_raw,
         "description": "Total raw submissions extracted"},
        {"metric": "n_quality_excluded", "count": n_quality_excluded,
         "description": "Excluded by the QA keep-list (manual_flags.csv reasons: "
                         "duplicates, errors, nonresponse, placebo station, "
                         "dishonesty concerns, not a radio listener, etc.)"},
        {"metric": "n_after_qa", "count": len(cleaned_df),
         "description": "Rows in cleaned_data.csv (n_raw - n_quality_excluded, "
                         "or n_raw if no --keep-list was applied)"},
    ])
    population_summary.to_csv(OUTPUT_DIR / "population_summary.csv", index=False)

    for name, tbl in stat_tables.items():
        if not tbl.empty:
            tbl.to_csv(STATS_DIR / f"{name}.csv", index=False)

    if not sentinel_rates.empty:
        sentinel_rates.to_csv(STATS_DIR / "sentinel_rates.csv", index=False)

    # ── 6. Print summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Done. Outputs written to:", OUTPUT_DIR)
    print("=" * 60)

    if not validation_report.empty:
        errors = validation_report[validation_report["severity"] == "error"]
        if not errors.empty:
            print(f"\n⚠  {len(errors)} ERROR(S) require attention:")
            for _, row in errors.iterrows():
                print(f"   [{row['respondent_id']}] {row['check_name']}: {row['detail']}")

    warnings = validation_report[validation_report["severity"] == "warning"] if not validation_report.empty else pd.DataFrame()
    if not warnings.empty:
        print(f"\n   {len(warnings)} WARNING(S) flagged for review (see validation_report.csv)")


if __name__ == "__main__":
    main()
