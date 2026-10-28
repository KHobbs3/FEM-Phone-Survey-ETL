"""
Export pre-aggregated, PII-free summary tables for the Phone Pulse Streamlit app.

Input:  etl_pipeline/outputs/cleaned_data.csv  (keep-group, PII already stripped)
Outputs (all written to etl_pipeline/outputs/app_data/; upload to Drive for the app):
  pp_respondents_profile.csv   — demographics + FP use + radio + unmet need proxy
  pp_fp_awareness.csv          — method awareness by fp-use group
  pp_fp_method_used.csv        — method currently used (fp users only)
  pp_fp_whynot.csv             — reasons for non-use by fp-use group (each of the
                                  59 reasons, plus one row per reason group: `level`)
  pp_fp_preg_chance.csv        — perceived pregnancy chance by fp-use group
  pp_attitudes.csv             — attitude item means by fp-use group
  pp_info_perceptions.csv      — fertility-return / FP-myth / program-message
                                  knowledge items by fp-use group (Pulse-only,
                                  no formative baseline equivalent)
  pp_radio_any.csv             — radio listenership by fp-use group
  pp_radio_hours.csv           — hours per day by fp-use group
  pp_radio_days.csv            — days per week by fp-use group
  pp_radio_uptake.csv          — heard FP content on radio by fp-use group
  pp_radio_stations.csv        — individual station listenership by fp-use group
  pp_radio_fp_stations.csv     — individual station "heard FP content at all" by fp-use group
  pp_partner_decision.csv      — FP decision-making by fp-use group
  pp_partner_norms.csv         — social norm mean scores by fp-use group
  pp_partner_discuss.csv       — FP discussion norms by fp-use group

Analysis population
--------------------
Every table above is restricted to respondents who reported listening to at
least one FEM partner radio station (see FEM_PARTNER_STATIONS below).
Respondents who never listened to a partner station (e.g. placebo-only
listeners, or non-listeners) are excluded from ALL exports. The full
interviewed count and the partner-listener count are both reported as
context rows in pp_respondents_profile.csv.

Run after run.py --keep-list to refresh:
    python export_pp_app_data.py
"""

from pathlib import Path
import pandas as pd
import numpy as np

CLEANED_DATA = Path(__file__).parent / "outputs" / "cleaned_data.csv"
POPULATION_SUMMARY = Path(__file__).parent / "outputs" / "population_summary.csv"
# Formative-baseline demographics per linked Pulse respondent (resp_id_pull),
# written by 2_phone pulse/linkage/link_respondents.py. Pulse didn't ask age, occupation,
# religion or settlement type, so the respondents profile takes them from here.
LINKED_DEMOGRAPHICS = (
    Path(__file__).parent.parent
    / "linkage" / "outputs" / "linked_demographics.csv"
)
LINKED_DEMOGRAPHIC_VARS = ["age_group", "occupation", "religion", "urban_rural"]
APP_DATA_DIR = Path(__file__).parent / "outputs" / "app_data"
VILLAGE_MIN_N = 5   # suppress villages smaller than this

# ── Scale / label maps ────────────────────────────────────────────────────────

AGREE_LABELS = {
    0.0: "Strongly disagree", 1.0: "Disagree",
    2.0: "Neither", 3.0: "Agree", 4.0: "Strongly agree",
}
PREG_CHANCE_LABELS = {
    1.0: "Very likely", 2.0: "Somewhat likely", 3.0: "Neither",
    4.0: "Unlikely", 5.0: "Very unlikely",
}
FP_DECISION_LABELS = {
    1.0: "Mainly respondent", 2.0: "Mainly spouse",
    3.0: "Joint decision",    4.0: "Other / not applicable",
}
YESNO_LABELS = {1.0: "Yes", 0.0: "No"}

# fpbeh_whynot uses the deployed form's fp_whynot_v2 list (59 reasons, English
# half of each label; 2_phone pulse/meta/...(hau).xlsx) -- the same list as the
# baseline's reason_nonuse_mc. -22 / -88 / -99 (other / don't know / prefer not
# to say) are not reasons and are left out. 2_phone pulse/linkage/config.py imports these.
WHYNOT_LABELS = {
    1: "Lack of funding to access contraceptives: the products are too expensive",
    2: "Lack of funding to access contraceptives: Unspecified",
    3: "Lack of access: the health center is too far away",
    4: "Lack of knowledge: Don't know how to choose a suitable method",
    5: "Lack of knowledge: Don't know the benefits",
    6: "Lack of knowledge: Don't know the method options",
    7: "Lack of knowledge: Don't know where and how to access",
    8: "Lack of knowledge: Unspecified",
    9: "Desire to have children: New couple seeking first child(ren)",
    10: "Desire to have children: I see children as an achievement",
    11: "Desire to have children: Competition among co-wives",
    12: "Desire to have children: Not done with childbearing",
    13: "Desire to have children: We want to replace a child who passed away",
    14: "Desire to have children: We seek a specific gender",
    15: "Desire to have children: We benefit from having more children",
    16: "Desire to have more children: Unspecified",
    17: "Fear of side effects: Fear of changes in bleeding pattern",
    18: "Fear of side effects: Fear of increase in bleeding",
    19: "Fear of side effects: Fear of painful period",
    20: "Fear of side effects: Fear of infertility",
    21: "Fear of side effects: Fear of weight gain",
    22: "Fear of side effects: Fear of weight loss",
    23: "Fear of side effects: Fear of birth complications",
    24: "Fear of side effects: Fear of condom getting lost in the body",
    25: "Fear of side effects: Fear of death",
    26: "Fear of side effects: Fear of cancer",
    27: "Fear of side effects: Fear of cardiac arrest",
    28: "Fear of side effects: Fear of dizziness and headache",
    29: "Fear of side effects: Fear of IUD/ implant moving around or sticking to the body",
    30: "Fear of side effects: Fear of swelling/inflammation",
    31: "Fear of side effects: Fear of tiredness",
    32: "Fear of side effects: Phobia of drugs or anything foreign in the body",
    33: "Fear of side effects: Fear of dryness",
    34: "Fear of side effects: Fear of the development of pimples",
    35: "Fear of side effects: Fear of infections when urinating in dirty places",
    36: "Fear of side effects: Womb weakness",
    37: "Fear of side effects: Fear of reduced pleasure due to condom use",
    38: "Fear of side effects: Unspecified",
    39: "Fear of privacy invasion",
    40: "Against religion: my religion does not allow childbirth spacing",
    41: "Against religion: some religious role models did not use contraception",
    42: "Against religion: only God decides on childbirth spacing",
    43: "Against religion: God will take good care of all my children",
    44: "Against religion: Unspecified",
    45: "Use of non-effective traditional contraception (plants, traditional medicine, etc)",
    46: "Need to birth all children out of the body",
    47: "Associating contraceptives with promiscuity",
    48: "Stigma",
    49: "Family disapproves: Husband disapproves",
    50: "Family disapproves: Parents disapprove",
    51: "Family disapproves: Siblings disapprove",
    52: "Family disapproves: Spouse's family disapproves",
    53: "Doubts about contraceptive effectiveness",
    54: "Experience of body spacing births itself",
    55: "Not using contraceptives while breastfeeding",
    56: "My wife/I recently gave birth and I don't have my menstruation back yet",
    57: "My wife/I am menopaused",
    58: "Not sexually active",
    59: "It is not important",
}


def whynot_group(code: int) -> str:
    """The form's own heading for a reason (the text before ':'), so e.g. the
    22 "Fear of side effects: ..." reasons roll up to one row. Reasons without
    a heading are their own group."""
    label = WHYNOT_LABELS[code]
    if code == 16:   # "Desire to have MORE children: Unspecified"
        return "Desire to have children"
    if code in (1, 2):
        return "Lack of funding"
    return label.split(":")[0] if ":" in label else label


WHYNOT_GROUPS = {code: whynot_group(code) for code in WHYNOT_LABELS}

FP_METHOD_LABELS = {
    1.0:  "Female sterilisation",   2.0:  "Male sterilisation",
    3.0:  "Implant",                4.0:  "IUD",
    5.0:  "Injectables",            6.0:  "Pill",
    7.0:  "Emergency contraception",8.0:  "Male condom",
    9.0:  "Female condom",          10.0: "Vaginal ring",
    11.0: "Vaginal barrier",        12.0: "Standard days / cycle beads",
    13.0: "LAM",                    14.0: "Rhythm method",
    15.0: "Withdrawal",             16.0: "Other traditional",
    17.0: "Contraceptive patch",
}

# Statement wording from the deployed Hausa form (2_phone pulse/meta/
# Niger+_+Appels+de+Suivi+avec+les+Participants+(hau).xlsx), not the English draft.
ATTITUDE_LABELS = {
    "fpatt_immoral":        "Religious leaders I admire do not use or encourage contraception",
    "fpatt_immoral_2":      "Contraceptive use does not encourage promiscuity",
    "fpatt_dontplan":       "A woman must give birth to all the children in her body",
    "fpatt_femresponsible": "My spouse needs to approve for me to use contraception",
    "fpatt_finance":        "Having many children is important (they benefit the family)",
    "fpatt_childinvest":    "Longer spacing gives more time and resources for children's growth",
    "fpatt_steril":         "Contraceptives can stop a woman from ever conceiving again",
    "fpatt_knowledge":      "I don't think I have enough information to use contraceptives properly",
}

DAY_LABELS = {
    "radio_days_1": "Monday",    "radio_days_2": "Tuesday",
    "radio_days_3": "Wednesday", "radio_days_4": "Thursday",
    "radio_days_5": "Friday",    "radio_days_6": "Saturday",
    "radio_days_7": "Sunday",
}

SKIP_CODES = {-88.0, -99.0, 88.0, 99.0}

# ── Media / access / social-pressure label maps ─────────────────────────────────

TOPICS_LABELS = {
    1.0: "News", 2.0: "Health", 3.0: "Education", 4.0: "Sports",
    5.0: "Celebrities & entertainment", 6.0: "Music", 7.0: "Travel",
    8.0: "Food & drink", 9.0: "Culture", 10.0: "Crime", 11.0: "Lifestyle",
    12.0: "Politics", 13.0: "Games / competition", 14.0: "Chat shows",
    16.0: "Drama",
}

RADIO_DEVICE_LABELS = {
    1.0: "Own radio", 2.0: "Cellphone (via social media)",
    3.0: "Cellphone (as a radio)", 4.0: "Someone else's radio",
    5.0: "Someone else's cellphone", 6.0: "Public space",
}

FREQUENCY_LABELS = {
    0.0: "Never", 1.0: "Once a month", 2.0: "Once a week",
    3.0: "Several times a week", 4.0: "Every day", 5.0: "Several times a day",
}

TIMESWEEK_LABELS = {
    0.0: "Never", 1.0: "Once a week", 2.0: "Several times a week",
    3.0: "Every day", 4.0: "Several times a day",
}

DISCUSS_RAISED_LABELS = {
    0.0: "No", 1.0: "Yes, I referred to what I heard",
    2.0: "Yes, others referred to what they heard",
    3.0: "Yes, both",
}

FREQ_FEEL_LABELS = {
    3.0: "Would like it broadcast more often", 2.0: "Current frequency is about right",
    1.0: "Broadcast a bit too often", 0.0: "Broadcast far too often",
}

ALREADY_LISTEN_LABELS = {
    4.0: "Listen again", 3.0: "Sometimes listen, sometimes not",
    2.0: "Usually stop listening / switch", 1.0: "Always switch / turn off",
    0.0: "Never happened",
}

METHOD_UNAVAILABLE_LABELS = {
    1.0: "Went somewhere else", 2.0: "Used a different method",
    3.0: "Came back later", 4.0: "Stopped using contraception",
}

HEALTH_FACILITY_LABELS = {
    1.0: "Community-based distribution", 2.0: "Health centre",
    3.0: "Health post", 4.0: "Hospital", 5.0: "Pharmacy",
    6.0: "Specialised clinic", 7.0: "Health professional (independent)",
    8.0: "Itinerant / street vendor",
}

RELIGIOUS_INFLUENCE_LABELS = {
    1.0: "Never", 2.0: "Somewhat", 3.0: "Often", 4.0: "Always",
}

INFO_SOURCE_LABELS = {
    1.0: "Radio", 2.0: "TV", 3.0: "Videos", 4.0: "Newspapers",
    5.0: "Magazines / books", 6.0: "Flyers / leaflets", 7.0: "Billboards",
    8.0: "Wall painting", 9.0: "Facebook", 41.0: "Social media",
    10.0: "Internet", 11.0: "Email", 12.0: "SMS",
    13.0: "Clinical officer / doctor", 14.0: "Nurse / midwife",
    15.0: "Community health worker", 16.0: "Pharmacist", 17.0: "PMV / chemist",
    18.0: "Hospital", 22.0: "Cinema / mobile cinema", 23.0: "Video shops",
    24.0: "Social / community halls", 25.0: "Community outreach events",
    26.0: "Peer education", 27.0: "School", 28.0: "NGOs",
    29.0: "FBOs / churches / mosques", 30.0: "Community meetings",
    31.0: "Women's groups", 32.0: "Parents", 33.0: "In-laws",
    35.0: "Spouse / partner", 36.0: "Siblings", 37.0: "Siblings-in-law",
    38.0: "Friends / neighbours", 39.0: "Other relatives",
}

# ── FEM partner station matching ────────────────────────────────────────────────
# The 21 stations FEM partnered with for the on-air campaign. Respondents are
# assigned up to 7 of these (radio_pull_1..7 / radio_partner_1..7_listen) plus
# one non-partner "placebo" station (radio_placebo_pull) used to catch
# fabricated listenership — the placebo never counts as a partner station here.
FEM_PARTNER_STATIONS_RAW = [
    "Mouriyar karkara_Tahoua", "Radio Mai Tama_Zinder", "Alheri_Maradi",
    "Zumunci_Maradi", "Radio Tarka_Zinder", "Radio Darnako_Zinder",
    "Aissami_Zinder", "Bidizguiri_Tahoua", "Haddin Kay Dakoro",
    "Radio Tsirkao FM_Zinder", "Gyare_Maradi", "Hadin Kai FM - Aguie_Maradi",
    "Haddin Kay Tagriss", "Kitari_Zinder", "Anfani Zinder_Zinder",
    "Ta Karkara (ou Takarkara)_Tahoua", "Anfani Maradi_Maradi",
    "Radio Tarmamoua_Zinder", "Annuri_Maradi", "Kutukum_Zinder",
    "Alternative FM_Zinder",
]

RADIO_PULL_COLS = [f"radio_pull_{i}" for i in range(1, 8)]
RADIO_PARTNER_LISTEN_COLS = [f"radio_partner_{i}_listen" for i in range(1, 8)]

# DHS-standard modern method codes: all fpbeh_which codes except Rhythm (14),
# Withdrawal (15) and Other traditional (16). Standard Days/Cycle beads (12)
# and LAM (13) are classified as modern per current DHS/FP2020 convention.
MODERN_METHOD_CODES = (set(range(1, 14)) | {17}) - {14, 15, 16}

CHLDR_NO_MORE_CODE = 0   # chldr_other_none_yet: 0 = "No more" (wants no more children)

UNMET_NEED_DESCRIPTION = (
    "Share of respondents who are (1) not currently pregnant [current_pregnant = 0], "
    "AND (2) do not want more children [chldr_other_none_yet = 0, \"No more\" — excludes "
    "\"can't get pregnant\", conventionally dropped as fecundity-impaired], AND (3) are "
    "not currently using a modern contraceptive method [none of fpbeh_which_1..17 is 1 "
    "for a DHS-standard modern method code — Rhythm, Withdrawal and Other traditional "
    "are the only codes treated as non-modern]. Denominator: the whole analysis sample "
    "(FEM partner station listeners who passed QA), both genders — current_pregnant and "
    "chldr_other_none_yet were asked of men too. See the female-only figure alongside "
    "this one for the more conventional (women's-fecundity) denominator."
)

UNMET_NEED_DESCRIPTION_FEMALE = (
    "Same definition as the whole-sample figure, restricted to female respondents — "
    "the conventional denominator for unmet need, since it's a measure of women's "
    "fecundity (pregnancy status / desire for more children / current modern-method "
    "use)."
)


def _station_base(name: str) -> str:
    """
    Normalise a station name for fuzzy comparison, mirroring
    q_a/check_anomalies.py's _station_base(): strips a trailing region
    suffix (e.g. 'Radio Darnako_Zinder' -> 'radio darnako') so respondent
    free-text can be compared against the canonical partner-station list.
    """
    if not pd.notna(name) or not name:
        return ""
    s = str(name).strip().lower()
    for sep in (" - ", "_"):
        if sep in s:
            s = s.split(sep)[0].strip()
    return s


def _fuzzy_station_match(query: str, candidates: set[str], threshold: float = 0.75) -> str | None:
    """Best-matching candidate station name, or None. See check_anomalies.py for rationale."""
    import difflib
    if not query or not candidates:
        return None
    matches = difflib.get_close_matches(query, candidates, n=1, cutoff=threshold)
    return matches[0] if matches else None


FEM_PARTNER_STATION_BASES = {_station_base(s) for s in FEM_PARTNER_STATIONS_RAW}


def compute_fem_partner_listener(df: pd.DataFrame) -> pd.Series:
    """
    True if the respondent reported listening (radio_partner_N_listen == 1)
    to a station (radio_pull_N) matching one of the 21 FEM partner stations.
    Placebo listenership never counts — the placebo is deliberately a
    non-partner station.
    """
    result = pd.Series(False, index=df.index)
    for name_col, listen_col in zip(RADIO_PULL_COLS, RADIO_PARTNER_LISTEN_COLS):
        if name_col not in df.columns or listen_col not in df.columns:
            continue
        listened = pd.to_numeric(df[listen_col], errors="coerce").fillna(0).eq(1)
        matched = df[name_col].apply(
            lambda n: _fuzzy_station_match(_station_base(n), FEM_PARTNER_STATION_BASES) is not None
        )
        result = result | (listened & matched)
    return result


BASE_TO_CANONICAL = {_station_base(s): s for s in FEM_PARTNER_STATIONS_RAW}


def _canonical_station_name(raw: str) -> str | None:
    """
    Resolve a respondent's free-text assigned-station name (radio_pull_N) to
    its canonical FEM partner station name. Station identity must be resolved
    by NAME, not by column slot: slot position (radio_pull_1..7) is assigned
    per-respondent by the roster, so "radio_pull_3" is a different real
    station for different respondents. Returns None if the text doesn't match
    any of the 21 partner stations (e.g. blank slot, unrecognised text).
    """
    base = _station_base(raw)
    if not base:
        return None
    if base in BASE_TO_CANONICAL:
        return BASE_TO_CANONICAL[base]
    fuzzy = _fuzzy_station_match(base, FEM_PARTNER_STATION_BASES)
    return BASE_TO_CANONICAL.get(fuzzy) if fuzzy else None


def compute_placebo_only_listener(df: pd.DataFrame) -> pd.Series:
    """
    Listened to the placebo station but to no real FEM partner station.
    Informational only — a small subset (n~4) of compute_no_fp_ads_comparison
    below, which is the actual comparison arm used in analysis. Respondents
    who listen to the placebo AND a real partner station are NOT included
    here — they're Treatment (they were exposed).
    """
    placebo = pd.to_numeric(df.get("radio_partner_placebo_listen"), errors="coerce").fillna(0).eq(1)
    return placebo & ~compute_fem_partner_listener(df)


def compute_no_fp_ads_comparison(df: pd.DataFrame) -> pd.Series:
    """
    Comparison arm: everyone who is NOT a FEM partner station listener —
    i.e. not Treatment. Covers respondents who don't listen to radio at
    all, listen to radio but not a FEM/placebo station, and placebo-only
    listeners, regardless of their own uptake_fp answer. The only carve-out
    is the Treatment definition itself: a FEM partner station listener
    stays Treatment even if THEY personally report no FP-ad recall
    (uptake_fp == 0) — station assignment/listenership is what defines
    "said they hear the campaign", not their own ad-recall answer.
    """
    return ~compute_fem_partner_listener(df)


_SLOT_SPECS = [
    (RADIO_PULL_COLS[i], RADIO_PARTNER_LISTEN_COLS[i],
     f"radio_partner_{i + 1}_days-time", f"uptake_fp_freq_radio_{i + 1}", False)
    for i in range(7)
] + [("radio_placebo_pull", "radio_partner_placebo_listen",
      "radio_partner_placebo_days-time", "uptake_fp_freq_radio_placebo", True)]


def melt_station_slots(df: pd.DataFrame, extra_cols: list[str] | None = None) -> pd.DataFrame:
    """
    Long-format table: one row per (respondent, assigned station slot), with
    the free-text station name resolved to its canonical FEM partner name.
    The placebo slot's station is resolved the same way as a real slot: if
    its name matches one of the 21 partner stations (the common case — it's
    usually a real partner station that just doesn't cover this respondent's
    own settlement), it's merged into that station's real bucket (is_placebo
    stays True so assignment-coverage builders can still exclude it). Only
    when the placebo name matches none of the 21 does it keep the
    respondent's ACTUAL assigned placebo station name (base-normalised,
    title-cased, tagged "(placebo)") — a genuinely non-partner control
    station, never collapsed into a single generic label. Rows with no
    station text (blank slot) are dropped. extra_cols are carried through
    from the source row (e.g. fpbeh_fpnow, for group splits).

    This is the shared basis for every station-level chart, so that
    aggregation always groups by real station identity, never by the
    per-respondent slot column (see _canonical_station_name).
    """
    extra_cols = extra_cols or []
    rows = []
    for name_col, listen_col, freq_col, fpfreq_col, is_placebo in _SLOT_SPECS:
        if name_col not in df.columns:
            continue
        for idx, raw_name in df[name_col].items():
            if is_placebo:
                # The "placebo" slot's station is very often actually one of
                # the 21 real FEM partner stations too (a station that does
                # NOT cover this respondent's own settlement, used as an
                # over-claiming/honesty check) rather than a genuinely
                # separate non-partner control station — verified against
                # cleaned_data.csv: 450 of 509 placebo slots resolve to a
                # real partner name. Resolve it the same way as a real slot
                # so listening/frequency data for that station pools
                # together regardless of which slot asked about it;
                # otherwise the same station splits into two entries
                # ("Station X" / "Station X (placebo)") and each half can
                # look like nobody listens. Only fall back to the generic
                # "(placebo)" label for the small number of genuinely
                # non-partner control stations.
                station = _canonical_station_name(raw_name)
                if station is None:
                    base = _station_base(raw_name)
                    station = f"{base.title()} (placebo)" if base else None
            else:
                station = _canonical_station_name(raw_name)
            if station is None:
                continue
            row = {
                "station": station,
                "is_placebo": is_placebo,
                "listened": df.at[idx, listen_col] if listen_col in df.columns else None,
                "listen_frequency": df.at[idx, freq_col] if freq_col in df.columns else None,
                "fp_content_frequency": df.at[idx, fpfreq_col] if fpfreq_col in df.columns else None,
            }
            for c in extra_cols:
                row[c] = df.at[idx, c] if c in df.columns else None
            rows.append(row)
    return pd.DataFrame(rows)


def compute_unmet_need(df: pd.DataFrame) -> pd.Series:
    """
    Unmet-need proxy: not currently pregnant, does not want more children
    (chldr_other_none_yet == 0, "No more" — excludes code -1 "can't get
    pregnant", conventionally dropped from the unmet-need denominator as
    fecundity-impaired), and not currently using a modern FP method.
    """
    not_pregnant = pd.to_numeric(df.get("current_pregnant"), errors="coerce").eq(0)
    doesnt_want_more = pd.to_numeric(
        df.get("chldr_other_none_yet"), errors="coerce"
    ).eq(CHLDR_NO_MORE_CODE)

    which_cols = [f"fpbeh_which_{i}" for i in MODERN_METHOD_CODES if f"fpbeh_which_{i}" in df.columns]
    if which_cols:
        using_modern = pd.concat(
            [pd.to_numeric(df[c], errors="coerce").fillna(0).eq(1) for c in which_cols], axis=1
        ).any(axis=1)
    else:
        using_modern = pd.Series(False, index=df.index)

    return not_pregnant & doesnt_want_more & ~using_modern


# ── Core helpers ──────────────────────────────────────────────────────────────

def _split_groups(df: pd.DataFrame):
    """Return (all, fp_users, non_users) sub-DataFrames."""
    fp = pd.to_numeric(df.get("fpbeh_fpnow", pd.Series(dtype=float)), errors="coerce")
    return df, df[fp == 1.0], df[fp != 1.0]


def _freq_numeric(series: pd.Series, label_map: dict | None = None) -> pd.DataFrame:
    """Frequency table for a numeric column, excluding skip codes."""
    s = pd.to_numeric(series, errors="coerce")
    s = s[~s.isin(SKIP_CODES)].dropna()
    if s.empty:
        return pd.DataFrame(columns=["category", "count", "pct"])
    counts = s.value_counts().sort_index()
    total = counts.sum()
    rows = []
    for val, n in counts.items():
        cat = label_map.get(float(val), str(val)) if label_map else str(val)
        rows.append({"category": cat, "count": int(n),
                     "pct": round(100 * n / total, 1)})
    return pd.DataFrame(rows)


def _freq_str(series: pd.Series, min_n: int = 0) -> pd.DataFrame:
    """Frequency table for a string (categorical) column."""
    s = series.dropna().astype(str)
    s = s[s.str.strip() != ""]
    if s.empty:
        return pd.DataFrame(columns=["category", "count", "pct"])
    counts = s.value_counts()
    if min_n:
        counts = counts[counts >= min_n]
    total = counts.sum()
    rows = [{"category": str(v), "count": int(n),
              "pct": round(100 * n / total, 1)} for v, n in counts.items()]
    return pd.DataFrame(rows)


def _binary_indicators(df: pd.DataFrame,
                        col_label_pairs: list[tuple[str, str]],
                        n_base: int | None = None) -> pd.DataFrame:
    """
    For binary 0/1 indicator columns, compute % of base selecting each option.
    col_label_pairs: list of (column_name, display_label) in desired order.
    n_base: denominator (defaults to len(df)).
    """
    n = n_base if n_base is not None else len(df)
    if n == 0:
        return pd.DataFrame(columns=["category", "count", "pct"])
    rows = []
    for col, label in col_label_pairs:
        if col not in df.columns:
            continue
        count = int(pd.to_numeric(df[col], errors="coerce").fillna(0).eq(1).sum())
        rows.append({"category": label, "count": count,
                     "pct": round(100 * count / n, 1)})
    if not rows:
        return pd.DataFrame(columns=["category", "count", "pct"])
    return pd.DataFrame(rows).sort_values("pct", ascending=False).reset_index(drop=True)


GENDER_MALE_RAW = "Namiji / Homme"
GENDER_FEMALE_RAW = "Mace / Femme"


def _group_defs(all_df: pd.DataFrame,
                 exposure_df: pd.DataFrame | None = None) -> list[tuple[str, str, pd.DataFrame]]:
    """
    (split_by, label, sub_df) triples for every sliceable dimension the app
    supports — used by every group-comparison builder so the dimensions
    stay in sync in one place:
      split_by="fp_use"        — All / Using FP / Not using FP
      split_by="gender"        — All / Male / Female (skipped if gender_pull absent)
      split_by="treatment_arm" — All / Treatment / Comparison (only if exposure_df
                                  is passed — see build_radio_*/build_*_tv/social,
                                  the few builders analysed across BOTH arms, not
                                  just Treatment; "All" here means all QA-passed
                                  respondents, a different population from the
                                  "All" under fp_use/gender, which is Treatment-only)
    all_df must be the full unfiltered source population for the fp_use/gender
    splits (Treatment-only for every builder except the exposure_* ones).
    """
    fp = pd.to_numeric(all_df.get("fpbeh_fpnow", pd.Series(dtype=float)), errors="coerce")
    defs = [
        ("fp_use", "All", all_df),
        ("fp_use", "Using FP", all_df[fp == 1.0]),
        ("fp_use", "Not using FP", all_df[fp != 1.0]),
    ]
    if "gender_pull" in all_df.columns:
        gender = all_df["gender_pull"]
        defs += [
            ("gender", "All", all_df),
            ("gender", "Male", all_df[gender == GENDER_MALE_RAW]),
            ("gender", "Female", all_df[gender == GENDER_FEMALE_RAW]),
        ]
    if exposure_df is not None and "treatment_arm" in exposure_df.columns:
        arm = exposure_df["treatment_arm"]
        defs += [
            ("treatment_arm", "All", exposure_df),
            ("treatment_arm", "Treatment", exposure_df[arm == "Treatment"]),
            ("treatment_arm", "Comparison", exposure_df[arm == "Comparison"]),
        ]
    return defs


def _with_groups(fn, all_df, fp_df, non_df, exposure_df=None, **kw) -> pd.DataFrame:
    """
    Apply fn across every sliceable dimension (see _group_defs), tagged with
    a "split_by" column so the app can toggle between views. all_df is
    always the full unfiltered Treatment-only source population (that's what
    _split_groups's first return value is, and what melt_station_slots-based
    callers pass too) — fp_df/non_df are accepted for signature compat but
    the fp_use split is recomputed from all_df via _group_defs so it always
    matches the gender split's source population exactly. Pass exposure_df
    (the full QA-passed population, both arms, tagged with treatment_arm) to
    also get a Treatment vs Comparison split — only a few builders (radio,
    TV, socials) are called this way; see main().
    """
    parts = []
    for split_by, lbl, grp in _group_defs(all_df, exposure_df):
        part = fn(grp, **kw)
        if not part.empty:
            part.insert(0, "group", lbl)
            part.insert(0, "split_by", split_by)
        parts.append(part)
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["split_by", "group"])


def _mean_table(df: pd.DataFrame,
                col_label_pairs: list[tuple[str, str]]) -> pd.DataFrame:
    """Mean ± n for Likert columns (skip codes excluded)."""
    rows = []
    for col, label in col_label_pairs:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        s = s[~s.isin(SKIP_CODES)].dropna()
        rows.append({"variable": col, "label": label,
                     "mean": round(float(s.mean()), 3) if len(s) else float("nan"),
                     "n": int(len(s))})
    return pd.DataFrame(rows)


# ── Table builders ────────────────────────────────────────────────────────────

def _linked_demographic_parts(df: pd.DataFrame) -> list[pd.DataFrame]:
    """
    Age group / occupation / religion / settlement type for the analysis
    sample, from the formative baseline via LINKED_DEMOGRAPHICS (joined on
    resp_id_pull). Percentages are of linked respondents with a non-missing
    value for that variable, matching the formative Respondents page. Also
    emits a _n_linked row so the app can show how much of the sample the
    link covers. Returns [] (with a warning) if the linkage hasn't been run.
    """
    if not LINKED_DEMOGRAPHICS.exists():
        print(f"  ! {LINKED_DEMOGRAPHICS.name} not found — run "
              f"2_phone pulse/linkage/link_respondents.py to add age/occupation/religion/"
              f"settlement type to the respondents profile.")
        return []
    if "resp_id_pull" not in df.columns:
        return []

    demo = pd.read_csv(LINKED_DEMOGRAPHICS, dtype={"resp_id_pull": str})
    demo["resp_id_pull"] = demo["resp_id_pull"].str.strip()
    ids = df["resp_id_pull"].astype(str).str.strip()
    linked = demo[demo["resp_id_pull"].isin(set(ids))].set_index("resp_id_pull")
    # Re-expand to one row per Pulse respondent in the sample.
    linked = linked.reindex(ids[ids.isin(linked.index)])

    n_total = len(df)
    n_linked = len(linked)
    parts = [pd.DataFrame([{
        "variable": "_n_linked",
        "category": "Linked to formative baseline (demographics source)",
        "count": n_linked,
        "proportion": round(n_linked / n_total, 3) if n_total else None,
    }])]

    for var in LINKED_DEMOGRAPHIC_VARS:
        if var not in linked.columns:
            continue
        s = linked[var]
        if var in ("occupation", "religion"):
            # 'Hausa / English' → 'English', as the formative pipeline does
            # (pipeline_output/pipeline/etl_respondents.py _clean_bilingual).
            s = s.dropna().astype(str).str.split(" / ").str[-1].str.strip()
        t = _freq_str(s)
        if t.empty:
            continue
        t.insert(0, "variable", var)
        t["proportion"] = (t["pct"] / 100).round(3)
        parts.append(t)
    return parts


def build_respondents_profile(df: pd.DataFrame, funnel: dict | None = None) -> pd.DataFrame:
    """
    funnel (all optional, but pass all together — see main()):
      n_raw               — raw submissions extracted from SurveyCTO
      n_quality_excluded  — dropped by the QA keep-list (manual_flags.csv reasons:
                             duplicates, errors, nonresponse, placebo station,
                             dishonesty concerns, not-a-radio-listener, etc.)
      n_after_qa          — n_raw - n_quality_excluded (= rows in cleaned_data.csv)
      n_no_radio          — of n_after_qa, Comparison sub-group: does not listen to radio at all
      n_radio_not_fem     — of n_after_qa, Comparison sub-group: listens to radio but not a
                             FEM partner station
      n_control           — of n_after_qa, Comparison arm total (everyone NOT a FEM partner
                             station listener) — n_no_radio + n_radio_not_fem
      n_fem_listeners     — of n_after_qa, Treatment arm: listens to >=1 FEM partner station.
                             This page's analysis sample is Treatment only — Comparison
                             respondents are analysed on the Campaign Exposure page.
    """
    n_total = len(df)
    parts = []

    if funnel:
        n_raw = funnel.get("n_raw")
        n_after_qa = funnel.get("n_after_qa")
        rows = [
            {"variable": "_n_raw", "category": "Total raw submissions",
             "count": n_raw, "proportion": 1.0 if n_raw else None},
            {"variable": "_n_quality_excluded",
             "category": "Excluded — quality concerns (QA keep-list)",
             "count": funnel.get("n_quality_excluded"),
             "proportion": round(funnel["n_quality_excluded"] / n_raw, 3) if n_raw else None},
            {"variable": "_n_after_qa",
             "category": "Passed QA (before radio-listening filter)",
             "count": n_after_qa,
             "proportion": round(n_after_qa / n_raw, 3) if n_raw and n_after_qa is not None else None},
            {"variable": "_n_no_radio",
             "category": "Comparison — does not listen to any radio station",
             "count": funnel.get("n_no_radio"),
             "proportion": round(funnel["n_no_radio"] / n_after_qa, 3) if n_after_qa else None},
            {"variable": "_n_radio_not_fem",
             "category": "Comparison — listens to radio, not a FEM station",
             "count": funnel.get("n_radio_not_fem"),
             "proportion": round(funnel["n_radio_not_fem"] / n_after_qa, 3) if n_after_qa else None},
            {"variable": "_n_control",
             "category": "Comparison arm total (not a FEM partner station listener) "
                         "— see Campaign Exposure page",
             "count": funnel.get("n_control"),
             "proportion": round(funnel["n_control"] / n_after_qa, 3) if n_after_qa and funnel.get("n_control") is not None else None},
            {"variable": "_n_fem_listeners",
             "category": "Treatment arm (this page's analysis sample)",
             "count": funnel.get("n_fem_listeners"),
             "proportion": round(funnel["n_fem_listeners"] / n_after_qa, 3) if n_after_qa else None},
        ]
        parts.append(pd.DataFrame(rows))

    parts.append(pd.DataFrame([{"variable": "_total", "category": "Total (analysis sample)",
                                 "count": n_total, "proportion": 1.0}]))

    if "gender_pull" in df.columns:
        t = _freq_str(df["gender_pull"])
        t.insert(0, "variable", "gender")
        t["proportion"] = (t["pct"] / 100).round(3)
        parts.append(t)

    if "lga_pull" in df.columns:
        t = _freq_str(df["lga_pull"])
        t.insert(0, "variable", "region")
        t["proportion"] = (t["pct"] / 100).round(3)
        parts.append(t)

    if "village_pull" in df.columns:
        t = _freq_str(df["village_pull"], min_n=VILLAGE_MIN_N)
        t.insert(0, "variable", "village")
        t["proportion"] = (t["pct"] / 100).round(3)
        parts.append(t)

    for col, var, lmap in [
        ("fpbeh_fpnow",      "fp_use",     {1.0: "Using FP", 0.0: "Not using FP"}),
        ("fpbeh_pregchance", "preg_chance", PREG_CHANCE_LABELS),
    ]:
        if col in df.columns:
            t = _freq_numeric(df[col], lmap)
            t.insert(0, "variable", var)
            t["proportion"] = (t["pct"] / 100).round(3)
            parts.append(t)

    parts.extend(_linked_demographic_parts(df))

    # Unmet need, reported two ways (rendered on the Family Planning page,
    # not here — see page_pp_family_planning.py):
    #  - unmet_need_proxy: whole analysis sample (both genders), as
    #    originally defined.
    #  - unmet_need_proxy_female: female respondents only. Unmet need is
    #    conventionally a women's-fecundity measure (pregnancy / desire for
    #    more children / current modern-method use), and current_pregnant /
    #    chldr_other_none_yet were asked of men too, so the whole-sample
    #    figure above mixes in men who can't be "pregnant" by definition —
    #    this is the more standard denominator.
    unmet_all = compute_unmet_need(df)
    n_unmet_all = int(unmet_all.sum())
    parts.append(pd.DataFrame([{
        "variable": "unmet_need_proxy",
        "category": "Unmet need for contraception (whole sample)",
        "count": n_unmet_all,
        "proportion": round(n_unmet_all / n_total, 3) if n_total else None,
        "description": UNMET_NEED_DESCRIPTION,
    }]))

    female_df = df[df["gender_pull"] == GENDER_FEMALE_RAW] if "gender_pull" in df.columns else df
    n_female = len(female_df)
    unmet_female = compute_unmet_need(female_df)
    n_unmet_female = int(unmet_female.sum())
    parts.append(pd.DataFrame([{
        "variable": "_n_female_unmet_base",
        "category": "Female respondents (unmet-need denominator)",
        "count": n_female,
        "proportion": round(n_female / n_total, 3) if n_total else None,
    }]))
    parts.append(pd.DataFrame([{
        "variable": "unmet_need_proxy_female",
        "category": "Unmet need for contraception (female respondents)",
        "count": n_unmet_female,
        "proportion": round(n_unmet_female / n_female, 3) if n_female else None,
        "description": UNMET_NEED_DESCRIPTION_FEMALE,
    }]))

    result = pd.concat(parts, ignore_index=True)
    if "description" not in result.columns:
        result["description"] = pd.NA
    return result


def build_village_stations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coverage map: for each village, which real FEM partner station(s) are
    assigned to cover it (radio_pull_1..7, canonicalised — NOT whether
    respondents actually listened). Villages below VILLAGE_MIN_N respondents
    are suppressed for privacy, matching the village breakdown in the main
    respondents profile.
    """
    if "village_pull" not in df.columns:
        return pd.DataFrame(columns=["village", "station", "n_respondents"])

    village_counts = df["village_pull"].value_counts()
    valid_villages = set(village_counts[village_counts >= VILLAGE_MIN_N].index)

    melted = melt_station_slots(df, extra_cols=["village_pull"])
    if melted.empty:
        return pd.DataFrame(columns=["village", "station", "n_respondents"])
    melted = melted[~melted["is_placebo"]]
    melted = melted[melted["village_pull"].isin(valid_villages)]
    if melted.empty:
        return pd.DataFrame(columns=["village", "station", "n_respondents"])

    counts = (melted.groupby(["village_pull", "station"]).size()
              .reset_index(name="n_respondents")
              .rename(columns={"village_pull": "village"}))
    return counts.sort_values(["village", "n_respondents"], ascending=[True, False]).reset_index(drop=True)


def build_fp_awareness(df: pd.DataFrame) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(f"fpbeh_awarefp_{i}", FP_METHOD_LABELS[float(i)])
             for i in range(1, 18) if f"fpbeh_awarefp_{i}" in df.columns]

    return _with_groups(lambda d: _binary_indicators(d, pairs), all_df, fp_df, non_df)


def build_fp_method_used(df: pd.DataFrame) -> pd.DataFrame:
    _, fp_df, _ = _split_groups(df)
    pairs = [(f"fpbeh_which_{i}", FP_METHOD_LABELS[float(i)])
             for i in range(1, 18) if f"fpbeh_which_{i}" in df.columns]
    t = _binary_indicators(fp_df, pairs)
    if not t.empty:
        t.insert(0, "group", "Using FP")
    return t


def build_fp_whynot(df: pd.DataFrame) -> pd.DataFrame:
    """% citing each reason (level "reason") and each reason group, i.e. any
    reason under that heading (level "group")."""
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(f"fpbeh_whynot_{i}", label)
             for i, label in WHYNOT_LABELS.items() if f"fpbeh_whynot_{i}" in df.columns]
    group_cols = {}
    for i, group in WHYNOT_GROUPS.items():
        if f"fpbeh_whynot_{i}" in df.columns:
            group_cols.setdefault(group, []).append(f"fpbeh_whynot_{i}")

    def _fn(d):
        reasons = _binary_indicators(d, pairs).assign(level="reason")
        cited = pd.DataFrame({g: d[cols].apply(pd.to_numeric, errors="coerce").fillna(0).eq(1).any(axis=1)
                              .astype(int) for g, cols in group_cols.items()}, index=d.index)
        groups = _binary_indicators(cited, [(g, g) for g in group_cols]).assign(level="group")
        reasons["reason_group"] = reasons["category"].map({WHYNOT_LABELS[i]: g for i, g in WHYNOT_GROUPS.items()})
        groups["reason_group"] = groups["category"]
        return pd.concat([groups, reasons], ignore_index=True)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_fp_preg_chance(df: pd.DataFrame) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("fpbeh_pregchance", pd.Series(dtype=float)),
                              PREG_CHANCE_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_attitudes(df: pd.DataFrame) -> pd.DataFrame:
    """Mean agreement scores (0-4 scale) for self / spouse / community, sliceable by FP use or gender."""
    att_cols = list(ATTITUDE_LABELS.keys())

    rows = []
    for split_by, grp_label, grp_df in _group_defs(df):
        for perspective, suffix in [("self", ""), ("spouse", "_spouse"), ("community", "_commu")]:
            pairs = [(f"{c}{suffix}", ATTITUDE_LABELS[c])
                     for c in att_cols if f"{c}{suffix}" in df.columns]
            t = _mean_table(grp_df, pairs)
            if not t.empty:
                t.insert(0, "perspective", perspective)
                t.insert(0, "group", grp_label)
                t.insert(0, "split_by", split_by)
            rows.append(t)

    return pd.concat(rows, ignore_index=True)


# Phone-Pulse-only knowledge/perception items — no formative-survey
# equivalent exists for any of these four (checked both SurveyCTO form
# definitions by field name and English hint text; the closest formative
# items — statement_57 "no need for contraception until menstruation
# returns" and time_before_preferred_pregnancy — are different constructs,
# not the same question). So these are descriptive-only on the app side,
# never a baseline-vs-follow-up comparison.
PREGNANT_AGAIN_LABELS = {
    1.0: "Immediately / within days", 2.0: "Within the first month",
    3.0: "1–3 months after delivery", 4.0: "4–6 months after delivery",
    5.0: "6–12 months after delivery", 6.0: "More than a year",
    7.0: "It depends",
}
LIKELY_LONG_LABELS = {
    1.0: "Very likely", 2.0: "Somewhat likely", 3.0: "Neither likely nor unlikely",
    4.0: "Unlikely", 5.0: "Very unlikely",
}
# WHO recommends waiting at least 24 months after a live birth before the
# next pregnancy — "At least two years" (code 3) is the medically correct
# answer, used to compute a %-correct figure on the app side.
KNOWLEDGE_WAITING_LABELS = {
    1.0: "At least 6 months", 2.0: "At least one year",
    3.0: "At least two years", 4.0: "At least 4 years",
}
KNOWLEDGE_WAITING_CORRECT_CODE = 3.0

INFO_PERCEPTION_ITEMS = [
    ("info_newpregnancy", "When can a woman become pregnant again after delivery?",
     PREGNANT_AGAIN_LABELS),
    ("info_likely_infertile",
     "Likelihood FP methods make it harder for a woman to get pregnant later",
     LIKELY_LONG_LABELS),
    ("info_likely_mcycle",
     "Likelihood a woman's menstrual cycle changes or stops while using FP",
     LIKELY_LONG_LABELS),
    ("knowledge_waiting",
     "Recommended wait after giving birth before trying to conceive again",
     KNOWLEDGE_WAITING_LABELS),
]


def build_info_perceptions(df: pd.DataFrame) -> pd.DataFrame:
    """Fertility-return / FP-myth / program-message knowledge items, sliceable by FP use or gender."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        parts = []
        for col, question, lmap in INFO_PERCEPTION_ITEMS:
            if col not in d.columns:
                continue
            t = _freq_numeric(d[col], lmap)
            if t.empty:
                continue
            t.insert(0, "question", question)
            parts.append(t)
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
            columns=["question", "category", "count", "pct"])

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_radio_any(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("radio_any", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_radio_hours(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Distribution of daily radio hours among listeners, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        listeners = d[pd.to_numeric(d.get("radio_any", pd.Series(dtype=float)),
                                     errors="coerce") == 1.0]
        if listeners.empty or "radio_hours" not in d.columns:
            return pd.DataFrame(columns=["category", "count", "pct"])
        s = pd.to_numeric(listeners["radio_hours"], errors="coerce").dropna()
        s = s[(s >= 0) & (s <= 16)]
        if s.empty:
            return pd.DataFrame(columns=["category", "count", "pct"])
        bins   = [0, 1, 2, 3, 4, 6, 8, 16]
        labels = ["<1 hr", "1 hr", "2 hrs", "3 hrs", "4 hrs", "5–6 hrs", "7+ hrs"]
        bucketed = pd.cut(s, bins=bins, labels=labels, right=True, include_lowest=True)
        counts = bucketed.value_counts().sort_index()
        total = counts.sum()
        return pd.DataFrame([{"category": str(lbl), "count": int(n),
                               "pct": round(100 * n / total, 1)}
                              for lbl, n in counts.items()])

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_radio_days(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """% of radio listeners tuning in on each day of the week, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(col, label) for col, label in DAY_LABELS.items() if col in df.columns]

    def _fn(d):
        listeners = d[pd.to_numeric(d.get("radio_any", pd.Series(dtype=float)),
                                     errors="coerce") == 1.0]
        return _binary_indicators(listeners, pairs)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_radio_uptake(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Heard FP content on radio, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("uptake_fp", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def _melt_for_exposure(exposure_df: pd.DataFrame | None, keep_placebo: bool = False) -> pd.DataFrame | None:
    """
    Melt the full (Treatment+Comparison) population the same way a builder
    melted its own Treatment-only df, so _group_defs can add a
    treatment_arm split alongside fp_use/gender. keep_placebo matches
    whichever builder is calling this — build_radio_stations drops placebo
    (real-station ranking only), the per-station frequency builders keep it
    (per-respondent placebo detail).
    """
    if exposure_df is None:
        return None
    melted = melt_station_slots(exposure_df, extra_cols=["treatment_arm"])
    if melted.empty or keep_placebo:
        return melted
    return melted[~melted["is_placebo"]]


def build_radio_stations(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Real FEM partner station listenership (placebo excluded — this is the
    partner-station ranking view; see build_radio_station_frequency /
    build_radio_fp_freq for per-respondent placebo detail). Grouped by real
    station NAME (see melt_station_slots — never by column slot, since slot
    1..7 is a different real station per respondent).

    % and count are of respondents ASSIGNED that station (i.e. it covers
    their settlement) who reported listening to it — NOT of all respondents,
    since not everyone is assigned every station. n_assigned (the
    denominator) is included so a 100% on a station assigned to only 1-2
    respondents isn't misread as a strong result — check n_assigned before
    trusting a percentage. n_no_response is the subset of n_assigned who
    left the listening question blank (distinct from an explicit "No") —
    without it, a station where everyone was simply never asked/answered
    would look identical to one where everyone said "No".
    """
    melted = melt_station_slots(df, extra_cols=["fpbeh_fpnow", "gender_pull"])
    if melted.empty:
        return pd.DataFrame(columns=["group", "category", "count", "pct", "n_assigned", "n_no_response"])
    melted = melted[~melted["is_placebo"]]
    melted["listened"] = pd.to_numeric(melted["listened"], errors="coerce")
    fp = pd.to_numeric(melted["fpbeh_fpnow"], errors="coerce")
    all_m, fp_m, non_m = melted, melted[fp == 1.0], melted[fp != 1.0]

    exposure_melted = _melt_for_exposure(exposure_df)
    if exposure_melted is not None and not exposure_melted.empty:
        exposure_melted["listened"] = pd.to_numeric(exposure_melted["listened"], errors="coerce")

    def _fn(d):
        if d.empty:
            return pd.DataFrame(columns=["category", "count", "pct", "n_assigned", "n_no_response"])
        grp = d.groupby("station")["listened"].agg(
            n_assigned="size",
            n_listened=lambda s: (s == 1).sum(),
            n_no_response=lambda s: int(s.isna().sum()),
        )
        grp["pct"] = (100 * grp["n_listened"] / grp["n_assigned"]).round(1)
        out = grp.reset_index().rename(columns={"station": "category", "n_listened": "count"})
        return out[["category", "count", "pct", "n_assigned", "n_no_response"]].sort_values(
            "pct", ascending=False).reset_index(drop=True)

    return _with_groups(_fn, all_m, fp_m, non_m, exposure_df=exposure_melted)


def build_radio_fp_stations(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Same structure/denominator semantics as build_radio_stations, but for
    whether the respondent reported hearing ANY FP/MCH programs or ads on
    that station (fp_content_frequency != "Never"), not general
    listenership. Placebo excluded, grouped by real station NAME.

    % and count are of respondents ASSIGNED that station who reported
    hearing FP content at all — NOT of all respondents. n_assigned is the
    same "assigned to this station" denominator as build_radio_stations.
    n_no_response is bigger here than in the listenership chart BY DESIGN:
    the FP-content-frequency question is only asked of that station's
    listeners (verified against cleaned_data.csv — 0 non-null for
    listened != 1), so everyone who said they don't listen to a given
    station shows up as "no response" for it, not a data gap.
    """
    melted = melt_station_slots(df, extra_cols=["fpbeh_fpnow", "gender_pull"])
    if melted.empty:
        return pd.DataFrame(columns=["group", "category", "count", "pct", "n_assigned", "n_no_response"])
    melted = melted[~melted["is_placebo"]]
    melted["fp_freq_num"] = pd.to_numeric(melted["fp_content_frequency"], errors="coerce")
    fp = pd.to_numeric(melted["fpbeh_fpnow"], errors="coerce")
    all_m, fp_m, non_m = melted, melted[fp == 1.0], melted[fp != 1.0]

    exposure_melted = _melt_for_exposure(exposure_df)
    if exposure_melted is not None and not exposure_melted.empty:
        exposure_melted["fp_freq_num"] = pd.to_numeric(exposure_melted["fp_content_frequency"], errors="coerce")

    def _fn(d):
        if d.empty:
            return pd.DataFrame(columns=["category", "count", "pct", "n_assigned", "n_no_response"])
        grp = d.groupby("station")["fp_freq_num"].agg(
            n_assigned="size",
            n_heard=lambda s: (s > 0).sum(),
            n_no_response=lambda s: int(s.isna().sum()),
        )
        grp["pct"] = (100 * grp["n_heard"] / grp["n_assigned"]).round(1)
        out = grp.reset_index().rename(columns={"station": "category", "n_heard": "count"})
        return out[["category", "count", "pct", "n_assigned", "n_no_response"]].sort_values(
            "pct", ascending=False).reset_index(drop=True)

    return _with_groups(_fn, all_m, fp_m, non_m, exposure_df=exposure_melted)


def build_partner_decision(df: pd.DataFrame) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("partner_pressure", pd.Series(dtype=float)),
                              FP_DECISION_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_partner_norms(df: pd.DataFrame) -> pd.DataFrame:
    """Mean agreement scores for social norm statements, sliceable by FP use or gender."""
    pairs = [
        ("pressure_pnorm",   "Embarrassing for woman to seek contraception"),
        ("pressure_discuss", "Not acceptable to discuss FP with friends"),
    ]
    rows = []
    for split_by, grp_label, grp_df in _group_defs(df):
        t = _mean_table(grp_df, pairs)
        if not t.empty:
            t.insert(0, "group", grp_label)
            t.insert(0, "split_by", split_by)
        rows.append(t)
    return pd.concat(rows, ignore_index=True)


def build_partner_discuss(df: pd.DataFrame) -> pd.DataFrame:
    """Agreement with norm around FP discussion, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("pressure_discuss", pd.Series(dtype=float)), AGREE_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


# ── Shared numeric-bucketing helper (TV / social / distance) ───────────────────

def _bucket_hours(df: pd.DataFrame, gate_col: str, hours_col: str) -> pd.DataFrame:
    """Distribution of daily hours among users of a medium (gate_col == 1)."""
    users = df[pd.to_numeric(df.get(gate_col, pd.Series(dtype=float)),
                              errors="coerce") == 1.0]
    if users.empty or hours_col not in df.columns:
        return pd.DataFrame(columns=["category", "count", "pct"])
    s = pd.to_numeric(users[hours_col], errors="coerce").dropna()
    s = s[(s >= 0) & (s <= 16)]
    if s.empty:
        return pd.DataFrame(columns=["category", "count", "pct"])
    bins   = [0, 1, 2, 3, 4, 6, 8, 16]
    labels = ["<1 hr", "1 hr", "2 hrs", "3 hrs", "4 hrs", "5–6 hrs", "7+ hrs"]
    bucketed = pd.cut(s, bins=bins, labels=labels, right=True, include_lowest=True)
    counts = bucketed.value_counts().sort_index()
    total = counts.sum()
    return pd.DataFrame([{"category": str(lbl), "count": int(n),
                           "pct": round(100 * n / total, 1)}
                          for lbl, n in counts.items()])


# ── Media: TV ─────────────────────────────────────────────────────────────────

def build_tv_any(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("tv_any", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_tv_hours(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Distribution of daily TV hours among viewers, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)
    return _with_groups(lambda d: _bucket_hours(d, "tv_any", "tv_hours"), all_df, fp_df, non_df, exposure_df=exposure_df)


def build_tv_topics(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Topics watched on TV among viewers, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(f"uptake_topics_tv_{int(code)}", label) for code, label in TOPICS_LABELS.items()
             if f"uptake_topics_tv_{int(code)}" in df.columns]

    def _fn(d):
        viewers = d[pd.to_numeric(d.get("tv_any", pd.Series(dtype=float)),
                                   errors="coerce") == 1.0]
        return _binary_indicators(viewers, pairs)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_tv_uptake(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Remember MCH / birth-spacing content on TV, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("uptake_fp_tv", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


# ── Media: Radio (additional detail) ────────────────────────────────────────────

def build_radio_device(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Device used to listen to radio, among radio listeners, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(f"Device_{int(code)}", label) for code, label in RADIO_DEVICE_LABELS.items()
             if f"Device_{int(code)}" in df.columns]

    def _fn(d):
        listeners = d[pd.to_numeric(d.get("radio_any", pd.Series(dtype=float)),
                                     errors="coerce") == 1.0]
        return _binary_indicators(listeners, pairs)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_radio_topics(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Topics heard on radio among listeners, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(f"uptake_topics_{int(code)}", label) for code, label in TOPICS_LABELS.items()
             if f"uptake_topics_{int(code)}" in df.columns]

    def _fn(d):
        listeners = d[pd.to_numeric(d.get("radio_any", pd.Series(dtype=float)),
                                     errors="coerce") == 1.0]
        return _binary_indicators(listeners, pairs)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def _freq_by_station(melted: pd.DataFrame, value_col: str, label_map: dict) -> pd.DataFrame:
    """
    Frequency table per real station name, using melt_station_slots long
    format. value_col (listen_frequency / fp_content_frequency) is only
    populated for respondents who reported listening to the station at all
    ("listened" == 1) — everyone else is skip-logic NaN, not a data gap.
    Every station with >=1 respondent assigned still appears in the output,
    even when literally nobody assigned to it reported listening (so a
    station never just silently vanishes from the chart) — n_assigned and
    n_listened travel with every row so the UI can show that context, e.g.
    "0 of 43 respondents assigned to this station reported listening".
    """
    if melted.empty:
        return pd.DataFrame(columns=["station", "category", "count", "pct", "n_assigned", "n_listened"])
    listened = pd.to_numeric(melted.get("listened"), errors="coerce")
    parts = []
    for station, grp in melted.groupby("station"):
        n_assigned = len(grp)
        n_listened = int((listened.loc[grp.index] == 1).sum())
        t = _freq_numeric(grp[value_col], label_map)
        if t.empty:
            t = pd.DataFrame([{"category": None, "count": 0, "pct": None}])
        t["n_assigned"] = n_assigned
        t["n_listened"] = n_listened
        t.insert(0, "station", station)
        parts.append(t)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["station", "category", "count", "pct", "n_assigned", "n_listened"])


def build_radio_station_frequency(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    How often respondents listen to each assigned station, grouped by real
    station name (see melt_station_slots), by FP use group.
    """
    melted = melt_station_slots(df, extra_cols=["fpbeh_fpnow", "gender_pull"])
    if melted.empty:
        return pd.DataFrame(columns=["group", "station", "category", "count", "pct"])
    fp = pd.to_numeric(melted["fpbeh_fpnow"], errors="coerce")
    all_m, fp_m, non_m = melted, melted[fp == 1.0], melted[fp != 1.0]
    exposure_melted = _melt_for_exposure(exposure_df, keep_placebo=True)

    def _fn(d):
        return _freq_by_station(d, "listen_frequency", TIMESWEEK_LABELS)

    return _with_groups(_fn, all_m, fp_m, non_m, exposure_df=exposure_melted)


def build_radio_fp_freq(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Frequency of hearing FP/MCH content per station, grouped by real station
    name (see melt_station_slots), by FP use group.
    """
    melted = melt_station_slots(df, extra_cols=["fpbeh_fpnow", "gender_pull"])
    if melted.empty:
        return pd.DataFrame(columns=["group", "station", "category", "count", "pct"])
    fp = pd.to_numeric(melted["fpbeh_fpnow"], errors="coerce")
    all_m, fp_m, non_m = melted, melted[fp == 1.0], melted[fp != 1.0]
    exposure_melted = _melt_for_exposure(exposure_df, keep_placebo=True)

    def _fn(d):
        return _freq_by_station(d, "fp_content_frequency", FREQUENCY_LABELS)

    return _with_groups(_fn, all_m, fp_m, non_m, exposure_df=exposure_melted)


def build_radio_conversation(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Frequency of FP/MCH conversations with family & friends, and whether
    those conversations referenced radio content, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        parts = []
        t1 = _freq_numeric(d.get("uptake_discuss", pd.Series(dtype=float)), FREQUENCY_LABELS)
        if not t1.empty:
            t1.insert(0, "question", "How often discussed with family/friends")
            parts.append(t1)
        t2 = _freq_numeric(d.get("uptake_discuss_who", pd.Series(dtype=float)), DISCUSS_RAISED_LABELS)
        if not t2.empty:
            t2.insert(0, "question", "Conversation referenced radio content")
            parts.append(t2)
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
            columns=["question", "category", "count", "pct"])

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_radio_broadcast_opinion(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Opinion on how often FP programs are broadcast, and behaviour when a
    program repeats, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        parts = []
        t1 = _freq_numeric(d.get("freq_feeling", pd.Series(dtype=float)), FREQ_FEEL_LABELS)
        if not t1.empty:
            t1.insert(0, "question", "Opinion on broadcast frequency")
            parts.append(t1)
        t2 = _freq_numeric(d.get("already-listen", pd.Series(dtype=float)), ALREADY_LISTEN_LABELS)
        if not t2.empty:
            t2.insert(0, "question", "What they do when a program repeats")
            parts.append(t2)
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
            columns=["question", "category", "count", "pct"])

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


# ── Media: Socials ───────────────────────────────────────────────────────────

def build_social_any(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("social_any", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


def build_social_hours(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)
    return _with_groups(lambda d: _bucket_hours(d, "social_any", "social_hours"),
                         all_df, fp_df, non_df, exposure_df=exposure_df)


def build_social_uptake(df: pd.DataFrame, exposure_df: pd.DataFrame | None = None) -> pd.DataFrame:
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("uptake_fp_social", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df, exposure_df=exposure_df)


# ── Access barriers ──────────────────────────────────────────────────────────

def build_access_tried(df: pd.DataFrame) -> pd.DataFrame:
    """Tried to get contraception since last contact, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("lastspoke_try", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_access_appointment(df: pd.DataFrame) -> pd.DataFrame:
    """Had a health appointment since last contact (asked if not tried FP), by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("lastspoke_healthvisit", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_access_got_wanted(df: pd.DataFrame) -> pd.DataFrame:
    """Got the wanted method when they tried, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("got_wanted_method", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_access_unavailable(df: pd.DataFrame) -> pd.DataFrame:
    """What respondents did when their wanted method was unavailable, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("method_notavailable", pd.Series(dtype=float)),
                              METHOD_UNAVAILABLE_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_access_location(df: pd.DataFrame) -> pd.DataFrame:
    """Where respondents sought contraceptives, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(f"contraceptives_location_{int(code)}", label)
             for code, label in HEALTH_FACILITY_LABELS.items()
             if f"contraceptives_location_{int(code)}" in df.columns]

    return _with_groups(lambda d: _binary_indicators(d, pairs), all_df, fp_df, non_df)


def build_access_distance(df: pd.DataFrame) -> pd.DataFrame:
    """Travel time to the health facility (minutes), among those who tried, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        tried = d[pd.to_numeric(d.get("lastspoke_try", pd.Series(dtype=float)),
                                 errors="coerce") == 1.0]
        if tried.empty or "distance_facility" not in d.columns:
            return pd.DataFrame(columns=["category", "count", "pct"])
        s = pd.to_numeric(tried["distance_facility"], errors="coerce").dropna()
        s = s[(s >= 0) & (s <= 300)]
        if s.empty:
            return pd.DataFrame(columns=["category", "count", "pct"])
        bins   = [0, 15, 30, 45, 60, 90, 120, 300]
        labels = ["<15 min", "15–30 min", "30–45 min", "45–60 min",
                  "60–90 min", "90–120 min", "120+ min"]
        bucketed = pd.cut(s, bins=bins, labels=labels, right=True, include_lowest=True)
        counts = bucketed.value_counts().sort_index()
        total = counts.sum()
        return pd.DataFrame([{"category": str(lbl), "count": int(n),
                               "pct": round(100 * n / total, 1)}
                              for lbl, n in counts.items()])

    return _with_groups(_fn, all_df, fp_df, non_df)


# ── Social pressure / info sources ──────────────────────────────────────────────

def build_religious_influence(df: pd.DataFrame) -> pd.DataFrame:
    """Degree to which religion influences FP decisions, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)

    def _fn(d):
        return _freq_numeric(d.get("oth_religiousinfluence", pd.Series(dtype=float)),
                              RELIGIOUS_INFLUENCE_LABELS)

    return _with_groups(_fn, all_df, fp_df, non_df)


def build_info_sources(df: pd.DataFrame) -> pd.DataFrame:
    """Main sources of health information, by FP use group."""
    all_df, fp_df, non_df = _split_groups(df)
    pairs = [(f"oth_infsource_{int(code)}", label) for code, label in INFO_SOURCE_LABELS.items()
             if f"oth_infsource_{int(code)}" in df.columns]

    return _with_groups(lambda d: _binary_indicators(d, pairs), all_df, fp_df, non_df)


# ── Campaign exposure comparison: Treatment vs Comparison ──────────────────────
# Treatment = FEM partner station listener ("said they hear the campaign").
# Comparison = not a FEM listener, radio listener, explicitly no FP-ad recall
# ("did not hear the campaign"). See compute_no_fp_ads_comparison() and
# main() for exactly how these two groups are built; requires the
# "exposure_group" column added to df there.

EXPOSURE_LABELS = ["Heard campaign (Treatment)", "Did not hear FP ads (Comparison)"]


def _split_exposure(df: pd.DataFrame):
    """Return (treatment_df, comparison_df) sub-DataFrames by exposure_group."""
    if "exposure_group" not in df.columns:
        empty = df.iloc[0:0]
        return empty, empty
    return (df[df["exposure_group"] == EXPOSURE_LABELS[0]],
            df[df["exposure_group"] == EXPOSURE_LABELS[1]])


def _with_exposure_groups(fn, treatment_df, comparison_df, **kw) -> pd.DataFrame:
    """Apply fn to Treatment and Comparison, tag with a group column."""
    parts = []
    for lbl, grp in zip(EXPOSURE_LABELS, [treatment_df, comparison_df]):
        part = fn(grp, **kw)
        if not part.empty:
            part.insert(0, "group", lbl)
        parts.append(part)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["group"])


def build_exposure_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    Headline comparison: sample size, current FP use, unmet need, and
    perceived pregnancy chance, Treatment vs Comparison.
    """
    treatment_df, comparison_df = _split_exposure(df)
    parts = [pd.DataFrame([
        {"group": EXPOSURE_LABELS[0], "variable": "_n", "category": "n respondents",
         "count": len(treatment_df), "pct": None},
        {"group": EXPOSURE_LABELS[1], "variable": "_n", "category": "n respondents",
         "count": len(comparison_df), "pct": None},
    ])]

    for lbl, grp in zip(EXPOSURE_LABELS, [treatment_df, comparison_df]):
        n = len(grp)
        if n == 0:
            continue
        unmet = compute_unmet_need(grp)
        n_unmet = int(unmet.sum())
        fp_using = pd.to_numeric(grp.get("fpbeh_fpnow"), errors="coerce").eq(1.0).sum()
        rows = [
            {"group": lbl, "variable": "unmet_need_proxy", "category": "Unmet need for contraception",
             "count": n_unmet, "pct": round(100 * n_unmet / n, 1)},
            {"group": lbl, "variable": "fp_use", "category": "Currently using FP",
             "count": int(fp_using), "pct": round(100 * fp_using / n, 1)},
        ]
        parts.append(pd.DataFrame(rows))

    return pd.concat(parts, ignore_index=True)


def build_exposure_fp_awareness(df: pd.DataFrame) -> pd.DataFrame:
    """Contraceptive method awareness, Treatment vs Comparison."""
    treatment_df, comparison_df = _split_exposure(df)
    pairs = [(f"fpbeh_awarefp_{i}", FP_METHOD_LABELS[float(i)])
             for i in range(1, 18) if f"fpbeh_awarefp_{i}" in df.columns]
    return _with_exposure_groups(lambda d: _binary_indicators(d, pairs), treatment_df, comparison_df)


def build_exposure_fp_use(df: pd.DataFrame) -> pd.DataFrame:
    """Current FP use, Treatment vs Comparison."""
    treatment_df, comparison_df = _split_exposure(df)

    def _fn(d):
        return _freq_numeric(d.get("fpbeh_fpnow", pd.Series(dtype=float)), YESNO_LABELS)

    return _with_exposure_groups(_fn, treatment_df, comparison_df)


def build_exposure_attitudes(df: pd.DataFrame) -> pd.DataFrame:
    """Mean self-attitude scores (0-4 scale), Treatment vs Comparison."""
    treatment_df, comparison_df = _split_exposure(df)
    pairs = [(c, label) for c, label in ATTITUDE_LABELS.items() if c in df.columns]
    rows = []
    for lbl, grp in zip(EXPOSURE_LABELS, [treatment_df, comparison_df]):
        t = _mean_table(grp, pairs)
        if not t.empty:
            t.insert(0, "group", lbl)
        rows.append(t)
    return pd.concat(rows, ignore_index=True)


def build_exposure_partner_norms(df: pd.DataFrame) -> pd.DataFrame:
    """Mean social-norm agreement scores, Treatment vs Comparison."""
    treatment_df, comparison_df = _split_exposure(df)
    pairs = [
        ("pressure_pnorm",   "Embarrassing for woman to seek contraception"),
        ("pressure_discuss", "Not acceptable to discuss FP with friends"),
    ]
    rows = []
    for lbl, grp in zip(EXPOSURE_LABELS, [treatment_df, comparison_df]):
        t = _mean_table(grp, pairs)
        if not t.empty:
            t.insert(0, "group", lbl)
        rows.append(t)
    return pd.concat(rows, ignore_index=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 58)
    print("Phone Pulse — App Data Export")
    print("=" * 58)

    if not CLEANED_DATA.exists():
        raise FileNotFoundError(
            f"cleaned_data.csv not found at {CLEANED_DATA}.\n"
            "Run:  python run.py --keep-list ../q_a/reference_data/keep_list.csv"
        )

    print(f"\n  Reading {CLEANED_DATA.name}")
    df_all = pd.read_csv(CLEANED_DATA, low_memory=False)
    n_after_qa = len(df_all)
    print(f"  {n_after_qa} rows, {len(df_all.columns)} columns")

    if POPULATION_SUMMARY.exists():
        pop = pd.read_csv(POPULATION_SUMMARY).set_index("metric")["count"]
        n_raw = int(pop.get("n_raw", n_after_qa))
        n_quality_excluded = int(pop.get("n_quality_excluded", 0))
    else:
        print(f"  ! {POPULATION_SUMMARY.name} not found — re-run run.py to regenerate it. "
              f"Falling back to n_raw = n_after_qa (quality-excluded count unavailable).")
        n_raw = n_after_qa
        n_quality_excluded = 0

    radio_any = pd.to_numeric(df_all.get("radio_any"), errors="coerce")
    fem_listener = compute_fem_partner_listener(df_all)            # Treatment arm
    comparison = compute_no_fp_ads_comparison(df_all)              # Comparison arm = ~Treatment
    no_radio = radio_any.ne(1.0) if radio_any is not None else pd.Series(False, index=df_all.index)
    # Informational sub-breakdown of Comparison — not an exclusion. Every
    # respondent is either Treatment or Comparison; nobody is dropped here.
    comparison_no_radio = comparison & no_radio
    comparison_radio_not_fem = comparison & ~no_radio

    n_no_radio = int(comparison_no_radio.sum())
    n_radio_ambiguous = int(comparison_radio_not_fem.sum())
    n_comparison = int(comparison.sum())
    n_fem_listeners = int(fem_listener.sum())

    funnel = {
        "n_raw": n_raw,
        "n_quality_excluded": n_quality_excluded,
        "n_after_qa": n_after_qa,
        "n_no_radio": n_no_radio,
        "n_radio_not_fem": n_radio_ambiguous,
        "n_control": n_comparison,
        "n_fem_listeners": n_fem_listeners,
    }
    print(f"  Raw submissions              : {n_raw}")
    print(f"  Excluded — quality concerns  : {n_quality_excluded}")
    print(f"  Passed QA                    : {n_after_qa}")
    print(f"    Comparison — no radio at all           : {n_no_radio}")
    print(f"    Comparison — radio, not a FEM station  : {n_radio_ambiguous}")
    print(f"    Comparison (total)                     : {n_comparison}")
    print(f"    Treatment (FEM partner station listener): {n_fem_listeners}  "
          f"(analysis sample = Treatment + Comparison = everyone who passed QA)")

    # df_all, tagged, feeds the Campaign Exposure page (build_exposure_*) AND
    # is passed as `exposure_df` to the Radio/TV/Socials builders below, so
    # those specific charts can ALSO be sliced Treatment vs Comparison
    # (everywhere else stays Treatment-only — see df below).
    df_all["treatment_arm"] = np.where(fem_listener, "Treatment", "Comparison")
    df_all["exposure_group"] = np.where(
        fem_listener, "Heard campaign (Treatment)", "Did not hear FP ads (Comparison)"
    )

    # df, Treatment-only, feeds every other export — "only FEM partner
    # station listeners are included in the analysis" (the original scope
    # for the Phone Pulse app pages other than Campaign Exposure/Radio/Media).
    df = df_all[fem_listener].copy()

    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _w(tbl, name):
        path = APP_DATA_DIR / name
        tbl.to_csv(path, index=False)
        print(f"  → {name}  ({len(tbl)} rows)")

    print("\n  [1/8] Respondents profile")
    _w(build_respondents_profile(df, funnel=funnel), "pp_respondents_profile.csv")
    _w(build_village_stations(df), "pp_village_stations.csv")

    print("\n  [2/8] FP behavior")
    _w(build_fp_awareness(df),   "pp_fp_awareness.csv")
    _w(build_fp_method_used(df), "pp_fp_method_used.csv")
    _w(build_fp_whynot(df),      "pp_fp_whynot.csv")
    _w(build_fp_preg_chance(df), "pp_fp_preg_chance.csv")

    print("\n  [3/8] Attitudes")
    _w(build_attitudes(df), "pp_attitudes.csv")
    _w(build_info_perceptions(df), "pp_info_perceptions.csv")

    # Radio/TV/Socials also get a Treatment-vs-Comparison split (exposure_df
    # = the full QA-passed population, both arms) alongside the usual
    # Treatment-only fp_use/gender splits — see _group_defs.
    print("\n  [4/8] Radio")
    _w(build_radio_any(df, exposure_df=df_all),      "pp_radio_any.csv")
    _w(build_radio_hours(df, exposure_df=df_all),    "pp_radio_hours.csv")
    _w(build_radio_days(df, exposure_df=df_all),     "pp_radio_days.csv")
    _w(build_radio_uptake(df, exposure_df=df_all),   "pp_radio_uptake.csv")
    _w(build_radio_stations(df, exposure_df=df_all), "pp_radio_stations.csv")
    _w(build_radio_fp_stations(df, exposure_df=df_all), "pp_radio_fp_stations.csv")
    _w(build_radio_device(df, exposure_df=df_all),          "pp_radio_device.csv")
    _w(build_radio_station_frequency(df, exposure_df=df_all), "pp_radio_station_frequency.csv")
    _w(build_radio_topics(df, exposure_df=df_all),          "pp_radio_topics.csv")
    _w(build_radio_fp_freq(df, exposure_df=df_all),         "pp_radio_fp_freq.csv")
    _w(build_radio_conversation(df, exposure_df=df_all),    "pp_radio_conversation.csv")
    _w(build_radio_broadcast_opinion(df, exposure_df=df_all), "pp_radio_broadcast_opinion.csv")

    print("\n  [5/8] Partner & norms")
    _w(build_partner_decision(df), "pp_partner_decision.csv")
    _w(build_partner_norms(df),    "pp_partner_norms.csv")
    _w(build_partner_discuss(df),  "pp_partner_discuss.csv")

    print("\n  [6/8] TV & Socials")
    _w(build_tv_any(df, exposure_df=df_all),      "pp_tv_any.csv")
    _w(build_tv_hours(df, exposure_df=df_all),    "pp_tv_hours.csv")
    _w(build_tv_topics(df, exposure_df=df_all),   "pp_tv_topics.csv")
    _w(build_tv_uptake(df, exposure_df=df_all),   "pp_tv_uptake.csv")
    _w(build_social_any(df, exposure_df=df_all),    "pp_social_any.csv")
    _w(build_social_hours(df, exposure_df=df_all),  "pp_social_hours.csv")
    _w(build_social_uptake(df, exposure_df=df_all), "pp_social_uptake.csv")

    print("\n  [7/8] Access barriers")
    _w(build_access_tried(df),        "pp_access_tried.csv")
    _w(build_access_appointment(df),  "pp_access_appointment.csv")
    _w(build_access_got_wanted(df),   "pp_access_got_wanted.csv")
    _w(build_access_unavailable(df),  "pp_access_unavailable.csv")
    _w(build_access_location(df),     "pp_access_location.csv")
    _w(build_access_distance(df),     "pp_access_distance.csv")

    print("\n  [8/9] Social pressure & info sources")
    _w(build_religious_influence(df), "pp_religious_influence.csv")
    _w(build_info_sources(df),        "pp_info_sources.csv")

    print("\n  [9/9] Campaign exposure comparison (Treatment vs Comparison)")
    _w(build_exposure_profile(df_all),        "pp_exposure_profile.csv")
    _w(build_exposure_fp_awareness(df_all),   "pp_exposure_fp_awareness.csv")
    _w(build_exposure_fp_use(df_all),         "pp_exposure_fp_use.csv")
    _w(build_exposure_attitudes(df_all),      "pp_exposure_attitudes.csv")
    _w(build_exposure_partner_norms(df_all),  "pp_exposure_partner_norms.csv")

    print(f"\nAll files written to: {APP_DATA_DIR}")
    print("=" * 58)


if __name__ == "__main__":
    main()
