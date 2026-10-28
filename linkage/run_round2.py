"""
Baseline vs Phone Pulse round 2, for the two round 2 analysis groups.

  A. Baseline to Round 2 -- everyone who responded to round 2 and baseline,
     whether or not they responded to round 1. Baseline vs round 2: the
     largest sample for the 6-month change.
  B. Three-wave panel -- everyone who responded to baseline, round 1 and
     round 2. Baseline vs round 1 vs round 2: the trajectory of the same
     people across all three points.
  E. Early group -- the 35 respondents on Haddin Kay (Dakoro, Tagriss)
     interviewed in mid-August (round2_early, ~5 months), analysed separately:
     baseline vs round2_early, as group A. With so few people the weighted
     figures are fragile; read the unweighted ones alongside.

"Responded" to a Pulse round = in that round's QA-passed cleaned_data.csv
(etl_pipeline/run_round.py etl --round <round>).

Nothing here changes how a result is computed: the round 1 scripts in this
folder (link_respondents, attrition_weights, compare_*.py,
compare_key_indicators) are run unchanged on each group, pointed at the
group's own Pulse data and output folder. Per group:
  - attrition weights model P(in the group | baseline characteristics), so
    each group is re-weighted to the full baseline;
  - compare_key_indicators.py gives the weighted figures and, in its
    unweighted_* columns, the same figures unweighted -- so A and B, weighted
    and unweighted, are the four sets of results;
  - the compare_*.py scripts (knowledge, FP use, switching, unmet need,
    attitudes, barriers) are paired tests on the linked respondents, as for
    round 1 (unweighted).
Group B uses the same respondents and the same weights at round 1 and round 2.

Run after `run_round.py etl --round round2` (and round 1's ETL), from 2_phone pulse/linkage/:
    python run_round2.py              # both groups
    python run_round2.py --group A

Outputs (aggregates, plus the same respondent-level linked / weight files
round 1 writes to outputs/):
  outputs/round2/A_baseline_round2/   *_change_summary.csv (round = round2),
                                      key_indicators_change.csv, linked data, weights
  outputs/round2/B_three_wave/        *_change_summary.csv and key_indicators_change.csv
                                      with round = round1 and round = round2 rows
                                      (baseline -> R1 and baseline -> R2, same people)
    round1/, round2/                  that leg's linked data, weights, key indicators
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

import config as cfg

sys.path.insert(0, str(cfg.NIGER_ROOT / "2_phone pulse" / "etl_pipeline"))
import rounds  # noqa: E402  (Phone Pulse round paths)

import link_respondents  # noqa: E402
import attrition_weights  # noqa: E402
import compare_key_indicators  # noqa: E402
import compare_knowledge, compare_fp_use, compare_method_switching  # noqa: E402,E401
import compare_unmet_need, compare_attitudes, compare_barriers  # noqa: E402,E401

COMPARE_SCRIPTS = [compare_knowledge, compare_fp_use, compare_method_switching,
                   compare_unmet_need, compare_attitudes, compare_barriers]
ROUND2_DIR = cfg.OUTPUT_DIR / "round2"
GROUP_DIRS = {"A": ROUND2_DIR / "A_baseline_round2", "B": ROUND2_DIR / "B_three_wave",
              "E": ROUND2_DIR / "A_baseline_round2_early"}


def _cleaned(round_id: str) -> Path:
    path = rounds.get_round(round_id)["etl_output_dir"] / "cleaned_data.csv"
    if not path.exists():
        sys.exit(f"{path} not found. Run `python run_round.py etl --round {round_id}` "
                 f"in 2_phone pulse/etl_pipeline/ first.")
    return path


def _ids(path: Path) -> set:
    ids = pd.read_csv(path, usecols=["resp_id_pull"], dtype=str)["resp_id_pull"]
    return set(ids.dropna().str.strip())


def _run_leg(round_id: str, pulse_data: Path, summary_dir: Path, work_dir: Path) -> None:
    """Link, weight and compare one Pulse round for one group: the round 1
    scripts as they are, with config/module paths pointed at this leg."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cfg.PULSE_DATA = pulse_data
    cfg.CROSSWALK_FILE = rounds.get_round(round_id)["crosswalk"]
    cfg.OUTPUT_DIR = summary_dir                       # compare_*.py summaries (upserted by round)
    cfg.LINKED_RESPONDENTS_CSV = work_dir / "linked_respondents.csv"
    cfg.UNLINKED_RESPONDENTS_CSV = work_dir / "unlinked_respondents.csv"
    cfg.MATCH_REPORT_TXT = work_dir / "match_report.txt"
    cfg.LINKED_DEMOGRAPHICS_CSV = work_dir / "linked_demographics.csv"
    attrition_weights.ATTRITION_WEIGHTS_CSV = work_dir / "attrition_weights.csv"
    attrition_weights.ATTRITION_REPORT_TXT = work_dir / "attrition_report.txt"
    compare_key_indicators.ATTRITION_WEIGHTS_CSV = work_dir / "attrition_weights.csv"
    compare_key_indicators.KEY_INDICATORS_CSV = work_dir / "key_indicators_change.csv"
    compare_key_indicators.PP_HEADLINE_CSV = work_dir / "pp_headline.csv"
    compare_key_indicators.ROUND_ID = round_id

    print(f"\n{'-' * 70}\n{round_id}: {pulse_data.name} -> {work_dir.relative_to(cfg.NIGER_ROOT)}\n{'-' * 70}")
    link_respondents.cmd_link()
    attrition_weights.main()
    for script in COMPARE_SCRIPTS:
        print(f"\n[{script.__name__}]")
        script.main(round_id)
    print("\n[compare_key_indicators]")
    compare_key_indicators.main()


def group_a() -> None:
    out = GROUP_DIRS["A"]
    print(f"\n{'=' * 70}\nA. Baseline to Round 2\n{'=' * 70}")
    _run_leg("round2", _cleaned("round2"), out, out)


def group_e() -> None:
    out = GROUP_DIRS["E"]
    print(f"\n{'=' * 70}\nE. Early group (Haddin Kay, ~5 months)\n{'=' * 70}")
    _run_leg("round2_early", _cleaned("round2_early"), out, out)


def group_b() -> None:
    out = GROUP_DIRS["B"]
    r1, r2 = _cleaned("round1"), _cleaned("round2")
    both = _ids(r1) & _ids(r2)
    print(f"\n{'=' * 70}\nB. Three-wave panel\n{'=' * 70}")
    print(f"Pulse respondents in both round 1 and round 2: {len(both)} "
          f"(linking to baseline below narrows this to the three-wave panel)")
    legs = []
    for round_id, path in [("round1", r1), ("round2", r2)]:
        work = out / round_id
        work.mkdir(parents=True, exist_ok=True)
        pulse = pd.read_csv(path, low_memory=False, dtype={"resp_id_pull": str})
        pulse = pulse[pulse["resp_id_pull"].str.strip().isin(both)]
        panel_data = work / "pulse_cleaned_panel.csv"
        pulse.to_csv(panel_data, index=False)
        _run_leg(round_id, panel_data, out, work)
        legs.append(pd.read_csv(work / "key_indicators_change.csv"))
    pd.concat(legs, ignore_index=True).to_csv(out / "key_indicators_change.csv", index=False)
    print(f"\nWritten: {out / 'key_indicators_change.csv'} (round1 and round2 rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--group", choices=["A", "B", "E"],
                        help="run one group only (default: every group whose round has been processed)")
    args = parser.parse_args()
    done = {rid for rid in ("round2_early", "round2")
            if (rounds.get_round(rid)["etl_output_dir"] / "cleaned_data.csv").exists()}
    if args.group == "E" or (args.group is None and "round2_early" in done):
        group_e()
    if args.group == "A" or (args.group is None and "round2" in done):
        group_a()
    if args.group == "B" or (args.group is None and "round2" in done):
        group_b()
    if args.group is None and not done:
        sys.exit("No round 2 data processed yet: run `run_round.py etl --round round2_early` "
                 "(and/or round2) in 2_phone pulse/etl_pipeline/ first.")


if __name__ == "__main__":
    main()
