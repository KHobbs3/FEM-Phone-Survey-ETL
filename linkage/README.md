# Linking Formative Research (baseline) to Phone Pulse (follow-up)

Links respondents across the two survey waves and compares their answers,
with a focus on whether contraceptive knowledge increased.

## Status: working

The roster crosswalk (`2_phone pulse/data/crosswalk/Niger Phone survey - round 1 -
crosswalk.csv`) links Phone Pulse `id`/`resp_id_pull` to the formative
research `KEY`. **92.5% of Phone Pulse respondents (471/509) are linked** to
their formative baseline record.

```bash
cd "2_phone pulse/linkage"
python link_respondents.py --inspect     # verify column names first
python link_respondents.py               # build the linked dataset
python compare_knowledge.py              # headline: has knowledge increased?
python compare_fp_use.py                 # example: current FP use change
python compare_method_switching.py       # traditional -> modern switching
python compare_unmet_need.py             # unmet need change
python compare_attitudes.py              # attitude-item change (7 identical statements)
python compare_barriers.py               # reason-for-non-use change (same 59-reason list)

python diagnose_unlinked.py              # why the 38 unlinked Pulse respondents didn't match (counts only)
python attrition_weights.py              # attrition-adjusted baseline weights for the Pulse panel
python compare_key_indicators.py         # key indicators, baseline vs Pulse, with CIs and p-values
python compare_exposure_rounds.py        # Campaign Exposure: recall + awareness, Treatment vs Comparison, by round
```

## Key indicators and attrition weights

Run after any refresh of the formative weights (`table_analysis/rerun_weights.py`) or the
Phone Pulse data, in this order:

1. `attrition_weights.py` — each linked Pulse respondent's weight = their baseline weight ÷
   their estimated chance of being in the Pulse panel (survey-weighted logistic regression on
   state, gender, age group, FP user group, plus gender × FP use and state × gender), rescaled
   to the baseline total. Writes `outputs/attrition_weights.csv` (Pulse study ID, weights,
   location, state) and `outputs/attrition_report.txt` (counts and percentages only), including
   two checks: the panel's mix and its baseline key indicators, re-weighted, against the full
   baseline.
2. `compare_key_indicators.py` — writes `outputs/key_indicators_change.csv` (Change Over Time
   tab: baseline vs round 1 per mode, with the change in pp, its 95% CI and a two-sided
   bootstrap p-value) and `outputs/pp_headline.csv` (Phone Pulse Family Planning page:
   Treatment arm, plus campaign content recall). Phone Pulse only measures mCPR and awareness;
   unmet need, unmet demand and demand satisfied are written as `not_asked`. Pulse mCPR uses
   the baseline's modern-method list (Standard Days and LAM counted as modern). CIs use the same
   settlement draws for both waves. It also writes the seven attitude items of
   `ATTITUDE_CROSSWALK` (metrics `att_*`: % agreeing with the statement among those who answered — baseline
   "Agree", Pulse score ≥ 3 of 0–4), with the same weights, populations, CIs and p-values, from a
   separate bootstrap stream so the other indicators' CIs are unchanged. Upload both CSVs to Drive (file IDs in
   `niger_app/src/data_loader.py`).

The 38 unlinked respondents were all interviewed at baseline but removed in formative cleaning
(19 outside the sample, 10 East of Guidan Barmou, 9 under 18 minutes), so they have no
baseline weight and are left out of the weighted figures.

Every `compare_*.py` script above takes an optional `--round <round_id>`
(default: `round1`, `2_phone pulse/linkage/config.py`'s `ROUNDS`/`DEFAULT_ROUND_ID`).
Each script's output CSV gets a `round` column and re-running it for a
different round UPSERTS that round's rows into the same file rather than
overwriting other rounds' rows — so `outputs/knowledge_change_summary.csv`
(etc.) is designed to hold every round stacked together, ready for a
time-series chart. Today only `round1` has real source data; `round2`
("~6 mo") and `round3` ("~24 mo") are registered in `config.py` as
`status="pending"` placeholders — add a new row there (and, on the
cross-sectional side, a `ROUND_PULSE_DATA` entry) once that round's data
exists, no other structural change needed.

## Round 2 (~6 months): `run_round2.py`

Round 2 was interviewed in two fieldwork waves (`2_phone pulse/etl_pipeline/run_round.py split`):
`round2_early`, the 35 Haddin Kay (Dakoro, Tagriss) respondents interviewed in mid-August (~5 months),
analysed separately, and `round2`, everyone else at ~6 months. There are three analysis groups:

| | Who is included | Comparison | Main value |
|---|---|---|---|
| **A. Baseline to Round 2** | Everyone who responded to round 2 and baseline, whether or not they responded to round 1 | Baseline vs round 2 | Largest sample for the 6-month change |
| **B. Three-wave panel** | Everyone who responded to baseline, round 1 and round 2 | Baseline vs round 1 vs round 2 | Trajectory for the same people across all three points |
| **E. Early group** | The 35 `round2_early` respondents linked to baseline | Baseline vs `round2_early` | Kept apart from the 6-month results; with 35 people the weighted figures are fragile, so read the unweighted ones too |

"Responded to a Pulse round" means being in that round's QA-passed `cleaned_data.csv`.

```bash
# after `python run_round.py etl --round round2_early` (and/or round2) in 2_phone pulse/etl_pipeline/
cd "2_phone pulse/linkage"
python run_round2.py              # every group whose round has been processed (E; A and B once round2 is)
python run_round2.py --group A    # one group (A, B or E)
```

The round 1 scripts above are not changed. `run_round2.py` runs them as they are on each group, pointed at the group's own Pulse data and output folder: `link_respondents` → `attrition_weights` → the six `compare_*.py` → `compare_key_indicators`.

- **Weights.** For each group, `attrition_weights.py` models the chance of being in *that group*. For group A that is "linked to round 2"; for group B it is "in round 1 and round 2". So each group is re-weighted to the full baseline. Group B uses the same respondents and the same weights at round 1 and round 2.
- **Weighted and unweighted.** `key_indicators_change.csv` has the weighted figures plus the same figures unweighted (`unweighted_*` columns), for both groups. Those are the four sets of results. The six `compare_*.py` scripts are paired tests on the linked respondents and are unweighted, as for round 1.
- **Round 2 crosswalk / form.** If round 2 used a new roster or form, save them in `2_phone pulse/data/crosswalk/` (with "round 2" in the name) / `meta/round2/`; otherwise round 1's are used (`2_phone pulse/etl_pipeline/rounds.py`).

Outputs:

```
outputs/round2/A_baseline_round2/   *_change_summary.csv (round = round2), key_indicators_change.csv,
                                    linked_respondents.csv, attrition_weights.csv, linked_demographics.csv, reports
outputs/round2/B_three_wave/        *_change_summary.csv and key_indicators_change.csv with round = round1
                                    and round = round2 rows (baseline -> R1 and baseline -> R2, same people)
    round1/, round2/                each leg's linked data, weights, key indicators and reports
```

Round 1's files in `outputs/` are not touched. `config.py`'s `ROUNDS` still lists round 2 as `pending`. Set it to `live` when the app should show round 2. `compare_key_indicators.py` labels its console printout "R1" for every round; the CSVs carry the right `round`.

## Two comparison types

This folder (`2_phone pulse/linkage/`) holds the **longitudinal / linked** comparison —
the SAME respondents, paired across waves, using paired tests (McNemar,
Wilcoxon). `2_phone pulse/linkage/cross_sectional/` holds a second, independent
**cross-sectional** comparison — the FULL formative baseline (968
respondents) vs. each round's FULL achieved Phone Pulse sample (509 for
round 1), as two different groups of people, using independent-samples
tests (two-proportion z-test, Mann-Whitney U, chi-square). See
`cross_sectional/README.md` for that pipeline. Both cover the same six
metrics (method awareness, current FP use, method switching, unmet need,
attitudes, barriers) and both write a `round` column, so the Streamlit page
can render either as a time series with the same code.

## What we found

| Fact | Source |
|---|---|
| Crosswalk file has 533 rows: `ID`, `radio_pull_1..7`, `KEY` — no duplicate `ID` or `KEY` | Schema inspection |
| Join: formative `KEY` <-> crosswalk `KEY`, then crosswalk `ID` <-> pulse `resp_id_pull`/`id`/`id_re` (best match rate wins) | `link_respondents.py` Strategy B |
| `formative_known_contraceptive_options` is **pipe-separated bilingual (Hausa/English) label text** (e.g. `"Allurai / Injectables\|Karan damtse / Implants"`), NOT numeric SurveyCTO codes as originally assumed | Inspected `linked_respondents.csv` value_counts after the first `compare_knowledge.py` run produced an implausible 0% baseline for every method |
| `formative_current_use` is similarly bilingual text (`"Ee / Oui"` = yes, `"A'a / Non"` = no), not `1`/`0` | Same discovery — `compare_fp_use.py` also showed 0% baseline before the fix |
| The two surveys use **different numeric codes** for the same method on the Phone Pulse side (e.g. Pulse code 3 = implant) | `config.py` `METHOD_CROSSWALK`, cross-checked against `export_pp_app_data.py` `FP_METHOD_LABELS` |

**Both label-text bugs are fixed** (`config.py`'s `FORMATIVE_LABEL_TO_METHOD`,
`compare_knowledge.py`'s `_parse_known_methods`, `compare_fp_use.py`'s
Hausa-text match). Headline results as of the last run:

- **Contraceptive knowledge increased significantly** (Wilcoxon p<0.0001):
  mean comparable methods known rose from 2.32/14 (baseline) to 3.38/14
  (follow-up); 57.5% of respondents gained ≥1 method, 16.1% lost ≥1.
- **Current FP use increased significantly** (McNemar p=0.0001): 49.5% →
  61.4%.

Re-run `compare_knowledge.py` / `compare_fp_use.py` after any ETL refresh —
these numbers will shift as the underlying `cleaned_data.csv` and keep-list
change.

## Files

- `config.py` — all paths, candidate ID columns, the contraceptive
  method name-crosswalk, and `FORMATIVE_LABEL_TO_METHOD` (the bilingual
  label -> canonical method name map). **Read the comments here first.**
- `link_respondents.py` — builds the linked dataset.
  - `python link_respondents.py --inspect` — prints column names only (zero
    data rows) for all three source files. Always safe to run/share.
  - `python link_respondents.py` — runs the real join.
- `compare_knowledge.py` — the main deliverable. Per-method McNemar tests
  (baseline vs. follow-up awareness) plus an overall paired test on total
  methods known.
- `compare_fp_use.py` — current FP use, baseline vs. follow-up, same pattern
  — copy this file's structure for other "similar question" comparisons.
- `compare_method_switching.py` — traditional -> modern method switching.
- `compare_unmet_need.py` — unmet need for contraception (restricted
  definition computable on both waves — see its docstring).
- `compare_attitudes.py` — the 7 Phone Pulse `fpatt_*` items that repeat a
  baseline statement word for word (`config.py`'s `ATTITUDE_CROSSWALK`;
  `fpatt_childinvest` has no baseline match). Every baseline respondent was
  asked all the statements. Scales differ (Agree/Disagree vs 0–4 with a
  neutral midpoint), so changes are directional.
- `compare_exposure_rounds.py` — Campaign Exposure page ("Recall & awareness" tab).
  Campaign recall (`uptake_fp` = 1 and `knowledge_waiting` = "At least two years"),
  its two parts, and prompted awareness of each method, for Treatment (lives in a
  partner station's area and listened to it in the past month), Comparison (everyone
  else) and All; weighted (each round's attrition weights) and unweighted (same
  linked respondents); 95% CIs and p-values from the cluster bootstrap used by
  `compare_key_indicators.py`, for Treatment − Comparison within a round and for each
  later round − round 1. Writes `outputs/exposure_by_round.csv` (upload to Drive
  for the app: `EXPOSURE_BY_ROUND_ID`). Rounds appear once their ETL and `run_round2.py` have run.
- `compare_barriers.py` — reasons for non-use. Both surveys use the same
  59-reason list (`reason_nonuse_mc` / `fpbeh_whynot_1..59`), matched option
  by option and also rolled up to the form's reason groups (`config.py`'s
  `formative_whynot_codes`, `whynot_items`). Restricted to the ~68 linked respondents who answered
  "why not using FP" on BOTH waves — small; treat as directional only.
- `outputs/` — generated data only (linked dataset, match report, summary
  CSVs, each with a `round` column). Not committed anywhere; this folder
  isn't even under git (the Niger project root has no `.git`).
- `cross_sectional/` — the independent-samples (full baseline vs. full
  achieved sample) version of all six comparisons. See its own README.md.

## Privacy design

- `link_respondents.py` only ever writes/prints **counts and percentages**
  to the console during the join — never a respondent-level ID or answer.
- The output `linked_respondents.csv` keeps only the columns explicitly
  listed in `config.py`'s `FORMATIVE_ANALYSIS_COLUMNS` /
  `PULSE_ANALYSIS_COLUMNS` — everything else (names, phone numbers, device
  IDs, raw join keys) is dropped, with a second blocklist pass
  (`PII_BLOCKLIST_SUBSTRINGS`) as defense in depth.
- Respondents get a sequential surrogate `link_id`; no cross-survey ID
  persists into the output.
- The comparison scripts (`compare_*.py`) only ever aggregate — no
  respondent-level row is printed or written.
