"""
Compare REASONS FOR NON-USE (barriers) between the full Formative Research
baseline and each round's full achieved Phone Pulse sample, as two
INDEPENDENT samples. Same option-by-option matching of the shared 59-reason
list as ../compare_barriers.py — see that file's docstring.

Unlike ../compare_barriers.py (which restricts to the ~68 linked
respondents who answered the "why not" question on BOTH waves), this script
uses EACH survey's own full set of respondents who were asked the question
(i.e. reported not currently using FP) — a much larger, and differently
composed, denominator on each side. That's the correct population for an
independent-samples design, but it does mean the two %'s below are not
restricted to comparable individuals the way the linked comparison is.

Output: outputs/barriers_change_summary_unlinked.csv
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

    asked_baseline = baseline["reason_nonuse_mc"].notna()
    n_base = int(asked_baseline.sum())
    parsed = baseline.loc[asked_baseline, "reason_nonuse_mc"].apply(cfg.formative_whynot_codes)
    base_codes = parsed.str[0]

    pulse_cited = pulse[cfg.PULSE_WHYNOT_COLUMNS].apply(pd.to_numeric, errors="coerce")
    asked_pulse = pulse_cited.notna().any(axis=1)
    n_pulse = int(asked_pulse.sum())
    pulse_cited = pulse_cited[asked_pulse].fillna(0).eq(1)

    print(f"Formative baseline: {len(baseline)} total, {n_base} asked 'why not using FP'")
    print(f"Phone Pulse {round_id}: {len(pulse)} total, {n_pulse} asked 'why not using FP'")
    unmatched = pd.Series([t for _, toks in parsed for t in toks], dtype=str).value_counts()
    if not unmatched.empty:
        print("\nBaseline answers matching no reason (expect only don't know / "
              "prefer not to say / other):")
        print(unmatched.to_string())

    rows = []
    for level, label, codes in cfg.whynot_items():
        cited_baseline = base_codes.apply(lambda cs, codes=codes: bool(cs & codes))
        cited_pulse = pulse_cited[[f"fpbeh_whynot_{c}" for c in codes]].any(axis=1)

        x1, x2 = int(cited_baseline.sum()), int(cited_pulse.sum())
        p_value = two_proportion_ztest(x1, n_base, x2, n_pulse)

        rows.append({
            "level": level,
            "reason_group": label if level == "group" else cfg.WHYNOT_GROUPS[min(codes)],
            "category": label,
            "n_baseline": n_base, "n_pulse": n_pulse,
            "cited_baseline_pct": round(100 * x1 / n_base, 1) if n_base else None,
            "cited_pulse_pct": round(100 * x2 / n_pulse, 1) if n_pulse else None,
            "ztest_p_value": round(p_value, 4) if pd.notna(p_value) else None,
            "direction": (
                "increased" if n_base and n_pulse and x2 / n_pulse > x1 / n_base
                else "decreased" if n_base and n_pulse and x2 / n_pulse < x1 / n_base
                else "no change"
            ),
        })

    summary = pd.DataFrame(rows).sort_values(["level", "cited_baseline_pct"], ascending=[True, False])
    print("\nReason groups and reasons — % citing, baseline (full sample) vs. "
          "follow-up (full sample):")
    print(summary.to_string(index=False))

    out_path = cfg.OUTPUT_DIR / "barriers_change_summary_unlinked.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
