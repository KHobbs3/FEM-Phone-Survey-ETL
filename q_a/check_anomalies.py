"""
Anomaly detection for Niger Phone Pulse QA.

Covers three categories:
  1. Duration anomalies   — total call too short/long, section durations suspicious,
                             or large gap between reported and computed duration
  2. Placebo listenership — respondent claimed to listen to a station that should
                             not exist in their area (honesty check)
  3. Honesty indicators   — overheard_yn flag or concerning language in notes

Output columns: KEY | respondent_id | category | flag_type | detail | supporting_data

flag_type:
  exclude  — strong case for exclusion
  review   — needs human judgment
  note     — informational
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from config_qa import (
    RAW_DATA_PATH, STATION_WHITELIST_CSV, QA_OUTPUT_DIR,
    COL_KEY, COL_RESPONDENT_ID, COL_LGA,
    COL_DURATION, COL_PLACEBO_STATION, COL_PLACEBO_LISTEN, COL_PLACEBO_FREQ,
    COL_OVERHEARD, COL_NOTES, RADIO_PULL_COLS,
    SECTION_DURATION_COLS,
    DURATION_SHORT_ERROR, DURATION_SHORT_WARN,
    DURATION_LONG_ERROR,  DURATION_LONG_WARN,
    DURATION_DISCREPANCY_MAX,
    NOTE_HIGH_CONCERN, NOTE_MEDIUM_CONCERN,
)


def _row(key, resp_id, category, flag_type, detail, supporting=""):
    return {
        "KEY": key,
        "respondent_id": resp_id,
        "category": category,
        "flag_type": flag_type,
        "detail": detail,
        "supporting_data": supporting,
    }


def _get(row, col, default=None):
    return row.get(col, default) if col in row.index else default


# ── 1. Duration anomalies ─────────────────────────────────────────────────────

def check_duration_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flags:
    • Total call too short or too long
    • Large discrepancy between form-reported duration and computed (endtime-starttime)
    • Any individual section that looks unreasonably fast

    Note from field: if an enumerator saves the form mid-interview and resumes later,
    the computed duration may include idle time and will appear inflated. The
    reported `duration` field from SurveyCTO is more reliable in those cases.
    Flag both for reviewer judgment.
    """
    if COL_DURATION not in df.columns:
        print("  [duration] 'duration' column not found — skipping")
        return pd.DataFrame()

    rows = []

    for _, row in df.iterrows():
        key = _get(row, COL_KEY, "")
        rid = _get(row, COL_RESPONDENT_ID, "")
        dur = _get(row, COL_DURATION)

        if pd.isna(dur):
            rows.append(_row(key, rid, "duration", "review",
                             "Duration is missing"))
            continue

        dur_min = dur / 60

        if dur < DURATION_SHORT_ERROR:
            rows.append(_row(key, rid, "duration", "review",
                             f"Call very short: {dur_min:.1f} min (expected ~25 min). "
                             "Possible incomplete interview or technical error.",
                             f"duration={dur:.0f}s"))
        elif dur < DURATION_SHORT_WARN:
            rows.append(_row(key, rid, "duration", "review",
                             f"Call short: {dur_min:.1f} min (expected ~25 min). Review if complete.",
                             f"duration={dur:.0f}s"))
        elif dur > DURATION_LONG_ERROR:
            rows.append(_row(key, rid, "duration", "review",
                             f"Call very long: {dur_min:.1f} min. "
                             "Possible: form saved and resumed later (timer kept running). "
                             "Check endtime vs starttime.",
                             f"duration={dur:.0f}s"))
        elif dur > DURATION_LONG_WARN:
            rows.append(_row(key, rid, "duration", "note",
                             f"Call longer than expected: {dur_min:.1f} min.",
                             f"duration={dur:.0f}s"))

        # Computed vs reported discrepancy
        disc = _get(row, "duration_discrepancy_seconds")
        if pd.notna(disc) and disc > DURATION_DISCREPANCY_MAX:
            computed = _get(row, "computed_duration_seconds", "?")
            rows.append(_row(key, rid, "duration_discrepancy", "review",
                             f"Reported duration {dur:.0f}s but endtime-starttime = {computed:.0f}s "
                             f"(gap: {disc:.0f}s). Likely form was saved and reopened mid-interview.",
                             f"reported={dur:.0f}s, computed={computed:.0f}s"))

    print(f"  [duration] {len(rows)} issue(s) flagged")
    return pd.DataFrame(rows)


# ── 2. Placebo listenership ────────────────────────────────────────────────────

def _load_station_whitelist() -> pd.DataFrame:
    """
    Load the station whitelist (LGA → real station names).
    Returns empty DataFrame if file is missing (check will still run but
    cannot distinguish 'lying' from 'wrong placebo assignment').
    """
    if not STATION_WHITELIST_CSV.exists():
        print("  [placebo] station_whitelist.csv not found — placebo check will run without LGA context")
        return pd.DataFrame()
    try:
        wl = pd.read_csv(STATION_WHITELIST_CSV, comment="#")
        wl["station_name"] = wl["station_name"].str.strip().str.lower()
        wl["lga"]          = wl["lga"].str.strip()
        return wl
    except Exception as e:
        print(f"  [placebo] could not read whitelist: {e}")
        return pd.DataFrame()


def _station_base(name: str) -> str:
    """
    Normalise a station name for fuzzy comparison.

    Survey responses often include a regional suffix appended by SurveyCTO, e.g.:
      'Hadin Kai FM - Aguie_Maradi'  →  'hadin kai fm'
      'Radio Darnako_Zinder'         →  'radio darnako'
      'Radio Saraounia'              →  'radio saraounia'

    We strip everything after the first '_' or ' - ' so that the comparison
    works on the base station name only, regardless of how the region was appended.
    """
    if not pd.notna(name) or not name:
        return ""
    s = str(name).strip().lower()
    for sep in (" - ", "_"):
        if sep in s:
            s = s.split(sep)[0].strip()
    return s


def _fuzzy_station_match(query: str, candidates: set[str], threshold: float = 0.75) -> str | None:
    """
    Return the best-matching candidate station name, or None if no match
    exceeds the similarity threshold.

    Uses difflib.SequenceMatcher (standard library). A threshold of 0.75 catches:
      • Single-letter spelling variants ('sarounia' / 'saraounia')
      • Minor punctuation differences
    while avoiding false positives between clearly different stations.

    Both query and candidates should already be base-normalised via _station_base().
    """
    import difflib
    if not query or not candidates:
        return None
    matches = difflib.get_close_matches(query, candidates, n=1, cutoff=threshold)
    return matches[0] if matches else None


def check_placebo_listenership(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag respondents who reported listening to the placebo (fake) radio station.

    Station names in survey responses include a regional suffix added by SurveyCTO,
    e.g. 'Radio Darnako_Zinder' or 'Hadin Kai FM - Aguie_Maradi'. The whitelist
    may use the bare station name. Both sides are base-normalised and compared
    with fuzzy matching (SequenceMatcher, threshold 0.75) to handle:
      • Regional suffixes stripped before comparison
      • Minor spelling variants ('Radio Sarounia' ↔ 'Radio Saraounia')
      • Slight formatting differences

    Three sub-cases once a listener is found:
      A. Placebo station fuzzy-matches a real station in respondent's LGA per whitelist
         → wrong placebo assignment (likely wrong participant ID entered)
      B. No fuzzy match in whitelist for this LGA
         → possible fabricated listenership (honesty concern)
      C. No whitelist available
         → flag for review without LGA context
    """
    if COL_PLACEBO_LISTEN not in df.columns:
        print(f"  [placebo] column '{COL_PLACEBO_LISTEN}' not found — skipping")
        return pd.DataFrame()

    whitelist = _load_station_whitelist()
    rows = []

    # Build LGA → set(base-normalised real station names) lookup
    wl_lookup: dict[str, set] = {}
    if not whitelist.empty and "lga" in whitelist.columns and "station_name" in whitelist.columns:
        for lga, grp in whitelist.groupby("lga"):
            wl_lookup[lga] = {_station_base(s) for s in grp["station_name"]}

    listeners = df[df[COL_PLACEBO_LISTEN] == 1]
    print(f"  [placebo] {len(listeners)} respondent(s) reported listening to placebo station")

    for _, row in listeners.iterrows():
        key         = _get(row, COL_KEY, "")
        rid         = _get(row, COL_RESPONDENT_ID, "")
        lga         = _get(row, COL_LGA, "unknown")
        placebo_raw = _get(row, COL_PLACEBO_STATION, "")
        placebo_base = _station_base(placebo_raw)
        freq_val    = _get(row, COL_PLACEBO_FREQ, "")

        pull_stations_raw = [
            str(_get(row, c, "")) for c in RADIO_PULL_COLS if c in row.index
        ]
        pull_stations_raw = [s for s in pull_stations_raw if s and s != "nan"]

        support = (
            f"placebo_station={placebo_raw!r} (base: {placebo_base!r}), "
            f"lga={lga}, freq={freq_val}, "
            f"real_stations_shown={pull_stations_raw}"
        )

        if wl_lookup:
            lga_real_bases = wl_lookup.get(lga, set())
            matched = _fuzzy_station_match(placebo_base, lga_real_bases)
            if matched:
                rows.append(_row(
                    key, rid, "placebo_wrong_assignment", "review",
                    f"Placebo station '{placebo_raw}' fuzzy-matches real station "
                    f"'{matched}' in {lga} (similarity ≥0.75). "
                    "Likely wrong participant ID entered — wrong placebo was assigned. "
                    "Respondent may not be fabricating.",
                    support,
                ))
            else:
                rows.append(_row(
                    key, rid, "placebo_honesty_concern", "review",
                    f"Respondent claims to listen to '{placebo_raw}' — no match found "
                    f"among real stations in {lga}. Possible fabricated listenership.",
                    support,
                ))
        else:
            rows.append(_row(
                key, rid, "placebo_no_whitelist", "review",
                f"Respondent claims to listen to placebo station '{placebo_raw}' in {lga}. "
                "Cannot classify (real vs fake) without station_whitelist.csv.",
                support,
            ))

    return pd.DataFrame(rows)


# ── 3. Honesty / overheard indicators ─────────────────────────────────────────

def check_honesty_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Two sub-checks:
      A. overheard_yn == 1  →  the enumerator directly recorded that the
                                respondent was overheard during the interview
      B. notes_enumerator   →  free-text notes containing language suggesting
                                compromised interview quality
    """
    rows = []

    # A. Structured overheard flag
    # overheard_yn=1 means respondent CAN speak privately (good — no flag needed).
    # overheard_yn=0 means they CANNOT speak privately or preferred not to say.
    if COL_OVERHEARD in df.columns:
        overheard = df[df[COL_OVERHEARD] == 0]
        for _, row in overheard.iterrows():
            rows.append(_row(
                _get(row, COL_KEY, ""), _get(row, COL_RESPONDENT_ID, ""),
                "overheard", "review",
                "overheard_yn=0: respondent could not or would not confirm they could speak "
                "privately. Answers may reflect social pressure rather than true views.",
                f"enumerator_note={_get(row, COL_NOTES, '')!r}",
            ))
        print(f"  [honesty] {len(overheard)} respondent(s) flagged as not able to speak privately (overheard_yn=0)")
    else:
        print(f"  [honesty] column '{COL_OVERHEARD}' not found — checking notes only")

    # B. Free-text notes keyword scan
    if COL_NOTES not in df.columns:
        print(f"  [honesty] column '{COL_NOTES}' not found — notes check skipped")
        return pd.DataFrame(rows)

    note_flag_count = 0
    for _, row in df.iterrows():
        note = str(_get(row, COL_NOTES, "") or "").lower()
        if not note or note == "nan":
            continue

        key = _get(row, COL_KEY, "")
        rid = _get(row, COL_RESPONDENT_ID, "")

        matched_high   = [kw for kw in NOTE_HIGH_CONCERN   if kw in note]
        matched_medium = [kw for kw in NOTE_MEDIUM_CONCERN if kw in note]

        # Don't double-flag if overheard_yn already caught this
        already_flagged = (
            COL_OVERHEARD in df.columns and
            _get(row, COL_OVERHEARD) == 1 and
            any(kw in note for kw in ["overheard", "overhead", "not freely"])
        )

        if matched_high and not already_flagged:
            rows.append(_row(
                key, rid, "note_honesty_concern", "review",
                f"Enumerator note suggests compromised interview quality "
                f"(keywords: {matched_high}). Review before including in analysis.",
                f"note={_get(row, COL_NOTES, '')!r}",
            ))
            note_flag_count += 1
        elif matched_medium:
            rows.append(_row(
                key, rid, "note_quality_concern", "note",
                f"Enumerator note mentions quality concern "
                f"(keywords: {matched_medium}). Likely benign but logged for awareness.",
                f"note={_get(row, COL_NOTES, '')!r}",
            ))
            note_flag_count += 1

    print(f"  [honesty] {note_flag_count} note-based concern(s) flagged")
    return pd.DataFrame(rows)


# ── 4. Straightlining on attitude scales ──────────────────────────────────────

def check_straightlining(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag respondents who gave the same answer to every attitude (Likert) question.
    Straightlining — repeatedly selecting the same scale point throughout a long
    battery — strongly suggests satisficing: the respondent was not engaging with
    individual questions. This is a recognised form of response bias in phone surveys.

    Threshold: ≥ 80% of valid attitude responses share a single value.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "etl_config",
        Path(__file__).parent.parent / "etl_pipeline" / "config.py"
    )
    etl_cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(etl_cfg)
    _LC = etl_cfg.LIKERT_COLUMNS

    likert_present = [c for c in _LC if c in df.columns]
    if not likert_present:
        print("  [straightline] no Likert columns found — skipping")
        return pd.DataFrame()

    STRAIGHTLINE_THRESHOLD = 0.80
    rows = []

    for _, row in df.iterrows():
        key = _get(row, COL_KEY, "")
        rid = _get(row, COL_RESPONDENT_ID, "")
        vals = row[likert_present].dropna()
        if len(vals) < 5:
            continue  # not enough responses to judge
        mode_count = vals.value_counts().iloc[0]
        mode_val   = vals.value_counts().index[0]
        rate = mode_count / len(vals)
        if rate >= STRAIGHTLINE_THRESHOLD:
            rows.append(_row(
                key, rid, "straightlining", "review",
                f"{rate:.0%} of Likert attitude items answered with the same value ({mode_val:.0f}). "
                f"Suggests satisficing / not engaging with individual questions "
                f"({mode_count} of {len(vals)} valid responses).",
                f"dominant_value={mode_val:.0f}, n_valid={len(vals)}",
            ))

    print(f"  [straightline] {len(rows)} respondent(s) flagged for straightlining")
    return pd.DataFrame(rows)


# ── 5. Implausible values ─────────────────────────────────────────────────────

def check_implausible_values(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag values that are logically impossible or highly improbable:
    • Media hours > 16 per day (leaves < 8 hours for sleep/everything else)
    • EDD (estimated due date) before the interview date
    • Section durations that sum to more than the total reported duration
      (suggests the form was paused/resumed, inflating individual section timers)
    """
    rows = []

    for _, row in df.iterrows():
        key = _get(row, COL_KEY, "")
        rid = _get(row, COL_RESPONDENT_ID, "")

        # Media hours
        for col, label in [("radio_hours", "radio"), ("tv_hours_per_day", "TV"),
                            ("social_media_hours_per_day", "social media")]:
            if col not in df.columns:
                continue
            val = _get(row, col)
            if pd.notna(val) and val > 16:
                rows.append(_row(
                    key, rid, "implausible_value", "review",
                    f"{label} hours/day = {val} (>16 is implausible as a daily average).",
                    f"{col}={val}",
                ))

    # EDD before interview date
    for date_col, ref_col in [("edd", "SubmissionDate"), ("edd", "starttime")]:
        if date_col not in df.columns or ref_col not in df.columns:
            continue
        edd_dates  = pd.to_datetime(df[date_col],  errors="coerce")
        ref_dates  = pd.to_datetime(df[ref_col],   errors="coerce")
        bad_mask   = edd_dates.notna() & ref_dates.notna() & (edd_dates < ref_dates)
        for idx in df.index[bad_mask]:
            row = df.loc[idx]
            rows.append(_row(
                _get(row, COL_KEY, ""), _get(row, COL_RESPONDENT_ID, ""),
                "implausible_value", "review",
                f"EDD ({edd_dates[idx].date()}) is before interview date "
                f"({ref_dates[idx].date()}). Check for data entry error.",
                f"edd={edd_dates[idx].date()}, {ref_col}={ref_dates[idx].date()}",
            ))
        break  # only run once (both ref_col options check the same thing)

    # Section durations > total duration
    sec_cols_present = {name: col for name, col in SECTION_DURATION_COLS.items()
                        if col in df.columns}
    if sec_cols_present and COL_DURATION in df.columns:
        sec_col_list = list(sec_cols_present.values())
        sec_totals = df[sec_col_list].apply(pd.to_numeric, errors="coerce").sum(axis=1)
        total_dur  = pd.to_numeric(df[COL_DURATION], errors="coerce")
        over_mask  = sec_totals.notna() & total_dur.notna() & (sec_totals > total_dur * 1.2)
        for idx in df.index[over_mask]:
            row = df.loc[idx]
            rows.append(_row(
                _get(row, COL_KEY, ""), _get(row, COL_RESPONDENT_ID, ""),
                "implausible_value", "review",
                f"Sum of section durations ({sec_totals[idx]:.0f}s) exceeds total call duration "
                f"({total_dur[idx]:.0f}s) by >20%. Form was likely paused and resumed, "
                "inflating one or more section timers.",
                f"sum_sections={sec_totals[idx]:.0f}s, duration={total_dur[idx]:.0f}s",
            ))

    print(f"  [implausible] {len(rows)} implausible value(s) flagged")
    return pd.DataFrame(rows)


# ── 6. Radio / media consistency ─────────────────────────────────────────────

def check_media_consistency(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-check media access responses for internal contradictions:
    • radio_any=0 but station-level listenership data is present
    • Respondent claims FP content heard on placebo station
      (covered by placebo check, but also flagged here for completeness)
    • All 7 partner stations listened to — statistically rare and worth reviewing
    """
    rows = []
    LISTEN_COLS = [f"radio_partner_{i}_listen" for i in range(1, 8)]
    listen_present = [c for c in LISTEN_COLS if c in df.columns]

    for _, row in df.iterrows():
        key = _get(row, COL_KEY, "")
        rid = _get(row, COL_RESPONDENT_ID, "")

        # radio_any=0 but station questions answered
        radio_any = _get(row, "radio_any")
        if radio_any == 0 and listen_present:
            answered = [c for c in listen_present if pd.notna(_get(row, c))]
            if answered:
                rows.append(_row(
                    key, rid, "media_consistency", "review",
                    "radio_any=0 (does not listen to radio) but station-level questions "
                    f"have responses ({len(answered)} columns populated). "
                    "Possible skip-logic error or enumerator did not follow routing.",
                    f"n_station_cols_populated={len(answered)}",
                ))

        # All partner stations listened to
        if listen_present:
            listens = [_get(row, c) for c in listen_present]
            listens_valid = [v for v in listens if pd.notna(v)]
            if listens_valid and all(v == 1 for v in listens_valid) and len(listens_valid) >= 4:
                rows.append(_row(
                    key, rid, "media_consistency", "note",
                    f"Respondent reports listening to all {len(listens_valid)} partner radio stations. "
                    "Uncommon — verify this is plausible for their location.",
                    f"stations_listened={len(listens_valid)}",
                ))

        # FP content heard on placebo (separate from placebo listenership check)
        placebo_fp_col = "uptake_fp_freq_radio_placebo"
        placebo_fp = _get(row, placebo_fp_col)
        if pd.notna(placebo_fp) and placebo_fp > 0:
            placebo_listen = _get(row, COL_PLACEBO_LISTEN)
            if placebo_listen != 1:
                rows.append(_row(
                    key, rid, "media_consistency", "review",
                    f"Respondent reports FP content frequency on placebo station "
                    f"({placebo_fp_col}={placebo_fp}) without confirming they listen to it. "
                    "Inconsistent response.",
                    f"{placebo_fp_col}={placebo_fp}, {COL_PLACEBO_LISTEN}={placebo_listen}",
                ))

    print(f"  [media] {len(rows)} media consistency issue(s) flagged")
    return pd.DataFrame(rows)


# ── 7. Enumerator-level patterns ──────────────────────────────────────────────

def check_enumerator_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Look for statistical anomalies at the enumerator level that may indicate
    systematic problems (coaching, rushing, fabrication):

    • Unusually short average call duration vs. other enumerators
    • Unusually high overheard rate (may be assigning interviews in non-private settings)
    • Unusually high placebo listenership rate among their respondents
    • Suspiciously uniform call durations (low variance → calls may be fabricated)

    Thresholds are relative (z-score based) so they scale to dataset size.
    """
    ENUM_COL = "enumerator"  # column in mock data; real data may differ
    if ENUM_COL not in df.columns:
        print(f"  [enumerator] '{ENUM_COL}' column not found — skipping")
        return pd.DataFrame()

    rows = []
    dur_col     = COL_DURATION
    overh_col   = COL_OVERHEARD
    placebo_col = COL_PLACEBO_LISTEN

    numeric_dur = pd.to_numeric(df[dur_col], errors="coerce") if dur_col in df.columns else None

    for enum_name, grp in df.groupby(ENUM_COL):
        key_str = ""
        rid_str = enum_name
        n = len(grp)
        if n < 3:
            continue  # too few to draw conclusions

        # Short average duration
        if numeric_dur is not None:
            grp_dur  = pd.to_numeric(grp[dur_col], errors="coerce").dropna()
            all_dur  = numeric_dur.dropna()
            if len(grp_dur) >= 3 and len(all_dur) > n:
                global_mean = all_dur.mean()
                global_std  = all_dur.std()
                enum_mean   = grp_dur.mean()
                if global_std > 0:
                    z = (enum_mean - global_mean) / global_std
                    if z < -1.5:
                        rows.append(_row(
                            "", f"[enumerator: {enum_name}]",
                            "enumerator_pattern", "review",
                            f"Average call duration {enum_mean/60:.1f} min is "
                            f"{abs(z):.1f} SD below the dataset mean "
                            f"({global_mean/60:.1f} min). May indicate rushed interviews.",
                            f"enum_mean={enum_mean:.0f}s, global_mean={global_mean:.0f}s, n={n}",
                        ))

            # Low duration variance (suspiciously uniform call lengths)
            if len(grp_dur) >= 5:
                cv = grp_dur.std() / grp_dur.mean() if grp_dur.mean() > 0 else 0
                if cv < 0.05:
                    rows.append(_row(
                        "", f"[enumerator: {enum_name}]",
                        "enumerator_pattern", "review",
                        f"Call durations are suspiciously uniform "
                        f"(CV={cv:.2%}, mean={grp_dur.mean()/60:.1f} min). "
                        "Very low variance may indicate fabricated submissions.",
                        f"std={grp_dur.std():.0f}s, n={n}",
                    ))

        # High overheard rate (overheard_yn=0 means cannot speak privately)
        if overh_col in df.columns:
            overh_rate = (pd.to_numeric(grp[overh_col], errors="coerce") == 0).mean()
            overall_rate = (pd.to_numeric(df[overh_col], errors="coerce") == 0).mean()
            if overh_rate > 0.4 and overh_rate > overall_rate * 2 and n >= 3:
                rows.append(_row(
                    "", f"[enumerator: {enum_name}]",
                    "enumerator_pattern", "note",
                    f"{overh_rate:.0%} of this enumerator's interviews were overheard "
                    f"(dataset average: {overall_rate:.0%}). "
                    "May be conducting interviews in non-private settings.",
                    f"overheard={overh_rate:.0%}, n={n}",
                ))

        # High placebo listenership rate
        if placebo_col in df.columns:
            placebo_vals = pd.to_numeric(grp[placebo_col], errors="coerce")
            placebo_rate = (placebo_vals == 1).sum() / placebo_vals.notna().sum() \
                           if placebo_vals.notna().sum() > 0 else 0
            overall_placebo = (pd.to_numeric(df[placebo_col], errors="coerce") == 1).mean()
            if placebo_rate > 0.3 and placebo_rate > overall_placebo * 2 and n >= 3:
                rows.append(_row(
                    "", f"[enumerator: {enum_name}]",
                    "enumerator_pattern", "review",
                    f"{placebo_rate:.0%} of this enumerator's respondents claimed to listen "
                    f"to the placebo station (dataset average: {overall_placebo:.0%}). "
                    "May indicate coaching or suggestive questioning.",
                    f"placebo_rate={placebo_rate:.0%}, n={n}",
                ))

    print(f"  [enumerator] {len(rows)} enumerator-level pattern(s) flagged")
    return pd.DataFrame(rows)


# ── Master runner ──────────────────────────────────────────────────────────────

def run_anomaly_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Run all anomaly checks and return a combined report DataFrame."""
    print("\n── Anomaly Checks ───────────────────────────────────────────────────")
    frames = [
        check_duration_anomalies(df),
        check_placebo_listenership(df),
        check_honesty_indicators(df),
        check_straightlining(df),
        check_implausible_values(df),
        check_media_consistency(df),
        check_enumerator_patterns(df),
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        print("  No anomalies detected.")
        return pd.DataFrame(
            columns=["KEY","respondent_id","category","flag_type","detail","supporting_data"]
        )

    report = pd.concat(frames, ignore_index=True)
    order = {"exclude": 0, "review": 1, "note": 2}
    report["_ord"] = report["flag_type"].map(order)
    report = report.sort_values(["_ord", "respondent_id"]).drop(columns=["_ord"])
    return report.reset_index(drop=True)


if __name__ == "__main__":
    print("Running anomaly checks standalone...")
    df = pd.read_excel(RAW_DATA_PATH, sheet_name='data',low_memory=False, report = run_anomaly_checks(df))
    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = QA_OUTPUT_DIR / "anomaly_report.csv"
    report.to_csv(out, index=False)
    print(f"\nSaved {len(report)} issue(s) to {out}")
    if not report.empty:
        print(report.groupby(["category","flag_type"]).size().to_string())
