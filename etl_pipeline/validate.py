"""
Validate: run quality checks and return a structured issue log.
Each check produces rows with columns:
  respondent_id | check_name | severity | detail
"""

import pandas as pd
import numpy as np
from config import (
    MIN_DURATION_SECONDS, MAX_DURATION_SECONDS, DURATION_DISCREPANCY_THRESHOLD,
    COL_RESPONDENT_ID, COL_DURATION, COL_OVERHEARD,
)


def _rid(row, df):
    return row.get(COL_RESPONDENT_ID, row.name) if COL_RESPONDENT_ID in df.columns else row.name


def _issue(respondent_id, check_name: str, severity: str, detail: str) -> dict:
    return {
        "respondent_id": respondent_id,
        "check_name": check_name,
        "severity": severity,
        "detail": detail,
    }


# ── Individual checks ──────────────────────────────────────────────────────────

def check_duration_thresholds(df: pd.DataFrame) -> list[dict]:
    issues = []
    if COL_DURATION not in df.columns:
        return issues
    for _, row in df.iterrows():
        rid = _rid(row, df)
        dur = row.get(COL_DURATION)
        if pd.isna(dur):
            issues.append(_issue(rid, "duration_missing", "warning", "duration field is missing"))
        elif dur < MIN_DURATION_SECONDS:
            issues.append(_issue(
                rid, "duration_too_short", "error",
                f"Reported duration {dur:.0f}s is below minimum {MIN_DURATION_SECONDS}s"
            ))
        elif dur > MAX_DURATION_SECONDS:
            issues.append(_issue(
                rid, "duration_too_long", "warning",
                f"Reported duration {dur:.0f}s exceeds maximum {MAX_DURATION_SECONDS}s"
            ))
    return issues


def check_duration_discrepancy(df: pd.DataFrame) -> list[dict]:
    issues = []
    if "duration_discrepancy_seconds" not in df.columns:
        return issues
    for _, row in df.iterrows():
        rid = _rid(row, df)
        disc = row.get("duration_discrepancy_seconds")
        if pd.notna(disc) and disc > DURATION_DISCREPANCY_THRESHOLD:
            reported = row.get(COL_DURATION, "?")
            computed = row.get("computed_duration_seconds", "?")
            issues.append(_issue(
                rid, "duration_discrepancy", "warning",
                f"Reported {reported:.0f}s vs computed {computed:.0f}s (diff {disc:.0f}s)"
            ))
    return issues


def check_timestamp_order(df: pd.DataFrame) -> list[dict]:
    issues = []
    if "starttime" not in df.columns or "endtime" not in df.columns:
        return issues
    for _, row in df.iterrows():
        rid = _rid(row, df)
        start, end = row.get("starttime"), row.get("endtime")
        if pd.isna(start) or pd.isna(end):
            issues.append(_issue(rid, "timestamp_missing", "error",
                                 "starttime or endtime is missing"))
        elif end <= start:
            issues.append(_issue(rid, "timestamp_order", "error",
                                 f"endtime {end} is not after starttime {start}"))
    return issues


def check_overheard(df: pd.DataFrame) -> list[dict]:
    """Flag respondents who were overheard — responses may reflect social pressure."""
    issues = []
    if COL_OVERHEARD not in df.columns:
        return issues
    mask = df[COL_OVERHEARD] == 1
    for _, row in df[mask].iterrows():
        issues.append(_issue(
            _rid(row, df), "respondent_overheard", "warning",
            "overheard_yn=1: respondent was overheard — answers may be socially biased"
        ))
    return issues


def check_consent_given(df: pd.DataFrame) -> list[dict]:
    issues = []
    if "futurecalls" not in df.columns:
        return issues
    mask = df["futurecalls"] == 0
    for _, row in df[mask].iterrows():
        issues.append(_issue(
            _rid(row, df), "no_consent_future", "info",
            "Respondent did not consent to future follow-up calls"
        ))
    return issues


def check_info_accuracy(df: pd.DataFrame) -> list[dict]:
    """Flag records where roster information was incorrect."""
    issues = []
    if "confirm_info" not in df.columns:
        return issues
    mask = df["confirm_info"] == 0
    for _, row in df[mask].iterrows():
        wrong_field = row.get("confirm_correct", "unspecified")
        issues.append(_issue(
            _rid(row, df), "roster_info_incorrect", "warning",
            f"Roster information was incorrect — field: {wrong_field}"
        ))
    return issues


def check_id_reentry_mismatch(df: pd.DataFrame) -> list[dict]:
    """Flag records where the re-entered participant ID doesn't match the first entry."""
    issues = []
    if "id" not in df.columns or "id_re" not in df.columns:
        return issues
    for _, row in df.iterrows():
        id1, id2 = str(row.get("id", "")).strip(), str(row.get("id_re", "")).strip()
        if id1 and id2 and id1 != id2:
            issues.append(_issue(
                _rid(row, df), "id_reentry_mismatch", "warning",
                f"ID entered ({id1}) differs from re-entry ({id2}) — possible wrong participant ID"
            ))
    return issues


def check_fp_logic_consistency(df: pd.DataFrame) -> list[dict]:
    """Check logical consistency within FP questions."""
    issues = []
    for _, row in df.iterrows():
        rid = _rid(row, df)
        using = row.get("fpbeh_fpnow")
        reason_not = row.get("fpbeh_whynot")
        if using == 1 and pd.notna(reason_not) and str(reason_not).strip():
            issues.append(_issue(
                rid, "fp_logic_using_but_reason_given", "warning",
                "fpbeh_fpnow=1 but fpbeh_whynot is populated"
            ))
        pregnant = row.get("current_pregnant")
        edd = row.get("edd")
        if pregnant == 1 and (pd.isna(edd) or str(edd).strip() == ""):
            issues.append(_issue(
                rid, "pregnant_no_edd", "info",
                "current_pregnant=1 but no estimated due date provided"
            ))
    return issues


def check_high_sentinel_rate(df: pd.DataFrame, threshold: float = 0.4) -> list[dict]:
    """Flag respondents with ≥ threshold fraction of Likert columns missing."""
    from config import LIKERT_COLUMNS
    issues = []
    likert_present = [c for c in LIKERT_COLUMNS if c in df.columns]
    if not likert_present:
        return issues
    for _, row in df.iterrows():
        rid = _rid(row, df)
        vals = row[likert_present]
        null_rate = vals.isna().mean()
        if null_rate >= threshold:
            issues.append(_issue(
                rid, "high_sentinel_rate", "warning",
                f"{null_rate:.0%} of Likert attitude items are missing/sentinel "
                f"({vals.isna().sum()}/{len(likert_present)} columns)"
            ))
    return issues


def check_agreement_scale_range(df: pd.DataFrame) -> list[dict]:
    """Agree/disagree items (fpatt_*, pressure_*) must be 0-4 once -88/-99 are
    removed. Any other code (e.g. 5 = "don't know" on an older answer list)
    would be counted as agreeing (score >= 3) by the attitude comparisons."""
    from config import LIKERT_COLUMNS
    cols = [c for c in LIKERT_COLUMNS
            if c in df.columns and (c.startswith("fpatt_") or c.startswith("pressure_"))]
    issues = []
    for _, row in df.iterrows():
        rid = _rid(row, df)
        for col in cols:
            val = pd.to_numeric(row[col], errors="coerce")
            if pd.notna(val) and val not in (0, 1, 2, 3, 4):
                issues.append(_issue(
                    rid, "agreement_out_of_range", "error",
                    f"{col}={val:g} is outside 0-4 (strongly disagree to strongly agree)"
                ))
    return issues


def check_exposure_logic(df: pd.DataFrame) -> list[dict]:
    """Questions behind the Campaign Exposure indicators (2_phone pulse/linkage/compare_exposure_rounds.py):
    uptake_fp is only asked of radio listeners, and knowledge_waiting has codes 1-4."""
    issues = []
    for _, row in df.iterrows():
        rid = _rid(row, df)
        radio = pd.to_numeric(row.get("radio_any"), errors="coerce")
        heard = pd.to_numeric(row.get("uptake_fp"), errors="coerce")
        if radio == 0 and pd.notna(heard):
            issues.append(_issue(
                rid, "uptake_fp_without_radio", "warning",
                f"radio_any=0 but uptake_fp={heard:g} (only asked of radio listeners)"
            ))
        wait = pd.to_numeric(row.get("knowledge_waiting"), errors="coerce")
        if pd.notna(wait) and wait not in (1, 2, 3, 4):
            issues.append(_issue(
                rid, "knowledge_waiting_unknown_code", "error",
                f"knowledge_waiting={wait:g} is not an answer code (1-4)"
            ))
    return issues


# ── Master validation runner ───────────────────────────────────────────────────

def run_validation(df: pd.DataFrame) -> pd.DataFrame:
    all_issues: list[dict] = []
    checks = [
        check_duration_thresholds,
        check_duration_discrepancy,
        check_timestamp_order,
        check_overheard,
        check_consent_given,
        check_info_accuracy,
        check_id_reentry_mismatch,
        check_fp_logic_consistency,
        check_high_sentinel_rate,
        check_agreement_scale_range,
        check_exposure_logic,
    ]
    for fn in checks:
        all_issues.extend(fn(df))

    if not all_issues:
        return pd.DataFrame(columns=["respondent_id", "check_name", "severity", "detail"])

    report = pd.DataFrame(all_issues)
    sev_order = {"error": 0, "warning": 1, "info": 2}
    report["_sev_ord"] = report["severity"].map(sev_order)
    report = report.sort_values(["_sev_ord", "respondent_id"]).drop(columns=["_sev_ord"])
    return report.reset_index(drop=True)
