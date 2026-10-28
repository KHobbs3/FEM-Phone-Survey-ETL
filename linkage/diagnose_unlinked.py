"""
Why didn't some Phone Pulse respondents link to the formative baseline?

Counts only — prints no IDs, keys or answers. Follows the same route as
link_respondents.py (Pulse resp_id_pull -> crosswalk ID -> crosswalk KEY ->
formative KEY) and reports where each unlinked respondent drops out:

  1. their Pulse ID isn't in the crosswalk at all;
  2. the crosswalk KEY exists in the raw formative export but was removed
     during cleaning (so it isn't in the mapped/analysis file);
  3. the crosswalk KEY isn't in the raw formative export either.

Usage:
    python diagnose_unlinked.py
"""

from pathlib import Path

import pandas as pd

import config as cfg

RAW_FORMATIVE = (
    cfg.NIGER_ROOT / "1_formative_research" / "table_analysis" / "data" / "1_raw"
    / "Ha-Fr_Collecte de Données sur le Terrain_WIDE.csv"
)


def _ids(series: pd.Series) -> set[str]:
    return set(series.dropna().astype(str).str.strip())


def main() -> None:
    pulse = pd.read_csv(cfg.PULSE_DATA, usecols=["resp_id_pull"], low_memory=False)
    cw = pd.read_csv(cfg.CROSSWALK_FILE, usecols=["ID", "KEY"], low_memory=False)
    formative_keys = _ids(pd.read_csv(cfg.FORMATIVE_DATA, usecols=["KEY"], low_memory=False)["KEY"])
    raw_keys = (_ids(pd.read_csv(RAW_FORMATIVE, usecols=["KEY"], low_memory=False)["KEY"])
                if RAW_FORMATIVE.exists() else None)

    cw = cw.assign(ID=cw["ID"].astype(str).str.strip(), KEY=cw["KEY"].astype(str).str.strip())
    id_to_key = dict(zip(cw["ID"], cw["KEY"]))
    pulse_ids = pulse["resp_id_pull"].dropna().astype(str).str.strip()

    n_rows, n_unique = len(pulse), pulse_ids.nunique()
    reasons = {"linked": 0, "not_in_crosswalk": 0, "dropped_in_cleaning": 0, "not_in_raw_export": 0,
               "key_missing_unknown_raw": 0}
    for pid in pulse_ids:
        key = id_to_key.get(pid)
        if key is None:
            reasons["not_in_crosswalk"] += 1
        elif key in formative_keys:
            reasons["linked"] += 1
        elif raw_keys is None:
            reasons["key_missing_unknown_raw"] += 1
        elif key in raw_keys:
            reasons["dropped_in_cleaning"] += 1
        else:
            reasons["not_in_raw_export"] += 1

    print(f"Phone Pulse rows: {n_rows}  (unique IDs: {n_unique}; missing ID: {n_rows - len(pulse_ids)})")
    print(f"Linked: {reasons['linked']}")
    print("Unlinked, by reason:")
    print(f"  Pulse ID not in crosswalk/roster:                 {reasons['not_in_crosswalk']}")
    print(f"  Baseline record removed during formative cleaning: {reasons['dropped_in_cleaning']}")
    print(f"  Crosswalk KEY not in raw formative export:        {reasons['not_in_raw_export']}")
    if raw_keys is None:
        print(f"  KEY not in analysis file (raw export not found):  {reasons['key_missing_unknown_raw']}")
        return

    # Which cleaning rule (00_clean_data.ipynb, applied in this order) removed them
    dropped = {id_to_key[p] for p in pulse_ids
               if p in id_to_key and id_to_key[p] not in formative_keys and id_to_key[p] in raw_keys}
    if not dropped:
        return
    raw = pd.read_csv(RAW_FORMATIVE, low_memory=False)
    raw = raw.loc[:, raw.isna().mean() < 1]           # cell 10: all-empty columns removed first
    raw["KEY"] = raw["KEY"].astype(str).str.strip()
    choices = pd.read_excel(RAW_FORMATIVE.parent / "Ha-Fr_Collecte+de+Données+sur+le+Terrain.xlsx",
                            sheet_name="choices")
    excluded_loc = choices.loc[(choices.list_name == "city")
                               & (choices.label == "East of Guidan Barmou"), "value"].iloc[0]
    loc = pd.to_numeric(raw["location"], errors="coerce")
    rules = [
        ("unfinished (>90% of answers blank)", raw.isna().sum(axis=1) / raw.shape[1] > 0.9),
        ("in excluded area 'East of Guidan Barmou'", loc == int(excluded_loc)),
        ("location outside the sample (-99)", loc == -99),
        # duration is in seconds in the raw export; cell 5 converts to minutes first
        ("interview shorter than 18 minutes", pd.to_numeric(raw["duration"], errors="coerce") / 60 < 18),
    ]
    remaining = raw["KEY"].isin(dropped)
    print("\nBaseline records removed during cleaning, by the cleaning rule that removed them:")
    for label, hit in rules:
        n = int((remaining & hit).sum())
        remaining &= ~hit
        print(f"  {label:<44} {n}")
    print(f"  {'(not explained by the four rules above)':<44} {int(remaining.sum())}")


if __name__ == "__main__":
    main()
