"""
Compare ATTITUDES toward family planning between the Formative Research
baseline and the Phone Pulse follow-up, for linked respondents only. Same
"linked pair" pattern as compare_knowledge.py.

Seven of Phone Pulse's 8 fpatt_* items (rated 0-4) repeat a baseline general
statement word for word; every baseline respondent was asked all of them
(Agree / Disagree). config.py's ATTITUDE_CROSSWALK lists the pairs;
fpatt_childinvest has no baseline match. The answer scales differ (the phone
scale has a neutral midpoint), so treat changes as directional.

For each of the 7 crosswalked items:
    - both sides binarized to "holds the view" = agrees with the statement
      (formative: Agree; pulse: score >= 3 of 0-4)
    - a 2x2 (holds-view-baseline x holds-view-pulse) table
    - McNemar's exact test on the discordant pairs

Requires outputs/linked_respondents.csv — run link_respondents.py first
(after config.py's FORMATIVE_ANALYSIS_COLUMNS / PULSE_ANALYSIS_COLUMNS
include the statement_*/fpatt_* columns ATTITUDE_CROSSWALK needs).

Output:
    outputs/attitudes_change_summary.csv — per-item stats (aggregate-only).
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
from scipy import stats

import config as cfg


def _mcnemar_exact_p(gained: int, lost: int) -> float:
    n_discordant = gained + lost
    if n_discordant == 0:
        return float("nan")
    return stats.binomtest(gained, n_discordant, p=0.5, alternative="two-sided").pvalue


def main(round_id: str = cfg.DEFAULT_ROUND_ID) -> None:
    cfg.get_round(round_id)
    if not cfg.LINKED_RESPONDENTS_CSV.exists():
        sys.exit(f"{cfg.LINKED_RESPONDENTS_CSV} not found. Run link_respondents.py first.")

    df = pd.read_csv(cfg.LINKED_RESPONDENTS_CSV)
    n = len(df)
    print(f"Linked respondents: {n}")
    if n == 0:
        sys.exit("No linked respondents — nothing to compare.")

    rows = []
    for item, (f_col_short, p_col_short, agree_is_view) in cfg.ATTITUDE_CROSSWALK.items():
        f_col, p_col = f"formative_{f_col_short}", f"pulse_{p_col_short}"
        if f_col not in df.columns or p_col not in df.columns:
            print(f"  ! skipping '{item}' — missing column {f_col} or {p_col}")
            continue

        formative_agree = df[f_col].astype(str).str.strip() == cfg.STATEMENT_AGREE_TEXT
        holds_view_baseline = formative_agree if agree_is_view else ~formative_agree
        # Only formative Agree/Disagree responses are usable (drop I-don't-
        # know / prefer-not-to-say / unasked — NaN there, not "no").
        formative_answered = df[f_col].astype(str).str.strip().isin(
            [cfg.STATEMENT_AGREE_TEXT, cfg.STATEMENT_DISAGREE_TEXT]
        )

        pulse_score = pd.to_numeric(df[p_col], errors="coerce")
        holds_view_pulse = pulse_score >= 3
        pulse_answered = pulse_score.notna()

        usable = formative_answered & pulse_answered
        n_item = int(usable.sum())
        if n_item == 0:
            print(f"  ! skipping '{item}' — no respondents answered both sides")
            continue

        base = holds_view_baseline[usable]
        pulse = holds_view_pulse[usable]

        both = int((base & pulse).sum())
        gained = int((~base & pulse).sum())
        lost = int((base & ~pulse).sum())

        p_value = _mcnemar_exact_p(gained, lost)

        rows.append({
            "item": item,
            "formative_statement": f_col_short,
            "pulse_item": p_col_short,
            "n": n_item,
            "holds_view_baseline_pct": round(100 * (both + lost) / n_item, 1),
            "holds_view_pulse_pct": round(100 * (both + gained) / n_item, 1),
            "gained_n": gained,
            "lost_n": lost,
            "mcnemar_p_value": round(p_value, 4) if pd.notna(p_value) else None,
            "direction": (
                "increased" if gained > lost
                else "decreased" if lost > gained
                else "no change"
            ),
        })

    summary = pd.DataFrame(rows)
    print("\nAttitude items — % holding the view, baseline -> follow-up:")
    print(summary.to_string(index=False) if not summary.empty else "  (none)")

    out_path = cfg.OUTPUT_DIR / "attitudes_change_summary.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
