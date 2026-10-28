"""
Recoding of "Other (specify)" write-ins in the Phone Pulse survey.

The phone counterpart of 1_formative_research/pipeline_output/pipeline/
other_recodes.py, and it uses that file's fuzzy matching (fuzzy_suggest), so
both surveys are coded the same way. run_round.py runs both steps on every run:

1. Refresh (doesn't change any output): every distinct write-in for
   OTHER_RECODE_QUESTIONS (config.py) is added to OTHER_RECODES_PATH with its
   count. Write-ins that clearly match one of the question's own choices on
   the SurveyCTO form (FORM_PATH: English label + Hausa translation) get
   `recode_to` filled (coded_by = "fuzzy <score>" / "fuzzy exact" / "group");
   the rest are left blank with 3 `candidates` each. Rows already in the file
   keep their `recode_to`, so hand-coding is never overwritten, and rows from
   other rounds are kept, so codes carry over between rounds. The question's
   choices are also written to OTHER_RECODE_CHOICES, for hand-coding.
       python other_recodes.py --round round2

2. Apply: for each "Other" answer whose write-in has a `recode_to` that is
   one of the question's choices (its label, English label or code), that
   choice is selected instead of "Other": in the space-separated answer, the
   choice's 0/1 column set to 1 and the <question>__22 column set to 0. A
   `recode_to` that isn't a choice on the form (a new theme) leaves the
   answer as "Other". Runs on the raw export, before transform.py.

Keyed by question + write-in text, never by respondent. Prints counts only.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from config import (
    OTHER_RECODE_QUESTIONS, FORM_PATH, OTHER_RECODES_PATH, OTHER_RECODE_CHOICES,
)

_FORMATIVE = Path(__file__).resolve().parents[2] / "1_formative_research" / "pipeline_output"
sys.path.insert(0, str(_FORMATIVE))
from pipeline.other_recodes import (  # noqa: E402  (shared with the formative survey)
    RECODE_COLS, _key, _load_recodes, clean_writein, fuzzy_suggest, export_choices,
)

OTHER_CODE = "-22"
NOT_A_CHOICE = {"-22", "-88", "-99"}   # other / don't know / refused


def form_choices(form_path=FORM_PATH, questions=OTHER_RECODE_QUESTIONS) -> dict:
    """{question: [(code, english_label, label)]} from the form's survey and
    choices sheets; label = "English/Hausa" where the form has a translation.
    Other / don't know / refused aren't choices to recode to."""
    survey = pd.read_excel(form_path, sheet_name="survey", dtype=str).fillna("")
    choices = pd.read_excel(form_path, sheet_name="choices", dtype=str).fillna("")
    list_of = {name.strip(): typ.split()[-1] for typ, name in zip(survey["type"], survey["name"])
               if typ.strip().startswith("select_")}
    out = {}
    for q in questions:
        if q not in list_of:
            print(f"  [other] {q}: not a select question on the form -- skipped")
            continue
        rows = choices[choices["list_name"].str.strip() == list_of[q]]
        out[q] = []
        for code, english, hausa in zip(rows["value"], rows["label"],
                                        rows.get("label:translation", pd.Series("", index=rows.index))):
            code, english, hausa = code.strip(), english.strip(), hausa.strip()
            if code and code not in NOT_A_CHOICE:
                out[q].append((code, english, f"{english}/{hausa}" if hausa else english))
    return out


def _other_rows(df: pd.DataFrame, question: str) -> pd.Series:
    """Boolean mask: the (space-separated) answer includes the "Other" code."""
    return df[question].apply(lambda v: pd.notna(v) and OTHER_CODE in str(v).split())


# ── Step 1: refresh ───────────────────────────────────────────────────────────

def export_writeins(df: pd.DataFrame, recodes_path=OTHER_RECODES_PATH, form_path=FORM_PATH,
                    choices_path=OTHER_RECODE_CHOICES) -> pd.DataFrame:
    existing = _load_recodes(recodes_path)
    coded = {(q, _key(t)): (r, b) for q, t, r, b in
             zip(existing["question"], existing["other_text"],
                 existing["recode_to"], existing["coded_by"])}

    rows, seen = [], set()
    for q, text_col in OTHER_RECODE_QUESTIONS.items():
        if q not in df.columns or text_col not in df.columns:
            print(f"  [other] {q}: skipped -- '{q}' or '{text_col}' not in data")
            continue
        mask = _other_rows(df, q)
        text = df.loc[mask, text_col].apply(clean_writein).dropna()
        counts = {}
        for t in text:
            k = _key(t)
            spelling, n = counts.get(k, (t, 0))
            counts[k] = (spelling, n + 1)
        for k, (spelling, n) in counts.items():
            recode_to, coded_by = coded.get((q, k), ("", ""))
            rows.append({"question": q, "other_text": spelling, "n": n,
                         "recode_to": recode_to, "coded_by": coded_by})
            seen.add((q, k))
        n_coded = sum(1 for k in counts if coded.get((q, k), ("",))[0])
        print(f"  [other] {q}: {int(mask.sum())} 'Other' answers ({int(mask.sum()) - len(text)} blank), "
              f"{len(counts)} distinct texts, {n_coded} already coded")

    # Write-ins only seen in another round stay in the file with their codes.
    in_this_data = pd.Series([(q, _key(t)) in seen for q, t in
                              zip(existing["question"], existing["other_text"])],
                             index=existing.index, dtype=bool)
    other_rounds = existing.loc[~in_this_data]
    out = pd.concat([pd.DataFrame(rows, columns=RECODE_COLS), other_rounds[RECODE_COLS]],
                    ignore_index=True)
    out["n"] = pd.to_numeric(out["n"], errors="coerce").fillna(0).astype(int)

    choices = form_choices(form_path)
    codes_by_q = {q: [label for _, _, label in c] for q, c in choices.items()}
    # Compare write-ins with the whole label, both languages ("/" is not a separator here).
    out = fuzzy_suggest(out, codes_by_q, label_text=lambda label: label.replace("/", " "))
    export_choices(codes_by_q, str(choices_path))
    out = out.sort_values(["question", "group", "n", "other_text"], ascending=[True, True, False, True])
    Path(recodes_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(recodes_path, index=False, encoding="utf-8-sig")
    print(f"  [other] wrote {len(out)} rows -> {recodes_path}")
    return out


# ── Step 2: apply ─────────────────────────────────────────────────────────────

def apply_other_recodes(df: pd.DataFrame, recodes_path=OTHER_RECODES_PATH,
                        form_path=FORM_PATH) -> pd.DataFrame:
    if not Path(recodes_path).exists():
        print(f"  [other] no recodes file ({recodes_path}) -- answers left as is")
        return df

    rec = _load_recodes(recodes_path)
    rec = rec[rec["recode_to"].str.strip() != ""]
    choices = form_choices(form_path)
    df = df.copy()
    for q, grp in rec.groupby("question"):
        text_col = OTHER_RECODE_QUESTIONS.get(q)
        if text_col is None or q not in df.columns or text_col not in df.columns:
            print(f"  [other] WARNING: recodes given for '{q}' but it isn't a recoded question in this data")
            continue
        # recode_to may be the full label, the English label alone, or the code.
        to_code = {}
        for code, english, label in choices.get(q, []):
            for name in (label, english, code):
                to_code.setdefault(_key(name), code)
        mapping = {_key(t): to_code.get(_key(r)) for t, r in zip(grp["other_text"], grp["recode_to"])}
        n_theme = sum(code is None for code in mapping.values())

        mask = _other_rows(df, q)
        target = df.loc[mask, text_col].apply(
            lambda t: mapping.get(_key(t)) if pd.notna(t) and str(t).strip() else None
        ).dropna()

        missing_cols = set()
        for i, code in target.items():
            answer = []
            for item in str(df.at[i, q]).split():
                item = code if item == OTHER_CODE else item
                if item not in answer:
                    answer.append(item)
            df.at[i, q] = " ".join(answer)
            for col, value in ((f"{q}_{code}", "1"), (f"{q}__22", "0")):
                if col in df.columns:
                    df.at[i, col] = value
                elif col.endswith(f"_{code}"):
                    missing_cols.add(col)
        print(f"  [other] {q}: recoded {len(target)} of {int(mask.sum())} 'Other' answers"
              + (f"; {n_theme} coded texts aren't a choice on the form, left as 'Other'" if n_theme else ""))
        if missing_cols and q != "method_notavailable":   # select_one: no 0/1 columns
            print(f"  [other] WARNING: {q}: 0/1 column(s) not in data: {sorted(missing_cols)}")
    return df


if __name__ == "__main__":
    import rounds
    from extract import load_raw_data

    parser = argparse.ArgumentParser(description="Refresh the Phone Pulse 'Other' recodes file.")
    parser.add_argument("--round", dest="round_id", default="round1", choices=list(rounds.ROUNDS))
    args = parser.parse_args()
    r = rounds.get_round(args.round_id)
    export_writeins(load_raw_data(r["data_dir"]), form_path=r["form_path"])
