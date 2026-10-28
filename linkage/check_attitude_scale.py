"""
Check which way the Phone Pulse attitude items (fpatt_*) are coded, before
trusting attitude comparisons. Prints counts and means only.

The deployed Hausa form (2_phone pulse/meta/...(hau).xlsx) codes every
fpatt_* item on agreedisagree_long, 0 = Strongly disagree ... 4 = Strongly
agree. Every attitude script reads a score >= 3 as "agrees". Two checks:

1. Answer distribution per item (codes and counts).
2. Mean score for FP users vs non-users (fpbeh_fpnow). With 4 = agree,
   users should score LOWER on the statements unfavourable to FP and HIGHER
   on the favourable ones. The opposite pattern on all of them points to a
   reversed scale (0 = strongly agree).

Run from 2_phone pulse/linkage/:  python check_attitude_scale.py
"""

import pandas as pd

import config as cfg

ITEMS = {
    "fpatt_steril": ("Contraceptives can stop a woman from ever conceiving again", "lower"),
    "fpatt_immoral_2": ("Contraceptive use does not encourage promiscuity", "higher"),
    "fpatt_dontplan": ("A woman must give birth to all the children in her body", "lower"),
    "fpatt_immoral": ("Religious leaders I admire do not use or encourage contraception", "lower"),
    "fpatt_knowledge": ("I don't think I have enough information to use contraceptives", "lower"),
    "fpatt_finance": ("Having many children is important", "lower"),
    "fpatt_childinvest": ("Longer spacing supports children's growth", "higher"),
}

pulse = pd.read_csv(cfg.PULSE_DATA, low_memory=False)
user = pd.to_numeric(pulse.get("fpbeh_fpnow"), errors="coerce")
print(f"Phone Pulse respondents: {len(pulse)}  (FP users: {int((user == 1).sum())}, "
      f"non-users: {int((user == 0).sum())})\n")

for col, (label, expected) in ITEMS.items():
    if col not in pulse.columns:
        print(f"{col}: not in data\n")
        continue
    raw = pulse[col]
    score = pd.to_numeric(raw, errors="coerce")
    counts = raw.value_counts(dropna=False).sort_index()
    m_user, m_non = score[user == 1].mean(), score[user == 0].mean()
    observed = "higher" if m_user > m_non else "lower"
    verdict = "consistent with 4 = agree" if observed == expected else "REVERSED? (opposite of expected)"
    print(f"{col} -- {label}")
    print("  answers: " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
    print(f"  mean score, users {m_user:.2f} vs non-users {m_non:.2f}: users {observed} "
          f"(expected {expected} if 4 = agree) -> {verdict}\n")
