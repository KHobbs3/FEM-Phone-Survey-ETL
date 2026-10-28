"""
Parse the PM validation status (round 2 onwards) into the round's keep-list.

From round 2 the QA review file has one status per submission in the column
'Validation status (PM)', instead of round 1's 'KH processing actions'
(parse_kh_flags.py, which stays as it is for round 1).

STATUS ROUTING
--------------
Validated  → keep_list.csv           (analysed)
Pending    → keep_list.csv           (analysed)
Invalid    → manual_flags.csv        (exclude)
anything else, or blank → not analysed; KEYs written to
                          validation_status_unrecognised.csv to resolve

Submissions in the raw export but not in the review file are not on the
keep-list, so run.py drops them too.

OUTPUT FILES (the round's q_a/reference_data/ folder, from etl_pipeline/rounds.py)
------------------------------------------------------------------------------
keep_list.csv                       KEYs to analyse; read by run_round.py etl.
manual_flags.csv                    Invalid KEYs added / updated (other rows kept).
validation_status_summary.csv       Counts per status.
validation_status_unrecognised.csv  Only if any status is not one of the three.

Only counts are printed.

USAGE (from q_a/)
-----
    python parse_validation_status.py --round round2
    python parse_validation_status.py --round round2 path/to/QA_file.csv
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "etl_pipeline"))
import rounds  # noqa: E402

COL_KEY    = "KEY"
COL_STATUS = "Validation status (PM)"
FLAGGED_BY = "PM"
TODAY      = date.today().isoformat()

KEEP_STATUSES    = {"validated", "pending"}
EXCLUDE_STATUSES = {"invalid"}


def load_statuses(path: Path) -> dict[str, str]:
    """{KEY: status (lower case)}. A KEY listed more than once is Invalid if any row says so."""
    statuses: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for col in (COL_KEY, COL_STATUS):
            if col not in headers:
                raise ValueError(f"Column '{col}' not found. Available: {headers}")
        for row in reader:
            key = (row[COL_KEY] or "").strip()
            if not key:
                continue
            status = (row[COL_STATUS] or "").strip().lower()
            if statuses.get(key) not in EXCLUDE_STATUSES:
                statuses[key] = status
    return statuses


def load_manual_flags(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(line for line in f if not line.startswith("#"))
        return {row["KEY"].strip(): row for row in reader if row.get("KEY", "").strip()}


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(r: dict, review_path: Path) -> None:
    ref_dir = r["keep_list"].parent
    print(f"\nReading: {review_path.name}")
    statuses = load_statuses(review_path)
    print(f"  {len(statuses)} submissions with a KEY")

    keep = sorted(k for k, s in statuses.items() if s in KEEP_STATUSES)
    invalid = sorted(k for k, s in statuses.items() if s in EXCLUDE_STATUSES)
    other = sorted(k for k, s in statuses.items() if s not in KEEP_STATUSES | EXCLUDE_STATUSES)

    write_csv(r["keep_list"], ["KEY"], [{"KEY": k} for k in keep])

    flags = load_manual_flags(r["manual_flags"])
    added = sum(k not in flags for k in invalid)
    for k in invalid:
        flags[k] = {"KEY": k, "reason": "invalid (PM validation status)", "flagged_by": FLAGGED_BY,
                    "date_flagged": TODAY, "notes": f"source: {review_path.name}"}
    write_csv(r["manual_flags"], ["KEY", "reason", "flagged_by", "date_flagged", "notes"],
              sorted(flags.values(), key=lambda row: row["KEY"]))

    counts: dict[str, int] = {}
    for s in statuses.values():
        counts[s or "(blank)"] = counts.get(s or "(blank)", 0) + 1
    write_csv(ref_dir / "validation_status_summary.csv", ["status", "action", "n_submissions"],
              [{"status": s, "n_submissions": n,
                "action": "analyse" if s in KEEP_STATUSES else
                          "exclude" if s in EXCLUDE_STATUSES else "not analysed: resolve"}
               for s, n in sorted(counts.items())])
    unrecognised_csv = ref_dir / "validation_status_unrecognised.csv"
    if other:
        write_csv(unrecognised_csv, ["KEY", "status"], [{"KEY": k, "status": statuses[k]} for k in other])
    elif unrecognised_csv.exists():
        unrecognised_csv.unlink()

    print(f"\n{'=' * 50}\nPM VALIDATION STATUS ({r['round_id']})\n{'=' * 50}")
    for s, n in sorted(counts.items()):
        action = "ANALYSE" if s in KEEP_STATUSES else "EXCLUDE" if s in EXCLUDE_STATUSES else "??"
        print(f"  {s:<20} {action:<8} {n:>5}")
    print(f"\n  keep_list.csv     — {len(keep)} KEYs  ({r['keep_list']})")
    print(f"  manual_flags.csv  — {len(invalid)} Invalid ({added} new)")
    if other:
        print(f"\n  ⚠  {len(other)} submission(s) with another or blank status are NOT analysed.")
        print(f"     Fix their status in the review file and re-run, or see {unrecognised_csv.name}.")
    print(f"\n  Next: python run_round.py etl --round {r['round_id']}  (from etl_pipeline/)\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse 'Validation status (PM)' into the round's keep-list")
    parser.add_argument("--round", dest="round_id", default="round2",
                        choices=[k for k in rounds.ROUNDS if k != "round1"])
    parser.add_argument("review_file", nargs="?", help="QA review CSV (default: the round's qa_review in rounds.py)")
    args = parser.parse_args()

    r = rounds.get_round(args.round_id)
    path = Path(args.review_file) if args.review_file else r["qa_review"]
    if not path.exists():
        sys.exit(f"ERROR: file not found: {path}")
    main(r, path)
