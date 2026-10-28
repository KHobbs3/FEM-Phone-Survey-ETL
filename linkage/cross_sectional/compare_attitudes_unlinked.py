"""
Compare ATTITUDES toward FP between the full Formative Research baseline and
each round's full achieved Phone Pulse sample, as two INDEPENDENT samples.
Same ATTITUDE_CROSSWALK (seven word-for-word statement pairs) and caveats as
../compare_attitudes.py — see that file's docstring. Two-proportion z-test per item instead of McNemar.

Output: outputs/attitudes_change_summary_unlinked.csv
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

import config as cfg
from stats_utils import two_proportion_ztest


def main(round_id: str = cfg.DEFAULT_ROUND_ID) -> None:
    cfg.get_round(round_id)
    pulse_path = cfg.ROUND_PULSE_DATA.get(round_id)
    if pulse_path is None:
        sys.exit(f"Round '{round_id}' has no source data wired up yet — nothing to compare.")

    baseline = pd.read_csv(cfg.FORMATIVE_DATA, low_memory=False)
    pulse = pd.read_csv(pulse_path, low_memory=False)
    print(f"Formative baseline (full sample): {len(baseline)}")
    print(f"Phone Pulse {round_id} (full achieved sample): {len(pulse)}")

    rows = []
    for item, (f_col, p_col, agree_is_view) in cfg.ATTITUDE_CROSSWALK.items():
        if f_col not in baseline.columns or p_col not in pulse.columns:
            print(f"  ! skipping '{item}' — missing column {f_col} or {p_col}")
            continue

        formative_agree = baseline[f_col].astype(str).str.strip() == cfg.STATEMENT_AGREE_TEXT
        formative_answered = baseline[f_col].astype(str).str.strip().isin(
            [cfg.STATEMENT_AGREE_TEXT, cfg.STATEMENT_DISAGREE_TEXT]
        )
        holds_view_baseline = (formative_agree if agree_is_view else ~formative_agree)[formative_answered]
        n_base = int(formative_answered.sum())

        pulse_score = pd.to_numeric(pulse[p_col], errors="coerce")
        pulse_answered = pulse_score.notna()
        holds_view_pulse = (pulse_score >= 3)[pulse_answered]
        n_pulse = int(pulse_answered.sum())

        x1, x2 = int(holds_view_baseline.sum()), int(holds_view_pulse.sum())
        p_value = two_proportion_ztest(x1, n_base, x2, n_pulse)

        rows.append({
            "item": item,
            "formative_statement": f_col, "pulse_item": p_col,
            "n_baseline": n_base, "n_pulse": n_pulse,
            "holds_view_baseline_pct": round(100 * x1 / n_base, 1) if n_base else None,
            "holds_view_pulse_pct": round(100 * x2 / n_pulse, 1) if n_pulse else None,
            "ztest_p_value": round(p_value, 4) if pd.notna(p_value) else None,
            "direction": (
                "increased" if n_base and n_pulse and x2 / n_pulse > x1 / n_base
                else "decreased" if n_base and n_pulse and x2 / n_pulse < x1 / n_base
                else "no change"
            ),
        })

    summary = pd.DataFrame(rows)
    print("\nAttitude items — % holding the view, baseline (full sample) vs. "
          "follow-up (full sample):")
    print(summary.to_string(index=False) if not summary.empty else "  (none)")

    out_path = cfg.OUTPUT_DIR / "attitudes_change_summary_unlinked.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
