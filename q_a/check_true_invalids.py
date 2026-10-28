"""
True invalid detection for Niger Phone Pulse QA.

Covers three categories:
  1. Manual flags    — submissions confirmed invalid by a human reviewer
  2. Training data   — submissions collected before the survey go-live date
  3. Duplicate IDs   — the same participant ID appearing more than once,
                        either as repeat contacts with inconsistent answers
                        or as a wrong-ID entry by the enumerator

Output columns: KEY | respondent_id | category | flag_type | detail | supporting_data

flag_type:
  exclude  — strong case for exclusion (manually confirmed, or clearly wrong)
  review   — needs human judgment before deciding
  note     — informational; unlikely to affect analysis but logged for awareness
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from config_qa import (
    RAW_DATA_PATH, MANUAL_FLAGS_CSV, QA_OUTPUT_DIR,
    COL_KEY, COL_RESPONDENT_ID, COL_ID_ENTERED, COL_ID_REENTRY,
    COL_LGA, COL_VILLAGE, COL_SUBMISSION_DATE,
    STABLE_COLS, SURVEY_KEY_COLS,
    TRAINING_CUTOFF_DATE,
)


def _row(key, resp_id, category, flag_type, detail, supporting=""):
    return {
        "KEY": key,
        "respondent_id": resp_id,
        "category": category,
        "flag_type": flag_type,
        "detail": detail,
        "supporting_data": supporting,
    }


# ── 1. Manual flags ────────────────────────────────────────────────────────────

def check_manual_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-reference submissions against the manual_flags.csv file.
    Any KEY listed there is flagged for exclusion with the reason given.
    """
    if not MANUAL_FLAGS_CSV.exists():
        print("  [manual flags] reference file not found — skipping")
        return pd.DataFrame()

    try:
        flags = pd.read_csv(MANUAL_FLAGS_CSV, comment="#")
    except Exception as e:
        print(f"  [manual flags] could not read {MANUAL_FLAGS_CSV}: {e}")
        return pd.DataFrame()

    if flags.empty or "KEY" not in flags.columns:
        print("  [manual flags] file is empty or has no KEY column — skipping")
        return pd.DataFrame()

    flagged_keys = set(flags["KEY"].dropna().str.strip())
    rows = []
    for _, row in df[df[COL_KEY].isin(flagged_keys)].iterrows():
        key   = row[COL_KEY]
        rid   = row.get(COL_RESPONDENT_ID, "unknown")
        match = flags[flags["KEY"] == key].iloc[0]
        reason     = match.get("reason", "unspecified")
        flagged_by = match.get("flagged_by", "unknown")
        date_flagged = match.get("date_flagged", "")
        rows.append(_row(
            key, rid, "manual_flag", "exclude",
            f"Manually flagged as invalid: {reason}",
            f"flagged_by={flagged_by}, date={date_flagged}",
        ))
    print(f"  [manual flags] {len(rows)} submission(s) matched")
    return pd.DataFrame(rows)


# ── 2. Training / test data ────────────────────────────────────────────────────

def check_training_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag submissions made before the go-live date as probable training data.
    TRAINING_CUTOFF_DATE must be set in config_qa.py once known.
    """
    if TRAINING_CUTOFF_DATE is None:
        print("  [training data] TRAINING_CUTOFF_DATE not set — skipping")
        return pd.DataFrame()

    cutoff = pd.Timestamp(TRAINING_CUTOFF_DATE)
    if COL_SUBMISSION_DATE not in df.columns:
        print(f"  [training data] column '{COL_SUBMISSION_DATE}' not found — skipping")
        return pd.DataFrame()

    dates = pd.to_datetime(df[COL_SUBMISSION_DATE], errors="coerce")
    mask  = dates < cutoff
    rows  = []
    for _, row in df[mask].iterrows():
        rows.append(_row(
            row.get(COL_KEY, ""), row.get(COL_RESPONDENT_ID, ""),
            "training_data", "exclude",
            f"SubmissionDate {dates[row.name].date()} is before go-live {cutoff.date()}",
            f"SubmissionDate={dates[row.name]}",
        ))
    print(f"  [training data] {len(rows)} submission(s) before cutoff {TRAINING_CUTOFF_DATE}")
    return pd.DataFrame(rows)


# ── 3. Duplicate respondent IDs ───────────────────────────────────────────────

def _compare_records(grp: pd.DataFrame) -> str:
    """Return a brief description of how two records in a duplicate group differ."""
    diffs = []
    check_cols = [c for c in STABLE_COLS + SURVEY_KEY_COLS if c in grp.columns]
    for col in check_cols:
        vals = grp[col].dropna().unique()
        if len(vals) > 1:
            diffs.append(f"{col}: {list(vals)}")
    return "; ".join(diffs) if diffs else "no differences detected in key columns"


def check_id_reentry_mismatch(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag records where the enumerator's re-entered participant ID does not
    match the original entry. This is the clearest signal of a data-entry error.
    """
    if COL_ID_ENTERED not in df.columns or COL_ID_REENTRY not in df.columns:
        print(f"  [id mismatch] columns '{COL_ID_ENTERED}' / '{COL_ID_REENTRY}' not found — skipping")
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        id1 = str(row.get(COL_ID_ENTERED, "")).strip()
        id2 = str(row.get(COL_ID_REENTRY, "")).strip()
        if id1 and id2 and id1 != id2:
            rows.append(_row(
                row.get(COL_KEY, ""), row.get(COL_RESPONDENT_ID, ""),
                "id_entry_error", "review",
                f"ID entered ({id1}) ≠ re-entry ({id2}): enumerator may have keyed wrong participant",
                f"id={id1}, id_re={id2}",
            ))
    print(f"  [id mismatch] {len(rows)} mismatch(es) detected")
    return pd.DataFrame(rows)


def check_duplicate_respondent_ids(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect respondent IDs that appear more than once in the dataset.

    Two scenarios:
      A. Stable demographics DIFFER between records → likely wrong participant ID
         entered by enumerator (the form pulled data for a different person).
      B. Stable demographics are the SAME → genuine repeat contact.
         If survey answers also differ → inconsistency flag.
    """
    if COL_RESPONDENT_ID not in df.columns:
        print(f"  [duplicates] column '{COL_RESPONDENT_ID}' not found — skipping")
        return pd.DataFrame()

    counts = df[COL_RESPONDENT_ID].value_counts()
    dup_ids = counts[counts > 1].index
    if len(dup_ids) == 0:
        print("  [duplicates] no duplicate respondent IDs found")
        return pd.DataFrame()

    rows = []
    stable_present = [c for c in STABLE_COLS if c in df.columns]
    survey_present = [c for c in SURVEY_KEY_COLS if c in df.columns]

    for rid in dup_ids:
        grp = df[df[COL_RESPONDENT_ID] == rid]
        keys = " | ".join(grp[COL_KEY].tolist()) if COL_KEY in grp.columns else ""
        n = len(grp)

        # Check if stable characteristics differ
        stable_differs = any(
            len(grp[col].dropna().unique()) > 1
            for col in stable_present
        )
        survey_differs = any(
            len(grp[col].dropna().unique()) > 1
            for col in survey_present
        )

        diff_summary = _compare_records(grp)

        if stable_differs:
            # Demographics differ → high suspicion of wrong ID
            for _, row in grp.iterrows():
                rows.append(_row(
                    row.get(COL_KEY, ""), rid,
                    "duplicate_wrong_id", "review",
                    f"ID appears {n}× with different demographics — probable wrong participant ID",
                    f"keys=[{keys}] | differences: {diff_summary}",
                ))
        elif survey_differs:
            # Same demographics, different answers → repeat contact with inconsistency
            for _, row in grp.iterrows():
                rows.append(_row(
                    row.get(COL_KEY, ""), rid,
                    "duplicate_inconsistent", "review",
                    f"ID appears {n}× (same demographics but survey answers differ)",
                    f"keys=[{keys}] | differences: {diff_summary}",
                ))
        else:
            # Identical records — exact repeat contact or actual duplicate submission
            for _, row in grp.iterrows():
                rows.append(_row(
                    row.get(COL_KEY, ""), rid,
                    "duplicate_repeat", "note",
                    f"ID appears {n}× with consistent answers — genuine repeat contact or duplicate submission",
                    f"keys=[{keys}]",
                ))

    print(f"  [duplicates] {len(dup_ids)} duplicate ID(s) across {len(rows)} record(s)")
    return pd.DataFrame(rows)


# ── Master runner ──────────────────────────────────────────────────────────────

def run_true_invalid_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Run all true-invalid checks and return a combined report DataFrame."""
    print("\n── True Invalid Checks ──────────────────────────────────────────────")
    frames = [
        check_manual_flags(df),
        check_training_data(df),
        check_id_reentry_mismatch(df),
        check_duplicate_respondent_ids(df),
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        print("  No true invalid issues found.")
        return pd.DataFrame(
            columns=["KEY","respondent_id","category","flag_type","detail","supporting_data"]
        )

    report = pd.concat(frames, ignore_index=True)
    order = {"exclude": 0, "review": 1, "note": 2}
    report["_ord"] = report["flag_type"].map(order)
    report = report.sort_values(["_ord", "respondent_id"]).drop(columns=["_ord"])
    return report.reset_index(drop=True)


if __name__ == "__main__":
    print("Running true invalid checks standalone...")
    df = pd.read_excel(RAW_DATA_PATH, sheet_name='data',low_memory=False)
    report = run_true_invalid_checks(df)
    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = QA_OUTPUT_DIR / "true_invalids_report.csv"
    report.to_csv(out, index=False)
    print(f"\nSaved {len(report)} issue(s) to {out}")
    if not report.empty:
        print(report.groupby(["category","flag_type"]).size().to_string())
