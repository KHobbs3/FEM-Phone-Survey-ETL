"""
Similarity scoring for submissions sharing the same `resp_id_pull`.

WHY THIS EXISTS
---------------
Enumerators type the participant ID by hand. Two kinds of problem arise:
  1. Wrong ID     — enumerator entered a different participant's ID, so the
                    form pulled roster data (name, LGA, village, radio stations)
                    for the wrong person. The two submissions look very different.
  2. Repeat call  — the same participant was legitimately called 2–3 times across
                    survey waves. Their demographics should match; some survey
                    answers may have changed.

This script uses `recordlinkage` to compute pairwise similarity scores for every
pair of submissions that share a `resp_id_pull` value, then produces a
per-pair verdict to guide the reviewer.

HOW IT WORKS
------------
Step 1 — Load
    Reads the RAW survey data (before PII removal) so that `name_pull` is
    available for string matching. Falls back to cleaned data with a warning
    if raw data is not found.

Step 2 — Index
    `recordlinkage.Index().block(on=COL_RESPONDENT_ID)` creates candidate pairs
    (i, j) only for rows that share the same respondent ID, avoiding the O(n²)
    cost of comparing every record against every other.

Step 3 — Compare
    One key column is chosen from each survey section:
      • Identity   — name_pull (Jaro-Winkler string), lga_pull, village_pull, gender_pull, age
      • Fertility  — current_pregnant / currently_pregnant
      • FP beh.    — fpbeh_fpnow / currently_using_fp
      • FP util.   — fptutil_any / visited_health_facility_fp
      • FP views   — fpatt_immoral / self_religious_leaders (stable attitude)
      • Info       — info_newpregnancy / fp_harder_conceive_likelihood
      • Partner    — partner_talk_fp_time / last_discussed_fp_with_spouse
      • Radio      — radio_any / listened_radio_past_month
      • Access     — lastspoke_try / tried_get_contraception_since_last
      • Pressure   — pressure_pnorm / community_look_down

    Comparison types:
      • string (Jaro-Winkler): values 0–1 based on edit distance. Handles
        name variants and typos better than exact match.
      • exact: 1.0 if equal, 0.0 otherwise. Used for binary/categorical fields.
      • numeric (Gaussian): similarity = exp(−(|a−b|/scale)²). At |a−b| = scale,
        similarity ≈ 0.37. Scale is set per column based on the answer range:
          age       → scale=5   (5-year difference → 0.37)
          Likert    → scale=1   (1-point difference → 0.37)
          frequency → scale=2

Step 4 — Weighted score
    Each comparison column has an assigned weight reflecting how stable the
    variable should be across genuine repeat contacts:
      • Identity columns: weight 2.0–3.0 (should not change at all)
      • Stable attitudes: weight 1.5 (slow-moving)
      • Behaviour / access: weight 1.0 (may change between waves)
      • Wave-specific outcomes: weight 0.8

    Weighted score = Σ(score_i × weight_i) / Σ(weight_i)
    Only columns that exist in the data contribute to the denominator.

Step 5 — Verdict
    Score ≥ 0.80 → `same_person`        Consistent records; genuine repeat contact.
    Score 0.55–0.79 → `review_needed`   Some differences; could be same person
                                          with changed circumstances, or partially
                                          wrong ID.
    Score < 0.55  → `probable_wrong_id` Too dissimilar to be the same person.
                                          The enumerator likely entered a wrong ID.

IMPORTANT — DATA HANDLING
--------------------------
This script reads PII (name_pull). Outputs must be kept internal.
Do not share `pair_similarity_scores.csv` outside the research team.

USAGE
-----
    cd q_a
    python compare_duplicates.py                  # reads raw data by default
    python compare_duplicates.py --cleaned        # use cleaned data (no name matching)
    python compare_duplicates.py --demo           # inject a synthetic duplicate for testing
"""

import sys
import argparse
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
import recordlinkage
from config_qa import (
    QA_OUTPUT_DIR, COL_KEY, COL_RESPONDENT_ID,
    RAW_DATA_PATH,
)

RAW_DATA_DIR  = Path(__file__).parent.parent / "data" / "raw_data"
OUTPUT_FILE   = QA_OUTPUT_DIR / "pair_similarity_scores.csv"
SUMMARY_FILE  = QA_OUTPUT_DIR / "duplicate_summary.csv"


# ── Column comparison spec ─────────────────────────────────────────────────────
# Each entry: (real_col, mock_fallback_col, compare_type, params, weight, section, rationale)
# The script uses the first column name found in the data; see _resolve_col().
#
# Rationale for column selection:
#   - One column per survey section so the score reflects the whole instrument
#   - Prefer STABLE questions (demographics, slow-changing attitudes) for identity
#   - Include some TIME-VARYING questions so the score reflects the current wave
#
COMPARISON_SPEC = [
    # ── Identity ──────────────────────────────────────────────────────────────
    # Name is the strongest identity signal; handles spelling variants well
    # with Jaro-Winkler (tolerant of transpositions and small edits).
    ("name_pull",       "name_pull",      "string",  {"method": "jarowinkler"}, 3.0, "identity",
     "Respondent name; most reliable identity anchor"),

    # Geographic location should be completely stable for the same respondent.
    ("lga_pull",        "lga_pull",       "exact",   {},                        2.0, "identity",
     "LGA; should not change between contacts"),
    ("village_pull",    "village_pull",   "exact",   {},                        2.0, "identity",
     "Village; should not change between contacts"),

    # Gender is immutable; a mismatch is near-certain evidence of a wrong ID.
    ("gender_pull",     "gender",         "exact",   {},                        2.0, "identity",
     "Gender; completely stable — mismatch strongly suggests wrong ID"),

    # Age should be constant or differ by 1 across consecutive survey waves.
    ("age",             "age",            "numeric", {"method": "gauss", "scale": 5}, 1.5, "identity",
     "Age; stable within a wave, may differ by 1 across annual waves (scale=5 yr)"),

    # ── Fertility section ─────────────────────────────────────────────────────
    # Pregnancy status changes, so mismatch is expected across waves; downweighted.
    ("current_pregnant",     "currently_pregnant",           "exact",   {}, 1.0, "fertility",
     "Currently pregnant; may legitimately differ between waves"),

    # ── FP behaviour section ──────────────────────────────────────────────────
    # Method use can change, but method awareness (which methods they know) is
    # more stable and is used as the key signal here.
    ("fpbeh_fpnow",          "currently_using_fp",           "exact",   {}, 1.0, "fp_behaviour",
     "Currently using a FP method; may change between waves"),

    # ── FP utilisation section ────────────────────────────────────────────────
    ("fptutil_any",          "visited_health_facility_fp",   "exact",   {}, 1.0, "fp_utilisation",
     "Visited health facility for FP; wave-specific but should be stable within a wave"),

    # ── FP attitudes / views section ──────────────────────────────────────────
    # Attitudes toward FP are relatively stable over short periods. A large
    # difference likely indicates a different respondent.
    ("fpatt_immoral",        "self_religious_leaders",       "numeric", {"method": "gauss", "scale": 1}, 1.5, "fp_views",
     "Attitude: FP is immoral (Likert 1-5); slow-changing — mismatch suggests wrong ID"),
    ("fpatt_dontplan",       "self_morally_wrong",           "numeric", {"method": "gauss", "scale": 1}, 1.5, "fp_views",
     "Attitude: FP undermines planning (Likert 1-5); slow-changing"),

    # ── Information section ───────────────────────────────────────────────────
    ("info_newpregnancy",    "fp_harder_conceive_likelihood","numeric", {"method": "gauss", "scale": 1}, 1.0, "info",
     "Belief about post-delivery pregnancy risk (Likert); fairly stable knowledge item"),

    # ── Partner section ───────────────────────────────────────────────────────
    ("partner_talk_fp_time", "last_discussed_fp_with_spouse","numeric", {"method": "gauss", "scale": 2}, 0.8, "partner",
     "When last discussed FP with partner; may change between waves (scale=2 units)"),

    # ── Radio section ─────────────────────────────────────────────────────────
    ("radio_any",            "listened_radio_past_month",    "exact",   {}, 1.0, "radio",
     "Listens to radio; generally stable media-access behaviour"),

    # ── Access section ────────────────────────────────────────────────────────
    ("lastspoke_try",        "tried_get_contraception_since_last", "exact", {}, 0.8, "access",
     "Tried to get contraception since last contact; wave-specific"),

    # ── Pressure / norms section ──────────────────────────────────────────────
    ("pressure_pnorm",       "community_look_down",          "numeric", {"method": "gauss", "scale": 1}, 1.0, "pressure_norms",
     "Perceived community norm about FP (Likert); fairly stable"),
]

# ── Verdict thresholds ─────────────────────────────────────────────────────────
VERDICT_SAME_PERSON   = 0.80   # ≥ this → genuine repeat contact
VERDICT_REVIEW        = 0.55   # ≥ this but < SAME → review needed
# < VERDICT_REVIEW → probable wrong ID


def _resolve_col(df: pd.DataFrame, real_name: str, mock_name: str) -> str | None:
    """Return the column name that exists in df, preferring the real name."""
    if real_name in df.columns:
        return real_name
    if mock_name in df.columns and mock_name != real_name:
        return mock_name
    return None


def _verdict(score: float) -> str:
    if pd.isna(score):
        return "insufficient_data"
    if score >= VERDICT_SAME_PERSON:
        return "same_person"
    if score >= VERDICT_REVIEW:
        return "review_needed"
    return "probable_wrong_id"


def _clean_raw_df(df: pd.DataFrame) -> None:
    """In-place: blank strings → NaN; numeric-looking columns → numeric dtype."""
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        df[col] = df[col].where(~df[col].str.fullmatch(r"\s*", na=False), other=np.nan)
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except (ValueError, TypeError):
            pass


def load_data(use_cleaned: bool = False) -> tuple[pd.DataFrame, bool]:
    """
    Load survey data. Tries raw data first (has name_pull) unless use_cleaned.
    Returns (df, has_name_col).
    """
    if not use_cleaned:
        csv_files = sorted(RAW_DATA_DIR.glob("*.csv"))
        if csv_files:
            df = pd.read_csv(csv_files[0], dtype=str, keep_default_na=False)
            _clean_raw_df(df)
            has_name = "name_pull" in df.columns
            print(f"  Loaded raw data: {csv_files[0].name} ({len(df)} rows)")
            if not has_name:
                print("  WARNING: name_pull not found in raw data — name matching disabled")
            return df, has_name

    # Fall back to cleaned data
    print(f"  Loading cleaned data (no name matching): {RAW_DATA_PATH}")
    df = pd.read_excel(RAW_DATA_PATH, sheet_name='data',low_memory=False)
    _clean_raw_df(df)
    return df, False


def inject_synthetic_duplicate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Copy the first two rows, give them the same respondent ID, and modify
    a few fields so the comparison is non-trivial. Used only for --demo mode.
    """
    id_col = _resolve_col(df, COL_RESPONDENT_ID, "respondent_id")
    key_col = COL_KEY

    row_a = df.iloc[0].copy()
    row_b = df.iloc[1].copy()

    # Force same respondent ID and similar demographics (same person)
    shared_id = "DEMO-DUPE-001"
    row_a[id_col] = shared_id
    row_b[id_col] = shared_id
    row_a[key_col] = "demo-key-A"
    row_b[key_col] = "demo-key-B"

    # Make row_b slightly different: different FP use, same demographics
    for col in ["currently_using_fp", "fpbeh_fpnow"]:
        if col in row_b.index:
            row_b[col] = 1 if str(row_a.get(col, 0)) == "0" else 0

    # Append both synthetic rows
    synthetic = pd.DataFrame([row_a, row_b])
    df_demo = pd.concat([df, synthetic], ignore_index=True)
    print(f"  [demo] Injected 2 synthetic rows with resp_id_pull='{shared_id}'")
    return df_demo


def run_comparison(df: pd.DataFrame, has_name: bool) -> pd.DataFrame:
    """
    Core comparison logic. Returns a DataFrame of pair-level similarity scores.
    """
    id_col = _resolve_col(df, COL_RESPONDENT_ID, "respondent_id")
    if id_col is None:
        raise ValueError(
            f"Could not find respondent ID column (tried '{COL_RESPONDENT_ID}' and 'respondent_id')"
        )

    # Find groups with more than one submission
    counts = df[id_col].value_counts()
    dup_ids = counts[counts > 1].index
    if len(dup_ids) == 0:
        print("  No duplicate respondent IDs found — nothing to compare.")
        return pd.DataFrame()

    df_dups = df[df[id_col].isin(dup_ids)].copy().reset_index(drop=True)
    print(f"  {len(dup_ids)} duplicate ID(s), {len(df_dups)} submission(s) involved")

    # ── Step 2: Index — block on respondent ID ─────────────────────────────────
    indexer = recordlinkage.Index()
    indexer.block(on=id_col)
    candidate_pairs = indexer.index(df_dups)
    print(f"  {len(candidate_pairs)} candidate pair(s) to compare")

    # ── Step 3: Build Compare object for available columns ────────────────────
    compare   = recordlinkage.Compare()
    col_meta  = []   # track (label, weight, section) for columns actually added

    for real_name, mock_name, ctype, params, weight, section, rationale in COMPARISON_SPEC:
        if not has_name and real_name == "name_pull":
            continue  # skip PII column when running on cleaned data

        col = _resolve_col(df_dups, real_name, mock_name)
        if col is None:
            continue   # column not in this dataset — skip silently

        label = real_name.replace("-", "_")   # label must be a valid identifier

        if ctype == "string":
            compare.string(col, col, label=label, **params)
        elif ctype == "exact":
            compare.exact(col, col, label=label, **params)
        elif ctype == "numeric":
            # Cast to numeric before comparison
            df_dups[col] = pd.to_numeric(df_dups[col], errors="coerce")
            compare.numeric(col, col, label=label, **params)

        col_meta.append((label, weight, section, col, rationale))

    if not col_meta:
        print("  WARNING: no comparison columns found in data — cannot compute scores")
        return pd.DataFrame()

    print(f"  Comparing {len(col_meta)} column(s): "
          f"{', '.join(s for _, _, s, _, _ in col_meta)}")

    # ── Step 4: Compute feature matrix ────────────────────────────────────────
    features = compare.compute(candidate_pairs, df_dups)

    # ── Step 5: Weighted score ────────────────────────────────────────────────
    total_weight = sum(w for _, w, _, _, _ in col_meta)
    features["similarity_score"] = sum(
        features.get(label, 0) * weight / total_weight
        for label, weight, _, _, _ in col_meta
    )
    features["n_columns_compared"] = len(col_meta)

    # ── Step 6: Annotate pairs with identifiers ───────────────────────────────
    key_col = COL_KEY if COL_KEY in df_dups.columns else None
    date_col = "SubmissionDate" if "SubmissionDate" in df_dups.columns else None

    rows = []
    for (idx_a, idx_b), feat_row in features.iterrows():
        row_a = df_dups.loc[idx_a]
        row_b = df_dups.loc[idx_b]
        score = feat_row["similarity_score"]
        record = {
            "resp_id_pull":        row_a[id_col],
            "KEY_a":               row_a[key_col] if key_col else "",
            "KEY_b":               row_b[key_col] if key_col else "",
            "date_a":              row_a[date_col] if date_col else "",
            "date_b":              row_b[date_col] if date_col else "",
            "similarity_score":    round(score, 4),
            "n_columns_compared":  int(feat_row["n_columns_compared"]),
            "verdict":             _verdict(score),
        }
        # Per-column scores
        for label, weight, section, col, _ in col_meta:
            if label in feat_row.index:
                record[f"score_{label}"] = round(feat_row[label], 4)
        rows.append(record)

    result = pd.DataFrame(rows).sort_values("similarity_score", ascending=True)

    # ── Print per-column legend ───────────────────────────────────────────────
    print("\n  Column weights and rationale:")
    print(f"  {'Section':<18} {'Column resolved':<30} {'Weight':>6}  Rationale")
    print("  " + "-" * 90)
    for label, weight, section, col, rationale in col_meta:
        print(f"  {section:<18} {col:<30} {weight:>6.1f}  {rationale[:55]}")

    return result


def summarise(result: pd.DataFrame) -> pd.DataFrame:
    """Group by respondent ID and pick the worst pair verdict."""
    if result.empty:
        return pd.DataFrame()
    verdict_rank = {"probable_wrong_id": 0, "review_needed": 1,
                    "same_person": 2, "insufficient_data": 3}
    summary_rows = []
    for rid, grp in result.groupby("resp_id_pull"):
        grp_ranked = grp.copy()
        grp_ranked["_rank"] = grp_ranked["verdict"].map(verdict_rank)
        worst = grp_ranked.sort_values("_rank").iloc[0]
        summary_rows.append({
            "resp_id_pull":      rid,
            "n_pairs":           len(grp),
            "min_score":         grp["similarity_score"].min(),
            "max_score":         grp["similarity_score"].max(),
            "worst_verdict":     worst["verdict"],
            "KEY_pair":          f"{worst['KEY_a']} vs {worst['KEY_b']}",
        })
    return (
        pd.DataFrame(summary_rows)
        .sort_values("min_score")
        .reset_index(drop=True)
    )


def main(use_cleaned: bool = False, demo: bool = False) -> None:
    print("=" * 64)
    print("Niger Phone Pulse — Duplicate Similarity Scoring")
    print("=" * 64)
    if demo:
        print("  *** DEMO MODE — synthetic duplicate injected ***")
    if not use_cleaned and not demo:
        print("  NOTE: This script reads PII (name_pull). Output is internal-only.")

    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df, has_name = load_data(use_cleaned=use_cleaned)
    if demo:
        df = inject_synthetic_duplicate(df)
    if not has_name:
        print("  Name matching disabled (running on cleaned/PII-free data).")

    result  = run_comparison(df, has_name)
    summary = summarise(result)

    if result.empty:
        print("\nNo duplicate pairs found. Nothing written.")
        return

    result.to_csv(OUTPUT_FILE, index=False)
    summary.to_csv(SUMMARY_FILE, index=False)

    print(f"\n  Pair-level scores → {OUTPUT_FILE}")
    print(f"  Summary           → {SUMMARY_FILE}")

    print("\n" + "=" * 64)
    print("VERDICT SUMMARY")
    print("=" * 64)
    vc = result["verdict"].value_counts()
    for v in ["probable_wrong_id", "review_needed", "same_person", "insufficient_data"]:
        n = vc.get(v, 0)
        bar = "█" * n
        print(f"  {v:<22} {n:>3}  {bar}")

    print(f"\n  Score range: {result['similarity_score'].min():.3f} – "
          f"{result['similarity_score'].max():.3f}")
    print(f"  Thresholds: same_person ≥ {VERDICT_SAME_PERSON}  |  "
          f"review_needed ≥ {VERDICT_REVIEW}  |  below → probable_wrong_id")

    if not summary.empty:
        wrong_id = summary[summary["worst_verdict"] == "probable_wrong_id"]
        if not wrong_id.empty:
            print(f"\n  ⚠  {len(wrong_id)} respondent ID(s) likely entered incorrectly:")
            for _, r in wrong_id.iterrows():
                print(f"     [{r['resp_id_pull']}] score={r['min_score']:.3f}  "
                      f"pair: {r['KEY_pair']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Similarity scoring for duplicate resp_id_pull")
    parser.add_argument("--cleaned", action="store_true",
                        help="Use cleaned data (no name_pull PII)")
    parser.add_argument("--demo",    action="store_true",
                        help="Inject a synthetic duplicate to demonstrate the pipeline")
    args = parser.parse_args()
    main(use_cleaned=args.cleaned, demo=args.demo)
