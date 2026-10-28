"""
Compare contraceptive-method KNOWLEDGE between the Formative Research
baseline and the Phone Pulse follow-up, for linked respondents only.

Answers: "has contraceptive knowledge increased?"

Requires outputs/linked_respondents.csv to already exist — run
link_respondents.py first.

The two surveys use different numeric codes for the same method, so this
script never compares raw codes directly; it goes through config.py's
METHOD_CROSSWALK (name-based) to build a common set of comparable methods.

For each comparable method:
    - a 2x2 (known-at-baseline x known-at-pulse) table
    - McNemar's exact test on the discordant pairs (gained vs lost),
      i.e. is the change in a consistent direction more often than chance

Overall:
    - mean/median number of comparable methods known, baseline vs pulse
    - Wilcoxon signed-rank test on the per-respondent change

Output:
    outputs/knowledge_change_summary.csv — per-method + overall stats
      (group-level counts and test statistics only — no respondent-level
      data is written or printed).
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd
from scipy import stats

import config as cfg


def _mcnemar_exact_p(gained: int, lost: int) -> float:
    """
    Exact McNemar test p-value: two-sided binomial test on the discordant
    pairs (gained vs lost) against the null of p=0.5 (change is equally
    likely in either direction).
    """
    n_discordant = gained + lost
    if n_discordant == 0:
        return float("nan")
    return stats.binomtest(gained, n_discordant, p=0.5, alternative="two-sided").pvalue


def _parse_known_methods(raw: str) -> set[str]:
    """
    Parse known_contraceptive_options: pipe-separated bilingual (Hausa /
    English) label text (e.g. 'Allurai / Injectables|Karan damtse /
    Implants'), NOT numeric codes — see config.py's FORMATIVE_LABEL_TO_METHOD
    note. Returns the set of canonical method names (METHOD_CROSSWALK keys)
    the respondent knows; unmapped labels (Abstinence, I don't know, Prefer
    not to say, Other) are dropped.
    """
    if pd.isna(raw) or str(raw).strip() == "":
        return set()
    methods = set()
    for tok in str(raw).split("|"):
        method = cfg.FORMATIVE_LABEL_TO_METHOD.get(tok.strip())
        if method:
            methods.add(method)
    return methods


def main(round_id: str = cfg.DEFAULT_ROUND_ID) -> None:
    cfg.get_round(round_id)  # raises if unknown
    if not cfg.LINKED_RESPONDENTS_CSV.exists():
        sys.exit(
            f"{cfg.LINKED_RESPONDENTS_CSV} not found. Run link_respondents.py "
            "first (it requires a working formative <-> pulse crosswalk — "
            "see config.py's CROSSWALK_FILE note)."
        )

    df = pd.read_csv(cfg.LINKED_RESPONDENTS_CSV)
    n = len(df)
    print(f"Linked respondents: {n}")
    if n == 0:
        sys.exit("No linked respondents — nothing to compare.")

    known_col = "formative_known_contraceptive_options"
    if known_col not in df.columns:
        sys.exit(
            f"Expected column '{known_col}' not found in linked_respondents.csv. "
            "Check config.py FORMATIVE_ANALYSIS_COLUMNS / the formative source "
            "file's real column name (see link_respondents.py --inspect)."
        )

    baseline_methods = df[known_col].apply(_parse_known_methods)

    rows = []
    baseline_count = pd.Series(0, index=df.index)
    pulse_count = pd.Series(0, index=df.index)

    for method, (formative_codes, pulse_cols) in cfg.METHOD_CROSSWALK.items():
        # Column names in the linked file are prefixed with "pulse_".
        pulse_col_names = [f"pulse_{cfg.PULSE_METHOD_COLUMNS[c]}" for c in pulse_cols]
        pulse_col_names = [c for c in pulse_col_names if c in df.columns]
        if not pulse_col_names:
            print(f"  ! skipping '{method}' — no pulse column present "
                  f"(expected one of {[cfg.PULSE_METHOD_COLUMNS[c] for c in pulse_cols]})")
            continue

        known_baseline = baseline_methods.apply(lambda methods, m=method: m in methods)
        known_pulse = (
            df[pulse_col_names].apply(pd.to_numeric, errors="coerce").fillna(0).eq(1).any(axis=1)
        )

        baseline_count = baseline_count + known_baseline.astype(int)
        pulse_count = pulse_count + known_pulse.astype(int)

        both = int((known_baseline & known_pulse).sum())
        gained = int((~known_baseline & known_pulse).sum())   # unknown -> known
        lost = int((known_baseline & ~known_pulse).sum())     # known -> unknown
        neither = int((~known_baseline & ~known_pulse).sum())

        p_value = _mcnemar_exact_p(gained, lost)

        rows.append({
            "method": method,
            "known_baseline_pct": round(100 * (both + lost) / n, 1),
            "known_pulse_pct": round(100 * (both + gained) / n, 1),
            "gained_awareness_n": gained,
            "lost_awareness_n": lost,
            "mcnemar_p_value": round(p_value, 4) if pd.notna(p_value) else None,
            "direction": (
                "increased" if gained > lost
                else "decreased" if lost > gained
                else "no change"
            ),
        })

    summary = pd.DataFrame(rows).sort_values("mcnemar_p_value", na_position="last")

    print("\nPer-method awareness change (baseline -> follow-up):")
    print(summary.to_string(index=False))

    # ── Overall: total comparable methods known per respondent ──────────────
    diff = pulse_count - baseline_count
    mean_base, mean_pulse = baseline_count.mean(), pulse_count.mean()
    try:
        wilcoxon_stat, wilcoxon_p = stats.wilcoxon(baseline_count, pulse_count)
    except ValueError:
        wilcoxon_stat, wilcoxon_p = float("nan"), float("nan")

    print("\n" + "=" * 60)
    print("OVERALL CONTRACEPTIVE KNOWLEDGE (comparable methods only)")
    print("=" * 60)
    print(f"  Mean methods known — baseline : {mean_base:.2f} / {len(cfg.METHOD_CROSSWALK)}")
    print(f"  Mean methods known — follow-up: {mean_pulse:.2f} / {len(cfg.METHOD_CROSSWALK)}")
    print(f"  Respondents who gained >= 1 method : "
          f"{int((diff > 0).sum())} ({100*(diff > 0).mean():.1f}%)")
    print(f"  Respondents who lost >= 1 method    : "
          f"{int((diff < 0).sum())} ({100*(diff < 0).mean():.1f}%)")
    print(f"  Respondents unchanged                : "
          f"{int((diff == 0).sum())} ({100*(diff == 0).mean():.1f}%)")
    print(f"  Wilcoxon signed-rank p-value          : {wilcoxon_p:.4f}"
          if pd.notna(wilcoxon_p) else "  Wilcoxon signed-rank p-value: n/a")

    if pd.notna(wilcoxon_p) and wilcoxon_p < 0.05:
        direction = "increased" if mean_pulse > mean_base else "decreased"
        print(f"\n  VERDICT: Contraceptive knowledge {direction} significantly "
              f"(p={wilcoxon_p:.4f}).")
    else:
        print("\n  VERDICT: No statistically significant change detected "
              "(or too few linked respondents to tell).")

    overall_row = pd.DataFrame([{
        "method": "__OVERALL__",
        "known_baseline_pct": round(100 * mean_base / len(cfg.METHOD_CROSSWALK), 1),
        "known_pulse_pct": round(100 * mean_pulse / len(cfg.METHOD_CROSSWALK), 1),
        "gained_awareness_n": int((diff > 0).sum()),
        "lost_awareness_n": int((diff < 0).sum()),
        "mcnemar_p_value": np.nan,
        "direction": f"wilcoxon_p={wilcoxon_p:.4f}" if pd.notna(wilcoxon_p) else "n/a",
    }])
    full = pd.concat([summary, overall_row], ignore_index=True)
    out_path = cfg.OUTPUT_DIR / "knowledge_change_summary.csv"
    cfg.upsert_round_rows(full, out_path, round_id)
    print(f"\nFull summary (round={round_id}) written to: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID,
                         help=f"Round id to tag this run's output with. One of "
                              f"{[r['round_id'] for r in cfg.ROUNDS]}.")
    args = parser.parse_args()
    main(args.round_id)
