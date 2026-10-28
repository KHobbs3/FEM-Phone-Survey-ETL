"""
Compare current-method-mix (modern / traditional / none-or-other) between
the full Formative Research baseline and each round's full achieved Phone
Pulse sample, as two INDEPENDENT samples.

IMPORTANT REINTERPRETATION: "switching" (traditional -> modern for the SAME
person) is a paired-data concept — see ../compare_method_switching.py, which
answers that question for the 471 linked respondents. Two independent
samples can't show individual switching at all (there's no "before" and
"after" for any one person here). What this script CAN show, and does show,
is whether the overall modern/traditional/none-or-other MIX shifted between
the two samples — a population-level, not individual-level, comparison —
via a chi-square test of independence on the 2x3 (sample x category) table.

Each category also gets a 95% Wilson CI per sample and a two-proportion
z-test of its change (unweighted, as the other scripts in this folder).

Output: outputs/method_switching_summary_unlinked.csv (category mix + tests)
        outputs/method_switching_crosstab_unlinked.csv (the 2x3 table)
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

import config as cfg
from stats_utils import chi_square_p, two_proportion_ztest, wilson_ci

PULSE_CODE_TO_METHOD = {
    code: name
    for name, (_f_codes, pulse_codes) in cfg.METHOD_CROSSWALK.items()
    for code in pulse_codes
}


def _classify(methods: set[str]) -> str:
    if methods & cfg.MODERN_METHODS:
        return "Modern"
    if methods & cfg.TRADITIONAL_METHODS:
        return "Traditional"
    return "None/other"


def _baseline_methods(cell) -> set[str]:
    if pd.isna(cell):
        return set()
    out = set()
    for part in str(cell).split("|"):
        name = cfg.FORMATIVE_LABEL_TO_METHOD.get(part.strip())
        if name:
            out.add(name)
    return out


def _pulse_methods(row: pd.Series) -> set[str]:
    out = set()
    for code, name in PULSE_CODE_TO_METHOD.items():
        col = f"fpbeh_which_{code}"
        if col in row.index and pd.to_numeric(row[col], errors="coerce") == 1:
            out.add(name)
    return out


def main(round_id: str = cfg.DEFAULT_ROUND_ID) -> None:
    cfg.get_round(round_id)
    pulse_path = cfg.ROUND_PULSE_DATA.get(round_id)
    if pulse_path is None:
        sys.exit(f"Round '{round_id}' has no source data wired up yet — nothing to compare.")

    baseline = pd.read_csv(cfg.FORMATIVE_DATA, low_memory=False)
    pulse = pd.read_csv(pulse_path, low_memory=False)
    n_base, n_pulse = len(baseline), len(pulse)
    print(f"Formative baseline (full sample): {n_base}")
    print(f"Phone Pulse {round_id} (full achieved sample): {n_pulse}")

    baseline_cat = baseline["current_use_methods"].apply(lambda c: _classify(_baseline_methods(c)))
    pulse_cat = pulse.apply(lambda r: _classify(_pulse_methods(r)), axis=1)

    categories = ["Modern", "Traditional", "None/other"]
    base_counts = baseline_cat.value_counts().reindex(categories, fill_value=0)
    pulse_counts = pulse_cat.value_counts().reindex(categories, fill_value=0)

    crosstab = pd.DataFrame({"Baseline (full sample)": base_counts,
                              "Follow-up (full sample)": pulse_counts})
    p_value = chi_square_p(crosstab.T.values)

    # Per category: 95% Wilson CIs for each sample's share, and a two-proportion
    # z-test of the change (as the other cross-sectional scripts); the
    # chi-square tests the whole mix at once.
    rows = []
    for cat in categories:
        b_lo, b_hi = wilson_ci(int(base_counts[cat]), n_base)
        p_lo, p_hi = wilson_ci(int(pulse_counts[cat]), n_pulse)
        z_p = two_proportion_ztest(int(base_counts[cat]), n_base, int(pulse_counts[cat]), n_pulse)
        b_pct, p_pct = 100 * base_counts[cat] / n_base, 100 * pulse_counts[cat] / n_pulse
        rows.append({
            "category": cat,
            "baseline_pct": round(b_pct, 1),
            "baseline_ci_low": round(100 * b_lo, 1), "baseline_ci_high": round(100 * b_hi, 1),
            "pulse_pct": round(p_pct, 1),
            "pulse_ci_low": round(100 * p_lo, 1), "pulse_ci_high": round(100 * p_hi, 1),
            "n_baseline": n_base, "n_pulse": n_pulse,
            "ztest_p_value": round(z_p, 4) if pd.notna(z_p) else None,
            "direction": "increased" if p_pct > b_pct else "decreased" if p_pct < b_pct else "no change",
            "chi_square_p_value": round(p_value, 4) if pd.notna(p_value) else None,
        })
    summary = pd.DataFrame(rows)

    print("\nCurrent-method mix, baseline (full sample) vs. follow-up (full sample):")
    print(summary.to_string(index=False))
    print(f"\nOverall chi-square test of independence p-value: "
          f"{p_value:.4f}" if pd.notna(p_value) else "n/a")

    out_path = cfg.OUTPUT_DIR / "method_switching_summary_unlinked.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)

    crosstab_out = crosstab.reset_index().rename(columns={"index": "category"})
    crosstab_path = cfg.OUTPUT_DIR / "method_switching_crosstab_unlinked.csv"
    cfg.upsert_round_rows(crosstab_out, crosstab_path, round_id)

    print(f"\nWritten to: {out_path} (round={round_id})")
    print(f"Written to: {crosstab_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
