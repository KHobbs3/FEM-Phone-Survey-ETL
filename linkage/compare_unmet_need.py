"""
Compare unmet need for contraception between baseline and follow-up, for
linked respondents. Same "similar question" pattern as compare_fp_use.py —
see that file's docstring for the general approach.

The two waves don't ask the same question, so this uses the NARROWEST
definition that's actually computable on both sides — "wants no more
children AND isn't currently using any method" — rather than the fuller
baseline "unmet need" (wants to delay 1+ years OR wants no more children)
used on the Family Planning page (etl_family_planning.py's WANTS_TO_DELAY_CODES).
That fuller definition can't be reproduced at follow-up: Phone Pulse never
asked a "how soon do you want your next child" question, only "do you want
more children at all" (chldr_other_none_yet). Comparing the fuller baseline
figure against this narrower follow-up figure would UNDERSTATE the
follow-up number relative to baseline for reasons that have nothing to do
with the campaign — so this script computes the same restricted definition
on both sides instead.

Formative: `time_before_preferred_pregnancy` == 6 ("wants no more children")
    AND `current_use` != yes.
Phone Pulse: `chldr_other_none_yet` == 0 ("No more") AND `current_pregnant`
    == 0 (not pregnant) AND `fpbeh_fpnow` != 1.

Requires outputs/linked_respondents.csv — run link_respondents.py first
(after adding time_before_preferred_pregnancy / current_pregnant /
chldr_other_none_yet to config.py's *_ANALYSIS_COLUMNS, done 2026-09-04).
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
from scipy import stats

import config as cfg

# formative_time_before_preferred_pregnancy holds bilingual "Hausa / English"
# label text, NOT TIME_TO_PREGNANT's numeric codes (verified by inspecting
# the column's full distinct value set in fem_survey_niger_mapped.csv --
# schema-level text only, same check pipeline_output/pipeline/
# etl_family_planning.py's TIME_TO_PREGNANT_RAW_TO_CODE relies on; that file
# had the same numeric-isin() bug against this text column until 2026-09-04
# -- see its comment for the full raw-string mapping). Matching on the exact
# raw string, same convention as compare_fp_use.py's "ee"-prefix match.
WANTS_NO_MORE_RAW = "Ba ni da niyar samun wasu yara / I am not planning on having more children"


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

    required = [
        "formative_time_before_preferred_pregnancy", "formative_current_use",
        "pulse_chldr_other_none_yet", "pulse_current_pregnant", "pulse_fpbeh_fpnow",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        sys.exit(
            f"Missing expected column(s): {missing}. Add them to config.py's "
            "FORMATIVE_ANALYSIS_COLUMNS / PULSE_ANALYSIS_COLUMNS and re-run "
            "link_respondents.py."
        )

    # ── Baseline: wants no more children AND not currently using anything ──
    wants_no_more_baseline = (
        df["formative_time_before_preferred_pregnancy"].astype(str).str.strip()
        == WANTS_NO_MORE_RAW
    )
    using_baseline = (
        df["formative_current_use"].astype(str).str.strip().str.lower().str.startswith("ee")
    )
    unmet_baseline = wants_no_more_baseline & ~using_baseline

    # ── Follow-up: not pregnant, wants no more, not currently using anything ──
    not_pregnant_pulse = pd.to_numeric(df["pulse_current_pregnant"], errors="coerce").eq(0)
    wants_no_more_pulse = pd.to_numeric(df["pulse_chldr_other_none_yet"], errors="coerce").eq(0)
    using_pulse = pd.to_numeric(df["pulse_fpbeh_fpnow"], errors="coerce").fillna(0).eq(1)
    unmet_pulse = not_pregnant_pulse & wants_no_more_pulse & ~using_pulse

    both = int((unmet_baseline & unmet_pulse).sum())
    gained = int((~unmet_baseline & unmet_pulse).sum())   # met -> unmet
    lost = int((unmet_baseline & ~unmet_pulse).sum())     # unmet -> met
    neither = int((~unmet_baseline & ~unmet_pulse).sum())

    p_value = _mcnemar_exact_p(gained, lost)

    summary = pd.DataFrame([{
        "question": "Unmet need (wants no more children, not using any method)",
        "unmet_need_baseline_pct": round(100 * (both + lost) / n, 1) if n else None,
        "unmet_need_pulse_pct": round(100 * (both + gained) / n, 1) if n else None,
        "increased_unmet_n": gained,
        "decreased_unmet_n": lost,
        "mcnemar_p_value": round(p_value, 4) if pd.notna(p_value) else None,
        "direction": (
            "increased" if gained > lost
            else "decreased" if lost > gained
            else "no change"
        ),
        "n": n,
    }])

    out_path = cfg.OUTPUT_DIR / "unmet_need_change_summary.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)
    print(summary.to_string(index=False))
    print(f"\nWritten to: {out_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
