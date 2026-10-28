"""
Parse KH manual QA flags into reference files for the QA pipeline.

Reads '[COMPLETED] Niger QA Pulse calls survey - 1st round - Full Data with QA.csv',
extracts the KEY (SurveyCTO form key) and 'KH processing actions' columns, and
routes each submission into the appropriate QA reference file.

CATEGORIES AND ROUTING
----------------------
KH processing action      → QA script that handles it
──────────────────────────────────────────────────────
drop - duplicate          → compare_duplicates.py  +  manual_flags.csv (exclude)
drop - error              → manual_flags.csv (exclude)
drop - nonresponse        → manual_flags.csv (exclude)
placebo station           → check_anomalies.py placebo check  +  manual_flags.csv (review)
overheard concern         → check_anomalies.py honesty check  +  manual_flags.csv (review)
review                    → manual_flags.csv (review)

OUTPUT FILES (all written to q_a/reference_data/)
--------------------------------------------------
manual_flags.csv          Updated in-place with all flagged KEYs. This is the
                          primary input to check_true_invalids.py and run_qa.py.
kh_flags_summary.csv      One row per category with counts and KEY lists.

USAGE
-----
    python parse_kh_flags.py path/to/QA_file.csv
    python parse_kh_flags.py                        # prompts for path
"""

import sys
import csv
import argparse
from pathlib import Path
from datetime import date

REFERENCE_DIR = Path(__file__).parent / "reference_data"
MANUAL_FLAGS  = REFERENCE_DIR / "manual_flags.csv"
SUMMARY_OUT   = REFERENCE_DIR / "kh_flags_summary.csv"

COL_KEY      = "KEY"
COL_KH       = "KH processing actions"
FLAGGED_BY   = "KH"
TODAY        = date.today().isoformat()

# Canonical category names → (flag_type, primary_qa_script)
CATEGORY_MAP = {
    "drop - duplicate":   ("exclude", "compare_duplicates.py"),
    "drop - error":       ("exclude", "check_true_invalids.py"),
    "drop - nonresponse": ("exclude", "check_true_invalids.py"),
    "placebo station":    ("review",  "check_anomalies.py (placebo check)"),
    "overheard concern":  ("review",  "check_anomalies.py (honesty check)"),
    "review":             ("review",  "run_qa.py"),
}


def normalise(value: str) -> str:
    return value.strip().lower()


def match_category(raw: str) -> str | None:
    """Return the canonical category for a raw KH action string, or None if unrecognised."""
    norm = normalise(raw)
    if not norm:
        return None
    # Exact match first
    if norm in CATEGORY_MAP:
        return norm
    # Partial / fuzzy match for robustness against minor typos or extra words
    for canon in CATEGORY_MAP:
        if canon in norm or norm in canon:
            return canon
    return None


def load_kh_file(path: Path) -> list[dict]:
    """Read the QA CSV and return rows that have a KEY and a KH action."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if COL_KEY not in headers:
            raise ValueError(f"Column '{COL_KEY}' not found. Available: {headers}")
        if COL_KH not in headers:
            raise ValueError(f"Column '{COL_KH}' not found. Available: {headers}")
        for row in reader:
            key = row[COL_KEY].strip()
            action = row[COL_KH].strip()
            if key and action:
                rows.append({"KEY": key, "action": action})
    return rows


def load_existing_manual_flags() -> dict[str, dict]:
    """Load existing manual_flags.csv keyed by KEY, skipping comment lines."""
    existing = {}
    if not MANUAL_FLAGS.exists():
        return existing
    with open(MANUAL_FLAGS, newline="", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            break  # stop at first non-comment to find headers
        # Re-read properly
    with open(MANUAL_FLAGS, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(
            (line for line in f if not line.startswith("#"))
        )
        for row in reader:
            key = row.get("KEY", "").strip()
            if key:
                existing[key] = row
    return existing


def write_manual_flags(flags: dict[str, dict]) -> None:
    """Write all flags back to manual_flags.csv."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANUAL_FLAGS, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["KEY", "reason", "flagged_by", "date_flagged", "notes"]
        )
        writer.writeheader()
        for row in sorted(flags.values(), key=lambda r: r["KEY"]):
            writer.writerow(row)


def write_summary(categorised: dict[str, list[str]]) -> None:
    """Write a summary CSV with counts and KEY lists per category."""
    with open(SUMMARY_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["category", "flag_type", "qa_script", "n_submissions", "keys"]
        )
        writer.writeheader()
        for canon, keys in sorted(categorised.items()):
            flag_type, script = CATEGORY_MAP[canon]
            writer.writerow({
                "category":      canon,
                "flag_type":     flag_type,
                "qa_script":     script,
                "n_submissions": len(keys),
                "keys":          "|".join(keys),
            })


def main(kh_path: Path) -> None:
    print(f"\nReading: {kh_path.name}")
    rows = load_kh_file(kh_path)
    print(f"  {len(rows)} rows with KEY + KH action")

    # Categorise
    categorised: dict[str, list[str]] = {c: [] for c in CATEGORY_MAP}
    unrecognised: list[tuple[str, str]] = []

    for row in rows:
        canon = match_category(row["action"])
        if canon:
            categorised[canon].append(row["KEY"])
        else:
            unrecognised.append((row["KEY"], row["action"]))

    # Load and update manual_flags.csv
    existing_flags = load_existing_manual_flags()
    added = 0
    updated = 0

    for canon, keys in categorised.items():
        flag_type, script = CATEGORY_MAP[canon]
        for key in keys:
            entry = {
                "KEY":          key,
                "reason":       canon,
                "flagged_by":   FLAGGED_BY,
                "date_flagged": TODAY,
                "notes":        f"qa_script: {script}",
            }
            if key in existing_flags:
                updated += 1
            else:
                added += 1
            existing_flags[key] = entry

    write_manual_flags(existing_flags)
    write_summary(categorised)

    # Print results
    total = sum(len(v) for v in categorised.values())
    print(f"\n{'='*56}")
    print("KH FLAG SUMMARY")
    print(f"{'='*56}")
    print(f"  {'Category':<25} {'Type':<8} {'Count':>5}  QA script")
    print(f"  {'-'*54}")
    for canon, keys in categorised.items():
        flag_type, script = CATEGORY_MAP[canon]
        marker = "DROP" if flag_type == "exclude" else "REVIEW"
        print(f"  {canon:<25} {marker:<8} {len(keys):>5}  {script}")
    print(f"  {'-'*54}")
    print(f"  {'TOTAL':<25} {'':8} {total:>5}")

    if unrecognised:
        print(f"\n  ⚠  {len(unrecognised)} unrecognised action(s) — not written to manual_flags.csv:")
        for key, action in unrecognised:
            print(f"     KEY={key}  action='{action}'")

    print(f"\n  manual_flags.csv — {added} added, {updated} updated")
    print(f"  kh_flags_summary.csv — written")
    print(f"\n  Next steps:")
    drops = [c for c, v in categorised.items() if CATEGORY_MAP[c][0] == "exclude" and v]
    reviews = [c for c, v in categorised.items() if CATEGORY_MAP[c][0] == "review" and v]
    if drops:
        print(f"  1. run_qa.py will exclude: {', '.join(drops)}")
    if "drop - duplicate" in categorised and categorised["drop - duplicate"]:
        print(f"  2. python compare_duplicates.py  — similarity scoring for {len(categorised['drop - duplicate'])} duplicate ID(s)")
    if reviews:
        print(f"  3. run_qa.py will flag for review: {', '.join(reviews)}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse KH QA flags into manual_flags.csv")
    parser.add_argument(
        "kh_file",
        nargs="?",
        help="Path to the completed QA CSV file",
    )
    args = parser.parse_args()

    if args.kh_file:
        path = Path(args.kh_file)
    else:
        default = (
            Path(__file__).parent.parent / "data" / "q_a"
            / "Niger QA Pulse calls survey - 1st round.csv"
        )
        if default.exists():
            path = default
        else:
            path = Path(input("Path to QA CSV file: ").strip().strip("'\""))

    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(1)

    main(path)
