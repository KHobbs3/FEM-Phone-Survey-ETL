"""
Run the Phone Pulse processing for one survey round.

This runs the round 1 scripts (../q_a/run_qa.py, run.py, export_pp_app_data.py)
with the paths of the chosen round from rounds.py, so every round is processed
exactly the same way -- including run.py's "Other (specify)" recodes
(other_recodes.py), which use the round's own form.

Usage (from etl_pipeline/), in this order for a new round:
    python run_round.py split                   # single export -> one raw file per round
    python run_round.py parse  --round round2   # QA review file -> keep_list.csv + manual_flags.csv
    python run_round.py qa     --round round2   # QA reports (check before etl)
    python run_round.py etl    --round round2   # recodes + run.py --keep-list
    #   then 2_phone pulse/linkage/run_round2.py (links round 2 to the baseline)
    python run_round.py export --round round2   # app tables (round 2: outputs/round2/app_data/)

    python run_round.py etl --round round2 --no-recode-refresh   # apply recodes as they are
    python run_round.py etl --round round2 --all-submissions      # no keep-list yet

For round 1, `etl` is the same as `run.py --keep-list
../q_a/reference_data/keep_list.csv`.
"""

import argparse
import sys
from pathlib import Path

ETL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ETL_DIR))

import rounds  # noqa: E402


def run_qa(r: dict) -> None:
    sys.path.insert(0, str(rounds.QA_DIR))
    import config_qa
    # Before run_qa (and the check_* modules it imports) read these names.
    config_qa.RAW_DATA_PATH = r["raw_xlsx"]
    config_qa.QA_OUTPUT_DIR = r["qa_output_dir"]
    config_qa.MANUAL_FLAGS_CSV = r["manual_flags"]
    config_qa.TRAINING_CUTOFF_DATE = r["training_cutoff"]
    if r["training_cutoff"] is None:
        print(f"  ! training_cutoff not set for {r['round_id']} in rounds.py -- "
              f"pre-go-live submissions won't be flagged")
    if not r["manual_flags"].exists():
        print(f"  ! {r['manual_flags']} not found -- create it (same columns as round 1's "
              f"manual_flags.csv) to record reviewed exclusions")
    import run_qa
    run_qa.main()
    print(f"\nNext: review the QA reports; the keep-list run_round.py etl uses is {r['keep_list']}")


def run_split() -> None:
    import split_rounds
    split_rounds.main()


def run_parse(r: dict) -> None:
    """The round's QA review file -> keep-list / manual flags. Round 1 used KH's
    processing actions (parse_kh_flags.py); later rounds use 'Validation status (PM)'."""
    sys.path.insert(0, str(rounds.QA_DIR))
    if not r["qa_review"].exists():
        sys.exit(f"QA review file not found: {r['qa_review']}")
    if r["round_id"] == "round1":
        import parse_kh_flags
        parse_kh_flags.main(r["qa_review"])
    else:
        import parse_validation_status
        parse_validation_status.main(r, r["qa_review"])


def run_etl(r: dict, refresh_recodes: bool, all_submissions: bool) -> None:
    import config
    import extract
    config.DATA_DIR, config.OUTPUT_DIR = r["data_dir"], r["etl_output_dir"]
    config.STATS_DIR = r["etl_output_dir"] / "stats"
    import run

    # run.py recodes "Other" write-ins itself; it just needs this round's data and form.
    run.load_raw_data = lambda: extract.load_raw_data(r["data_dir"], r["raw_xlsx"])
    run.FORM_PATH = r["form_path"]
    run.OUTPUT_DIR, run.STATS_DIR = config.OUTPUT_DIR, config.STATS_DIR
    argv = ["run.py"] + ([] if refresh_recodes else ["--no-recode-refresh"])
    if not all_submissions:
        if not r["keep_list"].exists():
            sys.exit(f"Keep-list not found: {r['keep_list']}. Run `run_round.py qa --round "
                     f"{r['round_id']}` and save the reviewed keep-list, or pass --all-submissions.")
        argv += ["--keep-list", str(r["keep_list"])]
    sys.argv = argv
    run.main()


def run_export(r: dict) -> None:
    import export_pp_app_data as export
    export.CLEANED_DATA = r["etl_output_dir"] / "cleaned_data.csv"
    export.POPULATION_SUMMARY = r["etl_output_dir"] / "population_summary.csv"
    export.APP_DATA_DIR = r["app_data_dir"]
    export.LINKED_DEMOGRAPHICS = r["linked_demographics"]
    export.main()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phone Pulse processing for one round.")
    parser.add_argument("step", choices=["split", "parse", "qa", "etl", "export"])
    parser.add_argument("--round", dest="round_id", choices=list(rounds.ROUNDS),
                        help="required for every step except split")
    parser.add_argument("--no-recode-refresh", action="store_true",
                        help="apply the recodes file as it is, without the --fuzzy refresh")
    parser.add_argument("--all-submissions", action="store_true",
                        help="etl: process every submission (no QA keep-list)")
    args = parser.parse_args()

    if args.step == "split":
        run_split()
        return
    if args.round_id is None:
        parser.error("--round is required for this step")
    r = rounds.get_round(args.round_id)
    if args.step in ("qa", "etl") and not r["raw_xlsx"].exists():
        sys.exit(f"{r['raw_xlsx'].name} not found: run `python run_round.py split` first "
                 f"(or {args.round_id} is not in the export yet).")
    print(f"Round: {args.round_id}  |  data: {r['raw_xlsx'].name}  |  form: {r['form_path'].name}")
    if args.step == "parse":
        run_parse(r)
    elif args.step == "qa":
        run_qa(r)
    elif args.step == "etl":
        run_etl(r, refresh_recodes=not args.no_recode_refresh, all_submissions=args.all_submissions)
    else:
        run_export(r)


if __name__ == "__main__":
    main()
