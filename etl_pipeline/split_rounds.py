"""
Split the single Phone Pulse export into one raw file per round.

All rounds are recorded in one SurveyCTO export (rounds.RAW_XLSX). Rounds
are found from the gaps in SubmissionDate: consecutive submission days at
least rounds.MIN_GAP_DAYS apart start a new fieldwork wave, and the waves are
named in date order from rounds.WAVE_ORDER. Submissions before round 1's
training_cutoff (enumerator training) stay in round 1, where the QA flags them.

Run after every update of the export, before the parse / qa / etl steps:
    python run_round.py split            # from etl_pipeline/
    python split_rounds.py               # same

Outputs:
  data/raw_data/by_round/<round_id>.xlsx   that round's submissions, sheet "data",
                                           columns and values as in the export
  q_a/outputs/round_waves.csv              per round: first / last date, submissions,
                                           and submissions per region (lga_pull)
Prints dates and counts only.
"""

import sys

import pandas as pd

import rounds

COL_DATE, COL_REGION = "SubmissionDate", "lga_pull"
WAVES_CSV = rounds.QA_DIR / "outputs" / "round_waves.csv"


def assign_waves(dates: pd.Series, min_gap_days: int, cutoff: str | None) -> pd.Series:
    """Wave number (0, 1, ...) per submission. Days before `cutoff` join wave 0."""
    day = dates.dt.normalize()
    live = day if cutoff is None else day.where(day >= pd.Timestamp(cutoff))
    days = pd.Series(sorted(live.dropna().unique()))
    starts = days[days.diff().dt.days.fillna(0) >= min_gap_days].tolist()
    wave = live.apply(lambda d: sum(d >= s for s in starts) if pd.notna(d) else 0)
    return wave.astype(int)


def main() -> None:
    if not rounds.RAW_XLSX.exists():
        sys.exit(f"Export not found: {rounds.RAW_XLSX}")
    print(f"Reading: {rounds.RAW_XLSX.name}")
    df = pd.read_excel(rounds.RAW_XLSX, sheet_name="data")
    dates = pd.to_datetime(df[COL_DATE].astype(str), errors="coerce", format="mixed")
    if dates.isna().any():
        sys.exit(f"{int(dates.isna().sum())} submission(s) have no readable {COL_DATE} -- check the export.")

    wave = assign_waves(dates, rounds.MIN_GAP_DAYS, rounds.ROUNDS["round1"]["training_cutoff"])
    n_waves = wave.max() + 1
    if n_waves > len(rounds.WAVE_ORDER):
        sys.exit(f"Found {n_waves} fieldwork waves but WAVE_ORDER names {len(rounds.WAVE_ORDER)}: "
                 f"add the new round to rounds.py (WAVE_ORDER and ROUNDS).")

    rounds.BY_ROUND_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for w in range(n_waves):
        round_id = rounds.WAVE_ORDER[w]
        part = df[wave == w]
        part.to_excel(rounds.ROUNDS[round_id]["raw_xlsx"], sheet_name="data", index=False)
        d = dates[wave == w]
        regions = part[COL_REGION].fillna("(blank)").value_counts() if COL_REGION in part else {}
        summary.append({"round": round_id, "first_date": d.min().date().isoformat(),
                        "last_date": d.max().date().isoformat(), "n_submissions": len(part),
                        "by_region": "; ".join(f"{k}: {v}" for k, v in regions.items())})
    for round_id in rounds.WAVE_ORDER[n_waves:]:
        stale = rounds.ROUNDS[round_id]["raw_xlsx"]
        if stale.exists():
            stale.unlink()   # from an earlier split that found more waves

    summary = pd.DataFrame(summary)
    WAVES_CSV.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(WAVES_CSV, index=False)
    print(f"\nFieldwork waves (new wave after a gap of {rounds.MIN_GAP_DAYS}+ days):")
    for _, s in summary.iterrows():
        print(f"  {s['round']:<13} {s['first_date']} to {s['last_date']}  {s['n_submissions']:>4} submissions"
              f"  | {s['by_region']}")
    print(f"\nWritten: {rounds.BY_ROUND_DIR.relative_to(rounds.PULSE_DIR)}/<round>.xlsx, "
          f"{WAVES_CSV.relative_to(rounds.PULSE_DIR)}")
    if n_waves < len(rounds.WAVE_ORDER):
        print(f"Not in the field yet: {', '.join(rounds.WAVE_ORDER[n_waves:])}")


if __name__ == "__main__":
    main()
