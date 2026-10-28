# Niger Phone Pulse — Follow-up analysis

Three analyses requested on top of the existing `etl_pipeline/` + `q_a/`
pipeline output. All read only `etl_pipeline/outputs/cleaned_data.csv`
(PII-stripped) and the already-published `pp_*.csv` aggregate tables in
`etl_pipeline/outputs/app_data/` — never the raw SurveyCTO exports in
`data/`. Every script writes aggregated results to `outputs/`; the one
respondent-level export (`alheri_incongruent_respondents.csv`) carries no PII
(geography + roster ID only, same policy as `q_a/outputs/anomaly_report.csv`).

Run after `etl_pipeline/run.py` (and ideally after
`etl_pipeline/export_pp_app_data.py`, which `personas_users_vs_nonusers.py`
depends on):

```bash
cd analysis
python3 effective_fp_use.py
python3 personas_users_vs_nonusers.py
python3 alheri_credibility_check.py
```

## 1. `effective_fp_use.py` — is "currently using FP" inflated by non-effective methods?

fpbeh_fpnow ("are you currently doing/using something to delay or avoid
pregnancy") is binary and method-agnostic — a "yes" can include traditional
methods. fpbeh_which_1..17 records the specific method(s), so the script
splits the headline rate into modern/effective vs traditional-only vs
unrecorded, overall and by `gender_pull`. Modern/traditional classification
reuses `etl_pipeline/export_pp_app_data.py`'s `MODERN_METHOD_CODES`
(DHS/FP2020 convention) so the two scripts can't drift apart.

**Finding:** the inflation is modest. 61.7% report current use
(`fpbeh_fpnow`); 58.5% of the whole sample is on a modern/effective method —
a 3.1pt gap. Men: 65.7% → 61.9% (3.8pt gap). Women: 48.3% → 47.5% (0.8pt
gap). "Other traditional" (16.2% of male users) is the largest single
traditional-method contributor. See
`outputs/effective_fp_use_summary.csv` and `outputs/effective_fp_use_method_mix.csv`.

## 2. `personas_users_vs_nonusers.py` — FP users vs non-users, profile comparison

Reuses the `fp_use`-split tables already built by `export_pp_app_data.py`
(`pp_*.csv`, Treatment/QA-passed analysis population, n=414) instead of
recomputing — pulls every "Using FP" vs "Not using FP" row across ~30
question domains, computes the gap, and ranks by size.

**Finding:** the two personas are similar on most items (attitudes, radio
habits, social norms) — differences cluster in a handful of
access-to-services and knowledge items, which is close to definitional
(access questions are largely gated on being a user in the first place).
Largest gaps: access to a facility ever attempted (+41.9pt), used a health
centre (+40.7pt), "neither likely nor unlikely" pregnancy-chance
non-answer (−37.3pt, i.e. users are more decisive/informed), no religious
influence on FP decisions (+30pt), method awareness (Implant +18.1pt,
Injectables +16.9pt). See `outputs/persona_comparison_full.csv` (complete,
ranked), `outputs/persona_top_differences.csv` (top 25), and
`outputs/personas_summary.md` (narrative).

## 3. `alheri_credibility_check.py` — is FP-content recall on Alheri (and other stations) credible?

Alheri refused to carry FEM's FP content, so any respondent reporting having
heard FP programs/ads on it (`uptake_fp_freq_radio_N > "Never"`) is reporting
something that, per the project team, could not have happened. Station
identity is resolved by name (not slot number — `radio_pull_N` is a
different real station per respondent), reusing
`export_pp_app_data.py`'s `melt_station_slots` rather than re-implementing
the fuzzy station-name matching.

**Finding — bigger than an Alheri-specific problem.** Among self-reported
listeners, Alheri's FP-content-recall rate is 88.2% — high in absolute
terms, but actually *at the low end* of the range across all 21 partner
stations (50–100%, median 93.8%). Nearly every station shows a
90%+ "heard FP content" rate among people who say they listen to it,
including stations with very few listeners (e.g. Aissami: 1 listener,
100% recall). That pattern — recall rate tracking listenership almost
1:1 regardless of station — is the real credibility flag: it looks like
"I listen to it" and "I've heard FP content on it" are being answered
together as a pair, rather than the second question reflecting distinct,
specific memory. **This means other stations' FP-recall numbers deserve the
same scrutiny as Alheri's, not just Alheri's.**

30 of 34 self-reported Alheri listeners (of 103 respondents assigned Alheri
in some slot) report hearing FP content there. 28 of those 30 also report
FP content on *every other* station they claim to listen to
(straightlining), rather than singling out Alheri — consistent with a
general answer-pattern issue, not confusion specific to Alheri. Notably,
10 of these 30 respondents have a sentinel `-99_*` roster ID — a 53% hit
rate against only 19 such respondents in the whole 509-row dataset (vs. 5.9%
base rate), worth a manual look at that batch specifically. None of the 30
were already flagged in `q_a/outputs/qa_summary.csv` or
`true_invalids_report.csv` — this is a new signal, not a duplicate of the
existing QA checks.

Outputs: `outputs/station_fp_recall_rates.csv` (all 21 stations + placebo
variants, for context) and `outputs/alheri_incongruent_respondents.csv`
(the 30 respondents, for manual review — includes their roster ID, LGA/village,
gender, Alheri listen/frequency answer, and how their other assigned
stations answered the same question, so a reviewer can judge each case).
