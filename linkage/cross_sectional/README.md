# Cross-sectional (independent-samples) baseline-vs-follow-up comparison

Compares the FULL Formative Research baseline (968 respondents) against
each round's FULL achieved Phone Pulse sample (509 for round 1) as two
DIFFERENT groups of people — NOT the 471 respondents linked across both
waves that `../compare_*.py` (one directory up) uses. Because the two
samples are independent, every test here is an independent-samples test
(two-proportion z-test, Mann-Whitney U, chi-square of independence) rather
than the paired tests (McNemar, Wilcoxon) used on the linked side.

## Usage

```bash
cd "2_phone pulse/linkage/cross_sectional"
python compare_knowledge_unlinked.py         # method awareness
python compare_fp_use_unlinked.py            # current FP use
python compare_method_switching_unlinked.py  # method-mix shift (see caveat below)
python compare_unmet_need_unlinked.py        # unmet need
python compare_attitudes_unlinked.py         # attitude items (7 identical statements)
python compare_barriers_unlinked.py          # reasons for non-use (same 59-reason list)
```

Each script takes an optional `--round <round_id>` (default `round1`) and
UPSERTS that round's rows into its output CSV, same convention as the
linked side — see `../README.md`.

## Why cross-sectional AND longitudinal?

They answer different questions:
- **Longitudinal (linked, `../compare_*.py`)**: "did *this group's*
  answers change" — powerful (paired tests control for who's in the
  sample) but only covers the 471/968 baseline respondents who were
  successfully re-contacted and linked.
- **Cross-sectional (this folder)**: "does the population look different
  now" — covers the FULL achieved sample each round, including the ~85%
  of Phone Pulse respondents (438/509) who could NOT be linked back to a
  baseline record, at the cost of not controlling for who happens to be in
  each sample (representativeness / sampling differences between waves can
  masquerade as a "change").

## Files

- `config.py` — re-exports `../config.py`'s method crosswalk, bilingual
  label maps, and attitude/barrier crosswalks (loaded via `importlib` under
  a distinct module name to avoid the two files' name collision — see the
  comment at the top) rather than duplicating them, plus this pipeline's
  own `FORMATIVE_DATA` / `ROUND_PULSE_DATA` (per-round full Phone Pulse
  sample file) and `OUTPUT_DIR`.
- `stats_utils.py` — `two_proportion_ztest`, `mann_whitney_p`,
  `chi_square_p` — the independent-samples analogues of the linked side's
  McNemar/Wilcoxon.
- `compare_*_unlinked.py` — one per metric, mirroring `../compare_*.py`'s
  structure and column names (with `_unlinked` output filenames) so the
  Streamlit page can share rendering code across both comparison types.
- `outputs/` — generated data only, aggregate counts/percentages/test
  statistics, no respondent-level data. Not committed (no `.git` at the
  Niger project root).

## Known caveats (same crosswalks as the linked side — read those docstrings too)

- **Method switching** is inherently a paired concept ("did person X move
  from traditional to modern") — two independent samples can't show
  individual switching at all. `compare_method_switching_unlinked.py`
  instead compares the overall modern/traditional/none-or-other MIX
  between the two samples (population-level, not individual-level).
- **Attitudes**: 7 of Phone Pulse's 8 `fpatt_*` items repeat a baseline
  statement word for word (`../config.py`'s `ATTITUDE_CROSSWALK`), but the
  answer scales differ (Agree/Disagree vs 0–4 with a neutral midpoint).
- **Barriers**: both surveys use the same 59-reason list, matched option by
  option. The non-use window differs (no use in six months at baseline,
  not using now at follow-up).
- **Sample composition**: the two samples are drawn differently (in-person
  household roster vs. phone recontact of a subset) and are not
  necessarily comparable on age/gender/urbanicity/etc. — a shift shown
  here could reflect sample composition rather than a real population
  change. The Streamlit page's "Limitations" section repeats this caveat
  next to every cross-sectional chart.
