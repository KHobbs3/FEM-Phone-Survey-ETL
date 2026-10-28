"""
Where each Phone Pulse round's files live.

run.py, export_pp_app_data.py, q_a/run_qa.py and 2_phone pulse/linkage/ were written for
round 1 and are left as they are. run_round.py (and 2_phone pulse/linkage/run_round2.py)
run those same scripts for any round listed here, pointing them at that
round's input and output paths, so a new round gets identical processing.

Round 1 paths are the ones the scripts already use, so `run_round.py etl
--round round1` writes to the same places as `run.py --keep-list ...`.
Later rounds get their own folders so nothing from round 1 is overwritten.

All rounds are in one SurveyCTO export (RAW_XLSX). `run_round.py split`
(split_rounds.py) separates it into fieldwork waves wherever submissions
stop for at least MIN_GAP_DAYS, names the waves in WAVE_ORDER, and saves
each as data/raw_data/by_round/<round_id>.xlsx (each round's raw_xlsx).
Re-run split whenever the export is updated.

Round 2 has two fieldwork waves, analysed separately:
  round2_early -- 35 respondents on Haddin Kay (Dakoro, Tagriss), which began
                  airing in mid-March, interviewed in mid-August (~5 months).
  round2       -- everyone else, at about 6 months.

Self-contained (no `import config`): 2_phone pulse/linkage imports this file, and it
has its own config.py.
"""

from pathlib import Path

PULSE_DIR = Path(__file__).resolve().parent.parent
ETL_DIR = PULSE_DIR / "etl_pipeline"
QA_DIR = PULSE_DIR / "q_a"
NIGER_ROOT = PULSE_DIR.parent
LINKAGE_OUTPUT_DIR = PULSE_DIR / "linkage" / "outputs"

ROUND1_FORM = PULSE_DIR / "meta" / "Participants+_+Appels+de+Suivi.xlsx"
CROSSWALK_DIR = PULSE_DIR / "data" / "crosswalk"
ROUND1_CROSSWALK = CROSSWALK_DIR / "Niger Phone survey - round 1 - crosswalk.csv"
QA_REVIEW_DIR = PULSE_DIR / "data" / "q_a"     # QA review files (parse step)
RAW_DATA_DIR = PULSE_DIR / "data" / "raw_data"
RAW_XLSX = RAW_DATA_DIR / "Niger  Appels de Suivi avec les Participants (haoussa)_WIDE.xlsx"
BY_ROUND_DIR = RAW_DATA_DIR / "by_round"        # written by split_rounds.py
ROUND2_QA_REVIEW = QA_REVIEW_DIR / "[WIP] Niger QA Pulse calls survey - 2nd round.csv"

# Fieldwork waves in date order -> round. A wave = submissions with no gap of
# MIN_GAP_DAYS or more between consecutive submission days.
MIN_GAP_DAYS = 14
WAVE_ORDER = ["round1", "round2_early", "round2"]


def _later_round(round_id: str, crosswalk_pattern: str) -> dict:
    """Paths for a round after round 1: its own QA / ETL folders; round 1's
    form and crosswalk unless the round's own is saved."""
    return {
        "raw_xlsx": BY_ROUND_DIR / f"{round_id}.xlsx",
        "form_path": (PULSE_DIR / "meta" / "round2", ROUND1_FORM),
        "crosswalk": (CROSSWALK_DIR, ROUND1_CROSSWALK),
        "crosswalk_pattern": crosswalk_pattern,
        "qa_review": ROUND2_QA_REVIEW,
        "keep_list": QA_DIR / "reference_data" / round_id / "keep_list.csv",
        "manual_flags": QA_DIR / "reference_data" / round_id / "manual_flags.csv",
        "training_cutoff": None,
        "qa_output_dir": QA_DIR / "outputs" / round_id,
        "etl_output_dir": ETL_DIR / "outputs" / round_id,
        # App tables go next to each round's ETL outputs; the app reads them from Drive.
        "app_data_dir": ETL_DIR / "outputs" / round_id / "app_data",
        "linked_demographics": LINKAGE_OUTPUT_DIR / "round2" / f"A_baseline_{round_id}" / "linked_demographics.csv",
    }


ROUNDS = {
    "round1": {
        "label": "Phone Pulse round 1",
        "raw_xlsx": BY_ROUND_DIR / "round1.xlsx",
        "form_path": ROUND1_FORM,
        "crosswalk": ROUND1_CROSSWALK,
        "qa_review": QA_REVIEW_DIR / "Niger QA Pulse calls survey - 1st round.csv",
        "keep_list": QA_DIR / "reference_data" / "keep_list.csv",
        "manual_flags": QA_DIR / "reference_data" / "manual_flags.csv",
        "training_cutoff": "2026-06-10",   # earlier submissions are enumerator training
        "qa_output_dir": QA_DIR / "outputs",
        "etl_output_dir": ETL_DIR / "outputs",
        "app_data_dir": ETL_DIR / "outputs" / "app_data",
        "linked_demographics": LINKAGE_OUTPUT_DIR / "linked_demographics.csv",
    },
    "round2_early": {
        "label": "Phone Pulse round 2, early group (Haddin Kay Dakoro & Tagriss)",
        **_later_round("round2_early", "*round 2*crosswalk*.csv"),
    },
    "round2": {
        "label": "Phone Pulse round 2",
        **_later_round("round2", "*round 2*crosswalk*.csv"),
    },
}
for _rid, _r in ROUNDS.items():
    _r["data_dir"] = BY_ROUND_DIR   # CSV fallback folder for extract.load_raw_data


def _resolve(value, pattern):
    """A path, or (folder, fallback): the one file matching `pattern` in folder, else fallback."""
    if not isinstance(value, tuple):
        return value
    folder, fallback = value
    found = sorted(p for p in folder.glob(pattern) if not p.name.startswith(("~$", "."))) \
        if folder.exists() else []
    if len(found) > 1:
        raise RuntimeError(f"More than one {pattern} in {folder} -- keep only the one to use.")
    return found[0] if found else fallback


def get_round(round_id: str) -> dict:
    """The round's paths, with folder lookups (form, crosswalk) resolved."""
    if round_id not in ROUNDS:
        raise KeyError(f"Unknown round {round_id!r}. Known rounds: {list(ROUNDS)}")
    r = dict(ROUNDS[round_id], round_id=round_id)
    r["form_path"] = _resolve(r["form_path"], "*.xlsx")
    r["crosswalk"] = _resolve(r["crosswalk"], r.get("crosswalk_pattern", "*crosswalk*.csv"))
    return r
