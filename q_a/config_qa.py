"""
Configuration for Niger Phone Pulse quality assurance scripts.
"""

from pathlib import Path
import sys

QA_DIR = Path(__file__).parent
sys.path.insert(0, str(QA_DIR.parent / "etl_pipeline"))

# ── Paths ──────────────────────────────────────────────────────────────────────
# Round 1's submissions, split from the single export (etl_pipeline/run_round.py split)
RAW_DATA_PATH    = QA_DIR.parent / "data" / "raw_data" / "by_round" / "round1.xlsx"
REFERENCE_DATA_DIR   = QA_DIR / "reference_data"
QA_OUTPUT_DIR        = QA_DIR / "outputs"

MANUAL_FLAGS_CSV     = REFERENCE_DATA_DIR / "manual_flags.csv"
STATION_WHITELIST_CSV = REFERENCE_DATA_DIR / "station_whitelist.csv"

# ── Column names (must match real SurveyCTO schema) ────────────────────────────
COL_KEY            = "KEY"
COL_RESPONDENT_ID  = "resp_id_pull"  # roster ID pulled by form
COL_ID_ENTERED     = "id"            # ID typed by enumerator
COL_ID_REENTRY     = "id_re"         # re-typed for verification
COL_LGA            = "lga_pull"
COL_VILLAGE        = "village_pull"
COL_GENDER         = "gender_pull"
COL_DURATION       = "duration"      # total call duration (seconds)
COL_SUBMISSION_DATE = "SubmissionDate"
COL_INTERVIEW_DATE  = "interview_date"

# Radio placebo
COL_PLACEBO_STATION = "radio_placebo_pull"
COL_PLACEBO_LISTEN  = "radio_partner_placebo_listen"
COL_PLACEBO_FREQ    = "radio_partner_placebo_days-time"

# Partner station names (for context in placebo reports)
RADIO_PULL_COLS = [f"radio_pull_{i}" for i in range(1, 8)]

# Enumerator honesty indicators
COL_OVERHEARD      = "overheard_yn"   # 1 = CAN speak privately (fine); 0 = CANNOT speak privately (flag)
COL_NOTES          = "notes_enumerator"

# Section durations for per-section anomaly detection
SECTION_DURATION_COLS = {
    "fertility":  "dur_fertility",
    "fp_beh":     "dur_fpbeh",
    "fp_util":    "dur_fputil",
    "fp_view":    "dur_fpview",
    "info":       "dur_info",
    "partner":    "dur_partner",
    "radio":      "dur_radio",
    "access":     "dur_access",
    "pressure":   "dur_pressure",
    "ending":     "dur_ending",
}

# Stable demographic columns used to compare duplicate records
# (if these differ between records with same respondent ID → likely wrong ID)
STABLE_COLS = [COL_GENDER, "age", COL_LGA, COL_VILLAGE]

# Key survey answer columns used to detect inconsistency between repeat contacts
SURVEY_KEY_COLS = ["current_pregnant", "fpbeh_fpnow", "fpbeh_awarefp"]

# ── Duration thresholds ────────────────────────────────────────────────────────
DURATION_EXPECTED_SECONDS = 1500   # ~25 min
DURATION_SHORT_ERROR      = 600    # < 10 min: very suspicious
DURATION_SHORT_WARN       = 900    # < 15 min: flag for review
DURATION_LONG_WARN        = 4500   # > 75 min: flag for review
DURATION_LONG_ERROR       = 5400   # > 90 min: very suspicious
DURATION_DISCREPANCY_MAX  = 120    # max acceptable gap between reported and computed

# Minimum reasonable per-section duration (seconds)
MIN_SECTION_SECONDS = 60

# ── Enumerator note keywords ───────────────────────────────────────────────────
# HIGH: strong suggestion of compromised interview quality
NOTE_HIGH_CONCERN = [
    "overheard", "overhead", "not freely", "could not answer freely",
    "could not speak freely", "not honest", "pressured",
    "others present", "others listening", "someone else",
    "not alone", "not candid",
]
# MEDIUM: worth reviewing but may be benign
NOTE_MEDIUM_CONCERN = [
    "distracted", "background noise", "seemed nervous",
    "reluctant", "hesitant", "interrupted",
]

# ── Training data detection ────────────────────────────────────────────────────
# Set to the go-live date once known. Surveys submitted before this date
# are flagged as potential training / test data.
# Example: TRAINING_CUTOFF_DATE = "2026-01-15"
TRAINING_CUTOFF_DATE = "2026-06-10"   #
