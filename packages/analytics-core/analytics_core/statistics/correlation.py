"""Pairwise correlation and covariance."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats

Method = Literal["pearson", "spearman"]

MIN_OBSERVATIONS = 3

#: Thresholds for describing |r|. A convention (after Cohen), stated with every result.
STRENGTH_BANDS = ((0.1, "negligible"), (0.3, "weak"), (0.5, "moderate"), (0.7, "strong"))


def strength_label(r: float) -> str:
    magnitude = abs(r)
    for upper, label in STRENGTH_BANDS:
        if magnitude < upper:
            return label
    return "very strong"


def correlation_pairs(
    frame: pd.DataFrame,
    columns: Sequence[str],
    method: Method = "pearson",
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Correlation for every pair of ``columns`` using rows where both values exist.

    Returns ``(pairs, skipped)``. Pairs are sorted strongest first. A pair is skipped,
    with the reason, when it has fewer than three shared observations or one variable
    does not vary (correlation is undefined for a constant).
    """
    pairs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for left, right in combinations(columns, 2):
        both = frame[[left, right]].dropna()
        x, y = both[left].to_numpy(dtype="float64"), both[right].to_numpy(dtype="float64")
        n = int(x.size)
        if n < MIN_OBSERVATIONS:
            skipped.append({"x": left, "y": right, "reason": f"only {n} rows have both values"})
            continue
        if np.ptp(x) == 0 or np.ptp(y) == 0:
            constant = left if np.ptp(x) == 0 else right
            skipped.append({"x": left, "y": right, "reason": f"'{constant}' does not vary"})
            continue
        if method == "pearson":
            outcome = stats.pearsonr(x, y)
        else:
            outcome = stats.spearmanr(x, y)
        r, p_value = float(outcome.statistic), float(outcome.pvalue)
        pairs.append(
            {
                "x": left,
                "y": right,
                "method": method,
                "r": r,
                "r_squared": r * r,
                "p_value": p_value,
                "n": n,
                "covariance": float(np.cov(x, y, ddof=1)[0, 1]),
                "strength": strength_label(r),
                "direction": "positive" if r > 0 else "negative" if r < 0 else "none",
            }
        )
    pairs.sort(key=lambda pair: (-abs(pair["r"]), pair["x"], pair["y"]))
    return pairs, skipped
