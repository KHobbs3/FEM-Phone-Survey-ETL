"""
Configuration for linking Phone Pulse (follow-up) respondents back to their
Formative Research (baseline) records, and for comparing answers between the
two waves.

IMPORTANT — nothing in this package was written by inspecting respondent-level
data. Every path and column name below was derived from *schema* sources only:
  - SurveyCTO form definitions (survey/choices sheets — question metadata, no
    answers)
  - Each pipeline's own config.py (column-name constants the pipeline authors
    already declared)
  - Pipeline notebooks' source code (not their cell outputs)

Some of this is therefore inference, not verified fact. Run
`python link_respondents.py --inspect` FIRST — it prints column names only
(never values) for all three source files — and compare that output against
the *_ID_CANDIDATES lists below before trusting a real merge.

UPDATE: the crosswalk file was later located and the join now works (92.5%
match rate — see README.md "What we found"). Two label-text encoding bugs
were also found and fixed (FORMATIVE_LABEL_TO_METHOD below) — diagnosing
those required inspecting the *distinct value set* of two formative columns
(schema-level label text, e.g. "Ee / Oui"), never a respondent-level row.
"""

from pathlib import Path

import pandas as pd

NIGER_ROOT = Path(__file__).resolve().parents[2]   # Niger/ (this file: Niger/2_phone pulse/linkage/)

# ── Survey-round registry ────────────────────────────────────────────────────
# Single source of truth for every baseline-vs-follow-up comparison (both the
# linked/longitudinal scripts in this folder and the independent-samples
# scripts under cross_sectional/), and for the Streamlit page's time series.
# To add a new round once its data exists: append a row here with
# status="live" and point its comparison scripts at the new source file(s) —
# no other structural change needed. Until then, leave status="pending"; the
# comparison scripts skip pending rounds (nothing to compute yet) and the app
# renders them as empty/upcoming points rather than fabricating data.
ROUNDS = [
    {"round_id": "round1", "label": "Round 1 (~3 mo)",  "months_since_baseline": 3,  "status": "live"},
    # The 35 respondents on Haddin Kay (Dakoro, Tagriss) interviewed in mid-August, analysed separately.
    {"round_id": "round2_early", "label": "Round 2 early group (Haddin Kay, ~5 mo)", "months_since_baseline": 5, "status": "pending"},
    {"round_id": "round2", "label": "Round 2 (~6 mo)",  "months_since_baseline": 6,  "status": "pending"},
    {"round_id": "round3", "label": "Round 3 (~24 mo)", "months_since_baseline": 24, "status": "pending"},
]
DEFAULT_ROUND_ID = "round1"


def get_round(round_id: str) -> dict:
    for r in ROUNDS:
        if r["round_id"] == round_id:
            return r
    raise KeyError(f"Unknown round_id {round_id!r}. Known rounds: "
                    f"{[r['round_id'] for r in ROUNDS]}")


def upsert_round_rows(new_rows: "pd.DataFrame", path: Path, round_id: str) -> "pd.DataFrame":
    """
    Write new_rows (stamped with a 'round' column = round_id) into the CSV at
    `path`, replacing any existing rows for this round_id while preserving
    rows already written for other rounds — so re-running a comparison
    script for round 1 doesn't clobber round 2's rows once those exist, and
    the app can read one CSV per metric with every round stacked in it for
    a time series. Returns the full merged frame (also written to disk).
    """
    new_rows = new_rows.copy()
    new_rows["round"] = round_id
    if path.exists():
        existing = pd.read_csv(path)
        existing = existing[existing.get("round") != round_id] if "round" in existing.columns \
            else existing.iloc[0:0]  # legacy pre-round file: don't try to keep it, just replace
        merged = pd.concat([existing, new_rows], ignore_index=True)
    else:
        merged = new_rows
    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False)
    return merged

# ── Data sources ─────────────────────────────────────────────────────────────

# Formative research, baseline survey. "Mapped" = codes replaced with labels
# where applicable; multiselect columns (e.g. known_contraceptive_options)
# remain as raw space-separated SurveyCTO codes.
FORMATIVE_DATA = (
    NIGER_ROOT / "1_formative_research" / "table_analysis"
    / "data" / "2_cleaned" / "fem_survey_niger_mapped.csv"
)

# Phone Pulse, follow-up survey. PII-stripped by etl_pipeline/run.py
# (see 2_phone pulse/etl_pipeline/config.py PII_COLUMNS).
PULSE_DATA = (
    NIGER_ROOT / "2_phone pulse" / "etl_pipeline" / "outputs" / "cleaned_data.csv"
)

# The roster crosswalk, found: "Niger Phone survey - round 1 - crosswalk.csv".
# Columns: ID (matches Phone Pulse's `id`/`resp_id_pull`), radio_pull_1..7
# (station assignment — same info as in cleaned_data.csv), KEY (the
# formative research SurveyCTO submission key). 533 rows, no duplicate ID
# or KEY values.
CROSSWALK_FILE = (
    NIGER_ROOT / "2_phone pulse" / "data" / "crosswalk" / "Niger Phone survey - round 1 - crosswalk.csv"
)

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
LINKED_RESPONDENTS_CSV = OUTPUT_DIR / "linked_respondents.csv"
UNLINKED_RESPONDENTS_CSV = OUTPUT_DIR / "unlinked_respondents.csv"
MATCH_REPORT_TXT = OUTPUT_DIR / "match_report.txt"

# Formative demographics for each linked Phone Pulse respondent, keyed by
# resp_id_pull (the Pulse study ID, not PII) so export_pp_app_data.py can
# join them onto its own analysis sample (QA-passed Treatment arm) and
# publish counts only. Phone Pulse never asked these questions itself.
LINKED_DEMOGRAPHICS_CSV = OUTPUT_DIR / "linked_demographics.csv"
LINKED_DEMOGRAPHIC_COLUMNS = ["age_group", "occupation", "religion", "urban_rural"]

# ── Candidate join-key columns ──────────────────────────────────────────────
# Tried in order; link_respondents.py picks whichever pairing actually
# overlaps between the two files (reports match COUNTS only, never values).

# Formative: `caseid` is SurveyCTO's stable case-management ID (present for
# exactly this kind of re-contact tracking); `KEY` is the submission key.
FORMATIVE_ID_CANDIDATES = ["caseid", "KEY", "resp_id"]

# Phone Pulse: `resp_id_pull` is documented in etl_pipeline/config.py as
# "roster ID pulled by the form" — i.e. auto-filled from a pulldata roster,
# which is exactly what a formative -> pulse crosswalk would look like.
PULSE_ID_CANDIDATES = ["resp_id_pull", "id", "id_re"]

# Column-name substrings to search for inside CROSSWALK_FILE when trying to
# find the two join keys (case-insensitive "contains" match).
CROSSWALK_FORMATIVE_ID_HINTS = ["caseid", "case_id", "key", "resp_id"]
CROSSWALK_PULSE_ID_HINTS = ["resp_id", "id_pull", "pulse", "suivi", "appel", "id"]

# Minimum fraction of Phone Pulse respondents that must match a formative
# respondent for a join strategy to be accepted. Below this, the script
# refuses to write output and asks you to fix the column names above.
MIN_MATCH_RATE = 0.10

# ── Columns kept in the linked output (analysis only — minimizes exposure) ──
# Everything not listed here is dropped after the join, regardless of what
# else is present in the source files (defense in depth on top of each
# pipeline's own PII stripping).
FORMATIVE_ANALYSIS_COLUMNS = [
    "gender", "age", "age_group", "use",
    "occupation", "religion", "urban_rural",  # respondent-profile demographics
                                              # (see LINKED_DEMOGRAPHICS_CSV)
    "known_contraceptive_options",  # raw multiselect codes, baseline FP knowledge
    "considered_use", "ever_use", "current_use",
    "current_use_methods",  # which method(s) currently used — pipe-separated
                            # bilingual label text, same vocabulary as
                            # known_contraceptive_options (see
                            # FORMATIVE_LABEL_TO_METHOD below). Used by
                            # compare_method_switching.py.
    "time_before_preferred_pregnancy",  # unmet-need comparison
                                        # (compare_unmet_need.py) — same
                                        # field niger_app's etl_family_planning.py
                                        # uses for the baseline Unmet Need &
                                        # Demand section.
    "reason_nonuse_mc",  # pipe-separated bilingual reason labels, same
                         # 59-reason list as Phone Pulse's fpbeh_whynot_* —
                         # matched option by option in compare_barriers.py
                         # (formative_whynot_codes below).
    # Baseline statements that match a Phone Pulse fpatt_* item word for word
    # -- see ATTITUDE_CROSSWALK below. Used by compare_attitudes.py.
    "statement_9", "statement_16", "statement_21", "statement_42",
    "statement_47", "statement_48", "statement_53",
]

PULSE_ANALYSIS_COLUMNS = (
    ["gender_pull", "village_pull", "lga_pull", "fpbeh_fpnow", "radio_any"]
    + [f"fpbeh_awarefp_{i}" for i in range(1, 18)]
    + [f"fpbeh_which_{i}" for i in range(1, 18)]  # which method(s) currently
                                                    # used — binary indicator
                                                    # per code (FP_METHOD_LABELS
                                                    # in export_pp_app_data.py).
                                                    # Used by
                                                    # compare_method_switching.py.
    + ["current_pregnant", "chldr_other_none_yet"]  # unmet-need comparison
                                                    # (compare_unmet_need.py) —
                                                    # same fields
                                                    # export_pp_app_data.py's
                                                    # compute_unmet_need() uses.
    + [f"fpbeh_whynot_{i}" for i in range(1, 60)]  # 59 non-use reasons, same
                                                    # list as the baseline's
                                                    # reason_nonuse_mc (WHYNOT_LABELS)
                                                    # — used by compare_barriers.py.
    + ["fpatt_steril", "fpatt_immoral_2", "fpatt_knowledge", "fpatt_dontplan",
       "fpatt_immoral", "fpatt_femresponsible", "fpatt_finance"]
    # ^ the 7 fpatt_* items with a word-for-word baseline statement — see
    # ATTITUDE_CROSSWALK below. Used by compare_attitudes.py.
)

PII_BLOCKLIST_SUBSTRINGS = [
    "name", "phone", "device", "subscriber", "simid", "username", "compensation",
]

# ── Contraceptive-method crosswalk ──────────────────────────────────────────
# The two surveys use DIFFERENT numeric codes for the same method (e.g.
# formative code 3 = "pills", pulse code 3 = "implant") — codes must never be
# compared directly. This maps each survey's own code -> a shared method name.
#
# Formative codes: 1_formative_research/niger_app/pipeline/config.py
#   CONTRACEPTIVE_METHODS
# Pulse codes: 2_phone pulse/etl_pipeline/export_pp_app_data.py FP_METHOD_LABELS

FORMATIVE_METHOD_CODES = {
    1: "Sterilisation", 2: "Implants", 3: "Oral contraceptive pills",
    4: "IUD", 5: "Injectables", 6: "Condoms", 7: "Vaginal ring",
    8: "Contraceptive patch", 9: "Vaginal barrier", 10: "Withdrawal",
    11: "Abstinence", 12: "Calendar / Rhythm", 13: "Standard Days",
    14: "Lactational Amenorrhea", 15: "Emergency contraception",
    0: "None", -22: "Other",
}

PULSE_METHOD_COLUMNS = {
    1: "fpbeh_awarefp_1",   2: "fpbeh_awarefp_2",   3: "fpbeh_awarefp_3",
    4: "fpbeh_awarefp_4",   5: "fpbeh_awarefp_5",   6: "fpbeh_awarefp_6",
    7: "fpbeh_awarefp_7",   8: "fpbeh_awarefp_8",   9: "fpbeh_awarefp_9",
    10: "fpbeh_awarefp_10", 11: "fpbeh_awarefp_11", 12: "fpbeh_awarefp_12",
    13: "fpbeh_awarefp_13", 14: "fpbeh_awarefp_14", 15: "fpbeh_awarefp_15",
    16: "fpbeh_awarefp_16", 17: "fpbeh_awarefp_17",
}

# canonical_name -> (formative codes, pulse codes) — combine sub-methods
# (e.g. male+female sterilisation/condom) into one comparable bucket.
METHOD_CROSSWALK = {
    "Sterilisation":            ([1],  [1, 2]),
    "Implant":                  ([2],  [3]),
    "Pill":                     ([3],  [6]),
    "IUD":                      ([4],  [4]),
    "Injectables":               ([5],  [5]),
    "Condom":                    ([6],  [8, 9]),
    "Vaginal ring":              ([7],  [10]),
    "Contraceptive patch":       ([8],  [17]),
    "Vaginal barrier":           ([9],  [11]),
    "Withdrawal":                 ([10], [15]),
    "Calendar / Rhythm method":  ([12], [14]),
    "Standard Days":             ([13], [12]),
    "Lactational Amenorrhea (LAM)": ([14], [13]),
    "Emergency contraception":   ([15], [7]),
    # Not comparable — no equivalent on the other side:
    #   formative "Abstinence" (11), pulse "Other traditional" (16)
}

# Modern/traditional split for METHOD_CROSSWALK's canonical names — same
# DHS/FP2020 convention used in 2_phone pulse/etl_pipeline/export_pp_app_data.py
# (MODERN_METHOD_CODES: everything except Rhythm/Calendar, Withdrawal, and
# "Other traditional"). "Other traditional" and formative's "Abstinence" have
# no cross-survey equivalent (see METHOD_CROSSWALK comment) so they're not
# classifiable here and are excluded from both sets on purpose.
TRADITIONAL_METHODS = {"Withdrawal", "Calendar / Rhythm method"}
MODERN_METHODS = set(METHOD_CROSSWALK) - TRADITIONAL_METHODS

# `known_contraceptive_options` in fem_survey_niger_mapped.csv is NOT raw
# space-separated codes (contrary to the earlier assumption below the file
# header) — it holds pipe-separated bilingual (Hausa / English) label text,
# e.g. "Allurai / Injectables|Karan damtse / Implants". Verified by
# inspecting the full distinct label set in outputs/linked_respondents.csv
# (schema-level text, not respondent data). Maps each label to the same
# canonical method name used as a METHOD_CROSSWALK key; labels with no
# pulse-side equivalent (Abstinence) or that aren't a method at all
# (I don't know / Prefer not to say / Other) are omitted on purpose.
FORMATIVE_LABEL_TO_METHOD = {
    "Méthodes permanentes / Stérilisation": "Sterilisation",
    "Karan damtse / Implants": "Implant",
    "Magungunan tsarine iyali na hadiya / Oral contraceptive pills": "Pill",
    "Na'urorin intrauterine / Intrauterine devices": "IUD",
    "Allurai / Injectables": "Injectables",
    "Kwaroron roba / Condoms": "Condom",
    "Zoben farji / Vaginal ring": "Vaginal ring",
    "Facin sa tazara / Contraceptive patch": "Contraceptive patch",
    "Hanyoyin shingen farji (ciki har da diaphragm, hular mahaifa da magungunan ) / "
    "Vaginal barrier methods (including the diaphragm, cervical cap and spermicidal agents)": "Vaginal barrier",
    "Janyewa / Withdrawal": "Withdrawal",
    "Kalanda/Rhythm / Calendar/Rhythm": "Calendar / Rhythm method",
    "Tsarin kilga kwanaki (Tsakia ) / Standard Days Method (bead necklace)": "Standard Days",
    "Tsarin bada nonon uwa  / Lactational Amenorrhea Method": "Lactational Amenorrhea (LAM)",
    "Magungunan rigakafin gaggawa / Emergency contraceptive pills": "Emergency contraception",
    # Not mapped on purpose (no pulse-side equivalent / not a method):
    #   "Kauracewa / Abstinence", "Ban sani ba / I dont know",
    #   "Na fi son inyi shiru / Prefer not to say", "Wasu daban / Other"
}

# ── Attitudes crosswalk (compare_attitudes.py) ──────────────────────────────
# Seven of Phone Pulse's 8 fpatt_* items are word-for-word copies of baseline
# general statements (checked against the deployed Hausa phone form,
# 2_phone pulse/meta/Niger+_+Appels+de+Suivi+avec+les+Participants+(hau).xlsx,
# and the baseline XLSForm). Every baseline respondent was asked all 62
# statements (statement_50 women only) -- not a random subset. fpatt_childinvest
# ("Longer spacing ... supports children's growth") has no baseline match.
#
# Answer scales still differ: baseline is Agree / Disagree (plus DK / PNS);
# Phone Pulse is 0-4 with a neutral midpoint (2). Both are binarized to
# "agrees with the statement" = Agree (baseline) / score >= 3 (pulse), so a
# phone "neutral" counts as not agreeing -- read changes as directional.
#
# Each entry: item label (the statement itself) -> (formative statement
# column, pulse fpatt_* column, formative_agree_polarity). Polarity is True
# for every pair because the wording is identical: "holds the view" means
# agreeing with the statement as written. Agreeing is the FP-favourable view
# only for "does not encourage promiscuity"; for the other six it is the
# unfavourable view -- check the label before reading a rise as good or bad.
ATTITUDE_CROSSWALK = {
    "Contraceptives can stop a woman from ever conceiving again": (
        "statement_21", "fpatt_steril", True),
    "Contraceptive use does not encourage promiscuity": (
        "statement_48", "fpatt_immoral_2", True),
    "I don't think I have enough information to use contraceptives properly": (
        "statement_9", "fpatt_knowledge", True),
    "A woman must give birth to all the children that are in her body": (
        "statement_47", "fpatt_dontplan", True),
    "Religious leaders I admire do not use or encourage contraception": (
        "statement_42", "fpatt_immoral", True),
    "My spouse needs to approve in order for me to use contraception": (
        "statement_53", "fpatt_femresponsible", True),
    "Having many children is important because they bring benefits to the family": (
        "statement_16", "fpatt_finance", True),
}

# Formative statement Agree/Disagree text (bilingual, same convention as
# FORMATIVE_LABEL_TO_METHOD above).
STATEMENT_AGREE_TEXT = "Yarda / Agree"
STATEMENT_DISAGREE_TEXT = "Ban yarda ba / Disagree"

# ── Barriers / reasons-for-non-use crosswalk (compare_barriers.py) ─────────
# Both surveys use the SAME 59-reason list, so reasons are matched option by
# option, not by keyword. Formative: `reason_nonuse_mc`, pipe-separated
# bilingual label text ("Hausa / English"), asked of those who never used or
# didn't use in the last six months. Phone Pulse: `fpbeh_whynot_1..59` (list
# fp_whynot_v2), one 0/1 column per reason, asked of current non-users. Both
# unprompted (the enumerator ticks what the respondent says). The labels and
# their groups (the form's own headings, e.g. "Fear of side effects") live in
# 2_phone pulse/etl_pipeline/export_pp_app_data.py and are imported here.
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(NIGER_ROOT / "2_phone pulse" / "etl_pipeline"))
from export_pp_app_data import WHYNOT_LABELS, WHYNOT_GROUPS  # noqa: E402

PULSE_WHYNOT_COLUMNS = [f"fpbeh_whynot_{code}" for code in WHYNOT_LABELS]


def _norm_label(text: str) -> str:
    return " ".join(str(text).replace("\u2019", "'").lower().split()).rstrip(".")


_WHYNOT_CODE_BY_LABEL = {_norm_label(label): code for code, label in WHYNOT_LABELS.items()}


def formative_whynot_codes(cell) -> tuple[set[int], list[str]]:
    """Parse one reason_nonuse_mc cell into the set of fp_whynot_v2 codes it
    names, plus the English text of any token that matched no reason (don't
    know / prefer not to say / other, or a wording mismatch worth checking)."""
    if pd.isna(cell) or str(cell).strip() == "":
        return set(), []
    codes, unmatched = set(), []
    for tok in str(cell).split("|"):
        tok = tok.strip()
        english = tok.split(" / ")[-1] if " / " in tok else tok
        code = _WHYNOT_CODE_BY_LABEL.get(_norm_label(english))
        if code is None:
            unmatched.append(english)
        else:
            codes.add(code)
    return codes, unmatched


def whynot_items() -> list[tuple[str, str, set[int]]]:
    """(level, label, codes) for every comparison row: one per reason group
    (cited = any reason in the group), then one per reason."""
    groups = {}
    for code, group in WHYNOT_GROUPS.items():
        groups.setdefault(group, set()).add(code)
    return ([("group", g, codes) for g, codes in groups.items()]
            + [("reason", label, {code}) for code, label in WHYNOT_LABELS.items()])
