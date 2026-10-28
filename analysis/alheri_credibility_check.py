"""
Credibility check: respondents reporting FP content heard on Radio Alheri.

Context (from the project team, not derivable from the data): Alheri refused
to carry FEM's FP programming/ads, so — unlike the other FEM partner
stations — NO respondent should be able to truthfully report having heard FP
programs/ads on Alheri. Any respondent who does is either confusing Alheri
with another station, mis-answering, or not answering honestly.

Question used: uptake_fp_freq_radio_N ("How frequently have you heard these
programs or ads in the last few months on <station>?"), scored on
FREQUENCY_LABELS (0=Never .. 5=Several times a day), asked per assigned
station slot (radio_pull_1..7 + the placebo slot). A respondent's station
assignment is per-respondent (radio_pull_3 is a different real station for
different people), so identifying "the Alheri row" requires resolving each
respondent's station-name slots by NAME, not by slot number.

This reuses etl_pipeline/export_pp_app_data.py's existing station-name
resolution and long-format melt (melt_station_slots) rather than
reimplementing the fuzzy-matching/alias logic a second time.

Two checks:
  1. Station-level context: is Alheri's "heard FP content" rate unusual
     compared to genuine partner stations (which DID carry FP content, so
     some recall is expected there)? If Alheri's rate looks similar to (or
     not clearly lower than) real stations, that suggests respondents may be
     answering per-station recall questions somewhat randomly / by habit
     rather than from genuine memory — a credibility flag for the whole
     battery, not just Alheri.
  2. Respondent-level export: everyone who reports uptake_fp_freq_radio_N > 0
     ("Never") for their Alheri slot, alongside their own answer pattern for
     their OTHER assigned stations, so a reviewer can judge whether this
     looks like an isolated, specific false-positive (suspicious) or part of
     a broader straightlining pattern (a different, more general honesty
     concern already partly covered by q_a/check_anomalies.py).

Outputs (analysis/outputs/):
  station_fp_recall_rates.csv         — all stations, for context/comparison
  alheri_incongruent_respondents.csv  — respondent-level detail, for review
No names or other PII are included (cleaned_data.csv is already PII-stripped
by the ETL pipeline; only geographic/roster fields are retained, matching
etl_pipeline/README.md's PII policy).
"""

import sys
from pathlib import Path

import pandas as pd

ANALYSIS_DIR = Path(__file__).parent
PHONE_PULSE_DIR = ANALYSIS_DIR.parent
sys.path.insert(0, str(PHONE_PULSE_DIR / "etl_pipeline"))
from export_pp_app_data import melt_station_slots  # noqa: E402

CLEANED_DATA = PHONE_PULSE_DIR / "etl_pipeline" / "outputs" / "cleaned_data.csv"
OUTPUT_DIR = ANALYSIS_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

ALHERI_CANONICAL = "Alheri_Maradi"
RESP_ID_COLS = ["resp_id_pull", "id", "KEY", "lga_pull", "village_pull", "gender_pull"]


def main():
    df = pd.read_csv(CLEANED_DATA, low_memory=False)
    extra_cols = [c for c in RESP_ID_COLS if c in df.columns]
    melted = melt_station_slots(df, extra_cols=extra_cols)
    melted["listened"] = pd.to_numeric(melted["listened"], errors="coerce")
    melted["fp_content_frequency"] = pd.to_numeric(melted["fp_content_frequency"], errors="coerce")
    melted["heard_fp_content"] = melted["fp_content_frequency"] > 0

    # ── 1. Station-level context table ──────────────────────────────────────
    def _station_stats(g: pd.DataFrame) -> pd.Series:
        n_assigned = len(g)
        listeners = g[g["listened"] == 1]
        n_listeners = len(listeners)
        n_heard_fp = int(listeners["heard_fp_content"].sum())
        return pd.Series({
            "n_assigned": n_assigned,
            "n_listeners": n_listeners,
            "pct_listened": round(100 * n_listeners / n_assigned, 1) if n_assigned else float("nan"),
            "n_listeners_reporting_fp_content": n_heard_fp,
            "pct_of_listeners_reporting_fp_content": (
                round(100 * n_heard_fp / n_listeners, 1) if n_listeners else float("nan")
            ),
        })

    station_stats = (
        melted.groupby("station", dropna=False).apply(_station_stats, include_groups=False)
        .reset_index()
        .sort_values("pct_of_listeners_reporting_fp_content", ascending=False)
    )
    station_stats["is_alheri"] = station_stats["station"] == ALHERI_CANONICAL
    real_station_rate = station_stats.loc[
        ~station_stats["is_alheri"] & ~station_stats["station"].str.contains(r"\(placebo\)", na=False),
        "pct_of_listeners_reporting_fp_content",
    ]
    station_path = OUTPUT_DIR / "station_fp_recall_rates.csv"
    station_stats.to_csv(station_path, index=False)

    alheri_row = station_stats[station_stats["is_alheri"]]
    alheri_rate = float(alheri_row["pct_of_listeners_reporting_fp_content"].iloc[0]) if len(alheri_row) else float("nan")

    print("=" * 78)
    print("STATION-LEVEL CONTEXT: % of listeners reporting FP content heard")
    print("=" * 78)
    print(station_stats.to_string(index=False))
    print(f"\nAlheri (never carried FEM FP content): {alheri_rate}% of self-reported "
          f"listeners still report hearing FP content on it.")
    if len(real_station_rate):
        print(f"Genuine partner stations (which DID carry content), median rate: "
              f"{real_station_rate.median():.1f}%, range {real_station_rate.min():.1f}"
              f"-{real_station_rate.max():.1f}%.")
        if pd.notna(alheri_rate) and alheri_rate >= real_station_rate.median():
            print("=> Alheri's rate is AT OR ABOVE the typical genuine-station rate — "
                  "consistent with respondents answering per-station recall somewhat "
                  "indiscriminately rather than from specific memory. Treat other "
                  "stations' recall numbers with the same caution, not just Alheri's.")
        else:
            print("=> Alheri's rate is below the typical genuine-station rate — closer "
                  "to what you'd expect for a station that carried no content, though "
                  "still not zero. See the respondent-level export for the individual "
                  "cases.")

    # ── 2. Respondent-level incongruence export ─────────────────────────────
    id_col = next((c for c in ("resp_id_pull", "id") if c in melted.columns), None)
    alheri = melted[melted["station"] == ALHERI_CANONICAL].copy()
    incongruent = alheri[alheri["heard_fp_content"] == True].copy()  # noqa: E712

    rows = []
    for _, r in incongruent.iterrows():
        rid = r.get(id_col)
        others = melted[(melted[id_col] == rid) & (melted["station"] != ALHERI_CANONICAL)]
        other_listened = others[others["listened"] == 1]
        n_other_listened = len(other_listened)
        n_other_heard_fp = int(other_listened["heard_fp_content"].sum())
        row = {c: r.get(c) for c in extra_cols}
        row.update({
            "alheri_slot_is_placebo": bool(r["is_placebo"]),
            "alheri_listened": r["listened"],
            "alheri_fp_content_frequency_value": r["fp_content_frequency"],
            "n_other_assigned_stations": len(others),
            "n_other_stations_listened": n_other_listened,
            "n_other_stations_reporting_fp_content": n_other_heard_fp,
            "pct_other_stations_reporting_fp_content": (
                round(100 * n_other_heard_fp / n_other_listened, 1) if n_other_listened else None
            ),
            "straightlines_fp_content_all_stations": (
                n_other_listened > 0 and n_other_heard_fp == n_other_listened
            ),
        })
        rows.append(row)

    incongruent_report = pd.DataFrame(rows)
    if not incongruent_report.empty:
        incongruent_report = incongruent_report.sort_values(
            "pct_other_stations_reporting_fp_content", ascending=True, na_position="first"
        )
    detail_path = OUTPUT_DIR / "alheri_incongruent_respondents.csv"
    incongruent_report.to_csv(detail_path, index=False)

    n_assigned_alheri = len(alheri)
    n_listen_alheri = int((alheri["listened"] == 1).sum())
    print(f"\n{'=' * 78}")
    print("RESPONDENT-LEVEL: Alheri FP-content-recall incongruence")
    print("=" * 78)
    print(f"Respondents assigned Alheri (real or placebo slot): {n_assigned_alheri}")
    print(f"  of whom claim to listen to Alheri at all:          {n_listen_alheri}")
    print(f"  reporting having heard FP content on Alheri:       {len(incongruent_report)}  "
          f"<- exported for review, impossible per project team (Alheri carried no FEM content)")
    if not incongruent_report.empty:
        n_isolated = int((incongruent_report["pct_other_stations_reporting_fp_content"].fillna(0) == 0).sum())
        n_straightline = int(incongruent_report["straightlines_fp_content_all_stations"].sum())
        print(f"    - isolated to Alheri only (0% recall on their other stations): {n_isolated}")
        print(f"    - part of a straightlined pattern (FP content 'heard' on every "
              f"assigned station): {n_straightline}")
    print(f"\nWritten: {station_path}")
    print(f"Written: {detail_path}")


if __name__ == "__main__":
    main()
