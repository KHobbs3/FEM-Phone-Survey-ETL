"""
Link Phone Pulse (follow-up) respondents back to their Formative Research
(baseline) records.

Usage
-----
    # Step 1 — ALWAYS do this first. Prints column names only (no values,
    # no respondent data) for all three source files, so you can confirm
    # config.py's *_ID_CANDIDATES actually match reality before merging.
    python link_respondents.py --inspect

    # Step 2 — once the printed columns confirm (or you've corrected)
    # config.py, run the real merge:
    python link_respondents.py

Output
------
    outputs/linked_respondents.csv  — one row per matched respondent, with
        only the analysis columns listed in config.py (no names, phone
        numbers, device IDs, or raw join keys — those are dropped after
        the join, replaced by a sequential surrogate `link_id`).
    outputs/linked_demographics.csv — resp_id_pull + formative age_group,
        occupation, religion, urban_rural for each matched respondent; joined
        onto the Pulse sample by export_pp_app_data.py (counts only published).
    outputs/match_report.txt        — counts only (n formative, n pulse,
        n matched, match rate). No respondent-level values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

import config as cfg


def _inspect_csv(path: Path, label: str) -> None:
    print(f"\n--- {label}: {path} ---")
    if not path.exists():
        print("  ! FILE NOT FOUND")
        return
    cols = pd.read_csv(path, nrows=0).columns.tolist()
    print(f"  {len(cols)} columns:")
    for c in cols:
        print(f"    {c}")


def _inspect_excel(path: Path, label: str) -> None:
    print(f"\n--- {label}: {path} ---")
    if not path.exists():
        print("  ! FILE NOT FOUND")
        return
    xls = pd.ExcelFile(path)
    print(f"  sheets: {xls.sheet_names}")
    for sheet in xls.sheet_names:
        cols = pd.read_excel(xls, sheet_name=sheet, nrows=0).columns.tolist()
        print(f"\n  [{sheet}] {len(cols)} columns:")
        for c in cols:
            print(f"    {c}")


def cmd_inspect() -> None:
    print("=" * 70)
    print("SCHEMA INSPECTION — column names only, no respondent data shown")
    print("=" * 70)
    _inspect_csv(cfg.FORMATIVE_DATA, "Formative research")
    _inspect_csv(cfg.PULSE_DATA, "Phone Pulse")
    if cfg.CROSSWALK_FILE.suffix.lower() == ".csv":
        _inspect_csv(cfg.CROSSWALK_FILE, "Crosswalk / roster")
    else:
        _inspect_excel(cfg.CROSSWALK_FILE, "Crosswalk / roster")
    print("\n" + "=" * 70)
    print("Compare the columns above against config.py's *_ID_CANDIDATES and")
    print("CROSSWALK_*_HINTS lists. Edit config.py if the real column names")
    print("differ, then re-run without --inspect.")
    print("=" * 70)


def _load_crosswalk_sheets(path: Path) -> dict[str, pd.DataFrame]:
    """Load the crosswalk file, CSV or Excel, as {label: DataFrame}."""
    if path.suffix.lower() == ".csv":
        return {"(csv)": pd.read_csv(path, low_memory=False)}
    xls = pd.ExcelFile(path)
    return {sheet: pd.read_excel(xls, sheet_name=sheet) for sheet in xls.sheet_names}


def _find_crosswalk_columns(path: Path) -> tuple[str, str, str, pd.DataFrame] | None:
    """
    Search every sheet/table in the crosswalk file for one column whose
    name hints at a formative-side ID and one that hints at a pulse-side ID.
    Returns (sheet_label, formative_col, pulse_col, dataframe) or None.
    """
    for label, sdf in _load_crosswalk_sheets(path).items():
        lower = {c: c.lower() for c in sdf.columns}
        f_col = next(
            (c for c, lc in lower.items()
             if any(h in lc for h in cfg.CROSSWALK_FORMATIVE_ID_HINTS)),
            None,
        )
        p_col = next(
            (c for c, lc in lower.items()
             if any(h in lc for h in cfg.CROSSWALK_PULSE_ID_HINTS)),
            None,
        )
        if f_col and p_col and f_col != p_col:
            return label, f_col, p_col, sdf
    return None


def _match_rate(a: pd.Series, b: pd.Series) -> float:
    a_set = set(a.dropna().astype(str).str.strip())
    b_set = set(b.dropna().astype(str).str.strip())
    if not b_set:
        return 0.0
    return len(a_set & b_set) / len(b_set)


def _select_columns(df: pd.DataFrame, wanted: list[str], prefix: str) -> pd.DataFrame:
    keep = [c for c in wanted if c in df.columns]
    missing = [c for c in wanted if c not in df.columns]
    if missing:
        print(f"  ! {prefix}: {len(missing)} configured analysis column(s) not "
              f"found and will be skipped: {missing}")
    out = df[keep].copy()
    out.columns = [f"{prefix}{c}" for c in out.columns]
    return out


def cmd_link() -> None:
    if not cfg.FORMATIVE_DATA.exists() or not cfg.PULSE_DATA.exists():
        sys.exit(
            "Formative or Phone Pulse data file not found. Check config.py "
            "paths, or run --inspect to see what exists."
        )

    formative = pd.read_csv(cfg.FORMATIVE_DATA, low_memory=False)
    pulse = pd.read_csv(cfg.PULSE_DATA, low_memory=False)
    print(f"Loaded formative research: {len(formative)} rows")
    print(f"Loaded phone pulse:        {len(pulse)} rows")

    f_candidates = [c for c in cfg.FORMATIVE_ID_CANDIDATES if c in formative.columns]
    p_candidates = [c for c in cfg.PULSE_ID_CANDIDATES if c in pulse.columns]
    if not f_candidates or not p_candidates:
        sys.exit(
            "Could not find any configured ID columns in one of the source "
            f"files (formative candidates={cfg.FORMATIVE_ID_CANDIDATES}, "
            f"pulse candidates={cfg.PULSE_ID_CANDIDATES}). Run --inspect "
            "and update config.py."
        )

    # ── Strategy A: direct join — try every (formative ID, pulse ID) column
    # pair and keep whichever overlaps best. Reports match rate only. ──
    print("\nStrategy A (direct join) — trying all candidate ID column pairs:")
    direct_rate = 0.0
    # Default to the first candidates (preferring resp_id_pull on the pulse
    # side — see config.py) so Strategy B still has a pulse ID column to test
    # even when every direct-join rate is exactly 0%.
    f_id, p_id = f_candidates[0], p_candidates[0]
    for fc in f_candidates:
        for pc in p_candidates:
            rate = _match_rate(formative[fc], pulse[pc])
            print(f"  {fc} <-> {pc}: {rate:.1%} of pulse respondents matched")
            if rate > direct_rate:
                direct_rate, f_id, p_id = rate, fc, pc

    bridge = None
    bridge_rate = 0.0
    if cfg.CROSSWALK_FILE.exists():
        found = _find_crosswalk_columns(cfg.CROSSWALK_FILE)
        if found:
            label, cw_f_col, cw_p_col, cw_df = found
            bridge = cw_df[[cw_f_col, cw_p_col]].dropna()
            bridge.columns = ["_cw_formative_id", "_cw_pulse_id"]
            bridge_rate = _match_rate(pulse[p_id], bridge["_cw_pulse_id"])
            print(f"Strategy B (via crosswalk {label}, "
                  f"{cw_f_col} <-> {cw_p_col}): "
                  f"{bridge_rate:.1%} of pulse respondents matched")
        else:
            print("Strategy B: no column pair in the crosswalk file matched "
                  "the configured hints — skipped.")
    else:
        print("Strategy B: crosswalk file not found — skipped.")

    if max(direct_rate, bridge_rate) < cfg.MIN_MATCH_RATE:
        sys.exit(
            f"\nBoth join strategies matched under {cfg.MIN_MATCH_RATE:.0%} "
            "of respondents — refusing to write a linked dataset from an "
            "unreliable join. Run --inspect, confirm the real ID columns, "
            "and update config.py."
        )

    formative_keyed = formative.copy()
    formative_keyed["_join_formative_id"] = (
        formative_keyed[f_id].astype(str).str.strip()
    )

    pulse_keyed = pulse.copy()
    if direct_rate >= bridge_rate:
        print(f"\nUsing Strategy A (direct join) — higher match rate.")
        pulse_keyed["_join_formative_id"] = pulse_keyed[p_id].astype(str).str.strip()
    else:
        print(f"\nUsing Strategy B (crosswalk join) — higher match rate.")
        pulse_keyed = pulse_keyed.merge(
            bridge, left_on=p_id, right_on="_cw_pulse_id", how="left"
        )
        pulse_keyed["_join_formative_id"] = (
            pulse_keyed["_cw_formative_id"].astype(str).str.strip()
        )

    # Analysis-only frames (PII minimized) carrying just the join key.
    pulse_analysis = _select_columns(pulse_keyed, cfg.PULSE_ANALYSIS_COLUMNS, "pulse_")
    pulse_analysis["_join_formative_id"] = pulse_keyed["_join_formative_id"]
    # resp_id_pull is the canonical Phone Pulse respondent ID (what SurveyCTO
    # itself uses to pull roster data during the survey — not PII). Carried
    # through so the unlinked-respondents report below can identify WHICH
    # respondents need roster follow-up; dropped from the main linked output.
    pulse_analysis["_resp_id_pull"] = (
        pulse_keyed["resp_id_pull"] if "resp_id_pull" in pulse_keyed.columns else pulse_keyed[p_id]
    )

    formative_analysis = _select_columns(
        formative_keyed, cfg.FORMATIVE_ANALYSIS_COLUMNS, "formative_"
    )
    formative_analysis["_join_formative_id"] = formative_keyed["_join_formative_id"]

    merged = pulse_analysis.merge(
        formative_analysis, on="_join_formative_id", how="left", indicator=True
    )

    linked = merged[merged["_merge"] == "both"].drop(
        columns=["_join_formative_id", "_merge", "_resp_id_pull"]
    ).copy()
    linked.insert(0, "link_id", range(1, len(linked) + 1))

    unlinked = merged[merged["_merge"] == "left_only"].copy()
    # Keep only the pulse-side (non-PII) columns plus resp_id_pull for the
    # unlinked report — there's no formative match, so every formative_*
    # column is NaN anyway. resp_id_pull identifies WHICH respondents need
    # roster follow-up (see note above — it's a study ID, not PII).
    unlinked_cols = ["_resp_id_pull"] + [c for c in unlinked.columns if c.startswith("pulse_")]
    unlinked = unlinked[unlinked_cols].rename(columns={"_resp_id_pull": "resp_id_pull"}).reset_index(drop=True)

    # Formative demographics keyed by resp_id_pull, for the Phone Pulse
    # Respondent Profile page (see config.LINKED_DEMOGRAPHICS_CSV). Only the
    # configured demographic columns — no answers, no join keys beyond the
    # Pulse study ID. One row per resp_id_pull (duplicate Pulse submissions
    # share a roster ID and therefore a formative record).
    demo_cols = [f"formative_{c}" for c in cfg.LINKED_DEMOGRAPHIC_COLUMNS
                 if f"formative_{c}" in merged.columns]
    demographics = (
        merged.loc[merged["_merge"] == "both", ["_resp_id_pull"] + demo_cols]
        .rename(columns={"_resp_id_pull": "resp_id_pull",
                         **{c: c.removeprefix("formative_") for c in demo_cols}})
        .drop_duplicates(subset="resp_id_pull")
        .reset_index(drop=True)
    )

    n_matched = len(linked)
    n_unlinked = len(unlinked)
    match_rate = n_matched / len(pulse) if len(pulse) else 0.0

    # Defense in depth: drop anything that slipped through matching a PII hint.
    blocked = [
        c for c in linked.columns
        if any(h in c.lower() for h in cfg.PII_BLOCKLIST_SUBSTRINGS)
    ]
    if blocked:
        print(f"  ! Dropping columns matching PII blocklist: {blocked}")
        linked = linked.drop(columns=blocked)
    blocked_unlinked = [
        c for c in unlinked.columns
        if any(h in c.lower() for h in cfg.PII_BLOCKLIST_SUBSTRINGS)
    ]
    if blocked_unlinked:
        unlinked = unlinked.drop(columns=blocked_unlinked)

    cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    linked.to_csv(cfg.LINKED_RESPONDENTS_CSV, index=False)
    unlinked.to_csv(cfg.UNLINKED_RESPONDENTS_CSV, index=False)
    demographics.to_csv(cfg.LINKED_DEMOGRAPHICS_CSV, index=False)

    # Age distribution among linked respondents (counts/pct only — no
    # respondent-level rows) — age isn't reported in any Phone Pulse app
    # page (Phone Pulse doesn't collect age itself), so this is the one
    # place it's surfaced, via the formative-research link.
    age_report_lines = []
    if "formative_age_group" in linked.columns and n_matched:
        vc = linked["formative_age_group"].value_counts(dropna=False).sort_index()
        age_report_lines.append("\nAge distribution among linked respondents (from formative baseline):")
        for label, n in vc.items():
            label = label if pd.notna(label) else "(missing)"
            age_report_lines.append(f"  {label:<12} {n:>4}  ({100*n/n_matched:.1f}%)")
    elif "formative_age" in linked.columns and n_matched:
        age_series = pd.to_numeric(linked["formative_age"], errors="coerce").dropna()
        if len(age_series):
            age_report_lines.append("\nAge among linked respondents (from formative baseline):")
            age_report_lines.append(
                f"  mean={age_series.mean():.1f}  median={age_series.median():.1f}  "
                f"min={age_series.min():.0f}  max={age_series.max():.0f}  n={len(age_series)}"
            )
    age_report = "\n".join(age_report_lines)

    report = (
        f"Formative research respondents : {len(formative)}\n"
        f"Phone Pulse respondents        : {len(pulse)}\n"
        f"Matched (linked) respondents   : {n_matched}\n"
        f"Unlinked (no formative match)  : {n_unlinked}\n"
        f"Match rate (of pulse)          : {match_rate:.1%}\n"
        f"Join strategy used             : "
        f"{'direct' if direct_rate >= bridge_rate else 'crosswalk'}\n"
        f"{age_report}\n"
    )
    cfg.MATCH_REPORT_TXT.write_text(report)
    print("\n" + report)
    print(f"Linked dataset written to:   {cfg.LINKED_RESPONDENTS_CSV}")
    print(f"Unlinked pulse IDs written to: {cfg.UNLINKED_RESPONDENTS_CSV}")
    print(f"Linked demographics written to: {cfg.LINKED_DEMOGRAPHICS_CSV} "
          f"(columns: {', '.join(demographics.columns)})")
    print(f"Match report written to:     {cfg.MATCH_REPORT_TXT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inspect", action="store_true",
        help="Print column names only (no data) for all source files, then exit.",
    )
    args = parser.parse_args()

    if args.inspect:
        cmd_inspect()
    else:
        cmd_link()


if __name__ == "__main__":
    main()
