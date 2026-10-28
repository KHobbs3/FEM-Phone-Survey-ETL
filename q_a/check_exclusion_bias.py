"""
Compare excluded respondents against included respondents for systematic
differences (imbalance), across the three exclusion stages in the Phone
Pulse pipeline:

  A. Quality-excluded   — dropped by the QA keep-list (manual_flags.csv)
                           vs. respondents who passed QA.
                           Base: all 544 raw submissions.
  B. No radio at all    — passed QA but radio_any != 1
                           vs. FEM partner station listeners.
  C. Radio, not FEM      — passed QA, listens to radio, but to no FEM
                           partner station
                           vs. FEM partner station listeners.
                           Base (B & C): the 506 respondents who passed QA.

Why this matters: the Phone Pulse app's analysis sample is restricted to FEM
partner station listeners who passed QA. If excluded respondents differ
systematically from included ones (e.g. skew younger, more/less educated,
different baseline FP attitudes), the analysis sample is not representative
and headline numbers (e.g. unmet need %) may not generalise to the full
Phone Pulse contact list.

Variables compared: demographics (gender, age, LGA) + key outcomes (FP use,
perceived pregnancy chance, self-rated FP knowledge, attitude toward FP,
perceived community norm). radio_any is compared only in stage A, since
stages B/C are themselves defined by radio-listening status (comparing it
there would be circular).

Tests: Mann-Whitney U for continuous/ordinal variables (robust to the skew
and small subgroup sizes here), chi-square test of independence for
categorical variables (gender). LGA is summarised (top categories) but not
formally tested — too many sparse cells for a reliable chi-square.

Output: q_a/outputs/exclusion_bias_report.csv (group-level stats only — no
respondent-level values are ever written or printed).

Usage:
    cd q_a
    python check_exclusion_bias.py
"""

from __future__ import annotations

import sys
from pathlib import Path

QA_DIR = Path(__file__).parent
ETL_DIR = QA_DIR.parent / "etl_pipeline"
sys.path.insert(0, str(ETL_DIR))
sys.path.insert(0, str(QA_DIR))

import numpy as np
import pandas as pd
from scipy import stats

from config_qa import RAW_DATA_PATH, QA_OUTPUT_DIR, MANUAL_FLAGS_CSV
from extract import load_raw_data
from transform import transform
from export_pp_app_data import compute_fem_partner_listener

OUTPUT_CSV = QA_OUTPUT_DIR / "exclusion_bias_report.csv"

# ── Variables to compare ─────────────────────────────────────────────────────
CONTINUOUS_ORDINAL_VARS = [
    ("age",              "Age (years)"),
    ("fpbeh_pregchance",  "Perceived pregnancy chance (1=very likely .. 5=very unlikely)"),
    ("fpatt_knowledge",   "Attitude: 'I don't think I have enough information to use contraceptives' (higher = more agreement)"),
    ("fpatt_immoral",     "Attitude: 'Religious leaders I admire do not use or encourage contraception' (higher = more agreement)"),
    ("pressure_pnorm",    "Perceived community norm against FP (1-5, higher = more agreement)"),
]
BINARY_VARS = [
    ("fpbeh_fpnow", "Currently using FP"),
]
CATEGORICAL_VARS = [
    ("gender_pull", "Gender"),
]
LGA_VAR = "lga_pull"

SIG_THRESHOLD = 0.05


def _mannwhitney(included: pd.Series, excluded: pd.Series) -> dict:
    inc = pd.to_numeric(included, errors="coerce").dropna()
    exc = pd.to_numeric(excluded, errors="coerce").dropna()
    if len(inc) < 3 or len(exc) < 3:
        return {"included_mean": inc.mean() if len(inc) else np.nan,
                "excluded_mean": exc.mean() if len(exc) else np.nan,
                "included_n": len(inc), "excluded_n": len(exc),
                "test": "mannwhitneyu", "statistic": np.nan, "p_value": np.nan,
                "note": "too few non-missing values for a test"}
    stat, p = stats.mannwhitneyu(inc, exc, alternative="two-sided")
    return {
        "included_mean": round(inc.mean(), 2), "excluded_mean": round(exc.mean(), 2),
        "included_n": len(inc), "excluded_n": len(exc),
        "test": "mannwhitneyu", "statistic": round(float(stat), 2),
        "p_value": round(float(p), 4), "note": "",
    }


def _chi_square(included: pd.Series, excluded: pd.Series) -> dict:
    inc = included.dropna().astype(str)
    exc = excluded.dropna().astype(str)
    table = pd.DataFrame({
        "included": inc.value_counts(),
        "excluded": exc.value_counts(),
    }).fillna(0)
    if table.empty or table.shape[0] < 2 or (table.sum(axis=1) == 0).any():
        return {"included_n": len(inc), "excluded_n": len(exc),
                "test": "chi2", "statistic": np.nan, "p_value": np.nan,
                "note": "insufficient categories for a test"}
    chi2, p, dof, expected = stats.chi2_contingency(table.values.T)
    low_expected = (expected < 5).mean()
    note = "some expected cell counts < 5 — p-value may be unreliable" if low_expected > 0.2 else ""
    # Cramer's V effect size
    n = table.values.sum()
    cramers_v = float(np.sqrt(chi2 / (n * (min(table.shape) - 1)))) if n and min(table.shape) > 1 else np.nan
    top_included = inc.value_counts(normalize=True).head(3).round(3).to_dict()
    top_excluded = exc.value_counts(normalize=True).head(3).round(3).to_dict()
    return {
        "included_n": len(inc), "excluded_n": len(exc),
        "test": "chi2", "statistic": round(float(chi2), 2), "p_value": round(float(p), 4),
        "cramers_v": round(cramers_v, 3) if pd.notna(cramers_v) else np.nan,
        "note": note,
        "included_top_categories": str(top_included),
        "excluded_top_categories": str(top_excluded),
    }


def _binary_pct(included: pd.Series, excluded: pd.Series) -> dict:
    inc = pd.to_numeric(included, errors="coerce")
    exc = pd.to_numeric(excluded, errors="coerce")
    inc_pct = float(inc.eq(1).mean() * 100) if len(inc.dropna()) else np.nan
    exc_pct = float(exc.eq(1).mean() * 100) if len(exc.dropna()) else np.nan
    a = int(inc.eq(1).sum()); b = int(inc.eq(0).sum())
    c = int(exc.eq(1).sum()); d = int(exc.eq(0).sum())
    if min(a, b, c, d) == 0 or (a + b) == 0 or (c + d) == 0:
        return {"included_pct": round(inc_pct, 1) if pd.notna(inc_pct) else np.nan,
                "excluded_pct": round(exc_pct, 1) if pd.notna(exc_pct) else np.nan,
                "included_n": a + b, "excluded_n": c + d,
                "test": "chi2", "statistic": np.nan, "p_value": np.nan,
                "note": "degenerate 2x2 table — test skipped"}
    chi2, p, dof, expected = stats.chi2_contingency([[a, b], [c, d]])
    return {
        "included_pct": round(inc_pct, 1), "excluded_pct": round(exc_pct, 1),
        "included_n": a + b, "excluded_n": c + d,
        "test": "chi2", "statistic": round(float(chi2), 2), "p_value": round(float(p), 4),
        "note": "",
    }


def compare_groups(df: pd.DataFrame, included_mask: pd.Series, excluded_mask: pd.Series,
                    stage: str, include_lga: bool = True, include_radio: bool = False) -> list[dict]:
    rows = []
    included = df[included_mask]
    excluded = df[excluded_mask]

    for col, label in CONTINUOUS_ORDINAL_VARS:
        if col not in df.columns:
            continue
        res = _mannwhitney(included[col], excluded[col])
        res.update({"stage": stage, "variable": col, "label": label, "var_type": "continuous_ordinal"})
        rows.append(res)

    for col, label in BINARY_VARS:
        if col not in df.columns:
            continue
        res = _binary_pct(included[col], excluded[col])
        res.update({"stage": stage, "variable": col, "label": label, "var_type": "binary"})
        rows.append(res)

    if include_radio and "radio_any" in df.columns:
        res = _binary_pct(included["radio_any"], excluded["radio_any"])
        res.update({"stage": stage, "variable": "radio_any", "label": "Listens to radio at all",
                     "var_type": "binary"})
        rows.append(res)

    for col, label in CATEGORICAL_VARS:
        if col not in df.columns:
            continue
        res = _chi_square(included[col], excluded[col])
        res.update({"stage": stage, "variable": col, "label": label, "var_type": "categorical"})
        rows.append(res)

    if include_lga and LGA_VAR in df.columns:
        res = _chi_square(included[LGA_VAR], excluded[LGA_VAR])
        res.update({"stage": stage, "variable": LGA_VAR, "label": "LGA (geography)",
                     "var_type": "categorical_descriptive_only"})
        rows.append(res)

    return rows


def main() -> None:
    print("=" * 70)
    print("Niger Phone Pulse — Exclusion Bias Check")
    print("=" * 70)

    # ── Stage A: quality-excluded vs quality-included (full raw population) ──
    print("\n[1/3] Loading raw data and applying transform (PII-free)...")
    raw_df = load_raw_data()
    full_df, _ = transform(raw_df)
    print(f"  {len(full_df)} total raw submissions (PII-stripped)")

    manual_flags = pd.read_csv(MANUAL_FLAGS_CSV, comment="#") if MANUAL_FLAGS_CSV.exists() else pd.DataFrame()
    excluded_keys = set(manual_flags["KEY"].dropna()) if not manual_flags.empty else set()
    quality_excluded_mask = full_df["KEY"].isin(excluded_keys)
    quality_included_mask = ~quality_excluded_mask
    print(f"  Quality-excluded: {quality_excluded_mask.sum()}  |  "
          f"Quality-included: {quality_included_mask.sum()}")

    all_rows = compare_groups(
        full_df, quality_included_mask, quality_excluded_mask,
        stage="A_quality_excluded_vs_included", include_radio=True,
    )

    # ── Stage B & C: within QA-passed respondents, radio-listening splits ────
    print("\n[2/3] Splitting QA-passed respondents by radio-listening status...")
    qa_df = full_df[quality_included_mask].copy()
    radio_any = pd.to_numeric(qa_df.get("radio_any"), errors="coerce")
    fem_listener = compute_fem_partner_listener(qa_df)
    no_radio_mask = radio_any.ne(1.0)
    radio_not_fem_mask = radio_any.eq(1.0) & ~fem_listener

    print(f"  No radio at all: {no_radio_mask.sum()}  |  "
          f"Radio, not FEM: {radio_not_fem_mask.sum()}  |  "
          f"FEM listeners: {fem_listener.sum()}")

    all_rows += compare_groups(
        qa_df, fem_listener, no_radio_mask,
        stage="B_no_radio_vs_fem_listeners", include_radio=False,
    )
    all_rows += compare_groups(
        qa_df, fem_listener, radio_not_fem_mask,
        stage="C_radio_not_fem_vs_fem_listeners", include_radio=False,
    )

    print("\n[3/3] Writing report...")
    report = pd.DataFrame(all_rows)
    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report.to_csv(OUTPUT_CSV, index=False)
    print(f"  {len(report)} comparisons written to {OUTPUT_CSV}")

    print("\n" + "=" * 70)
    print("SIGNIFICANT IMBALANCES (p < %.2f)" % SIG_THRESHOLD)
    print("=" * 70)
    sig = report[report["p_value"] < SIG_THRESHOLD]
    if sig.empty:
        print("  None detected — excluded and included groups look statistically similar "
              "on the variables checked.")
    else:
        for _, r in sig.sort_values(["stage", "p_value"]).iterrows():
            print(f"\n  [{r['stage']}] {r['label']} ({r['variable']})")
            if r["var_type"] == "continuous_ordinal":
                print(f"    included mean={r['included_mean']}  (n={int(r['included_n'])})  |  "
                      f"excluded mean={r['excluded_mean']}  (n={int(r['excluded_n'])})")
            elif r["var_type"] == "binary":
                print(f"    included={r['included_pct']}%  (n={int(r['included_n'])})  |  "
                      f"excluded={r['excluded_pct']}%  (n={int(r['excluded_n'])})")
            else:
                print(f"    included top categories: {r.get('included_top_categories')}")
                print(f"    excluded top categories: {r.get('excluded_top_categories')}")
            print(f"    {r['test']} p={r['p_value']}"
                  + (f", Cramer's V={r['cramers_v']}" if pd.notna(r.get('cramers_v')) else ""))
            if r["note"]:
                print(f"    note: {r['note']}")

    print(f"\nFull report: {OUTPUT_CSV}")
    print("=" * 70)


if __name__ == "__main__":
    main()
