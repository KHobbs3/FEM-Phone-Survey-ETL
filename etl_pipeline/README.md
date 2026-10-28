# Niger Phone Pulse — ETL Pipeline

Cleans, validates, and summarises the phone pulse survey data collected in Niger as part of the FEM Family Planning research.

## Usage

```bash
cd etl_pipeline
python run_round.py split                   # single export -> one raw file per round
python run_round.py qa     --round round1   # QA reports (../q_a/run_qa.py)
python run_round.py etl    --round round1   # "Other" recodes + run.py --keep-list
python run_round.py export --round round1   # app tables (export_pp_app_data.py)
```

`run.py`, `export_pp_app_data.py` and `../q_a/run_qa.py` still run on their own for round 1 as before (`python run.py --keep-list ../q_a/reference_data/keep_list.csv`). `run_round.py` runs these same scripts for the round you name, with that round's paths. Either way, `run.py` recodes "Other" write-ins first (see below).

Requires Python 3.10+, `pandas` / `numpy`, `openpyxl` (reads the form) and `scikit-learn` (fuzzy matching; it falls back to `difflib` without it).

## Survey rounds

All rounds are in one SurveyCTO export, `data/raw_data/Niger  Appels de Suivi avec les Participants (haoussa)_WIDE.xlsx`. `python run_round.py split` (`split_rounds.py`) separates it into fieldwork waves: a new wave starts after a gap of 14 or more days with no submissions (`MIN_GAP_DAYS`). Waves are named in date order (`WAVE_ORDER`): `round1` (June), `round2_early` (the 35 Haddin Kay Dakoro / Tagriss respondents, mid-August, ~5 months, analysed separately) and `round2` (everyone else, ~6 months). Each is saved to `data/raw_data/by_round/<round>.xlsx`. Re-run `split` after every update of the export, and check its printout (dates and submissions per region per wave, also in `q_a/outputs/round_waves.csv`) before going on.

Each round's other paths are in `rounds.py`:

| | Round 1 | `round2_early` and `round2` |
|---|---|---|
| Raw submissions | `data/raw_data/by_round/round1.xlsx` | `data/raw_data/by_round/<round>.xlsx` |
| Form definition | `meta/Participants+_+Appels+de+Suivi.xlsx` | the `.xlsx` in `meta/round2/`, else round 1's |
| Roster crosswalk | `data/crosswalk/Niger Phone survey - round 1 - crosswalk.csv` | `data/crosswalk/*round 2*crosswalk*.csv`, else round 1's |
| QA review file | `data/q_a/Niger QA Pulse calls survey - 1st round.csv` | `data/q_a/[WIP] Niger QA Pulse calls survey - 2nd round.csv` (both groups) |
| QA flags / keep-list | `q_a/reference_data/` | `q_a/reference_data/<round>/` |
| QA reports | `q_a/outputs/` | `q_a/outputs/<round>/` |
| ETL outputs | `outputs/` | `outputs/<round>/` |
| App tables | `outputs/app_data/` | `outputs/<round>/app_data/` |
| Timeline inputs | `outputs/survey_windows.csv`, `outputs/airing_schedule.csv` (all rounds) | |

### Processing round 2 (each of `round2_early` and `round2`)

1. Save the updated export to `data/raw_data/` and the QA review file to `data/q_a/`. If the form or roster changed, also save the new form to `meta/round2/` and the new crosswalk to `data/crosswalk/` (with "round 2" in its name).
2. `python run_round.py split`.
3. `python run_round.py parse --round round2_early`. Reads `Validation status (PM)` in the QA review file (`q_a/parse_validation_status.py`): `Validated` and `Pending` go to `keep_list.csv` (analysed), `Invalid` to `manual_flags.csv` (excluded), all in `q_a/reference_data/<round>/`. Both round 2 groups read the same review file. Any other or blank status is not analysed (KEYs in `validation_status_unrecognised.csv`), nor are submissions missing from the review file. Re-run after the review file changes. (Round 1 used `parse_kh_flags.py`.)
4. `python run_round.py qa --round round2_early`. Check the QA reports before running `etl`.
5. `python run_round.py etl --round round2_early`. This refreshes and applies the "Other" recodes, then runs `run.py` with the round's keep-list. Review new rows in the recodes file and re-run if you change any.
6. In `2_phone pulse/linkage/`, run `python run_round2.py` for the baseline comparisons of every round 2 group processed so far (see `2_phone pulse/linkage/README.md`).
7. `python run_round.py export --round round2_early` writes the app tables, with formative demographics from step 6.

Repeat steps 3–7 with `--round round2` once the rest of round 2 is in the export.

## Recoding "Other (specify)" write-ins

Five questions have an "Other" (`-22`) choice with a write-in field (`OTHER_RECODE_QUESTIONS` in `config.py`, taken from the form's relevance conditions):

| Question | Write-in |
|---|---|
| `fpbeh_whynot` (reasons for not using FP) | `fpbeh_usedfp_oth` |
| `fputil_advs` (advantages of FP) | `fputil_advs_oth` |
| `fputil_disadvs` (disadvantages of FP) | `fputil_disadvs_oth` |
| `method_notavailable` (what they did when the method wasn't available) | `other_methodunavailable` |
| `oth_infsource` (sources of health information) | `other_source` |

Every `run.py` run (directly or through `run_round.py etl`) runs `other_recodes.py` on the raw export, before the keep-list and `transform.py`, in two steps:

1. **Refresh** (same as `python other_recodes.py --round <round>`). It adds each distinct write-in to `data/other_recodes/other_recodes.csv` (`OTHER_RECODES_PATH`). It reads the question's choices from the form (English label + Hausa translation; Other / don't know / refused excluded) and fuzzy-matches the write-ins against them, using the formative pipeline's matcher (`1_formative_research/pipeline_output/pipeline/other_recodes.py`, `fuzzy_suggest`). Clear matches get `recode_to` (`coded_by = fuzzy exact` / `fuzzy <score>` / `group`). The rest are left blank with 3 `candidates`. The choices go to `data/other_recodes/other_recode_choices.csv` for hand-coding. Codes already in the file are kept. The file is shared by all rounds, so a code made in round 1 applies to the same text in round 2.
2. **Apply**. When an "Other" answer's write-in has a `recode_to` that is one of the question's choices (its label, English label or code), that choice replaces "Other": in the space-separated answer, the choice's 0/1 column is set to 1 and `<question>__22` to 0. This raises that choice's share in the outputs (e.g. `pp_fp_whynot.csv`). A `recode_to` that isn't a choice on the form leaves the answer as "Other".

To review, open the recodes file, check the `fuzzy` / `group` codes, fill blank `recode_to` with a label from `other_recode_choices.csv`, and re-run `etl`. Use `--no-recode-refresh` to apply the file without the refresh. The file holds free text, so it stays in `data/`. Only counts are printed.

## What it does

1. **Extract** — reads the round's submissions from `../data/raw_data/by_round/<round>.xlsx` (written by `split`; all CSVs there if it is missing), recodes "Other (specify)" write-ins, then applies the `--keep-list`
2. **Transform** — standardises the data:
   - Replaces SurveyCTO sentinel codes (`-88` = not applicable, `-99` = don't know/refused) with `NaN`, and logs every replacement
   - Parses timestamps and computes a derived call duration for cross-checking against the reported `duration` field
   - Strips all PII columns (see below) — enforced by a hard assertion before any file is written
3. **Validate** — flags quality issues:
   - Call duration below 10 min or above 2 hours
   - Reported vs computed duration discrepancy > 2 min
   - Timestamps out of order
   - Respondent could not speak privately
   - Sampling roster information was incorrect
   - Logical inconsistencies (e.g. currently using FP but reason-not-using is populated)
   - Respondent with high rate of sentinel/missing values across attitude questions
   - Agree/disagree items (`fpatt_*`, `pressure_*`) outside 0–4 after `-88`/`-99` are removed (error: a stray code such as 5 would count as agreeing)
   - Campaign Exposure questions: `uptake_fp` answered by someone who said they don't listen to the radio (warning); `knowledge_waiting` not an answer code 1–4 (error)
   The checks only flag (`outputs/validation_report.csv`); they never drop a respondent.
4. **Stats** — generates descriptive statistics for every survey question, split by column type:
   - **Likert (0–4):** mean, median, SD, per-value distribution
   - **Binary (0/1):** yes/no counts and percentages
   - **Multi-select:** per-option counts and % of respondents who selected each option
   - **Categorical/ordinal:** value counts
   - **Continuous numeric:** mean, median, SD, min/max, quartiles

## Outputs

All outputs are written to `outputs/` and contain no PII.

```
outputs/
├── cleaned_data.csv          All 50 respondents, PII removed, sentinels replaced
├── validation_report.csv     Per-respondent quality issues (severity: error/warning/info)
├── sentinel_log.csv          Audit log of every -88/-99 replacement (respondent × column)
└── stats/
    ├── likert.csv            Attitude scale summaries (self/spouse/community perceptions)
    ├── binary.csv            Yes/no question summaries
    ├── multiselect.csv       FP method awareness, reasons, advantages, media topics, etc.
    ├── categorical.csv       Ordinal and single-choice question summaries
    ├── numeric.csv           Call duration, travel time, media hours per day, etc.
    └── sentinel_rates.csv    How frequently each sentinel code appears per column
```

## PII handling

The following columns are dropped before any output is written. The pipeline raises an exception if any of them are present in the output DataFrame.

| Column | Contains |
|---|---|
| `name_pull` | Respondent name from sampling roster |
| `correct_name` | Corrected respondent name |
| `compensation_name` | Name collected for airtime compensation |
| `compensation_phone` | Phone number collected for airtime compensation |
| `devicephonenum` | Enumerator device phone number |
| `deviceid` | Device hardware identifier |
| `subscriberid` | SIM subscriber identifier |
| `simid` | SIM card identifier |
| `username` | Enumerator SurveyCTO login (duplicated by `enumerator` field) |

Geographic fields (`lga_pull`, `village_pull`) are retained for analysis. In combination with names they could be identifying, but names are removed so the residual re-identification risk is low for a survey of this scale.

## Configuration

All thresholds and column classifications are in `config.py`:

- `MIN_DURATION_SECONDS` / `MAX_DURATION_SECONDS` — acceptable call length bounds
- `DURATION_DISCREPANCY_THRESHOLD` — max tolerable gap between reported and computed duration
- `PII_COLUMNS` — columns to drop
- `MULTISELECT_COLUMNS`, `LIKERT_COLUMNS`, `BINARY_COLUMNS`, etc. — drive the stats dispatch logic

## File structure

```
etl_pipeline/
├── config.py         Central configuration
├── rounds.py         Paths for each survey round; wave order and gap for split
├── run_round.py      Entry point for any round: split, parse, QA, recodes + ETL, app export
├── split_rounds.py   Single export -> data/raw_data/by_round/<round>.xlsx (run_round.py split)
├── export_survey_windows.py  First/last submission date per survey (Airing Timeline tab)
├── other_recodes.py  "Other (specify)" write-in recoding (fuzzy matching)
├── extract.py        Data loading
├── transform.py      Standardisation, PII removal, QA columns
├── validate.py       Quality checks
├── stats.py          Descriptive statistics
├── run.py            Round 1 ETL entry point (run by run_round.py)
├── export_pp_app_data.py  App tables (run by run_round.py)
└── outputs/          Generated on each run (not committed); outputs/<round>/ for later rounds
```
