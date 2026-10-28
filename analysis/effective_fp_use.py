"""
Effective (modern) vs any FP use, and the men-vs-women breakdown.

Motivation
----------
fpbeh_fpnow asks: "Are you currently doing something or using any method to
delay or avoid getting pregnant?" (binary). As the academic team flagged,
answering "yes" here does not imply a *modern/effective* method is being
used — traditional methods (rhythm, withdrawal, "other traditional") count
too. fpbeh_which_1..17 records which specific method(s) the respondent is
using, so it can split "any use" into modern-method use vs traditional-only
use. Method codes and the modern/traditional split reuse the same
classification already used by etl_pipeline/export_pp_app_data.py
(MODERN_METHOD_CODES, DHS/FP2020 convention: everything except Rhythm (14),
Withdrawal (15) and Other traditional (16)) — kept in one place so the two
scripts can't silently disagree.

Output: analysis/outputs/effective_fp_use_summary.csv (one row per
overall/gender group) plus a printed narrative. No respondent-level data
is written or printed — only aggregated counts/percentages.
"""

import sys
from pathlib import Path

import pandas as pd

ANALYSIS_DIR = Path(__file__).parent
PHONE_PULSE_DIR = ANALYSIS_DIR.parent
sys.path.insert(0, str(PHONE_PULSE_DIR / "etl_pipeline"))
from export_pp_app_data import FP_METHOD_LABELS, MODERN_METHOD_CODES  # noqa: E402

CLEANED_DATA = PHONE_PULSE_DIR / "etl_pipeline" / "outputs" / "cleaned_data.csv"
OUTPUT_DIR = ANALYSIS_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

TRADITIONAL_CODES = sorted(int(c) for c in (set(FP_METHOD_LABELS) - MODERN_METHOD_CODES))
WHICH_COLS = {int(i): f"fpbeh_which_{int(i)}" for i in FP_METHOD_LABELS}

GENDER_LABELS = {
    "Namiji / Homme": "Men",
    "Mace / Femme": "Women",
}


def classify(df: pd.DataFrame) -> pd.DataFrame:
    fp_now = pd.to_numeric(df.get("fpbeh_fpnow"), errors="coerce")

    modern_cols = [WHICH_COLS[c] for c in MODERN_METHOD_CODES if WHICH_COLS[c] in df.columns]
    trad_cols = [WHICH_COLS[c] for c in TRADITIONAL_CODES if WHICH_COLS[c] in df.columns]
    any_which_cols = modern_cols + trad_cols

    def _any_selected(cols):
        if not cols:
            return pd.Series(False, index=df.index)
        sub = df[cols].apply(pd.to_numeric, errors="coerce")
        return sub.eq(1).any(axis=1)

    has_modern = _any_selected(modern_cols)
    has_traditional = _any_selected(trad_cols)
    has_any_which = _any_selected(any_which_cols)

    out = pd.DataFrame({
        "fp_now": fp_now,
        "has_modern_method": has_modern,
        "has_traditional_method": has_traditional,
        "has_any_which_answer": has_any_which,
    }, index=df.index)

    def _bucket(row):
        if row["fp_now"] != 1.0:
            return "Not using (fpbeh_fpnow=0/missing)"
        if row["has_modern_method"]:
            return "Using: modern/effective method"
        if row["has_traditional_method"]:
            return "Using: traditional method only"
        return "Using (fpbeh_fpnow=1) but no method recorded in fpbeh_which"

    out["use_category"] = out.apply(_bucket, axis=1)
    return out


def summarize(labeled: pd.DataFrame, label: str) -> dict:
    n = len(labeled)
    if n == 0:
        return {"group": label, "n": 0}
    fp_now_rate = (labeled["fp_now"] == 1.0).mean() * 100
    modern_rate = (labeled["use_category"] == "Using: modern/effective method").mean() * 100
    trad_rate = (labeled["use_category"] == "Using: traditional method only").mean() * 100
    unspecified_rate = (
        labeled["use_category"] == "Using (fpbeh_fpnow=1) but no method recorded in fpbeh_which"
    ).mean() * 100
    inconsistent_no_but_method = (
        (labeled["fp_now"] != 1.0) & labeled["has_any_which_answer"]
    ).mean() * 100
    return {
        "group": label,
        "n": n,
        "pct_any_use_fpbeh_fpnow": round(fp_now_rate, 1),
        "pct_modern_effective_method": round(modern_rate, 1),
        "pct_traditional_method_only": round(trad_rate, 1),
        "pct_fpnow_yes_no_method_recorded": round(unspecified_rate, 1),
        "gap_any_use_minus_modern_pts": round(fp_now_rate - modern_rate, 1),
        "pct_fpnow_no_but_method_selected_inconsistency": round(inconsistent_no_but_method, 1),
    }


def main():
    df = pd.read_csv(CLEANED_DATA, low_memory=False)
    labeled = classify(df)
    labeled["gender_pull"] = df.get("gender_pull")

    rows = [summarize(labeled, "All respondents")]
    for raw_label, clean_label in GENDER_LABELS.items():
        sub = labeled[labeled["gender_pull"] == raw_label]
        rows.append(summarize(sub, clean_label))

    summary = pd.DataFrame(rows)
    out_path = OUTPUT_DIR / "effective_fp_use_summary.csv"
    summary.to_csv(out_path, index=False)

    # Method mix among those reporting current use (fpbeh_fpnow == 1), overall and by gender
    mix_rows = []
    users = df[pd.to_numeric(df.get("fpbeh_fpnow"), errors="coerce") == 1.0]
    for group_label, sub in [("All users", users)] + [
        (clean_label, users[users["gender_pull"] == raw_label])
        for raw_label, clean_label in GENDER_LABELS.items()
    ]:
        n_users = len(sub)
        for code, label in sorted(FP_METHOD_LABELS.items()):
            col = WHICH_COLS[code]
            if col not in sub.columns or n_users == 0:
                continue
            pct = (pd.to_numeric(sub[col], errors="coerce") == 1).mean() * 100
            mix_rows.append({
                "group": group_label,
                "n_users_in_group": n_users,
                "method": label,
                "is_modern": code in MODERN_METHOD_CODES,
                "pct_of_users_selecting": round(pct, 1),
            })
    mix = pd.DataFrame(mix_rows)
    mix_path = OUTPUT_DIR / "effective_fp_use_method_mix.csv"
    mix.to_csv(mix_path, index=False)

    print("=" * 78)
    print("EFFECTIVE (MODERN) VS ANY FP USE — fpbeh_fpnow vs fpbeh_which")
    print("=" * 78)
    print(summary.to_string(index=False))
    print(f"\nWritten: {out_path}")
    print(f"Written: {mix_path}")
    print("""
Reading guide:
  pct_any_use_fpbeh_fpnow          — the headline number as asked in the survey
                                      ("are you doing/using something"); can include
                                      traditional methods.
  pct_modern_effective_method      — % of the WHOLE group using a modern/effective
                                      method per fpbeh_which (DHS/FP2020 modern-method
                                      list). This is the more clinically meaningful
                                      "effective use" figure.
  gap_any_use_minus_modern_pts     — how many percentage points of the headline
                                      "currently using" figure are traditional-method-only
                                      or unrecorded — i.e. the inflation the academics
                                      were concerned about.
  pct_fpnow_no_but_method_selected_inconsistency
                                    — logical-inconsistency check: respondents who said
                                      they are NOT currently using anything, but still
                                      selected a method in fpbeh_which. Small numbers are
                                      expected form/skip-logic noise; investigate if large.
""")


if __name__ == "__main__":
    main()
