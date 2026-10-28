# FEM Phone Survey ETL

Phone survey (Phone Pulse) processing and baseline linkage, one branch per country,
the same pattern as the formative-research ETL repo.

| Branch | Country | Working copy |
|---|---|---|
| `niger` | Niger | `Niger/2_phone pulse/` |
| `benin` | Benin | `Benin/2_phone pulse/` (not started) |
| `togo` | Togo | `Togo/2_phone pulse/` (not started) |

`main` holds only this README and the shared `.gitignore`.

## Layout (country branches)

```
2_phone pulse/
├── etl_pipeline/   raw SurveyCTO export -> cleaned data -> app tables (export_pp_app_data.py)
├── q_a/            quality checks; reference_data/ holds per-respondent decisions (local only)
├── analysis/       one-off analyses
├── linkage/        link phone respondents to the baseline; baseline vs phone comparisons
│   └── cross_sectional/   the same comparisons as independent samples
├── data/           raw and intermediate data            (never committed)
└── meta/           forms, airing plans, budgets         (never committed)
```

Scripts find the baseline through relative paths (`../1_formative_research/...`), so the
working copy must sit inside the country folder next to `1_formative_research/`.

## Participant data

Never commit survey data or anything derived from it. The `.gitignore` excludes `data/`,
`meta/`, every `outputs/` folder, SurveyCTO exports (`*_WIDE*`), per-respondent QA files,
and data-like files (CSV, Excel, JSON, notebooks, audio, images, documents) except the
named allowlist at its end. Before each commit, check `git status` lists only code and
documentation.

## Sharing a fix across countries

Commit the fix on one country branch, then `git cherry-pick <commit>` onto the others.
