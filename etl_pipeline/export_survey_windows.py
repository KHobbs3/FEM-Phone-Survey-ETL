"""
When each survey wave was in the field: first and last SubmissionDate of the
baseline (formative) export and of each Phone Pulse round's raw file (from
`run_round.py split`), for the
airing timeline on the app's Baseline vs. Follow-up page.

Reads only the SubmissionDate column; writes dates and counts only. Phone
submissions before a round's training_cutoff (rounds.py) are left out.

Usage (from etl_pipeline/):
    python export_survey_windows.py

Output: etl_pipeline/outputs/survey_windows.csv
    wave, label, first_date, last_date, n_submissions
Upload it to Drive and set its ID in niger_app/src/data_loader.py
(load_survey_windows).
"""

import pandas as pd

import rounds

BASELINE_RAW = (rounds.NIGER_ROOT / "1_formative_research" / "table_analysis" / "data" / "1_raw"
                / "Ha-Fr_Collecte de Données sur le Terrain_WIDE.csv")
OUT_CSV = rounds.ETL_DIR / "outputs" / "survey_windows.csv"
LABELS = {"baseline": "Baseline (field survey)",
          **{rid: r["label"] for rid, r in rounds.ROUNDS.items()}}


def _submission_dates(path) -> pd.Series:
    if path.suffix == ".csv":
        s = pd.read_csv(path, usecols=["SubmissionDate"], dtype=str)["SubmissionDate"]
    else:
        s = pd.read_excel(path, sheet_name="data", usecols=["SubmissionDate"], dtype=str)["SubmissionDate"]
    return pd.to_datetime(s, errors="coerce", format="mixed").dropna()


def main() -> None:
    sources = {"baseline": BASELINE_RAW}
    sources.update({rid: r["raw_xlsx"] for rid, r in rounds.ROUNDS.items()})
    rows = []
    for wave, path in sources.items():
        if not path.exists():
            print(f"  {wave}: no raw export yet ({path.name}) -- skipped")
            continue
        dates = _submission_dates(path)
        cutoff = rounds.ROUNDS.get(wave, {}).get("training_cutoff")
        if cutoff:   # enumerator training submissions before go-live
            dates = dates[dates >= pd.Timestamp(cutoff)]
        if dates.empty:
            print(f"  {wave}: no readable SubmissionDate -- skipped")
            continue
        rows.append({"wave": wave, "label": LABELS.get(wave, wave),
                     "first_date": dates.min().date().isoformat(),
                     "last_date": dates.max().date().isoformat(),
                     "n_submissions": len(dates)})
        print(f"  {wave}: {rows[-1]['first_date']} to {rows[-1]['last_date']} ({len(dates)} submissions)")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
    print(f"\nWritten to: {OUT_CSV}")


if __name__ == "__main__":
    main()
