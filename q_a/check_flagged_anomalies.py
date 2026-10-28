"""
Compare manually-flagged submissions against the high-quality "keep" reference
group (all submissions NOT in manual_flags.csv) and report anomalous answers.

Two classes of anomaly are detected:

  single_column  — one variable is unusual vs the keep distribution
                   (z-score for numeric/Likert; rare value for binary)

  combination    — a pair or profile of variables is unusual together:
                     • rare_pair      – joint value pair seen in <5% of keep
                     • logic_conflict – one answer contradicts another
                     • mahal_outlier  – attitude profile (all fpatt_* together)
                                        lies far from the keep centroid

Outputs (q_a/outputs/):
  flagged_anomalies_detail.csv   — one row per anomaly
  flagged_anomalies_summary.csv  — one row per flagged KEY with counts by class
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
from config_qa import RAW_DATA_PATH, QA_OUTPUT_DIR, MANUAL_FLAGS_CSV


# ── Column lists ──────────────────────────────────────────────────────────────

NUMERIC_COLS = ["duration", "radio_hours"]

LIKERT_COLS = [
    "fpatt_immoral", "fpatt_immoral_2", "fpatt_dontplan", "fpatt_femresponsible",
    "fpatt_finance", "fpatt_childinvest", "fpatt_steril", "fpatt_knowledge",
    "fpatt_immoral_spouse", "fpatt_immoral_2_spouse", "fpatt_dontplan_spouse",
    "fpatt_femresponsible_spouse", "fpatt_finance_spouse", "fpatt_childinvest_spouse",
    "fpatt_steril_spouse", "fpatt_knowledge_spouse",
    "fpatt_immoral_commu", "fpatt_immoral_2_commu", "fpatt_dontplan_commu",
    "fpatt_femresponsible_commu", "fpatt_finance_commu", "fpatt_childinvest_commu",
    "fpatt_steril_commu", "fpatt_knowledge_commu",
]

BINARY_COLS = [
    "current_pregnant", "fpbeh_fpnow", "radio_any",
    "overheard_yn", "partner_pressure", "fpbeh_pregchance",
    "pressure_discuss",
]

# Cross-variable pairs to check for joint rarity.
# Each entry: (col_a, col_b, readable_label)
PAIR_CHECKS = [
    ("radio_any",        "radio_hours",                "radio_any × radio_hours"),
    ("fpbeh_fpnow",      "current_pregnant",           "fp_use × pregnancy"),
    ("fpbeh_fpnow",      "fpbeh_pregchance",           "fp_use × preg_chance"),
    ("partner_pressure", "pressure_discuss",           "partner_pressure × discuss"),
    ("overheard_yn",     "partner_pressure",           "overheard × partner_pressure"),
    ("radio_any",        "radio_partner_placebo_listen","radio_any × placebo_listen"),
]

# Hard logical rules: (col_a, val_a, col_b, expected_b_values, label)
# "if col_a == val_a, col_b should be one of expected_b_values"
LOGIC_RULES = [
    # Listening to radio but zero hours/day — inconsistent
    ("radio_any", 1, "radio_hours", lambda v: v > 0,
     "radio_any=1 but radio_hours=0"),
    # Not listening to radio but claims to listen to a specific partner station
    ("radio_any", 0, "radio_partner_1_listen", lambda v: v != 1,
     "radio_any=0 but radio_partner_1_listen=1"),
    ("radio_any", 0, "radio_partner_2_listen", lambda v: v != 1,
     "radio_any=0 but radio_partner_2_listen=1"),
    ("radio_any", 0, "radio_partner_3_listen", lambda v: v != 1,
     "radio_any=0 but radio_partner_3_listen=1"),
    ("radio_any", 0, "radio_partner_placebo_listen", lambda v: v != 1,
     "radio_any=0 but radio_partner_placebo_listen=1"),
    # Currently using FP but gave a reason for not using it
    ("fpbeh_fpnow", 1, "fpbeh_whynot", lambda v: pd.isna(v) or str(v).strip() in ("", "nan"),
     "fpbeh_fpnow=1 but fpbeh_whynot populated"),
]

# ── Thresholds ────────────────────────────────────────────────────────────────

MIN_KEEP_OBS       = 30
Z_THRESHOLD        = 2.0
BINARY_RARE_THRESHOLD = 0.15
SKIP_CODES         = {-88, -99, 88, 99}
SKIP_RATE_Z_THRESHOLD = 2.5
PAIR_RARE_THRESHOLD   = 0.05   # flag pair if < 5% of keep share this combo
MIN_MAHAL_COLS     = 16        # minimum valid attitude columns for Mahalanobis
MAHAL_P_THRESHOLD  = 0.99      # chi-squared tail probability for MD² threshold


# ── Helper: chi-squared inverse (Wilson-Hilferty approximation) ───────────────

def _chi2_inv(p: float, k: int) -> float:
    """Approximate chi2.ppf(p, k) — accurate to <0.5% for k≥5, p≥0.90."""
    try:
        from scipy.stats import chi2
        return chi2.ppf(p, k)
    except ImportError:
        from math import log
        # Cornish-Fisher / Wilson-Hilferty
        z = _normal_ppf(p)
        h = 2 / (9 * k)
        return k * max(0, 1 - h + z * h ** 0.5) ** 3


def _normal_ppf(p: float) -> float:
    """Rational approximation to Φ⁻¹(p) — Abramowitz & Stegun 26.2.17."""
    import math
    if p < 0.5:
        return -_normal_ppf(1 - p)
    t = math.sqrt(-2 * math.log(1 - p))
    c = (2.515517, 0.802853, 0.010328)
    d = (1.432788, 0.189269, 0.001308)
    return t - (c[0] + c[1]*t + c[2]*t**2) / (1 + d[0]*t + d[1]*t**2 + d[2]*t**3)


# ── Reference statistics ──────────────────────────────────────────────────────

def compute_keep_stats(keep_df: pd.DataFrame) -> dict:
    stats = {}

    # ── Numeric ──
    for col in NUMERIC_COLS:
        if col not in keep_df.columns:
            continue
        series = pd.to_numeric(keep_df[col], errors="coerce").dropna()
        if len(series) < MIN_KEEP_OBS:
            continue
        std = series.std()
        stats[col] = {"mean": series.mean(), "std": std if std > 0 else np.nan,
                      "n": len(series), "type": "numeric"}

    # ── Likert ──
    for col in LIKERT_COLS:
        if col not in keep_df.columns:
            continue
        numeric = pd.to_numeric(keep_df[col], errors="coerce").dropna()
        valid = numeric[~numeric.isin(SKIP_CODES)]
        if len(valid) < MIN_KEEP_OBS:
            continue
        std = valid.std()
        stats[col] = {"mean": valid.mean(), "std": std if std > 0 else np.nan,
                      "n": len(valid), "type": "likert"}

    # ── Binary ──
    for col in BINARY_COLS:
        if col not in keep_df.columns:
            continue
        series = pd.to_numeric(keep_df[col], errors="coerce").dropna()
        if len(series) < MIN_KEEP_OBS:
            continue
        vc = series.value_counts(normalize=True)
        stats[col] = {"value_props": vc.to_dict(), "n": len(series), "type": "binary"}

    # ── Bulk Likert skip count (for excessive-skip detection) ──
    likert_in = [c for c in LIKERT_COLS if c in keep_df.columns]
    if likert_in:
        skip_counts = keep_df[likert_in].apply(
            pd.to_numeric, errors="coerce"
        ).isin(SKIP_CODES).sum(axis=1).values.astype(float)
        stats["__likert_skip_count__"] = {
            "mean": skip_counts.mean(),
            "std":  skip_counts.std() if skip_counts.std() > 0 else np.nan,
            "n":    len(skip_counts), "type": "_meta",
        }

    return stats


def compute_combination_refs(keep_df: pd.DataFrame) -> dict:
    """
    Compute reference data for combination checks:
      "pairs"   — joint frequency tables for PAIR_CHECKS columns
      "mahal"   — mean vector + inverse covariance for LIKERT_COLS attitude block
    """
    refs = {}

    # ── Joint-frequency tables ──
    pair_tables = {}
    for col_a, col_b, label in PAIR_CHECKS:
        if col_a not in keep_df.columns or col_b not in keep_df.columns:
            continue
        a = pd.to_numeric(keep_df[col_a], errors="coerce")
        b = pd.to_numeric(keep_df[col_b], errors="coerce")
        both_valid = a.notna() & b.notna()
        n = both_valid.sum()
        if n < MIN_KEEP_OBS:
            continue
        # Joint counts as proportion of valid pairs
        pairs_series = list(zip(a[both_valid], b[both_valid]))
        from collections import Counter
        counts = Counter(pairs_series)
        total  = sum(counts.values())
        props  = {pair: cnt / total for pair, cnt in counts.items()}
        pair_tables[(col_a, col_b)] = {"props": props, "n": n, "label": label}
    refs["pairs"] = pair_tables

    # ── Mahalanobis: attitude block ──
    att_cols = [c for c in LIKERT_COLS if c in keep_df.columns]
    att_data = keep_df[att_cols].apply(pd.to_numeric, errors="coerce")
    # Replace skip codes with NaN
    att_data = att_data.where(~att_data.isin(SKIP_CODES))
    # Use rows with enough valid values
    enough = att_data.notna().sum(axis=1) >= MIN_MAHAL_COLS
    att_clean = att_data[enough].copy()
    col_means = att_clean.mean()
    # Impute remaining NaNs with column mean before covariance
    att_imputed = att_clean.fillna(col_means)
    if len(att_imputed) >= len(att_cols) + 5:
        cov = np.cov(att_imputed.values, rowvar=False)
        # Tikhonov regularisation to avoid singularity
        cov += np.eye(len(att_cols)) * 1e-4
        try:
            inv_cov = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            inv_cov = np.linalg.pinv(cov)
        md_threshold = _chi2_inv(MAHAL_P_THRESHOLD, len(att_cols)) ** 0.5
        refs["mahal"] = {
            "cols":      att_cols,
            "means":     col_means.values,
            "inv_cov":   inv_cov,
            "threshold": md_threshold,
            "n":         len(att_imputed),
        }

    return refs


# ── Single-column anomaly check ───────────────────────────────────────────────

def check_single_columns(row: pd.Series, stats: dict) -> list[dict]:
    anomalies = []

    for col, ref in stats.items():
        if ref["type"] == "_meta":
            continue
        val = row.get(col, np.nan)
        if pd.isna(val):
            continue

        if ref["type"] in ("numeric", "likert"):
            num_val = pd.to_numeric(val, errors="coerce")
            if pd.isna(num_val) or pd.isna(ref["std"]):
                continue
            if ref["type"] == "likert" and num_val in SKIP_CODES:
                continue
            z = (num_val - ref["mean"]) / ref["std"]
            if abs(z) >= Z_THRESHOLD:
                anomalies.append({
                    "check_scope":   "single_column",
                    "column":        col,
                    "column_b":      "",
                    "flagged_value": num_val,
                    "keep_mean":     round(ref["mean"], 3),
                    "keep_std":      round(ref["std"], 3),
                    "z_score":       round(z, 2),
                    "anomaly_type":  f"z_score_{'high' if z > 0 else 'low'}",
                    "keep_n":        ref["n"],
                    "detail":        "",
                })

        elif ref["type"] == "binary":
            num_val = pd.to_numeric(val, errors="coerce")
            if pd.isna(num_val):
                continue
            props = ref["value_props"]
            prop_of_val = props.get(num_val, 0.0)
            if prop_of_val < BINARY_RARE_THRESHOLD:
                majority_val = max(props, key=props.get)
                anomalies.append({
                    "check_scope":       "single_column",
                    "column":            col,
                    "column_b":          "",
                    "flagged_value":     num_val,
                    "keep_pct_same":     round(prop_of_val * 100, 1),
                    "keep_majority":     majority_val,
                    "keep_majority_pct": round(props[majority_val] * 100, 1),
                    "anomaly_type":      "rare_value",
                    "keep_n":            ref["n"],
                    "detail":            "",
                })

    # Bulk skip check
    skip_ref = stats.get("__likert_skip_count__")
    if skip_ref and not pd.isna(skip_ref.get("std")):
        likert_in = [c for c in LIKERT_COLS if c in row.index]
        vals = pd.to_numeric(pd.Series([row[c] for c in likert_in]), errors="coerce")
        skip_n = float(vals.isin(SKIP_CODES).sum())
        z_skip = (skip_n - skip_ref["mean"]) / skip_ref["std"]
        if z_skip >= SKIP_RATE_Z_THRESHOLD:
            anomalies.append({
                "check_scope":   "single_column",
                "column":        "likert_skip_count",
                "column_b":      "",
                "flagged_value": int(skip_n),
                "keep_mean":     round(skip_ref["mean"], 2),
                "keep_std":      round(skip_ref["std"], 2),
                "z_score":       round(z_skip, 2),
                "anomaly_type":  "excessive_skips",
                "keep_n":        skip_ref["n"],
                "detail":        "",
            })

    return anomalies


# ── Combination anomaly checks ────────────────────────────────────────────────

def check_combinations(row: pd.Series, combo_refs: dict) -> list[dict]:
    anomalies = []

    # ── 1. Joint rarity of key pairs ──────────────────────────────────────────
    for (col_a, col_b), ref in combo_refs.get("pairs", {}).items():
        va = pd.to_numeric(row.get(col_a, np.nan), errors="coerce")
        vb = pd.to_numeric(row.get(col_b, np.nan), errors="coerce")
        if pd.isna(va) or pd.isna(vb):
            continue
        pair_prop = ref["props"].get((va, vb), 0.0)
        if pair_prop < PAIR_RARE_THRESHOLD:
            anomalies.append({
                "check_scope":   "combination",
                "column":        col_a,
                "column_b":      col_b,
                "flagged_value": f"{col_a}={va}, {col_b}={vb}",
                "keep_pct_same": round(pair_prop * 100, 1),
                "anomaly_type":  "rare_pair",
                "keep_n":        ref["n"],
                "detail":        ref["label"],
            })

    # ── 2. Hard logical rules ─────────────────────────────────────────────────
    for col_a, val_a, col_b, condition, label in LOGIC_RULES:
        if col_a not in row.index or col_b not in row.index:
            continue
        va = pd.to_numeric(row.get(col_a, np.nan), errors="coerce")
        if pd.isna(va) or va != val_a:
            continue
        vb = row.get(col_b, np.nan)
        vb_num = pd.to_numeric(vb, errors="coerce")
        # Use numeric value if available, else raw
        check_val = vb_num if not pd.isna(vb_num) else vb
        if not condition(check_val):
            anomalies.append({
                "check_scope":   "combination",
                "column":        col_a,
                "column_b":      col_b,
                "flagged_value": f"{col_a}={va}, {col_b}={vb}",
                "anomaly_type":  "logic_conflict",
                "keep_n":        "",
                "detail":        label,
            })

    # ── 3. Mahalanobis distance on attitude block ─────────────────────────────
    mahal_ref = combo_refs.get("mahal")
    if mahal_ref:
        att_cols = mahal_ref["cols"]
        vals = np.array([
            pd.to_numeric(row.get(c, np.nan), errors="coerce")
            for c in att_cols
        ], dtype=float)
        skip_mask = np.isin(vals, list(SKIP_CODES))
        valid_mask = ~np.isnan(vals) & ~skip_mask
        if valid_mask.sum() >= MIN_MAHAL_COLS:
            # Impute missing/skip with keep mean
            imputed = np.where(valid_mask, vals, mahal_ref["means"])
            diff = imputed - mahal_ref["means"]
            md = float(np.sqrt(diff @ mahal_ref["inv_cov"] @ diff))
            if md > mahal_ref["threshold"]:
                anomalies.append({
                    "check_scope":   "combination",
                    "column":        "fpatt_* (all 24)",
                    "column_b":      "",
                    "flagged_value": round(md, 2),
                    "keep_mean":     "",
                    "keep_std":      "",
                    "z_score":       round(md, 2),
                    "anomaly_type":  "mahal_outlier",
                    "keep_n":        mahal_ref["n"],
                    "detail":        f"MD={md:.2f} > threshold {mahal_ref['threshold']:.2f} "
                                     f"(chi2 p={MAHAL_P_THRESHOLD}, k={len(att_cols)}); "
                                     f"{valid_mask.sum()}/{len(att_cols)} cols valid",
                })

    return anomalies


# ── Main runner ───────────────────────────────────────────────────────────────

def run_flagged_anomaly_check() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(f"Data not found: {RAW_DATA_PATH}")
    if not MANUAL_FLAGS_CSV.exists():
        raise FileNotFoundError(f"manual_flags.csv not found: {MANUAL_FLAGS_CSV}")

    print(f"  Loading data from {RAW_DATA_PATH.name}")
    df = pd.read_excel(RAW_DATA_PATH, sheet_name="data")
    print(f"  {len(df)} total submissions, {len(df.columns)} columns")

    flags = pd.read_csv(MANUAL_FLAGS_CSV)
    flagged_keys = set(flags["KEY"].dropna().tolist())
    print(f"  {len(flagged_keys)} flagged submissions (manual_flags.csv)")

    keep_df    = df[~df["KEY"].isin(flagged_keys)].copy()
    flagged_df = df[ df["KEY"].isin(flagged_keys)].copy()
    print(f"  Keep group: {len(keep_df)} | Flagged group: {len(flagged_df)}")

    print("  Computing single-column reference stats…")
    stats = compute_keep_stats(keep_df)
    print(f"    → {len(stats) - 1} columns with valid reference distributions")

    print("  Computing combination reference data…")
    combo_refs = compute_combination_refs(keep_df)
    n_pairs = len(combo_refs.get("pairs", {}))
    has_mahal = "mahal" in combo_refs
    print(f"    → {n_pairs} joint-frequency tables, "
          f"Mahalanobis reference {'built' if has_mahal else 'SKIPPED (too few valid rows)'}")
    if has_mahal:
        ref = combo_refs["mahal"]
        print(f"    → attitude block: {len(ref['cols'])} cols, "
              f"threshold MD={ref['threshold']:.2f} (chi2 p={MAHAL_P_THRESHOLD}), "
              f"n={ref['n']}")

    detail_rows = []
    for _, row in flagged_df.iterrows():
        key = row["KEY"]
        reason_vals = flags.loc[flags["KEY"] == key, "reason"].values
        reason = reason_vals[0] if len(reason_vals) > 0 else ""

        for a in check_single_columns(row, stats):
            detail_rows.append({"KEY": key, "flag_reason": reason, **a})
        for a in check_combinations(row, combo_refs):
            detail_rows.append({"KEY": key, "flag_reason": reason, **a})

    if not detail_rows:
        print("  No anomalies detected.")
        return pd.DataFrame(), pd.DataFrame()

    detail = pd.DataFrame(detail_rows)

    # Normalise columns — not all rows have all fields
    for c in ["keep_mean", "keep_std", "z_score", "keep_pct_same",
              "keep_majority", "keep_majority_pct", "column_b", "detail"]:
        if c not in detail.columns:
            detail[c] = ""
    detail = detail.fillna({"column_b": "", "detail": ""})
    detail = detail.sort_values(["KEY", "check_scope", "column"]).reset_index(drop=True)

    # ── Summary: one row per KEY ──
    summary_rows = []
    for key, grp in detail.groupby("KEY", sort=False):
        reason = grp["flag_reason"].iloc[0]
        n_single = (grp["check_scope"] == "single_column").sum()
        n_combo  = (grp["check_scope"] == "combination").sum()
        combo_types = ", ".join(
            grp[grp["check_scope"] == "combination"]["anomaly_type"].unique().tolist()
        )
        top_cols = ", ".join(
            grp.sort_values("check_scope")["column"].tolist()[:5]
        )
        z_max = grp["z_score"].apply(
            lambda v: abs(float(v)) if str(v).replace(".", "").replace("-", "").isdigit() else 0
        ).max()
        summary_rows.append({
            "KEY":               key,
            "flag_reason":       reason,
            "n_single_col":      int(n_single),
            "n_combination":     int(n_combo),
            "n_total":           int(n_single + n_combo),
            "combo_types":       combo_types,
            "max_abs_z_or_MD":   round(z_max, 2),
            "top_columns":       top_cols,
        })

    summary = pd.DataFrame(summary_rows)
    summary = summary.sort_values("n_total", ascending=False).reset_index(drop=True)

    return detail, summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 68)
    print("Niger Phone Pulse — Flagged Submission Anomaly Check")
    print("=" * 68)

    detail, summary = run_flagged_anomaly_check()

    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if detail.empty:
        print("\nNo anomalies found.")
        return

    detail.to_csv(QA_OUTPUT_DIR / "flagged_anomalies_detail.csv",  index=False)
    summary.to_csv(QA_OUTPUT_DIR / "flagged_anomalies_summary.csv", index=False)

    n_single = (detail["check_scope"] == "single_column").sum()
    n_combo  = (detail["check_scope"] == "combination").sum()
    print(f"\n  flagged_anomalies_detail.csv  — {len(detail)} anomalies "
          f"({n_single} single-column, {n_combo} combination)")
    print(f"  flagged_anomalies_summary.csv — {len(summary)} submissions with ≥1 anomaly")

    print("\n  Top submissions by total anomaly count:")
    hdr = f"  {'KEY':<44} {'reason':<22} {'single':>6} {'combo':>5}  combo types"
    print(hdr)
    print("  " + "-" * 105)
    for _, r in summary.head(15).iterrows():
        short_key = r["KEY"].replace("uuid:", "")[:40]
        print(f"  {short_key:<44} {str(r['flag_reason']):<22} "
              f"{r['n_single_col']:>6} {r['n_combination']:>5}  {r['combo_types']}")

    print("\n  Anomaly type breakdown:")
    for atype, n in detail["anomaly_type"].value_counts().items():
        scope = detail.loc[detail["anomaly_type"] == atype, "check_scope"].iloc[0]
        print(f"    [{scope[:6]}] {atype:<25} {n}")

    print(f"\nOutputs written to: {QA_OUTPUT_DIR}")
    print("=" * 68)


if __name__ == "__main__":
    main()
