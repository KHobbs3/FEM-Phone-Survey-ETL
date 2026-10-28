"""Shared statistics helpers for the cross-sectional (independent-samples)
comparison scripts. Unlike the linked/longitudinal scripts one directory up
(McNemar/Wilcoxon — paired tests for the SAME people at two time points),
these compare TWO DIFFERENT groups of people, so every test here is an
independent-samples test."""

from __future__ import annotations

import math

from scipy import stats


def two_proportion_ztest(x1: int, n1: int, x2: int, n2: int) -> float:
    """
    Two-sided two-proportion z-test p-value: is the proportion x2/n2
    (follow-up) different from x1/n1 (baseline), treating the two samples as
    independent. Returns NaN if either sample is empty or the pooled
    proportion gives a zero standard error (e.g. 0% in both groups).
    """
    if n1 == 0 or n2 == 0:
        return float("nan")
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return float("nan")
    z = (p2 - p1) / se
    return float(2 * (1 - stats.norm.cdf(abs(z))))


def wilson_ci(x: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for the proportion x/n, as (low, high)
    proportions. (NaN, NaN) if n == 0. Behaves well near 0% and 100%, where
    the usual normal interval doesn't."""
    if n == 0:
        return float("nan"), float("nan")
    p = x / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def mann_whitney_p(sample1, sample2) -> float:
    """Two-sided Mann-Whitney U test p-value for two independent samples of
    a count/continuous variable (e.g. number of methods known per
    respondent) — the independent-samples analogue of Wilcoxon signed-rank
    used on the linked side."""
    try:
        return float(stats.mannwhitneyu(sample1, sample2, alternative="two-sided").pvalue)
    except ValueError:
        return float("nan")


def chi_square_p(contingency_table) -> float:
    """Chi-square test of independence p-value for a full contingency table
    (e.g. modern/traditional/none-or-other x baseline/follow-up)."""
    try:
        _, p, _, _ = stats.chi2_contingency(contingency_table)
        return float(p)
    except ValueError:
        return float("nan")
