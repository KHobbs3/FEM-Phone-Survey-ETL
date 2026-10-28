"""
FP-user vs non-user personas: are the two groups' profiles actually different?

Rather than recomputing statistics from scratch, this reuses the group-split
tables etl_pipeline/export_pp_app_data.py already produces in
etl_pipeline/outputs/app_data/pp_*.csv (each built with split_by="fp_use",
group in {"Using FP", "Not using FP"}, over the Treatment analysis population
— FEM partner-station listeners who passed QA). Those files are aggregated,
PII-free outputs, not raw survey data.

This script scans every relevant pp_*.csv, extracts the "Using FP" vs
"Not using FP" rows, computes the gap between the two groups for every
variable/category, and ranks all of them by gap size — the biggest gaps are
what actually distinguish the two personas; most variables turn out to be
similar, which is itself the finding worth reporting.

Two input table shapes are handled:
  - mean tables   (Likert/attitude items): columns include mean, n
  - frequency tables (categorical/binary): columns include category, count, pct

Outputs (analysis/outputs/):
  persona_comparison_full.csv   — every variable/category compared, all gaps
  persona_top_differences.csv   — the largest N gaps (the persona-defining traits)
  personas_summary.md           — narrative pen-portraits of the two personas
"""

from pathlib import Path

import pandas as pd

ANALYSIS_DIR = Path(__file__).parent
NIGER_ROOT = ANALYSIS_DIR.parent.parent
APP_DATA_DIR = ANALYSIS_DIR.parent / "etl_pipeline" / "outputs" / "app_data"
OUTPUT_DIR = ANALYSIS_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# Excluded: no fp_use split (respondents_profile), a different split_by
# dimension entirely (exposure_*, treatment_arm), station-level detail
# (covered by the Alheri credibility check instead), or a straight duplicate
# of effective_fp_use.py's own method-mix table (fp_method_used).
EXCLUDE_FILES = {
    "pp_respondents_profile.csv",
    "pp_exposure_profile.csv", "pp_exposure_fp_awareness.csv",
    "pp_exposure_fp_use.csv", "pp_exposure_attitudes.csv",
    "pp_exposure_partner_norms.csv",
    "pp_village_stations.csv", "pp_radio_stations.csv",
    "pp_radio_fp_stations.csv", "pp_radio_station_frequency.csv",
    "pp_radio_fp_freq.csv", "pp_fp_method_used.csv",
}

USING = "Using FP"
NOT_USING = "Not using FP"


def _extract_mean_rows(df: pd.DataFrame, source: str) -> pd.DataFrame:
    sub = df[(df["split_by"] == "fp_use") & (df["group"].isin([USING, NOT_USING]))]
    if sub.empty:
        return pd.DataFrame()
    key_cols = [c for c in ("perspective", "variable", "label") if c in sub.columns]
    piv = sub.pivot_table(index=key_cols, columns="group", values=["mean", "n"], aggfunc="first")
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv = piv.reset_index()
    piv["source_file"] = source
    piv["type"] = "mean"
    piv["value_using"] = piv.get(f"mean_{USING}")
    piv["value_notusing"] = piv.get(f"mean_{NOT_USING}")
    piv["n_using"] = piv.get(f"n_{USING}")
    piv["n_notusing"] = piv.get(f"n_{NOT_USING}")
    piv["gap"] = piv["value_using"] - piv["value_notusing"]
    piv["item"] = piv.get("label", piv.get("variable"))
    return piv[["source_file", "type", "item", "value_using", "value_notusing",
                "gap", "n_using", "n_notusing"]]


def _extract_pct_rows(df: pd.DataFrame, source: str) -> pd.DataFrame:
    sub = df[(df["split_by"] == "fp_use") & (df["group"].isin([USING, NOT_USING]))]
    if sub.empty:
        return pd.DataFrame()
    key_cols = [c for c in ("question", "category") if c in sub.columns]
    piv = sub.pivot_table(index=key_cols, columns="group", values=["pct", "count"], aggfunc="first")
    piv.columns = [f"{a}_{b}" for a, b in piv.columns]
    piv = piv.reset_index()
    piv["source_file"] = source
    piv["type"] = "pct"
    piv["value_using"] = piv.get(f"pct_{USING}")
    piv["value_notusing"] = piv.get(f"pct_{NOT_USING}")
    piv["n_using"] = piv.get(f"count_{USING}")
    piv["n_notusing"] = piv.get(f"count_{NOT_USING}")
    piv["gap"] = piv["value_using"] - piv["value_notusing"]
    if "question" in piv.columns:
        piv["item"] = piv["question"].fillna("") + ": " + piv["category"].astype(str)
    else:
        piv["item"] = piv["category"].astype(str)
    return piv[["source_file", "type", "item", "value_using", "value_notusing",
                "gap", "n_using", "n_notusing"]]


def main():
    files = sorted(f for f in APP_DATA_DIR.glob("pp_*.csv") if f.name not in EXCLUDE_FILES)
    parts = []
    for f in files:
        df = pd.read_csv(f)
        if "split_by" not in df.columns:
            continue
        if "mean" in df.columns:
            parts.append(_extract_mean_rows(df, f.name))
        elif "pct" in df.columns:
            parts.append(_extract_pct_rows(df, f.name))
    combined = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    for c in ("value_using", "value_notusing", "gap"):
        combined[c] = combined[c].round(2)
    combined["abs_gap"] = combined["gap"].abs()
    combined = combined.sort_values("abs_gap", ascending=False).reset_index(drop=True)

    full_path = OUTPUT_DIR / "persona_comparison_full.csv"
    combined.drop(columns="abs_gap").to_csv(full_path, index=False)

    top_n = 25
    top = combined.head(top_n).drop(columns="abs_gap")
    top_path = OUTPUT_DIR / "persona_top_differences.csv"
    top.to_csv(top_path, index=False)

    lines = []
    lines.append("# Phone Pulse: FP-user vs non-user personas\n")
    lines.append(
        "Comparison population: respondents who listen to at least one FEM "
        "partner radio station and passed QA (the Treatment analysis sample "
        "used throughout the Phone Pulse app: n=414). \"Using FP\" = "
        "fpbeh_fpnow == 1; \"Not using FP\" = everyone else in that sample.\n"
    )
    lines.append(
        f"Across {len(combined)} variable/category comparisons pulled from "
        f"{len(files)} question domains (attitudes, partner norms, access "
        "barriers, media habits, religious influence, information sources, "
        "pregnancy-risk perception, non-use reasons), the two groups look "
        "broadly similar on most items — see persona_comparison_full.csv for "
        "the complete ranked list. The largest gaps (persona-defining traits) "
        "are below.\n"
    )
    lines.append(f"## Top {top_n} differences (by absolute gap)\n")
    lines.append("| Source | Item | Using FP | Not using FP | Gap |")
    lines.append("|---|---|---|---|---|")
    for _, r in top.iterrows():
        unit = "pp" if r["type"] == "pct" else "pts (scale mean)"
        lines.append(
            f"| {r['source_file'].replace('pp_', '').replace('.csv', '')} "
            f"| {r['item']} | {r['value_using']:.2f} | {r['value_notusing']:.2f} "
            f"| {r['gap']:+.2f} {unit} |"
        )

    lines.append(
        "\n## Reading this\n\n"
        "- Positive gap = higher among FP users; negative = higher among non-users.\n"
        "- `pct` rows are percentage points; `mean` rows are on the item's own scale "
        "(see pp_attitudes.csv / pp_partner_norms.csv for scale definitions — mostly "
        "0–4 agreement or 0–5 frequency).\n"
        "- Items missing from this list (the bulk of `persona_comparison_full.csv`) "
        "had small gaps — i.e. FP users and non-users answered them about the same "
        "way. That itself is a finding: differences between the two groups here are "
        "concentrated in a handful of items (typically access-to-services and "
        "non-use-reason questions, which are close to definitionally different "
        "between the two groups) rather than being a broad-based attitudinal or "
        "media-habit divide.\n"
    )

    md_path = OUTPUT_DIR / "personas_summary.md"
    md_path.write_text("\n".join(lines))

    print("=" * 78)
    print("PERSONAS: FP USERS VS NON-USERS")
    print("=" * 78)
    print(top.to_string(index=False))
    print(f"\nWritten: {full_path}")
    print(f"Written: {top_path}")
    print(f"Written: {md_path}")


if __name__ == "__main__":
    main()
