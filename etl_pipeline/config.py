"""
Central configuration for the Niger Phone Pulse ETL pipeline.
Column names reflect the real SurveyCTO form schema.
"""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
# Round 1's submissions, split from the single export by split_rounds.py
# (run_round.py split); rounds.py has the other rounds'. QA review files are in data/q_a/.
RAW_DATA_DIR = DATA_DIR / "raw_data" / "by_round"
RAW_XLSX = RAW_DATA_DIR / "round1.xlsx"
OUTPUT_DIR = Path(__file__).parent / "outputs"
STATS_DIR = OUTPUT_DIR / "stats"

# ── "Other (specify)" recoding (other_recodes.py) ─────────────────────────────
# Select question with an "Other" (-22) choice -> the text field holding its
# write-in (from the form's relevance, e.g. selected(${fpbeh_whynot}, '-22')).
OTHER_RECODE_QUESTIONS = {
    "fpbeh_whynot":        "fpbeh_usedfp_oth",
    "fputil_advs":         "fputil_advs_oth",
    "fputil_disadvs":      "fputil_disadvs_oth",
    "method_notavailable": "other_methodunavailable",
    "oth_infsource":       "other_source",
}
# SurveyCTO form definition: write-ins are matched against its choice labels.
FORM_PATH = ROOT_DIR / "meta" / "Participants+_+Appels+de+Suivi.xlsx"
# The recodes file run_round.py refreshes (--fuzzy) and applies. It holds free
# text, so it lives with the data. Shared by all rounds: codes carry over.
OTHER_RECODES_PATH = DATA_DIR / "other_recodes" / "other_recodes.csv"
# Answer labels per question, as a reference for hand-coding recode_to.
OTHER_RECODE_CHOICES = DATA_DIR / "other_recodes" / "other_recode_choices.csv"

# ── Key column names ───────────────────────────────────────────────────────────
# Respondent identity
COL_KEY           = "KEY"
COL_RESPONDENT_ID = "resp_id_pull"   # roster ID pulled by the form
COL_ID_ENTERED    = "id"             # ID typed by enumerator
COL_ID_REENTRY    = "id_re"          # re-typed ID (for verification)
COL_LGA           = "lga_pull"
COL_VILLAGE       = "village_pull"
COL_GENDER        = "gender_pull"
COL_DURATION      = "duration"
COL_OVERHEARD     = "overheard_yn"   # 1 = respondent was overheard

# Radio placebo
COL_PLACEBO_NAME  = "radio_placebo_pull"
COL_PLACEBO_LISTEN = "radio_partner_placebo_listen"

# ── PII columns to drop before any output ─────────────────────────────────────
PII_COLUMNS = [
    "deviceid",              # device-level hardware ID
    "subscriberid",          # SIM subscriber ID
    "simid",                 # SIM card ID
    "devicephonenum",        # enumerator device phone number
    "username",              # SurveyCTO system login
    "name_pull",             # respondent name from sampling roster
    "correct_name",          # corrected respondent name
    "incentive_phonenumber", # respondent phone for airtime compensation
    "incentive_fullname",    # respondent name for airtime compensation
    "futurenumber",          # respondent phone for future-round calls
    "futurenumber_2",        # respondent alternate phone for future-round calls
]

# ── Sentinel / special response codes ─────────────────────────────────────────
SENTINEL_MAP = {
    -99: "dont_know_refused",
    -88: "not_applicable",
    -22: "other_specify",
}

# ── Survey duration thresholds (seconds) ──────────────────────────────────────
# Expected average: ~25 min = 1500s
MIN_DURATION_SECONDS = 600   # < 10 min → suspiciously short
MAX_DURATION_SECONDS = 5400  # > 90 min → suspiciously long
DURATION_DISCREPANCY_THRESHOLD = 120  # max gap between reported and computed

# Minimum reasonable duration per section (seconds)
MIN_SECTION_DURATION = 60   # a section under 1 min was likely skipped/rushed

# ── Multi-select parent columns ────────────────────────────────────────────────
# These hold space-separated option codes; individual binary sub-columns
# (e.g. fpbeh_awarefp_1 … fpbeh_awarefp_17) are auto-detected as binary.
MULTISELECT_COLUMNS = [
    "fpbeh_awarefp",    # FP methods awareness
    "fpbeh_whynot",     # reasons for not using FP
    "fpbeh_which",      # FP method currently using
    "fputil_advs",      # perceived advantages of FP
    "fputil_disadvs",   # perceived disadvantages of FP
    "Device",           # radio device types
    "radio_days",       # days of radio listening
    "uptake_topics",    # topics heard on radio
    "oth_infsource",    # sources of health information
    "contraceptives_location",  # where contraceptives obtained
    "confirm_correct",  # which roster fields are incorrect
]

# ── Likert-style attitude columns (1–5 scale) ──────────────────────────────────
LIKERT_COLUMNS = [
    # Self attitudes
    "fpatt_immoral",         "fpatt_immoral_2",
    "fpatt_dontplan",        "fpatt_femresponsible",
    "fpatt_finance",         "fpatt_childinvest",
    "fpatt_steril",          "fpatt_knowledge",
    # Spouse perceptions
    "fpatt_immoral_spouse",  "fpatt_immoral_2_spouse",
    "fpatt_dontplan_spouse", "fpatt_femresponsible_spouse",
    "fpatt_finance_spouse",  "fpatt_childinvest_spouse",
    "fpatt_steril_spouse",   "fpatt_knowledge_spouse",
    # Community perceptions
    "fpatt_immoral_commu",   "fpatt_immoral_2_commu",
    "fpatt_dontplan_commu",  "fpatt_femresponsible_commu",
    "fpatt_finance_commu",   "fpatt_childinvest_commu",
    "fpatt_steril_commu",    "fpatt_knowledge_commu",
    # Knowledge / beliefs
    "info_newpregnancy", "info_likely_infertile",
    "info_likely_mcycle", "knowledge_waiting",
    # Partner / community norms
    "partner_talk_fp_time", "partner_pressure",
    "pressure_pnorm", "pressure_discuss",
    "oth_religiousinfluence",
    # Recall / engagement
    "freq_feeling", "already-listen",
]

# ── Binary (0/1) columns ───────────────────────────────────────────────────────
BINARY_COLUMNS = [
    # Interview logistics
    "approuval", "overheard_yn", "confirm_info",
    # Fertility
    "current_pregnant",
    # FP behaviour
    "fpbeh_fpnow", "fptutil_any",
    # Media
    "radio_any", "tv_any", "social_any",
    "uptake_fp", "uptake_fp_tv", "uptake_fp_social",
    "uptake_discuss",
    # Radio station listening (partner stations 1–7 + placebo)
    "radio_partner_1_listen", "radio_partner_2_listen", "radio_partner_3_listen",
    "radio_partner_4_listen", "radio_partner_5_listen", "radio_partner_6_listen",
    "radio_partner_7_listen", "radio_partner_placebo_listen",
    # Access
    "lastspoke_try", "lastspoke_healthvisit",
    "got_wanted_method", "method_notavailable",
    # Consent
    "futurecalls",
    # FP method awareness (binary indicators per method)
    "fpbeh_awarefp_1",  "fpbeh_awarefp_2",  "fpbeh_awarefp_3",
    "fpbeh_awarefp_4",  "fpbeh_awarefp_5",  "fpbeh_awarefp_6",
    "fpbeh_awarefp_7",  "fpbeh_awarefp_8",  "fpbeh_awarefp_9",
    "fpbeh_awarefp_10", "fpbeh_awarefp_11", "fpbeh_awarefp_12",
    "fpbeh_awarefp_13", "fpbeh_awarefp_14", "fpbeh_awarefp_15",
    "fpbeh_awarefp_16", "fpbeh_awarefp_17",
    # FP method currently using (binary indicators)
    "fpbeh_which_1",  "fpbeh_which_2",  "fpbeh_which_3",
    "fpbeh_which_4",  "fpbeh_which_5",  "fpbeh_which_6",
    "fpbeh_which_7",  "fpbeh_which_8",  "fpbeh_which_9",
    "fpbeh_which_10", "fpbeh_which_11", "fpbeh_which_12",
    "fpbeh_which_13", "fpbeh_which_14", "fpbeh_which_15",
    "fpbeh_which_16", "fpbeh_which_17",
    # Radio days (binary per day)
    "radio_days_1", "radio_days_2", "radio_days_3", "radio_days_4",
    "radio_days_5", "radio_days_6", "radio_days_7",
]

# ── Continuous numeric columns ─────────────────────────────────────────────────
NUMERIC_CONTINUOUS_COLUMNS = [
    # Total call
    "duration",
    # Section durations (seconds)
    "dur_fertility", "dur_fpbeh", "dur_fputil", "dur_fpview",
    "dur_info", "dur_partner", "dur_radio", "dur_access",
    "dur_pressure", "dur_ending",
    # Media
    "radio_hours", "distance_facility",
    # Frequency of hearing FP content per station
    "uptake_fp_freq_radio_1", "uptake_fp_freq_radio_2", "uptake_fp_freq_radio_3",
    "uptake_fp_freq_radio_4", "uptake_fp_freq_radio_5", "uptake_fp_freq_radio_6",
    "uptake_fp_freq_radio_7", "uptake_fp_freq_radio_placebo",
    # Days-time per station (ordinal but treat as numeric)
    "radio_partner_1_days-time", "radio_partner_2_days-time",
    "radio_partner_3_days-time", "radio_partner_4_days-time",
    "radio_partner_5_days-time", "radio_partner_6_days-time",
    "radio_partner_7_days-time", "radio_partner_placebo_days-time",
]

# ── Ordinal / categorical columns ──────────────────────────────────────────────
ORDINAL_COLUMNS = [
    "fpbeh_pregchance",       # pregnancy likelihood
    "chldr_other_none_yet",   # wants more children / none yet
    "chldr_many",             # number of additional children desired
    "partner_talk_fp_time",   # when last discussed FP with partner
]

# ── Demographic / descriptive columns ─────────────────────────────────────────
DEMOGRAPHIC_COLUMNS = ["gender_pull", "age"]

# ── Columns to skip in statistical output ─────────────────────────────────────
# Sentinel indicator sub-columns (e.g. fpbeh_awarefp__99) and operational fields.
# Pattern-matched skipping (columns ending in __99, __88, __22) is handled in stats.py.
SKIP_STATS_COLUMNS = [
    # Identifiers
    "KEY", "caseid", "instanceID", "formdef_version", "svy_name_v2",
    # Timestamps
    "SubmissionDate", "starttime", "endtime",
    "start_fertility", "end_fertility",
    "start_fpbeh",    "end_fpbeh",
    "start_fputil",   "end_fputil",
    "start_fpview",   "end_fpview",
    "start_info",     "end_info",
    "start_partner",  "end_partner",
    "start_radio",    "end_radio",
    "start_access",   "end_access",
    "start_pressure", "end_pressure",
    "start_ending",   "end_ending",
    # Dates
    "edd",
    # Operational / text
    "callback", "notes_enumerator",
    "fpbeh_usedfp_oth", "fputil_advs_oth", "fputil_disadvs_oth",
    "other_methodunavailable", "other_source",
    # Roster corrections (text)
    "correct_ward", "correct_village",
    # Station name text fields
    "radio_pull_1", "radio_pull_2", "radio_pull_3", "radio_pull_4",
    "radio_pull_5",  "radio_pull_6", "radio_pull_7",
    "radio_placebo_pull",
    # Computed QA columns added by pipeline
    "computed_duration_seconds", "duration_discrepancy_seconds",
    # Source tracking
    "_source_file",
]
