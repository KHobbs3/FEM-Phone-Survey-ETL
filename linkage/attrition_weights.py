"""
Attrition-adjusted baseline weights for the Phone Pulse panel.

Phone Pulse re-interviewed a subset of formative-research (baseline)
respondents by phone. Each linked Pulse respondent keeps their baseline
design weight, divided by their estimated chance of ending up in the Pulse
panel, so the panel is re-weighted to look like the full baseline:

    attrition_weight = baseline_weight / P(in panel | baseline characteristics)

P(in panel) comes from a survey-weighted logistic regression, fitted on all
baseline respondents, of "linked to Phone Pulse round 1" on state, gender,
age group and FP user group (ATTRITION_COVARIATES) plus gender x FP user
group and state x gender (ATTRITION_INTERACTIONS). The weights are then
rescaled so they sum to the full baseline's weight total.

Assumption: within groups that share those characteristics, the people who
were reached by phone resemble the people who weren't (missing at random).
The balance and indicator checks printed below show how well the adjusted
panel reproduces the full baseline.

Usage:
    python attrition_weights.py

Output (study IDs, weights and design columns only -- no answers):
    outputs/attrition_weights.csv   resp_id_pull, baseline_weight,
                                    response_propensity, attrition_weight,
                                    location, state
    outputs/attrition_report.txt    counts and percentages only
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg

sys.path.insert(0, str(cfg.NIGER_ROOT / "1_formative_research" / "pipeline_output"))
from pipeline import etl_family_planning as fp  # noqa: E402  (headline indicator logic)

WEIGHT_COL = "combined_weight_adjusted"
ATTRITION_COVARIATES = ["state", "gender", "age_group", "use"]
# Who was reachable by phone depended on combinations of traits (e.g. women who
# used FP were harder to reach than either trait alone predicts). Of the variants
# compared on 2026-10-26 -- main effects only, these interactions, raking on the
# four traits, raking + gender x use -- this one had the smallest gaps on the
# baseline key indicators, the largest effective sample and the least extreme
# weights.
ATTRITION_INTERACTIONS = [("gender", "use"), ("state", "gender")]
DESIGN_COLS = ["location", "state"]
HEADLINE_COLS = ["current_use", "current_use_methods", "time_before_preferred_pregnancy",
                 "future_intent", "known_contraceptive_options"]
ATTRITION_WEIGHTS_CSV = cfg.OUTPUT_DIR / "attrition_weights.csv"
ATTRITION_REPORT_TXT = cfg.OUTPUT_DIR / "attrition_report.txt"


def _fit_logistic(X: np.ndarray, y: np.ndarray, w: np.ndarray,
                  ridge: float = 1e-6, iters: int = 50) -> np.ndarray:
    """Survey-weighted logistic regression by Newton-Raphson; returns fitted
    probabilities. Weighting the fit by the baseline design weight makes the
    adjusted panel reproduce the *weighted* baseline mix, not the raw one."""
    w = w / w.mean()
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ beta))
        grad = X.T @ (w * (y - p)) - ridge * beta
        hess = X.T @ (X * (w * p * (1 - p))[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.abs(step).max() < 1e-10:
            break
    return 1 / (1 + np.exp(-X @ beta))


def _wshare(mask: pd.Series, w: pd.Series) -> float:
    return float(w[mask].sum() / w.sum())


def main() -> None:
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    formative = pd.read_csv(cfg.FORMATIVE_DATA, low_memory=False,
                            usecols=["KEY", WEIGHT_COL, *ATTRITION_COVARIATES, *DESIGN_COLS, *HEADLINE_COLS])
    formative = formative.loc[:, ~formative.columns.duplicated()]
    cw = pd.read_csv(cfg.CROSSWALK_FILE, usecols=["ID", "KEY"], low_memory=False).astype(str)
    pulse_ids = pd.read_csv(cfg.PULSE_DATA, usecols=["resp_id_pull"], low_memory=False)["resp_id_pull"]

    cw = cw.apply(lambda s: s.str.strip())
    key_to_pulse = (cw[cw["ID"].isin(set(pulse_ids.dropna().astype(str).str.strip()))]
                    .drop_duplicates("KEY").set_index("KEY")["ID"])
    formative["KEY"] = formative["KEY"].astype(str).str.strip()
    formative["resp_id_pull"] = formative["KEY"].map(key_to_pulse)
    in_panel = formative["resp_id_pull"].notna()
    w = formative[WEIGHT_COL]

    out(f"Baseline respondents: {len(formative)}   in Pulse panel (linked): {int(in_panel.sum())} "
        f"({in_panel.mean():.1%} unweighted, {_wshare(in_panel, w):.1%} weighted)")

    # ── Response propensity ──────────────────────────────────────────────────
    cov = formative[ATTRITION_COVARIATES].astype(str).fillna("missing")
    model_terms = cov.copy()
    for a, b in ATTRITION_INTERACTIONS:
        model_terms[f"{a} x {b}"] = cov[a] + " | " + cov[b]
    X = pd.get_dummies(model_terms, drop_first=True, dtype=float)
    X.insert(0, "intercept", 1.0)
    p = _fit_logistic(X.to_numpy(), in_panel.to_numpy(dtype=float), w.fillna(0).to_numpy())
    formative["response_propensity"] = p

    adj = w / formative["response_propensity"]
    adj = adj.where(in_panel)
    adj *= w.sum() / adj.sum()
    formative["attrition_weight"] = adj
    panel = formative[in_panel]

    pp = panel["response_propensity"]
    ratio = panel["attrition_weight"] / panel[WEIGHT_COL]
    out(f"Response propensity among panel: min {pp.min():.2f}, median {pp.median():.2f}, max {pp.max():.2f}")
    out(f"Weight inflation (attrition / baseline weight, rescaled): "
        f"min {ratio.min():.2f}, median {ratio.median():.2f}, max {ratio.max():.2f}")
    def n_eff(x):
        return x.sum() ** 2 / (x ** 2).sum()
    out(f"Effective sample size: full baseline {n_eff(w):.0f} of {len(formative)}; "
        f"panel with baseline weights {n_eff(panel[WEIGHT_COL]):.0f} of {len(panel)}; "
        f"panel with attrition weights {n_eff(panel['attrition_weight']):.0f} of {len(panel)}")

    # ── Check 1: balance on the adjustment characteristics ───────────────────
    out("\nCheck 1 - who is in the panel (weighted %): full baseline | panel, baseline weights | panel, attrition weights")
    for col in ATTRITION_COVARIATES:
        out(f"  {col}")
        for val in sorted(cov[col].unique()):
            full = _wshare(cov[col] == val, w)
            raw_ = _wshare(cov.loc[in_panel, col] == val, panel[WEIGHT_COL])
            adj_ = _wshare(cov.loc[in_panel, col] == val, panel["attrition_weight"])
            out(f"    {str(val)[:30]:<30} {full:6.1%} | {raw_:6.1%} | {adj_:6.1%}")

    # ── Check 2: key indicators the adjustment did NOT target ────────────────
    for c in ("current_use_methods", "known_contraceptive_options"):
        formative[c] = formative[c].apply(fp._strip_hausa)
    flags = fp._headline_flags(formative)
    women = formative["gender"].fillna("").str.contains("Femme|Female").to_numpy()
    out("\nCheck 2 - baseline key indicators: full baseline | panel, baseline weights | panel, attrition weights")
    for pop_name, pop in [("Full sample", np.ones(len(formative), dtype=bool)), ("All women", women)]:
        full = fp._headline_values(w.fillna(0).to_numpy(), pop, flags)
        base = fp._headline_values(w.where(in_panel, 0).fillna(0).to_numpy(), pop, flags)
        att = fp._headline_values(formative["attrition_weight"].fillna(0).to_numpy(), pop, flags)
        out(f"  {pop_name}")
        for m in full:
            out(f"    {m:<24} {full[m]:6.1%} | {base[m]:6.1%} | {att[m]:6.1%}")

    cfg.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel.rename(columns={WEIGHT_COL: "baseline_weight"})[
        ["resp_id_pull", "baseline_weight", "response_propensity", "attrition_weight", *DESIGN_COLS]
    ].to_csv(ATTRITION_WEIGHTS_CSV, index=False)
    ATTRITION_REPORT_TXT.write_text("\n".join(lines) + "\n")
    out(f"\nWritten: {ATTRITION_WEIGHTS_CSV.name}, {ATTRITION_REPORT_TXT.name}")


if __name__ == "__main__":
    main()
