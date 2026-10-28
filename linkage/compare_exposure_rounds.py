"""
Campaign Exposure indicators per Phone Pulse round: exposed (Treatment) vs
unexposed (Comparison), weighted and unweighted, with the Treatment - Comparison
difference and each later round compared with round 1 (change and p-value).

Indicators (Phone Pulse questions; share of everyone in the group -- anyone not
asked or answering don't know / refused counts as "no"):
  Recall
    campaign_recall        heard FP programmes/ads on the radio in the last month
                           (uptake_fp = 1, asked of radio listeners) AND knows the
                           spacing message (knowledge_waiting = 3, "At least two
                           years") -- the campaign_recall of compare_key_indicators.py
    heard_fp_radio         uptake_fp = 1
    knows_spacing_message  knowledge_waiting = 3
  Awareness (fpbeh_awarefp: methods read out, "have you heard of ...?")
    aware_modern           heard of at least one modern method (the baseline's
                           modern list, as compare_key_indicators.py)
    aware_<code>           heard of each method

Groups: Treatment = listens to a FEM partner station (export_pp_app_data's
compute_fem_partner_listener, from that round's answers); Comparison = everyone
else; All.

Weighting and CIs follow compare_key_indicators.py:
  - weighted   = the round's attrition weights (baseline weight / chance of being
                 in that round), so only respondents linked to the baseline count;
  - unweighted = the same respondents, each counted once;
  - 95% CIs: Rao-Wu cluster bootstrap on the baseline design (settlement within
    state), 1,000 replicates, the same settlement draws for every estimate, so
    differences account for groups and rounds sharing settlements and people;
  - two-sided bootstrap p-values (p < 0.05 exactly when the 95% CI excludes 0;
    smallest reportable value p < 0.002) for
      Treatment - Comparison, within each round   (diff_* columns, Treatment rows)
      this round - round 1, same group             (change_* columns, later rounds)

Baseline comparison (awareness only -- the baseline asked no recall questions, and the
campaign had not started): the same linked respondents' baseline answers, in the group
their phone answers put them in for that round, with the same weights and settlement
draws. aware_modern = known_contraceptive_options names a modern method (as
compare_key_indicators.py); aware_<code> only for methods matched one-to-one
(config.METHOD_CROSSWALK; not male/female sterilisation or condoms, which the baseline
combines, or "other traditional"). Baseline awareness was unprompted and only asked of
people who said they knew an effective method (others count as not aware), so part of
any rise is the question format. Columns baseline_*, change_vs_baseline_* (this round
minus baseline, same group) and, on Treatment rows, did_* (Treatment change minus
Comparison change: the campaign estimate net of change common to both groups).

Rounds are included once processed: round 1 (outputs/), and round2_early /
round2 after `run_round.py etl --round <round>` and `run_round2.py`
(weights in outputs/round2/A_baseline_<round>/).

Usage (from 2_phone pulse/linkage/):  python compare_exposure_rounds.py
Output (aggregates only): outputs/exposure_by_round.csv -- upload to Drive for the app
(EXPOSURE_BY_ROUND_ID in niger_app/src/data_loader.py).
"""

import sys

import numpy as np
import pandas as pd

import config as cfg
import compare_key_indicators as cki
from compare_key_indicators import compute_fem_partner_listener, fp

sys.path.insert(0, str(cfg.NIGER_ROOT / "2_phone pulse" / "etl_pipeline"))
import rounds  # noqa: E402
from export_pp_app_data import FP_METHOD_LABELS  # noqa: E402

OUT_CSV = cfg.OUTPUT_DIR / "exposure_by_round.csv"
REFERENCE_ROUND = "round1"
GROUPS = ["Treatment", "Comparison", "All"]
INDICATORS = {   # indicator -> (section, label)
    "campaign_recall": ("Recall", "Campaign recall (heard FP programmes/ads and knows the spacing message)"),
    "heard_fp_radio": ("Recall", "Heard FP programmes/ads on the radio in the last month"),
    "knows_spacing_message": ("Recall", "Knows the spacing message (wait at least two years after a birth)"),
    "aware_modern": ("Awareness", "Heard of at least one modern method"),
    **{f"aware_{int(c)}": ("Awareness", f"Heard of: {label}") for c, label in FP_METHOD_LABELS.items()},
}
WEIGHTS = {
    "round1": cfg.OUTPUT_DIR / "attrition_weights.csv",
    "round2_early": cfg.OUTPUT_DIR / "round2" / "A_baseline_round2_early" / "attrition_weights.csv",
    "round2": cfg.OUTPUT_DIR / "round2" / "A_baseline_round2" / "attrition_weights.csv",
}


def _flags(df: pd.DataFrame) -> dict:
    num = lambda c: pd.to_numeric(df[c], errors="coerce") if c in df.columns else pd.Series(np.nan, df.index)
    heard = num("uptake_fp").eq(1).to_numpy()
    message = num("knowledge_waiting").eq(cki.KNOWLEDGE_WAITING_CORRECT).to_numpy()
    flags = {"campaign_recall": heard & message, "heard_fp_radio": heard, "knows_spacing_message": message,
             "aware_modern": cki._any_selected(df, "fpbeh_awarefp", cki.PULSE_MODERN_CODES)}
    for c in FP_METHOD_LABELS:
        flags[f"aware_{int(c)}"] = num(f"fpbeh_awarefp_{int(c)}").eq(1).to_numpy()
    return flags


def _values(w, pop, flags):
    d = (w * pop).sum()
    return pd.Series({m: (w * (flags[m] & pop)).sum() / d if d else np.nan for m in flags})


def _baseline_known(base: pd.DataFrame) -> pd.DataFrame:
    """resp_id_pull -> baseline known_contraceptive_options (raw bilingual labels)."""
    cw = pd.read_csv(cfg.CROSSWALK_FILE, usecols=["ID", "KEY"]).astype(str).apply(lambda s: s.str.strip())
    out = pd.DataFrame({"resp_id_pull": base["KEY"].astype(str).str.strip().map(cw.set_index("KEY")["ID"]),
                        "base_known": base["known_contraceptive_options"]})
    return out.dropna(subset=["resp_id_pull"]).drop_duplicates("resp_id_pull")


def _baseline_flags(df: pd.DataFrame) -> dict:
    """Baseline awareness for the indicators that have a baseline equivalent."""
    raw = df["base_known"]
    flags = {"aware_modern": raw.apply(fp._strip_hausa).apply(fp._mentions_modern_method).to_numpy(dtype=bool)}
    named = raw.apply(lambda c: {cfg.FORMATIVE_LABEL_TO_METHOD.get(p.strip()) for p in str(c).split("|")}
                      if pd.notna(c) else set())
    for method, (_, pulse_codes) in cfg.METHOD_CROSSWALK.items():
        if len(pulse_codes) == 1:
            flags[f"aware_{pulse_codes[0]}"] = named.apply(lambda s, m=method: m in s).to_numpy(dtype=bool)
    return flags


def _load_round(round_id: str, base_known: pd.DataFrame):
    data = rounds.get_round(round_id)["etl_output_dir"] / "cleaned_data.csv"
    if not data.exists() or not WEIGHTS[round_id].exists():
        return None
    att = pd.read_csv(WEIGHTS[round_id], dtype={"resp_id_pull": str})
    df = pd.read_csv(data, low_memory=False, dtype={"resp_id_pull": str})
    df["resp_id_pull"] = df["resp_id_pull"].str.strip()
    df = df.merge(att, on="resp_id_pull", how="inner")      # linked respondents only
    df = df.merge(base_known, on="resp_id_pull", how="left")
    treatment = compute_fem_partner_listener(df).to_numpy()
    pops = {"Treatment": treatment, "Comparison": ~treatment, "All": np.ones(len(df), bool)}
    return df, _flags(df), pops, _baseline_flags(df)


def _p_and_ci(reps: pd.Series):
    r = reps.dropna().to_numpy()
    if len(r) == 0:
        return np.nan, np.nan, np.nan
    lo, hi = np.percentile(r, [2.5, 97.5])
    p = max(min(1.0, 2 * min((r <= 0).mean(), (r >= 0).mean())), 2 / len(r))
    return lo, hi, p


def main() -> None:
    # Settlement draws on the baseline design, shared by every round and group.
    base = pd.read_csv(cfg.FORMATIVE_DATA, usecols=["KEY", "location", "state", "known_contraceptive_options"],
                       low_memory=False)
    rows_mult = cki._cluster_multipliers(base, np.random.default_rng(fp.BOOT_SEED + 3))
    base_known = _baseline_known(base)

    loaded = {rid: _load_round(rid, base_known) for rid in WEIGHTS}
    loaded = {rid: v for rid, v in loaded.items() if v is not None}
    if REFERENCE_ROUND not in loaded:
        sys.exit("Round 1 cleaned data or attrition weights not found -- run attrition_weights.py first.")
    print("Rounds included: " + ", ".join(f"{rid} ({len(v[0])} linked)" for rid, v in loaded.items()))

    # est[(round, weighting)][group] = (point Series, replicates DataFrame)
    # base_est: the same respondents' baseline answers, same groups, weights and draws.
    est, base_est = {}, {}
    for rid, (df, flags, pops, b_flags) in loaded.items():
        mult = rows_mult(df)
        for weighting in ("weighted", "unweighted"):
            w_s = df["attrition_weight"] if weighting == "weighted" else cki._unweighted(df["attrition_weight"])
            w = w_s.fillna(0).to_numpy()
            for target, f in ((est, flags), (base_est, b_flags)):
                target[(rid, weighting)] = {
                    g: (_values(w, pop, f),
                        pd.DataFrame([_values(w * mult[i], pop, f) for i in range(fp.N_BOOT)]))
                    for g, pop in pops.items()}

    rows = []
    for (rid, weighting), groups in est.items():
        df, flags, pops, b_flags = loaded[rid]
        b_groups = base_est[(rid, weighting)]
        for g in GROUPS:
            point, reps = groups[g]
            for m, (section, label) in INDICATORS.items():
                lo, hi = np.nanpercentile(reps[m], [2.5, 97.5]) if reps[m].notna().any() else (np.nan, np.nan)
                row = {"round": rid, "weighting": weighting, "group": g, "section": section,
                       "indicator": m, "label": label, "n": int(pops[g].sum()),
                       "count": int((flags[m] & pops[g]).sum()),
                       "pct": round(100 * point[m], 1),
                       "ci_low": round(100 * lo, 1), "ci_high": round(100 * hi, 1)}
                if g == "Treatment":
                    c_point, c_reps = groups["Comparison"]
                    d_lo, d_hi, d_p = _p_and_ci(reps[m] - c_reps[m])
                    row.update({"diff_vs_comparison_pp": round(100 * (point[m] - c_point[m]), 1),
                                "diff_ci_low_pp": round(100 * d_lo, 1), "diff_ci_high_pp": round(100 * d_hi, 1),
                                "diff_p_value": round(d_p, 4)})
                if m in b_flags:
                    b_point, b_reps = b_groups[g]
                    b_lo, b_hi = np.nanpercentile(b_reps[m], [2.5, 97.5])
                    ch_lo, ch_hi, ch_p = _p_and_ci(reps[m] - b_reps[m])
                    row.update({"baseline_count": int((b_flags[m] & pops[g]).sum()),
                                "baseline_pct": round(100 * b_point[m], 1),
                                "baseline_ci_low": round(100 * b_lo, 1), "baseline_ci_high": round(100 * b_hi, 1),
                                "change_vs_baseline_pp": round(100 * (point[m] - b_point[m]), 1),
                                "change_vs_baseline_ci_low_pp": round(100 * ch_lo, 1),
                                "change_vs_baseline_ci_high_pp": round(100 * ch_hi, 1),
                                "change_vs_baseline_p_value": round(ch_p, 4)})
                    if g == "Treatment":
                        c_point, c_reps = groups["Comparison"]
                        cb_point, cb_reps = b_groups["Comparison"]
                        did = (point[m] - b_point[m]) - (c_point[m] - cb_point[m])
                        did_lo, did_hi, did_p = _p_and_ci((reps[m] - b_reps[m]) - (c_reps[m] - cb_reps[m]))
                        row.update({"did_pp": round(100 * did, 1), "did_ci_low_pp": round(100 * did_lo, 1),
                                    "did_ci_high_pp": round(100 * did_hi, 1), "did_p_value": round(did_p, 4)})
                if rid != REFERENCE_ROUND:
                    r_point, r_reps = est[(REFERENCE_ROUND, weighting)][g]
                    c_lo, c_hi, c_p = _p_and_ci(reps[m] - r_reps[m])
                    row.update({"vs_round": REFERENCE_ROUND,
                                "change_pp": round(100 * (point[m] - r_point[m]), 1),
                                "change_ci_low_pp": round(100 * c_lo, 1),
                                "change_ci_high_pp": round(100 * c_hi, 1),
                                "change_p_value": round(c_p, 4)})
                rows.append(row)

    out = pd.DataFrame(rows)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)

    show = out[out["indicator"].isin(["campaign_recall", "aware_modern"]) & out["group"].eq("Treatment")]
    print("\nTreatment vs Comparison (% of group, 95% CI):")
    for _, r in show.iterrows():
        c = out[(out["round"] == r["round"]) & (out["weighting"] == r["weighting"])
                & (out["group"] == "Comparison") & (out["indicator"] == r["indicator"])].iloc[0]
        print(f"  {r['round']:<13} {r['weighting']:<10} {r['indicator']:<16} "
              f"T {r['pct']:5.1f}% (N={r['n']})  C {c['pct']:5.1f}% (N={c['n']})  "
              f"diff {r['diff_vs_comparison_pp']:+.1f} pp, p = {r['diff_p_value']:.3f}")
    print("\nAwareness of a modern method, baseline -> round (same people, weighted):")
    for _, r in out[(out["indicator"] == "aware_modern") & (out["weighting"] == "weighted")].iterrows():
        did = f", Treatment - Comparison change {r['did_pp']:+.1f} pp (p = {r['did_p_value']:.3f})" \
            if r["group"] == "Treatment" else ""
        print(f"  {r['round']:<13} {r['group']:<10} {r['baseline_pct']:5.1f}% -> {r['pct']:5.1f}%  "
              f"({r['change_vs_baseline_pp']:+.1f} pp, p = {r['change_vs_baseline_p_value']:.3f}){did}")
    print(f"\nWritten: {OUT_CSV}")


if __name__ == "__main__":
    main()
