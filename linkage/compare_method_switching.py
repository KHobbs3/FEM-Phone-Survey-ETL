"""
Method switching: traditional -> modern/effective, baseline vs. follow-up,
for linked respondents. Same "linked pair" pattern as compare_fp_use.py.

Formative: `current_use_methods` — pipe-separated bilingual label text,
    e.g. "Janyewa / Withdrawal|Allurai / Injectables" (same vocabulary as
    known_contraceptive_options). Mapped to canonical method names via
    config.py's FORMATIVE_LABEL_TO_METHOD.
Phone Pulse: `fpbeh_which_1..17` — binary indicator per method code. Mapped
    to canonical method names via config.py's METHOD_CROSSWALK (inverted on
    the pulse-code side).

A respondent's baseline/follow-up method-use is classified into one of:
    "Modern"      — at least one MODERN_METHODS method selected
    "Traditional" — no modern method, but at least one TRADITIONAL_METHODS
                    method selected (withdrawal / calendar-rhythm)
    "None/other"  — no method selected, or only an unmappable one
                    (formative "Abstinence", pulse "Other traditional" —
                    no cross-survey equivalent, see METHOD_CROSSWALK)

Two headline metrics (only the two well-defined populations for a
"switched FROM traditional" question — you can't switch from a method you
weren't using):
  1. % of baseline TRADITIONAL-method users who are on a MODERN method at
     follow-up ("of the people who could make this switch, how many did").
  2. % of ALL linked WOMEN (any baseline status) who made that same
     switch ("population-level scale of the switch among women").
A same-population "% of all linked respondents (both genders)" row is
included too, for context.

Requires outputs/linked_respondents.csv — run link_respondents.py first
(after confirming config.py's FORMATIVE_ANALYSIS_COLUMNS/PULSE_ANALYSIS_COLUMNS
include current_use_methods / fpbeh_which_1..17).
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

import config as cfg

GENDER_FEMALE = "Mace / Femme"

# Invert METHOD_CROSSWALK's pulse-code lists into pulse_code -> canonical name.
PULSE_CODE_TO_METHOD = {
    code: name
    for name, (_formative_codes, pulse_codes) in cfg.METHOD_CROSSWALK.items()
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
        col = f"pulse_fpbeh_which_{code}"
        if col in row.index and pd.to_numeric(row[col], errors="coerce") == 1:
            out.add(name)
    return out


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 1) if denominator else None


def main(round_id: str = cfg.DEFAULT_ROUND_ID) -> None:
    cfg.get_round(round_id)
    if not cfg.LINKED_RESPONDENTS_CSV.exists():
        sys.exit(f"{cfg.LINKED_RESPONDENTS_CSV} not found. Run link_respondents.py first.")

    df = pd.read_csv(cfg.LINKED_RESPONDENTS_CSV)
    n = len(df)
    print(f"Linked respondents: {n}")

    required = ["formative_current_use_methods", "formative_gender"] + \
        [f"pulse_fpbeh_which_{i}" for i in range(1, 18)]
    missing = [c for c in required if c not in df.columns]
    if missing:
        sys.exit(
            f"Missing expected column(s): {missing}. Add "
            "'current_use_methods' to config.py's FORMATIVE_ANALYSIS_COLUMNS "
            "and 'fpbeh_which_1'..'fpbeh_which_17' to PULSE_ANALYSIS_COLUMNS, "
            "then re-run link_respondents.py."
        )

    df["_baseline_category"] = df["formative_current_use_methods"].apply(
        lambda c: _classify(_baseline_methods(c))
    )
    df["_followup_category"] = df.apply(lambda r: _classify(_pulse_methods(r)), axis=1)
    df["_switched_trad_to_modern"] = (
        (df["_baseline_category"] == "Traditional") & (df["_followup_category"] == "Modern")
    )

    is_female = df["formative_gender"] == GENDER_FEMALE

    n_baseline_traditional = int((df["_baseline_category"] == "Traditional").sum())
    n_switched_of_traditional = int(
        (df["_switched_trad_to_modern"] & (df["_baseline_category"] == "Traditional")).sum()
    )
    n_women = int(is_female.sum())
    n_switched_women = int((df["_switched_trad_to_modern"] & is_female).sum())
    n_switched_all = int(df["_switched_trad_to_modern"].sum())

    summary = pd.DataFrame([
        {
            "metric": "% of baseline traditional-method users now on a modern method",
            "numerator_n": n_switched_of_traditional,
            "denominator_n": n_baseline_traditional,
            "pct": _pct(n_switched_of_traditional, n_baseline_traditional),
            "denominator_description": "Linked respondents using a traditional "
                                        "method (withdrawal/calendar-rhythm) at baseline",
        },
        {
            "metric": "% of all linked women who switched traditional -> modern",
            "numerator_n": n_switched_women,
            "denominator_n": n_women,
            "pct": _pct(n_switched_women, n_women),
            "denominator_description": "All linked female respondents, regardless "
                                        "of baseline method-use status",
        },
        {
            "metric": "% of all linked respondents (both genders) who switched "
                      "traditional -> modern",
            "numerator_n": n_switched_all,
            "denominator_n": n,
            "pct": _pct(n_switched_all, n),
            "denominator_description": "All linked respondents, regardless of "
                                        "gender or baseline method-use status",
        },
    ])

    # Context: full baseline x follow-up category crosstab (counts only).
    crosstab = pd.crosstab(df["_baseline_category"], df["_followup_category"]).reset_index()
    crosstab_path = cfg.OUTPUT_DIR / "method_switching_crosstab.csv"
    cfg.upsert_round_rows(crosstab, crosstab_path, round_id)

    out_path = cfg.OUTPUT_DIR / "method_switching_summary.csv"
    cfg.upsert_round_rows(summary, out_path, round_id)

    print(summary.to_string(index=False))
    print("\nBaseline category x follow-up category (all linked respondents):")
    print(crosstab.to_string(index=False))
    print(f"\nWritten to: {out_path} (round={round_id})")
    print(f"Written to: {crosstab_path} (round={round_id})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", dest="round_id", default=cfg.DEFAULT_ROUND_ID)
    args = parser.parse_args()
    main(args.round_id)
