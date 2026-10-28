"""
Key indicators (mCPR, unmet need, unmet demand, demand satisfied, awareness)
at baseline and Phone Pulse round 1, with 95% CIs.

Run after attrition_weights.py:
    python compare_key_indicators.py

Weighting: baseline uses its design weight. Phone Pulse has no design
weights of its own, so Pulse respondents use attrition_weights.csv (their
baseline weight / chance of being in the Pulse panel). Only the 471 linked
Pulse respondents have one; the 38 unlinked are left out of every figure.

Phone Pulse only measures three of the six indicators:
  - mCPR                       fpbeh_fpnow + fpbeh_which
  - awareness (all/non-users)  fpbeh_awarefp -- read aloud (aided recall), vs
                               baseline's unprompted list, so expect higher
  Unmet need / unmet demand / demand satisfied are not measurable: Pulse never
  asks *when* the next child is wanted, nor about future use. Those rows are
  written with status "not_asked" and no value.

"Modern method" follows the baseline headline definition (sterilisation,
implant, IUD, injectables, pill, emergency contraception, condoms, ring,
vaginal barrier, patch, Standard Days (12), LAM (13)) -- the same list as the
other Phone Pulse pages.

Outputs (aggregates only):
  outputs/key_indicators_change.csv  baseline vs round 1, per comparison mode:
      cross_sectional -- full baseline vs. weighted Pulse panel (all arms)
      longitudinal    -- the same linked panel at both waves, same weights
  outputs/pp_headline.csv            Phone Pulse FP page: Treatment arm
                                     (FEM-station listeners), weighted; also
                                     campaign_recall (see KNOWLEDGE_WAITING_CORRECT)
CIs: Rao-Wu cluster bootstrap on the baseline design (settlement within
state), same as the formative pipeline. Attrition weights are treated as
fixed, so the Pulse CIs are slightly too narrow.

key_indicators_change.csv also carries unweighted_* columns: the same
respondents, populations, cluster bootstrap and replicate draws, but everyone
who has a weight counts once -- so weighted vs unweighted differ only by the
weighting.
"""

import sys

import numpy as np
import pandas as pd

import config as cfg

sys.path.insert(0, str(cfg.NIGER_ROOT / "1_formative_research" / "pipeline_output"))
sys.path.insert(0, str(cfg.NIGER_ROOT / "2_phone pulse" / "etl_pipeline"))
from pipeline import etl_family_planning as fp  # noqa: E402
from export_pp_app_data import compute_fem_partner_listener, GENDER_FEMALE_RAW  # noqa: E402

WEIGHT_COL = "combined_weight_adjusted"
ATTRITION_WEIGHTS_CSV = cfg.OUTPUT_DIR / "attrition_weights.csv"
KEY_INDICATORS_CSV = cfg.OUTPUT_DIR / "key_indicators_change.csv"
PP_HEADLINE_CSV = cfg.OUTPUT_DIR / "pp_headline.csv"

PULSE_MODERN_CODES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17]   # baseline-consistent; includes 12 SDM, 13 LAM
PULSE_MEASURED = ["mcpr", "aware_modern", "aware_modern_nonusers"]
# Campaign content recall (Phone Pulse page only -- no campaign at baseline):
# heard FP programmes/ads on the radio (uptake_fp = 1) AND knows the campaign's
# spacing message (knowledge_waiting = 3, "At least two years"). Share of
# everyone in the column; anyone who didn't hear it counts as "no".
KNOWLEDGE_WAITING_CORRECT = 3
PULSE_PAGE_METRICS = PULSE_MEASURED + ["campaign_recall"]
ROUND_ID = cfg.DEFAULT_ROUND_ID

# Attitude items (config.ATTITUDE_CROSSWALK, as compare_attitudes.py): % agreeing
# with the statement, among those who answered the item -- baseline: "Agree" of
# Agree/Disagree answers; Phone Pulse: score >= 3 of 0-4. Metric name per Phone
# Pulse item.
ATTITUDE_METRICS = {"fpatt_steril": "att_stops_conceiving", "fpatt_immoral_2": "att_not_promiscuity",
                    "fpatt_knowledge": "att_lacks_information", "fpatt_dontplan": "att_birth_all_children",
                    "fpatt_immoral": "att_religious_leaders", "fpatt_femresponsible": "att_spouse_approval",
                    "fpatt_finance": "att_many_children"}
# Own bootstrap stream, drawn after everything above, so adding these rows
# leaves every other indicator's CIs exactly as before.
ATTITUDE_SEED_OFFSET = 2


def _any_selected(df, prefix, codes):
    cols = [f"{prefix}_{c}" for c in codes if f"{prefix}_{c}" in df.columns]
    if not cols:
        return np.zeros(len(df), dtype=bool)
    return (df[cols].apply(pd.to_numeric, errors="coerce").fillna(0) == 1).any(axis=1).to_numpy()


def _pulse_flags(df):
    using_any = pd.to_numeric(df["fpbeh_fpnow"], errors="coerce").eq(1).to_numpy()
    zeros = np.zeros(len(df), dtype=bool)
    return {
        "any":    using_any,
        "modern": using_any & _any_selected(df, "fpbeh_which", PULSE_MODERN_CODES),
        "unmet":  zeros, "open": zeros,          # not asked in Phone Pulse
        "aware":  _any_selected(df, "fpbeh_awarefp", PULSE_MODERN_CODES),
        "recall": (pd.to_numeric(df["uptake_fp"], errors="coerce").eq(1)
                   & pd.to_numeric(df["knowledge_waiting"], errors="coerce").eq(KNOWLEDGE_WAITING_CORRECT)).to_numpy(),
    }


def _pulse_values(w, pop, flags):
    v = fp._headline_values(w, pop, flags)
    d = (w * pop).sum()
    v["campaign_recall"] = (w * (flags["recall"] & pop)).sum() / d if d else np.nan
    return v


def _baseline_attitude_flags(df):
    """{metric: (holds the view, answered)} for the formative statements."""
    flags = {}
    for f_col, p_col, agree_is_view in cfg.ATTITUDE_CROSSWALK.values():
        if p_col not in ATTITUDE_METRICS or f_col not in df.columns:
            continue
        s = df[f_col].astype(str).str.strip()
        agree = (s == cfg.STATEMENT_AGREE_TEXT).to_numpy()
        answered = s.isin([cfg.STATEMENT_AGREE_TEXT, cfg.STATEMENT_DISAGREE_TEXT]).to_numpy()
        flags[ATTITUDE_METRICS[p_col]] = ((agree if agree_is_view else ~agree) & answered, answered)
    return flags


def _pulse_attitude_flags(df):
    """{metric: (holds the view, answered)} for the Phone Pulse fpatt_* items."""
    flags = {}
    for p_col, metric in ATTITUDE_METRICS.items():
        if p_col in df.columns:
            score = pd.to_numeric(df[p_col], errors="coerce")
            flags[metric] = ((score >= 3).to_numpy(), score.notna().to_numpy())
    return flags


def _attitude_values(w, pop, flags):
    """Share holding each view among those in `pop` who answered the item."""
    out = {}
    for metric, (holds, answered) in flags.items():
        d = (w * (pop & answered)).sum()
        out[metric] = (w * (pop & answered & holds)).sum() / d if d else np.nan
    return out


def _unweighted(w):
    """Weight 1 for everyone the weighted estimate includes (non-missing
    weight), 0 otherwise -- same respondents, no weighting."""
    return w.notna().astype(float)


def _unweighted_cols(b, fu, ch):
    """unweighted_* columns for one key_indicators_change.csv row."""
    return {
        "unweighted_baseline_value": b[0],
        "unweighted_baseline_ci_low": b[1],
        "unweighted_baseline_ci_high": b[2],
        "unweighted_followup_value": fu[0] if fu else np.nan,
        "unweighted_followup_ci_low": fu[1] if fu else np.nan,
        "unweighted_followup_ci_high": fu[2] if fu else np.nan,
        "unweighted_change_pp": 100 * ch[0] if ch else np.nan,
        "unweighted_change_ci_low_pp": 100 * ch[1] if ch else np.nan,
        "unweighted_change_ci_high_pp": 100 * ch[2] if ch else np.nan,
        "unweighted_change_p_value": ch[3] if ch else np.nan,
    }


def _estimate(df, weights, flags, pops, metrics, rng, values=fp._headline_values):
    """{(population, metric): (value, ci_low, ci_high, n)} using fp's Rao-Wu bootstrap."""
    w = weights.fillna(0).to_numpy()
    mult = fp._rao_wu_multipliers(df, rng)
    res = {}
    for pop_name, pop in pops.items():
        point = values(w, pop, flags)
        reps = pd.DataFrame([values(w * m, pop, flags) for m in mult]) if mult is not None else None
        for m in metrics:
            lo, hi = (np.nanpercentile(reps[m], [2.5, 97.5]) if reps is not None else (np.nan, np.nan))
            n = int((pop & ~flags["any"]).sum()) if m == "aware_modern_nonusers" else int(pop.sum())
            res[(pop_name, m)] = (point[m], lo, hi, n)
    return res


def _cluster_multipliers(base, rng):
    """Rao-Wu multipliers drawn once per settlement, (N_BOOT, n_settlements),
    plus a function mapping any frame's rows to their settlement column. Using
    the same draw for baseline and Pulse makes the change's CI reflect that
    both waves come from the same settlements (and, longitudinally, the same
    people)."""
    key = lambda d: d["state"].astype(str).str.strip() + "|" + d["location"].astype(str).str.strip()
    clusters = pd.Series(key(base).unique())
    col = {c: i for i, c in enumerate(clusters)}
    strata = clusters.str.split("|").str[0]
    M = np.ones((fp.N_BOOT, len(clusters)))
    for s in strata.unique():
        idx = np.flatnonzero(strata == s)
        n_h = len(idx)
        if n_h < 2:
            continue
        draws = rng.integers(0, n_h, size=(fp.N_BOOT, n_h - 1))
        counts = np.stack([np.bincount(d, minlength=n_h) for d in draws])
        M[:, idx] = counts * n_h / (n_h - 1)
    return lambda d: M[:, key(d).map(col).to_numpy()]


def _change(base, b_w, b_flags, b_pops, pulse, p_w, p_flags, p_pops, metrics, rows_mult,
            values=fp._headline_values):
    """{(population, metric): (diff, ci_low, ci_high, p_value)} for Pulse minus
    baseline. Two-sided bootstrap p-value: 2 x the share of replicate changes
    on the other side of zero (so p < 0.05 exactly when the 95% CI excludes 0);
    with 1,000 replicates the smallest reportable value is p < 0.002."""
    bw, pw = b_w.fillna(0).to_numpy(), p_w.fillna(0).to_numpy()
    bm, pm = rows_mult(base), rows_mult(pulse)
    res = {}
    for pop in b_pops:
        bp, pp = values(bw, b_pops[pop], b_flags), values(pw, p_pops[pop], p_flags)
        reps = np.array([[values(pw * pm[i], p_pops[pop], p_flags)[m]
                          - values(bw * bm[i], b_pops[pop], b_flags)[m]
                          for m in metrics] for i in range(fp.N_BOOT)])
        for j, m in enumerate(metrics):
            r = reps[:, j][~np.isnan(reps[:, j])]
            lo, hi = np.percentile(r, [2.5, 97.5])
            p = min(1.0, 2 * min((r <= 0).mean(), (r >= 0).mean()))
            res[(pop, m)] = (pp[m] - bp[m], lo, hi, max(p, 2 / len(r)))
    return res


def main():
    rng = np.random.default_rng(fp.BOOT_SEED)
    att = pd.read_csv(ATTRITION_WEIGHTS_CSV, dtype={"resp_id_pull": str})

    # ── Baseline ──────────────────────────────────────────────────────────────
    statement_cols = [f_col for f_col, _, _ in cfg.ATTITUDE_CROSSWALK.values()]
    base = pd.read_csv(cfg.FORMATIVE_DATA, low_memory=False,
                       usecols=lambda c: c in {"KEY", WEIGHT_COL, "gender", "location", "state",
                                               "current_use", "current_use_methods",
                                               "time_before_preferred_pregnancy", "future_intent",
                                               "known_contraceptive_options", *statement_cols})
    for c in ("current_use_methods", "known_contraceptive_options"):
        base[c] = base[c].apply(fp._strip_hausa)
    cw = pd.read_csv(cfg.CROSSWALK_FILE, usecols=["ID", "KEY"]).astype(str).apply(lambda s: s.str.strip())
    base["resp_id_pull"] = base["KEY"].astype(str).str.strip().map(cw.set_index("KEY")["ID"])
    base = base.merge(att[["resp_id_pull", "attrition_weight"]], on="resp_id_pull", how="left")
    b_flags = fp._headline_flags(base)
    b_women = base["gender"].fillna("").str.contains("Femme|Female").to_numpy()
    in_panel = base["attrition_weight"].notna().to_numpy()
    metrics = list(fp._headline_values(np.ones(1), np.ones(1, bool), {k: np.zeros(1, bool) for k in b_flags}))

    base_cross = _estimate(base, base[WEIGHT_COL], b_flags,
                           {"full_sample": np.ones(len(base), bool), "women": b_women}, metrics, rng)
    base_long = _estimate(base, base["attrition_weight"], b_flags,
                          {"full_sample": in_panel, "women": in_panel & b_women}, metrics, rng)

    # ── Phone Pulse round 1 ───────────────────────────────────────────────────
    pulse = pd.read_csv(cfg.PULSE_DATA, low_memory=False, dtype={"resp_id_pull": str})
    pulse["resp_id_pull"] = pulse["resp_id_pull"].str.strip()
    pulse = pulse.merge(att, on="resp_id_pull", how="inner")       # linked respondents only
    p_flags = _pulse_flags(pulse)
    p_women = pulse["gender_pull"].eq(GENDER_FEMALE_RAW).to_numpy()
    treatment = compute_fem_partner_listener(pulse).to_numpy()
    print(f"Phone Pulse linked respondents: {len(pulse)} ({int(p_women.sum())} women); "
          f"Treatment arm: {int(treatment.sum())} ({int((treatment & p_women).sum())} women)")

    pulse_all = _estimate(pulse, pulse["attrition_weight"], p_flags,
                          {"full_sample": np.ones(len(pulse), bool), "women": p_women}, PULSE_MEASURED, rng)
    pulse_treat = _estimate(pulse, pulse["attrition_weight"], p_flags,
                            {"full_sample": treatment, "women": treatment & p_women}, PULSE_PAGE_METRICS, rng,
                            values=_pulse_values)

    # ── Change, baseline -> round 1 (same settlement draws for both waves) ──
    rows_mult = _cluster_multipliers(base, np.random.default_rng(fp.BOOT_SEED + 1))
    p_pops = {"full_sample": np.ones(len(pulse), bool), "women": p_women}
    changes = {
        "cross_sectional": _change(base, base[WEIGHT_COL], b_flags,
                                   {"full_sample": np.ones(len(base), bool), "women": b_women},
                                   pulse, pulse["attrition_weight"], p_flags, p_pops, PULSE_MEASURED, rows_mult),
        "longitudinal": _change(base, base["attrition_weight"], b_flags,
                                {"full_sample": in_panel, "women": in_panel & b_women},
                                pulse, pulse["attrition_weight"], p_flags, p_pops, PULSE_MEASURED, rows_mult),
    }

    # ── Unweighted: same respondents, populations and bootstrap draws ────────
    # Replaying BOOT_SEED in the same call order as above gives each unweighted
    # estimate the same replicate draws as its weighted counterpart.
    uw_rng = np.random.default_rng(fp.BOOT_SEED)
    uw_base_cross = _estimate(base, _unweighted(base[WEIGHT_COL]), b_flags,
                              {"full_sample": np.ones(len(base), bool), "women": b_women}, metrics, uw_rng)
    uw_base_long = _estimate(base, _unweighted(base["attrition_weight"]), b_flags,
                             {"full_sample": in_panel, "women": in_panel & b_women}, metrics, uw_rng)
    uw_pulse_all = _estimate(pulse, _unweighted(pulse["attrition_weight"]), p_flags,
                             {"full_sample": np.ones(len(pulse), bool), "women": p_women}, PULSE_MEASURED, uw_rng)
    uw_changes = {
        "cross_sectional": _change(base, _unweighted(base[WEIGHT_COL]), b_flags,
                                   {"full_sample": np.ones(len(base), bool), "women": b_women},
                                   pulse, _unweighted(pulse["attrition_weight"]), p_flags, p_pops,
                                   PULSE_MEASURED, rows_mult),
        "longitudinal": _change(base, _unweighted(base["attrition_weight"]), b_flags,
                                {"full_sample": in_panel, "women": in_panel & b_women},
                                pulse, _unweighted(pulse["attrition_weight"]), p_flags, p_pops,
                                PULSE_MEASURED, rows_mult),
    }

    # ── Attitudes: same populations, weights and settlement draws ─────────────
    ba_flags, pa_flags = _baseline_attitude_flags(base), _pulse_attitude_flags(pulse)
    att_metrics = [m for m in ATTITUDE_METRICS.values() if m in ba_flags and m in pa_flags]
    b_pops_cross = {"full_sample": np.ones(len(base), bool), "women": b_women}
    b_pops_long = {"full_sample": in_panel, "women": in_panel & b_women}
    att_est = {}
    for label, wfun in [("", lambda w: w), ("unweighted_", _unweighted)]:
        rng_att = np.random.default_rng(fp.BOOT_SEED + ATTITUDE_SEED_OFFSET)   # same draws weighted/unweighted
        att_est[label] = {
            "base_cross": _estimate(base, wfun(base[WEIGHT_COL]), ba_flags, b_pops_cross, att_metrics,
                                    rng_att, values=_attitude_values),
            "base_long": _estimate(base, wfun(base["attrition_weight"]), ba_flags, b_pops_long, att_metrics,
                                   rng_att, values=_attitude_values),
            "pulse": _estimate(pulse, wfun(pulse["attrition_weight"]), pa_flags, p_pops, att_metrics,
                               rng_att, values=_attitude_values),
            "cross_sectional": _change(base, wfun(base[WEIGHT_COL]), ba_flags, b_pops_cross, pulse,
                                       wfun(pulse["attrition_weight"]), pa_flags, p_pops, att_metrics,
                                       rows_mult, values=_attitude_values),
            "longitudinal": _change(base, wfun(base["attrition_weight"]), ba_flags, b_pops_long, pulse,
                                    wfun(pulse["attrition_weight"]), pa_flags, p_pops, att_metrics,
                                    rows_mult, values=_attitude_values),
        }

    def _answered_n(flags, pops, has_weight):
        """Respondents in each population who answered each item (and have a weight)."""
        return {(pop, m): int((mask & answered & has_weight).sum())
                for pop, mask in pops.items() for m, (_, answered) in flags.items() if m in att_metrics}
    n_att = {
        "cross_sectional": _answered_n(ba_flags, b_pops_cross, base[WEIGHT_COL].notna().to_numpy()),
        "longitudinal": _answered_n(ba_flags, b_pops_long, base["attrition_weight"].notna().to_numpy()),
        "pulse": _answered_n(pa_flags, p_pops, pulse["attrition_weight"].notna().to_numpy()),
    }

    # ── Write ─────────────────────────────────────────────────────────────────
    rows = []
    for mode, baseline, uw_baseline in [("cross_sectional", base_cross, uw_base_cross),
                                        ("longitudinal", base_long, uw_base_long)]:
        for (pop, m), (v, lo, hi, n) in baseline.items():
            fu = pulse_all.get((pop, m))
            ch = changes[mode].get((pop, m))
            rows.append({
                "mode": mode, "round": ROUND_ID, "population": pop, "metric": m,
                "baseline_value": v, "baseline_ci_low": lo, "baseline_ci_high": hi, "baseline_n": n,
                "followup_status": "measured" if fu else "not_asked",
                "followup_value": fu[0] if fu else np.nan,
                "followup_ci_low": fu[1] if fu else np.nan,
                "followup_ci_high": fu[2] if fu else np.nan,
                "followup_n": fu[3] if fu else np.nan,
                "change_pp": 100 * ch[0] if ch else np.nan,
                "change_ci_low_pp": 100 * ch[1] if ch else np.nan,
                "change_ci_high_pp": 100 * ch[2] if ch else np.nan,
                "change_p_value": ch[3] if ch else np.nan,
                **_unweighted_cols(uw_baseline[(pop, m)], uw_pulse_all.get((pop, m)),
                                   uw_changes[mode].get((pop, m))),
            })
    for mode, base_key in [("cross_sectional", "base_cross"), ("longitudinal", "base_long")]:
        w_, uw_ = att_est[""], att_est["unweighted_"]
        for (pop, m), (v, lo, hi, _) in w_[base_key].items():
            fu, ch = w_["pulse"][(pop, m)], w_[mode][(pop, m)]
            rows.append({
                "mode": mode, "round": ROUND_ID, "population": pop, "metric": m,
                "baseline_value": v, "baseline_ci_low": lo, "baseline_ci_high": hi,
                "baseline_n": n_att[mode][(pop, m)],
                "followup_status": "measured",
                "followup_value": fu[0], "followup_ci_low": fu[1], "followup_ci_high": fu[2],
                "followup_n": n_att["pulse"][(pop, m)],
                "change_pp": 100 * ch[0], "change_ci_low_pp": 100 * ch[1],
                "change_ci_high_pp": 100 * ch[2], "change_p_value": ch[3],
                **_unweighted_cols(uw_[base_key][(pop, m)], uw_["pulse"][(pop, m)], uw_[mode][(pop, m)]),
            })
    pd.DataFrame(rows).to_csv(KEY_INDICATORS_CSV, index=False)

    pp_rows = []
    for (pop, m) in list(base_cross) + [(p, "campaign_recall") for p in ("full_sample", "women")]:
        r = pulse_treat.get((pop, m))
        pp_rows.append({"population": pop, "metric": m,
                        "status": "measured" if r else "not_asked",
                        "value": r[0] if r else np.nan, "ci_low": r[1] if r else np.nan,
                        "ci_high": r[2] if r else np.nan, "n_unweighted": r[3] if r else np.nan})
    pd.DataFrame(pp_rows).to_csv(PP_HEADLINE_CSV, index=False)

    print("\nmetric (full sample / women)   baseline (all) | baseline (panel) | Pulse R1 (panel) | Pulse R1 (Treatment)")
    for m in metrics:
        for pop in ("full_sample", "women"):
            def f(d):
                r = d.get((pop, m))
                return f"{r[0]:6.1%} [{r[1]:5.1%}-{r[2]:5.1%}]" if r else "   not asked       "
            print(f"  {m:<22} {pop:<11} {f(base_cross)} | {f(base_long)} | {f(pulse_all)} | {f(pulse_treat)}")
    print("\nUnweighted: baseline (all) | baseline (panel) | Pulse R1 (panel)")
    for m in metrics:
        for pop in ("full_sample", "women"):
            def f(d):
                r = d.get((pop, m))
                return f"{r[0]:6.1%} [{r[1]:5.1%}-{r[2]:5.1%}]" if r else "   not asked       "
            print(f"  {m:<22} {pop:<11} {f(uw_base_cross)} | {f(uw_base_long)} | {f(uw_pulse_all)}")
    for label, chs in [("", changes), ("Unweighted ", uw_changes)]:
        print(f"\n{label}Change, baseline -> round 1 (pp, 95% CI, p):")
        for mode, ch in chs.items():
            for (pop, m), (d, lo, hi, p) in ch.items():
                ptxt = "p < 0.002" if p <= 2 / fp.N_BOOT else f"p = {p:.3f}"
                print(f"  {mode:<16} {pop:<11} {m:<22} {100*d:+5.1f} ({100*lo:+5.1f} to {100*hi:+5.1f}), {ptxt}")
    print("\nAttitudes, % holding the view (weighted), baseline -> Pulse R1 (pp, 95% CI, p):")
    for mode in ("cross_sectional", "longitudinal"):
        for (pop, m), (d, lo, hi, p) in att_est[""][mode].items():
            ptxt = "p < 0.002" if p <= 2 / fp.N_BOOT else f"p = {p:.3f}"
            print(f"  {mode:<16} {pop:<11} {m:<24} {100*d:+5.1f} ({100*lo:+5.1f} to {100*hi:+5.1f}), {ptxt}")
    for pop in ("full_sample", "women"):
        r = pulse_treat[(pop, "campaign_recall")]
        print(f"  {'campaign_recall':<22} {pop:<11} Pulse R1 (Treatment): {r[0]:6.1%} [{r[1]:5.1%}-{r[2]:5.1%}]")
    print(f"\nWritten: {KEY_INDICATORS_CSV.name}, {PP_HEADLINE_CSV.name}")


if __name__ == "__main__":
    main()
