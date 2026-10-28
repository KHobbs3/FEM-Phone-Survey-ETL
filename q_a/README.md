# Niger Phone Pulse — Quality Assurance

Scripts for detecting invalid and anomalous survey submissions before analysis.

## Usage

```bash
cd q_a
python run_qa.py          # full QA run (recommended)

python check_true_invalids.py   # true invalid checks only
python check_anomalies.py       # anomaly checks only

python compare_duplicates.py              # similarity scoring for duplicate resp_id_pull
python compare_duplicates.py --cleaned    # use cleaned data (no name_pull PII)
python compare_duplicates.py --demo       # inject a synthetic duplicate to test the pipeline
```

Each round's raw submissions come from `etl_pipeline/run_round.py split`, which splits the
single export (`data/raw_data/Niger  Appels de Suivi avec les Participants (haoussa)_WIDE.xlsx`)
into `data/raw_data/by_round/<round>.xlsx`. On its own, `run_qa.py` checks round 1
(`by_round/round1.xlsx`); for other rounds use `python run_round.py qa --round <round>` from
`etl_pipeline/`, which writes to `outputs/<round>/`.

### Parsing the manual QA review into flags / keep-list

| Round | Script | Reads | Writes |
|---|---|---|---|
| 1 | `parse_kh_flags.py` | `data/q_a/Niger QA Pulse calls survey - 1st round.csv`, column `KH processing actions` | `reference_data/manual_flags.csv`, `kh_flags_summary.csv` |
| 2 onwards | `parse_validation_status.py --round <round>` | `data/q_a/[WIP] Niger QA Pulse calls survey - 2nd round.csv`, column `Validation status (PM)` | `reference_data/<round>/keep_list.csv` (Validated + Pending), `manual_flags.csv` (Invalid), `validation_status_summary.csv`, `validation_status_unrecognised.csv` (any other or blank status) |

Both run through `python run_round.py parse --round <round>` (from `etl_pipeline/`).

## Setup required before first production run

Two reference files need to be populated before the QA checks can run at full depth:

**`reference_data/manual_flags.csv`**
Add one row per submission manually confirmed as invalid (training data, fabrication, etc.). The `KEY` column must match the UUID `KEY` field in the survey data.

**`reference_data/station_whitelist.csv`**
Marion to confirm which radio stations are genuinely broadcast in each LGA. This drives the placebo listenership check. Placeholder entries are already in the file — update and remove the `PLACEHOLDER` notes before use.

**`config_qa.py` → `TRAINING_CUTOFF_DATE`**
Set this to the survey go-live date (e.g. `"2026-01-15"`) once confirmed. All submissions before this date will be flagged as probable training data.

---

## Outputs

All outputs are written to `q_a/outputs/`.

| File | Contents |
|---|---|
| `true_invalids_report.csv` | Manually confirmed invalids, training data, duplicate / wrong IDs |
| `anomaly_report.csv` | All potential anomalies for review (duration, placebo, honesty, etc.) |
| `qa_summary.csv` | One row per affected respondent with their highest flag and all issues combined |
| `pair_similarity_scores.csv` | Per-pair similarity scores for duplicate `resp_id_pull` values (**contains `name_pull` PII — keep internal**) |
| `duplicate_summary.csv` | One row per respondent ID with worst-pair verdict and score range |

**Flag types:**
- `exclude` — strong case for exclusion from analysis (manually confirmed, or clearly erroneous)
- `review` — needs human judgment before a decision is made
- `note` — informational; unlikely to affect analysis but logged for awareness

---

## Checks

### True invalid detection (`check_true_invalids.py`)

| Check | Flag | Logic |
|---|---|---|
| **Manual flags** | `exclude` | Submission KEY is listed in `reference_data/manual_flags.csv` |
| **Training data** | `exclude` | SubmissionDate is before `TRAINING_CUTOFF_DATE` (config_qa.py) |
| **ID re-entry mismatch** | `review` | `id ≠ id_re` — the enumerator's two entries of the participant ID do not match, indicating a likely data-entry error |
| **Duplicate respondent IDs** | `review` / `note` | The same `resp_id_pull` appears more than once. Sub-cases: (a) demographics differ → probable wrong ID entered; (b) demographics same but answers differ → repeat contact with inconsistency; (c) identical records → duplicate submission |

**On the "wrong ID" problem:** Enumerators fill in the participant ID by hand; typos or confusion about the list can cause the form to pull roster data (name, LGA, village, assigned radio stations) for the wrong person. The re-entry mismatch check (`id ≠ id_re`) is the cleanest early signal. Duplicate `resp_id_pull` values are a secondary signal but require judgment: the same person may legitimately be called 2–3 times across survey waves.

---

### Anomaly detection (`check_anomalies.py`)

#### 1. Duration anomalies

| Sub-check | Flag | Threshold |
|---|---|---|
| Call very short | `review` | < 10 min (600s) |
| Call short | `review` | 10–15 min (600–900s) |
| Call very long | `review` | > 90 min (5400s) |
| Call longer than expected | `note` | > 75 min (4500s) |
| Reported vs computed discrepancy | `review` | Gap > 120s between `duration` field and `endtime − starttime` |
| Section too short | `review` | Any `dur_*` section < 60s |
| Section sum > total duration | `review` | Sum of all `dur_*` columns exceeds `duration` by > 20% |

**Field note:** If an enumerator saves the form mid-interview and reopens it later, the system timer continues running, inflating `endtime − starttime` while the SurveyCTO-reported `duration` field stays accurate. When the two diverge by > 2 minutes, flag for review but do not automatically exclude — the reported `duration` is usually the more reliable figure in these cases.

Expected average call duration: **~25 minutes**.

#### 2. Placebo station listenership

The survey includes one fake ("placebo") radio station per respondent, chosen from stations that do not broadcast in their area. If a respondent says they listened to this station, their responses may be fabricated.

| Sub-check | Flag | Logic |
|---|---|---|
| Placebo claimed, station not real in LGA | `review` | `radio_partner_placebo_listen = 1` AND `radio_placebo_pull` is not in `station_whitelist.csv` for this LGA |
| Placebo claimed, station IS real in LGA | `review` | `radio_partner_placebo_listen = 1` AND `radio_placebo_pull` IS in the whitelist — the enumerator likely entered the wrong participant ID, causing the wrong station to be assigned as the placebo |
| No whitelist available | `review` | Placebo claimed but station cannot be verified without the whitelist |
| FP content heard on placebo (without listening) | `review` | `uptake_fp_freq_radio_placebo > 0` but `radio_partner_placebo_listen ≠ 1` |

**Known name variants:** `Radio Sarounia` and `Radio Saraounia` appear in the data and may refer to the same station. Similarly, `Radio Anfani Maradi` and `Radio Anfani Zinder` may both appear as `Radio Anfani`. The script normalises to lowercase and checks a hardcoded alias table — update `STATION_ALIASES` in `check_anomalies.py` as new variants are discovered.

#### 3. Honesty / overheard indicators

| Sub-check | Flag | Logic |
|---|---|---|
| `overheard_yn = 1` | `review` | Enumerator directly recorded that the respondent was overheard during the interview — answers may reflect social desirability rather than true views |
| Note — high concern keyword | `review` | `notes_enumerator` contains words like: *overheard*, *overhead*, *not freely*, *not honest*, *pressured*, *others present*, *others listening* |
| Note — medium concern keyword | `note` | `notes_enumerator` contains: *distracted*, *background noise*, *hesitant*, *interrupted* |

Note: `overheard_yn` is the more reliable signal; the notes keyword check is a backstop for cases where the enumerator wrote their concern in free text but did not tick the structured field.

#### 4. Straightlining on attitude scales

| Flag | Logic |
|---|---|
| `review` | ≥ 80% of valid Likert attitude items (`fpatt_*` columns) answered with the same scale value |

Straightlining — repeatedly selecting the same answer across a long question battery without engaging with individual items — is a recognised form of satisficing in phone surveys. It is most detectable in the `fpatt_*` attitude blocks (self / spouse / community perceptions of FP). Threshold: 80% same value across ≥ 5 valid responses.

#### 5. Implausible values

| Sub-check | Flag | Logic |
|---|---|---|
| Excessive media hours | `review` | `radio_hours`, `tv_hours_per_day`, or `social_media_hours_per_day` > 16 |
| EDD before interview | `review` | Estimated due date is earlier than the interview date |
| Section sum > total | `review` | Sum of `dur_*` section columns > `duration` × 1.2 |

#### 6. Radio / media consistency

| Sub-check | Flag | Logic |
|---|---|---|
| Radio skip but stations answered | `review` | `radio_any = 0` but one or more `radio_partner_*_listen` columns have responses |
| All stations listened to | `note` | Respondent reports listening to all partner stations — statistically unusual |

The first check typically indicates a skip-logic error or enumerator who did not follow the routing correctly (answered station-level questions for a respondent who said they don't listen to radio).

#### 7. Enumerator-level patterns

These are statistical signals across an enumerator's full set of submissions, not individual records. Checks apply only when an enumerator has ≥ 3 submissions.

| Sub-check | Flag | Logic |
|---|---|---|
| Short average duration | `review` | Enumerator's mean call duration is ≥ 1.5 SD below the dataset mean |
| Uniform call durations | `review` | Coefficient of variation < 5% across ≥ 5 calls (suspiciously identical lengths may indicate fabricated submissions) |
| High overheard rate | `note` | ≥ 40% of this enumerator's interviews were overheard AND rate is > 2× the dataset average |
| High placebo listenership rate | `review` | ≥ 30% of respondents reported listening to the placebo AND rate is > 2× the dataset average — may indicate coaching or leading questions |

---

## Decision guidance

Not all flags warrant exclusion. Suggested workflow:

1. Start with `exclude` flags in `qa_summary.csv` — these can generally be excluded without further review.
2. Review all `review` flags, grouping by `category`. Many will have innocent explanations (e.g., duration discrepancy from a mid-call save).
3. `note` flags can be skimmed; they are unlikely to affect analysis but are logged for transparency.
4. For placebo and honesty flags, consider running a sensitivity analysis: compare key outcomes with and without flagged respondents.
5. Add confirmed invalids to `reference_data/manual_flags.csv` so they are always excluded in future runs.

---

## Similarity scoring for duplicate IDs (`compare_duplicates.py`)

When the same `resp_id_pull` appears more than once, this script computes a pairwise similarity score to answer: **are these two submissions the same person, or was the ID entered for the wrong respondent?**

The script uses `recordlinkage` to compare one representative column from each survey section:

| Column | Section | Comparison | Weight | Rationale |
|---|---|---|---|---|
| `name_pull` | Identity | Jaro-Winkler string | 3.0 | Strongest identity anchor; tolerates spelling variants |
| `lga_pull` | Identity | Exact | 2.0 | Should never change |
| `village_pull` | Identity | Exact | 2.0 | Should never change |
| `gender_pull` | Identity | Exact | 2.0 | Immutable — mismatch is near-certain wrong ID |
| `age` | Identity | Gaussian (scale=5 yr) | 1.5 | Stable, may differ by 1 across annual waves |
| `current_pregnant` | Fertility | Exact | 1.0 | May change between waves |
| `fpbeh_fpnow` | FP behaviour | Exact | 1.0 | May change between waves |
| `fptutil_any` | FP utilisation | Exact | 1.0 | Wave-specific |
| `fpatt_immoral` | FP attitudes | Gaussian (scale=1) | 1.5 | Slow-changing — mismatch suggests wrong ID |
| `fpatt_dontplan` | FP attitudes | Gaussian (scale=1) | 1.5 | Slow-changing |
| `info_newpregnancy` | Information | Gaussian (scale=1) | 1.0 | Fairly stable knowledge item |
| `partner_talk_fp_time` | Partner | Gaussian (scale=2) | 0.8 | May change between waves |
| `radio_any` | Radio | Exact | 1.0 | Generally stable |
| `lastspoke_try` | Access | Exact | 0.8 | Wave-specific |
| `pressure_pnorm` | Pressure/norms | Gaussian (scale=1) | 1.0 | Fairly stable |

**Weighted score** = Σ(score × weight) / Σ(weight). Columns missing from the data are skipped and their weight removed from the denominator.

**Verdicts:**
- **`same_person`** (score ≥ 0.80) — genuine repeat contact; demographics and attitudes consistent
- **`review_needed`** (score 0.55–0.79) — some differences; may be same person with changed circumstances
- **`probable_wrong_id`** (score < 0.55) — too dissimilar to be the same person; likely ID entry error

**Note on PII:** `name_pull` is included in the comparison. `pair_similarity_scores.csv` contains respondent names and must not be shared outside the research team.

---

## File structure

```
q_a/
├── config_qa.py                   QA-specific configuration (column names, thresholds)
├── check_true_invalids.py         Manual flags, training data, ID / duplicate checks
├── check_anomalies.py             Duration, placebo, honesty, straightlining, implausible
├── compare_duplicates.py          Similarity scoring for duplicate resp_id_pull values
├── run_qa.py                      Master runner — runs all checks and writes outputs
├── parse_kh_flags.py              Round 1 manual QA review -> manual_flags.csv
├── parse_validation_status.py     Round 2+ 'Validation status (PM)' -> keep_list.csv / manual_flags.csv
├── reference_data/
│   ├── manual_flags.csv           ← populate with confirmed invalid KEYs
│   └── station_whitelist.csv      ← Marion to confirm LGA → real station mapping
└── outputs/                       Created on first run
    ├── true_invalids_report.csv
    ├── anomaly_report.csv
    ├── qa_summary.csv
    ├── pair_similarity_scores.csv  ⚠ contains name_pull PII — internal only
    └── duplicate_summary.csv
```
