"""
Compare contraceptive-method KNOWLEDGE between the full Formative Research
baseline (968 respondents) and each round's full achieved Phone Pulse
sample (509 for round 1), as TWO INDEPENDENT SAMPLES — NOT the same people
(compare that to ../compare_knowledge.py, which pairs the same 471 linked
respondents). Uses a two-proportion z-test per method (not McNemar, which
requires paired data) and a Mann-Whitney U test on methods-known-per-
respondent (not Wilcoxon).

Same METHOD_CROSSWALK / FORMATIVE_LABEL_TO_METHOD logic as the linked
pipeline (see config.py here, re-exported from ../config.py) — this script
only changes WHICH respondents are compared and HOW (independent vs.
paired), not the method-name crosswalk itself.

Output:
    outputs/knowledge_change_summary_unlinked.csv — per-method + overall
    stats (aggregate-only, one 'round' per Phone Pulse round compared).
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

import config as cfg
from stats_utils import two_proportion_ztest, mann_whitney_p


def _parse_known_methods(raw) -> set[str]:
    if pd.isna(raw) or str(raw).strip() == "":
        return set()
    out = set()
    for tok in str(raw).split("|"):
        method = cfg.FORMATIVE_LABEL_TO_METHOD.get(tok.strip())
        if method:
            out.add(method)
    return out


def main(round_id: str = cfg.DEFAULT_ROUND_ID) -> None:
    cfg.get_round(round_id)
    pulse_path = cfg.ROUND_PULSE_DATA.get(round_id)
    if pulse_path is None:
        sys.exit(f"Round '{round_id}' has no source data wired up yet "
                  "(config.py ROUND_PULSE_DATA) — nothing to compare.")
    if not cfg.FORMATIVE_DATA.exists() or not pulse_path.exists():
        sys.exit(f"Missing source file(s): {cfg.FORMATIVE_DATA} / {pulse_path}")

    baseline = pd.read_csv(cfg.FORMATIVE_DATA, low_memory=False)
    pulse = pd.read_csv(pulse_path, low_memory=False)
    n_base, n_pulse = len(baseline), len(pulse)
    print(f"Formative baseline (full sample): {n_base}")
    print(f"Phone Pulse {round_id} (full achieved sample): {n_pulse}")

    baseline_methods = baseline["known_contraceptive_options"].apply(_parse_known_methods)

    rows = []
    base_count = pd.Series(0, index=baseline.index)
    pulse_count = pd.Series(0, index=pulse.index)

    for method, (_f_codes, pulse_codes) in cfg.METHOD_CROSSWALK.items():
        pulse_col_names = [cfg.PULSE_METHOD_COLUMNS[c] for c in pulse_codes]
        pulse_col_names = [c for c in pulse_col_names if c in pulse.columns]
        if not pulse_col_names:
            print(f"  ! skipping '{method}' — no pulse column present")
            continue

        known_baseline = baseline_methods.apply(lambda methods, m=method: m in methods)
        known_pulse = (
            pulse[pulse_col_names].apply(pd.to_numeric, errors="coerce").fillna(0).eq(1).any(axis=1)
        )

        base_count = base_count + known_baseline.astype(int)
        pulse_count = pulse_count + known_pulse.astype(int)

        x1, x2 = int(known_baseline.sum()), int(known_pulse.sum())
        p_value = two_proportion_ztest(x1, n_base, x2, n_pulse)

        rows.append({
            "method": method,
            "known_baseline_pct": round(100 * x1 / n_base, 1),
            "known_pulse_pct": round(100 * x2 / n_pulse, 1),
            "n_baseline": n_base, "n_pulse": n_pulse,
            "ztest_p_value": round(p_value, 4) if pd.notna(p_value) else None,
            "direction": (
                "increased" if x2 / n_pulse > x1 / n_base
                else "decreased" if x2 / n_pulse < x1 / n_base
                else "no change"
            ),
        })

    summary = pd.DataFrame(rows).sort_values("ztest_p_value", na_position="last")
    print("\nPer-method awareness, baseline (full sample) vs. follow-up (full sample):")
    print(summary.to_string(index=False))

    mw_p = mann_whitney_p(base_count, pulse_count)
    mean_base, mean_pulse = base_count.mean(), pulse_count.mean()
    print("\n" + "=" * 60)
    print("OVERALL CONTRACEPTIVE KNOWLEDGE (comparable methods only)")
    print("=" * 60)
    print(f"  Mean methods known — baseline : {mean_base:.2f} / {len(cfg.METHOD_CROSSWALK)}")
    print(f"  Mean methods known — follow-up: {mean_pulse:.2f} / {len(cfg.METHOD_CROSSWALK)}")
    print(f"  Mann-Whitney U p-value        : {mw_p:.4f}" if pd.notna(mw_p) else "  Mann-Whitney U p-value: n/a")

    overall_row = pd.DataFrame([{
        "method": "__OVERALL__",
        "known_baseline_pct": round(100 * mean_base / len(cfg.METHOD_CROSSWALK), 1),
        "known_pulse_pct": round(100 * mean_pulse / len(cfg.METHOD_CROSSWALK), 1),
        "n_baseline": n_base, "n_pulse": n_pulse,
        "ztest_p_value": None,
        "direction": f"mannwhitney_p={mw_p:.4f}" if pd.notna(mw_p) else "n/a",
    }])
    full = pd.concat([summary, overall_row], ignore_index=True)

    out_path = cfg.OUTPUT_DIR / "knowledge_change_summary_unlinked.csv"
    cfg.upsert_round_rows(full, out_path, round_id)
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
