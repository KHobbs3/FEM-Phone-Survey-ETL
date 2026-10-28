"""
Master QA runner for the Niger Phone Pulse survey.

Usage:
    cd q_a
    python run_qa.py

Outputs (q_a/outputs/):
  true_invalids_report.csv     — manually flagged, training data, duplicate / wrong IDs
  anomaly_report.csv           — duration, placebo listenership, honesty, media, enumerator
  qa_summary.csv               — one row per respondent with all flags consolidated
  pair_similarity_scores.csv   — pairwise similarity scores for duplicate resp_id_pull
  duplicate_summary.csv        — one row per duplicate ID with worst-pair verdict
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from config_qa import RAW_DATA_PATH, QA_OUTPUT_DIR, MANUAL_FLAGS_CSV
from check_true_invalids import run_true_invalid_checks
from check_anomalies import run_anomaly_checks
from compare_duplicates import run_comparison, summarise as summarise_duplicates


def build_summary(true_inv: pd.DataFrame, anomalies: pd.DataFrame,
                  df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per respondent. Columns show highest flag_type per category
    and a pipe-separated list of all issues.
    """
    all_flags = pd.concat([true_inv, anomalies], ignore_index=True)
    if all_flags.empty:
        return pd.DataFrame()

    sev_rank = {"exclude": 0, "review": 1, "note": 2}

    summary_rows = []
    for rid, grp in all_flags.groupby("respondent_id", sort=False):
        keys = " | ".join(grp["KEY"].dropna().unique().tolist())
        highest = grp["flag_type"].map(sev_rank).min()
        highest_label = {0: "exclude", 1: "review", 2: "note"}[highest]
        categories = ", ".join(sorted(grp["category"].unique()))
        issues = " || ".join(grp["detail"].tolist())
        summary_rows.append({
            "respondent_id":     rid,
            "KEY":               keys,
            "highest_flag":      highest_label,
            "categories":        categories,
            "n_flags":           len(grp),
            "issues_summary":    issues,
        })

    summary = pd.DataFrame(summary_rows)
    order = {"exclude": 0, "review": 1, "note": 2}
    summary["_ord"] = summary["highest_flag"].map(order)
    summary = summary.sort_values(["_ord", "respondent_id"]).drop(columns=["_ord"])
    return summary.reset_index(drop=True)


def print_report(true_inv: pd.DataFrame, anomalies: pd.DataFrame,
                 summary: pd.DataFrame) -> None:
    print("\n" + "=" * 64)
    print("QA REPORT SUMMARY")
    print("=" * 64)

    for label, df in [("True Invalids", true_inv), ("Anomalies", anomalies)]:
        print(f"\n{label}:")
        if df.empty:
            print("  None detected.")
        else:
            counts = df.groupby(["category", "flag_type"]).size().reset_index(name="n")
            for _, r in counts.iterrows():
                print(f"  [{r['flag_type'].upper():>7}] {r['category']}: {r['n']}")

    if not summary.empty:
        n_excl   = (summary["highest_flag"] == "exclude").sum()
        n_review = (summary["highest_flag"] == "review").sum()
        n_note   = (summary["highest_flag"] == "note").sum()
        print(f"\nAffected respondents:")
        print(f"  EXCLUDE: {n_excl}  |  REVIEW: {n_review}  |  NOTE: {n_note}")
        print(f"  Total flagged: {len(summary)} of {_n_total} respondents")

        if n_excl > 0:
            print("\n  ⚠  Respondents recommended for EXCLUSION:")
            for _, r in summary[summary["highest_flag"] == "exclude"].iterrows():
                print(f"     [{r['respondent_id']}] {r['issues_summary'][:100]}")

    print("\nOutputs written to:", QA_OUTPUT_DIR)
    print("=" * 64)


_n_total = 0


def _manual_duplicate_keys() -> set[str]:
    """Return KEYs flagged as 'drop - duplicate' in manual_flags.csv."""
    if not MANUAL_FLAGS_CSV.exists():
        return set()
    try:
        flags = pd.read_csv(MANUAL_FLAGS_CSV)
        return set(flags[flags["reason"] == "drop - duplicate"]["KEY"].dropna())
    except Exception:
        return set()


def run_duplicate_scoring(df: pd.DataFrame, manual_dup_keys: set[str]) -> None:
    """
    Run pairwise similarity scoring for duplicate resp_id_pull groups and write
    pair_similarity_scores.csv + duplicate_summary.csv to outputs/.

    Triggered when either:
      • check_duplicate_respondent_ids found resp_id_pull values appearing > 1x
      • manual_flags.csv contains entries with reason 'drop - duplicate'

    No synthetic data is injected — only real survey rows are compared.
    If a manually-flagged duplicate KEY shares its resp_id_pull with other
    submissions, it will appear in the scored pairs automatically.
    If not (i.e. different IDs were entered), it is listed in the unpaired warning.
    """
    print("\n── Duplicate Similarity Scoring ─────────────────────────────────────")
    has_name = "name_pull" in df.columns
    if not has_name:
        print("  name_pull not present — name matching disabled")

    scores  = run_comparison(df, has_name)
    summary = summarise_duplicates(scores)

    # Warn about manually-flagged duplicates that weren't auto-paired
    if manual_dup_keys and "KEY" in df.columns:
        scored_keys = set(scores["KEY_a"].tolist() + scores["KEY_b"].tolist()) if not scores.empty else set()
        unpaired = manual_dup_keys - scored_keys
        if unpaired:
            print(f"\n  ⚠  {len(unpaired)} manually-flagged duplicate KEY(s) not found in any scored pair.")
            print("     These submissions may have a unique resp_id_pull — check the raw data to identify their pair:")
            for k in sorted(unpaired):
                print(f"     {k}")

    if scores.empty:
        print("  No duplicate pairs found to score.")
        return

    scores.to_csv(QA_OUTPUT_DIR / "pair_similarity_scores.csv",  index=False)
    summary.to_csv(QA_OUTPUT_DIR / "duplicate_summary.csv",       index=False)
    print(f"\n  pair_similarity_scores.csv — {len(scores)} pair(s)")
    print(f"  duplicate_summary.csv      — {len(summary)} respondent ID(s)")

    verdict_counts = summary["worst_verdict"].value_counts()
    for verdict in ["probable_wrong_id", "review_needed", "same_person"]:
        n = verdict_counts.get(verdict, 0)
        print(f"    {verdict:<22} {n}")


def main() -> None:
    global _n_total
    print("=" * 64)
    print("Niger Phone Pulse — Quality Assurance")
    print("=" * 64)

    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Data file not found at {RAW_DATA_PATH}."
        )

    print(f"\n[1/5] Loading data")
    print(f"      {RAW_DATA_PATH.name}")
    df = pd.read_excel(RAW_DATA_PATH, sheet_name='data')
    _n_total = len(df)
    print(f"      {_n_total} submissions loaded, {len(df.columns)} columns")

    print(f"\n[2/5] True invalid checks")
    true_inv = run_true_invalid_checks(df)

    # Trigger duplicate scoring if auto-detected OR manually flagged
    DUP_CATEGORIES = {"duplicate_wrong_id", "duplicate_inconsistent", "duplicate_repeat"}
    auto_dups = not true_inv.empty and true_inv["category"].isin(DUP_CATEGORIES).any()
    manual_dup_keys = _manual_duplicate_keys()
    has_duplicates = auto_dups or bool(manual_dup_keys)
    if manual_dup_keys:
        print(f"  {len(manual_dup_keys)} manually-flagged duplicate KEY(s) from manual_flags.csv")

    print(f"\n[3/5] Anomaly detection")
    anomalies = run_anomaly_checks(df)

    print(f"\n[4/5] Duplicate similarity scoring")
    if has_duplicates:
        run_duplicate_scoring(df, manual_dup_keys)
    else:
        print("      No duplicate respondent IDs detected — skipping")

    print(f"\n[5/5] Building summary and writing outputs")
    summary = build_summary(true_inv, anomalies, df)

    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    true_inv.to_csv(QA_OUTPUT_DIR / "true_invalids_report.csv",  index=False)
    anomalies.to_csv(QA_OUTPUT_DIR / "anomaly_report.csv",       index=False)
    summary.to_csv(QA_OUTPUT_DIR / "qa_summary.csv",             index=False)
    print(f"      true_invalids_report.csv, anomaly_report.csv, qa_summary.csv")

    print_report(true_inv, anomalies, summary)


if __name__ == "__main__":
    main()
