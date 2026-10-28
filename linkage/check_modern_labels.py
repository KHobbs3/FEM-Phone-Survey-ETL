"""
Check which baseline method labels the formative pipeline counts as modern.
Prints each distinct method label (form text, after _strip_hausa) in
current_use_methods and known_contraceptive_options, how many respondents
named it, and whether etl_family_planning._mentions_modern_method counts it.
Counts and label text only.

A modern method showing "no" means its label doesn't match
MODERN_METHODS / FORM_LABEL_TO_METHOD and it is left out of mCPR and awareness.

Run from 2_phone pulse/linkage/:  python check_modern_labels.py
"""

import sys

import pandas as pd

import config as cfg

sys.path.insert(0, str(cfg.NIGER_ROOT / "1_formative_research" / "pipeline_output"))
from pipeline import etl_family_planning as fp  # noqa: E402

cols = ["current_use_methods", "known_contraceptive_options"]
base = pd.read_csv(cfg.FORMATIVE_DATA, low_memory=False, usecols=lambda c: c in cols)
for col in cols:
    labels = base[col].apply(fp._strip_hausa).dropna().str.split("|").explode().str.strip()
    print(f"\n{col}:")
    for label, n in labels.value_counts().items():
        modern = "yes" if fp._mentions_modern_method(label) else "no"
        print(f"  modern={modern:<3}  n={n:<4}  {label}")
