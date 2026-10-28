"""
Compare current FP USE (not just knowledge) between baseline and follow-up,
for linked respondents. Demonstrates the general pattern for comparing any
"similar question" pair across the two waves — copy this for other
comparisons (e.g. attitudes, radio listenership).

Formative: `current_use` — select_one yesno ("Are you currently using a
    family planning method?")
Phone Pulse: `fpbeh_fpnow` — binary 0/1, same question intent.

Both are believed to code 1 = Yes on the survey side, but this has not been
verified against real values (only against the SurveyCTO form/pipeline
schema — see README.md). Spot-check outputs/fp_use_change_summary.csv
against a handful of known cases before treating results as final.

Requires outputs/linked_respondents.csv — run link_respondents.py first.
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

    f_col, p_col = "formative_current_use", "pulse_fpbeh_fpnow"
    missing = [c for c in (f_col, p_col) if c not in df.columns]
    if missing:
        sys.exit(f"Missing expected column(s): {missing}. Check config.py "
                  "FORMATIVE_ANALYSIS_COLUMNS / PULSE_ANALYSIS_COLUMNS.")

    # formative_current_use holds bilingual label text in the mapped data
    # (e.g. "Ee / Oui" = yes, "A'a / Non" = no) — not numeric codes. Verified
    # by inspecting outputs/linked_respondents.csv's value_counts (schema-
    # level text only). Match on the leading token before " / ", which is
    # the Hausa "yes" spelling regardless of the paired French/English text.
    using_baseline = df[f_col].astype(str).str.strip().str.lower().str.startswith("ee")
    using_pulse = pd.to_numeric(df[p_col], errors="coerce").fillna(0).eq(1)

    both = int((using_baseline & using_pulse).sum())
    gained = int((~using_baseline & using_pulse).sum())   # not using -> using
    lost = int((using_baseline & ~using_pulse).sum())     # using -> not using
    neither = int((~using_baseline & ~using_pulse).sum())

    p_value = _mcnemar_exact_p(gained, lost)

    summary = pd.DataFrame([{
        "question": "Currently using FP",
        "using_baseline_pct": round(100 * (both + lost) / n, 1) if n else None,
        "using_pulse_pct": round(100 * (both + gained) / n, 1) if n else None,
        "started_using_n": gained,
        "stopped_using_n": lost,
        "mcnemar_p_value": round(p_value, 4) if pd.notna(p_value) else None,
        "direction": (
            "increased" if gained > lost
            else "decreased" if lost > gained
            else "no change"
        ),
    }])

    out_path = cfg.OUTPUT_DIR / "fp_use_change_summary.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)
    print(summary.to_string(index=False))
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
