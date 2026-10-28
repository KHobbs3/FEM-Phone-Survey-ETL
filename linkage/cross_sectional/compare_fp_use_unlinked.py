"""
Compare current FP USE between the full Formative Research baseline (968
respondents) and each round's full achieved Phone Pulse sample, as two
INDEPENDENT samples — see compare_knowledge_unlinked.py's docstring for the
general approach and ../compare_fp_use.py for the linked/paired version this
mirrors.

Output: outputs/fp_use_change_summary_unlinked.csv
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
    n_base, n_pulse = len(baseline), len(pulse)
    print(f"Formative baseline (full sample): {n_base}")
    print(f"Phone Pulse {round_id} (full achieved sample): {n_pulse}")

    using_baseline = baseline["current_use"].astype(str).str.strip().str.lower().str.startswith("ee")
    using_pulse = pd.to_numeric(pulse["fpbeh_fpnow"], errors="coerce").fillna(0).eq(1)

    x1, x2 = int(using_baseline.sum()), int(using_pulse.sum())
    p_value = two_proportion_ztest(x1, n_base, x2, n_pulse)

    summary = pd.DataFrame([{
        "question": "Currently using FP",
        "using_baseline_pct": round(100 * x1 / n_base, 1),
        "using_pulse_pct": round(100 * x2 / n_pulse, 1),
        "n_baseline": n_base, "n_pulse": n_pulse,
        "ztest_p_value": round(p_value, 4) if pd.notna(p_value) else None,
        "direction": (
            "increased" if x2 / n_pulse > x1 / n_base
            else "decreased" if x2 / n_pulse < x1 / n_base
            else "no change"
        ),
    }])
    print(summary.to_string(index=False))

    out_path = cfg.OUTPUT_DIR / "fp_use_change_summary_unlinked.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
