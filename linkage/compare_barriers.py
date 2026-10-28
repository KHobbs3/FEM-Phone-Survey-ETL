"""
Compare REASONS FOR NON-USE (barriers to FP) between the Formative Research
baseline and the Phone Pulse follow-up, for linked respondents only. Same
"linked pair" pattern as compare_knowledge.py.

Both surveys use the same 59-reason list (config.WHYNOT_LABELS), so reasons
are matched option by option:
Formative: `reason_nonuse_mc` — pipe-separated bilingual label text, asked of
    those who never used or didn't use in the last six months.
Phone Pulse: `fpbeh_whynot_1..59` — one 0/1 column per reason, asked of
    current non-users.
Both unprompted. Baseline tokens that match no reason (don't know / prefer not
to say / other) are ignored; the script prints any it finds so wording
mismatches can be spotted.

Only respondents asked the question at BOTH waves are in scope — a much
smaller, non-random subset of the 471 linked respondents. The non-use window
also differs (six months at baseline, now at follow-up).

For each reason group (cited = any reason in the group) and each reason:
    - both sides binarized to "cited this reason"
    - a 2x2 table + McNemar's exact test on the discordant pairs

Requires outputs/linked_respondents.csv — run link_respondents.py first.

Output:
    outputs/barriers_change_summary.csv — per-category stats (aggregate-only).
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

    f_col = "formative_reason_nonuse_mc"
    pulse_cols = [f"pulse_{c}" for c in cfg.PULSE_WHYNOT_COLUMNS]
    missing = [c for c in [f_col] + pulse_cols if c not in df.columns]
    if missing:
        sys.exit(f"Missing expected column(s): {missing}. Check config.py "
                  "FORMATIVE_ANALYSIS_COLUMNS / PULSE_ANALYSIS_COLUMNS.")

    # In scope: was asked at baseline (non-users only; NaN for users) AND has
    # at least one non-null fpbeh_whynot_N on the pulse side.
    asked_baseline = df[f_col].notna()
    pulse_cited = df[pulse_cols].apply(pd.to_numeric, errors="coerce")
    asked_pulse = pulse_cited.notna().any(axis=1)
    in_scope = asked_baseline & asked_pulse
    n_scope = int(in_scope.sum())
    print(f"Respondents asked 'why not using FP' on BOTH waves: {n_scope} "
          f"(of {n} linked)")

    parsed = df.loc[in_scope, f_col].apply(cfg.formative_whynot_codes)
    baseline_codes = parsed.str[0]
    unmatched = pd.Series([t for _, toks in parsed for t in toks], dtype=str).value_counts()
    if not unmatched.empty:
        print("\nBaseline answers matching no reason (expect only don't know / "
              "prefer not to say / other):")
        print(unmatched.to_string())
    pulse_cited = pulse_cited[in_scope].fillna(0).eq(1)

    rows = []
    for level, label, codes in cfg.whynot_items():
        cited_baseline = baseline_codes.apply(lambda cs, codes=codes: bool(cs & codes))
        cited_pulse = pulse_cited[[f"pulse_fpbeh_whynot_{c}" for c in codes]].any(axis=1)

        both = int((cited_baseline & cited_pulse).sum())
        gained = int((~cited_baseline & cited_pulse).sum())
        lost = int((cited_baseline & ~cited_pulse).sum())

        p_value = _mcnemar_exact_p(gained, lost)

        rows.append({
            "level": level,
            "reason_group": label if level == "group" else cfg.WHYNOT_GROUPS[min(codes)],
            "category": label,
            "n": n_scope,
            "cited_baseline_pct": round(100 * (both + lost) / n_scope, 1) if n_scope else None,
            "cited_pulse_pct": round(100 * (both + gained) / n_scope, 1) if n_scope else None,
            "gained_n": gained,
            "lost_n": lost,
            "mcnemar_p_value": round(p_value, 4) if pd.notna(p_value) else None,
            "direction": (
                "increased" if gained > lost
                else "decreased" if lost > gained
                else "no change"
            ),
        })

    summary = pd.DataFrame(rows).sort_values(["level", "cited_baseline_pct"], ascending=[True, False])
    print("\nReason groups and reasons — % citing, baseline -> follow-up (among "
          "respondents not using FP on both waves):")
    print(summary.to_string(index=False))

    out_path = cfg.OUTPUT_DIR / "barriers_change_summary.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
