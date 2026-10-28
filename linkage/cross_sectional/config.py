"""
Configuration for the CROSS-SECTIONAL (independent-samples) baseline-vs-
follow-up comparison — full Formative Research baseline (968 respondents)
vs. each round's full achieved Phone Pulse sample (509 for round 1), as two
DIFFERENT groups of people, not the same 471 linked individuals used by the
scripts one directory up (../compare_*.py).

Deliberately reuses ../config.py's method crosswalk, bilingual label maps,
and attitude/barrier crosswalks rather than duplicating them — the two
comparison types (linked vs. independent-samples) describe the exact same
underlying questions/instruments, they just differ in study design and
statistical test. See ../README.md and this folder's README.md.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
LINKAGE_DIR = THIS_DIR.parent

# Load ../config.py under a distinct module name (not "config") — this
# file is ALSO named config.py and runs as module "config" when a
# compare_*_unlinked.py script here does `import config`, so a plain
# `sys.path` trick would self-reference instead of reaching the parent file.
_spec = importlib.util.spec_from_file_location("linkage_config", LINKAGE_DIR / "config.py")
linked_cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(linked_cfg)

# ── Re-exported shared config (no duplication) ──────────────────────────────
NIGER_ROOT = linked_cfg.NIGER_ROOT
ROUNDS = linked_cfg.ROUNDS
DEFAULT_ROUND_ID = linked_cfg.DEFAULT_ROUND_ID
get_round = linked_cfg.get_round
upsert_round_rows = linked_cfg.upsert_round_rows

METHOD_CROSSWALK = linked_cfg.METHOD_CROSSWALK
PULSE_METHOD_COLUMNS = linked_cfg.PULSE_METHOD_COLUMNS
FORMATIVE_LABEL_TO_METHOD = linked_cfg.FORMATIVE_LABEL_TO_METHOD
TRADITIONAL_METHODS = linked_cfg.TRADITIONAL_METHODS
MODERN_METHODS = linked_cfg.MODERN_METHODS
ATTITUDE_CROSSWALK = linked_cfg.ATTITUDE_CROSSWALK
STATEMENT_AGREE_TEXT = linked_cfg.STATEMENT_AGREE_TEXT
STATEMENT_DISAGREE_TEXT = linked_cfg.STATEMENT_DISAGREE_TEXT
WHYNOT_LABELS = linked_cfg.WHYNOT_LABELS
WHYNOT_GROUPS = linked_cfg.WHYNOT_GROUPS
PULSE_WHYNOT_COLUMNS = linked_cfg.PULSE_WHYNOT_COLUMNS
formative_whynot_codes = linked_cfg.formative_whynot_codes
whynot_items = linked_cfg.whynot_items

# ── Data sources ─────────────────────────────────────────────────────────────
# Full formative baseline — ALL 968 respondents (not just the 471 linked to
# a Phone Pulse record). Same file as ../config.py FORMATIVE_DATA.
FORMATIVE_DATA = linked_cfg.FORMATIVE_DATA

# Per-round full achieved Phone Pulse sample. Only round1 has a real file
# today; add round2/round3 here (pointing at that round's own
# etl_pipeline/outputs/cleaned_data.csv-equivalent) once that data exists —
# no other change needed, the compare_*_unlinked.py scripts already loop
# over whichever rounds have a non-None path here.
ROUND_PULSE_DATA: dict[str, Path | None] = {
    "round1": linked_cfg.NIGER_ROOT / "2_phone pulse" / "etl_pipeline" / "outputs" / "cleaned_data.csv",
    # Set automatically once `run_round.py etl --round <round>` has written the file.
    **{rid: (p if p.exists() else None) for rid, p in {
        rid: linked_cfg.NIGER_ROOT / "2_phone pulse" / "etl_pipeline" / "outputs" / rid / "cleaned_data.csv"
        for rid in ("round2_early", "round2")}.items()},
    "round3": None,  # not yet collected
}

OUTPUT_DIR = THIS_DIR / "outputs"
