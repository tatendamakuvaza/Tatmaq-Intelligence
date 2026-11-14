"""Outlier detection with the interquartile-range rule."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Tukey's conventional fences: 1.5 x IQR for "outside", 3 x IQR for "far outside".
STANDARD_K = 1.5
EXTREME_K = 3.0
MIN_OBSERVATIONS = 8


@dataclass(frozen=True)
class IqrBounds:
    q1: float
    q3: float
    iqr: float
    lower: float
    upper: float
    k: float
    n: int


def iqr_bounds(values: object, k: float = STANDARD_K) -> IqrBounds | None:
    """Fences ``Q1 - k x IQR`` and ``Q3 + k x IQR``; ``None`` with too few observations."""
    data = np.asarray(values, dtype="float64")
    data = data[np.isfinite(data)]
    if data.size < MIN_OBSERVATIONS:
        return None
    q1, q3 = (float(q) for q in np.percentile(data, [25, 75]))
    spread = q3 - q1
    return IqrBounds(q1=q1, q3=q3, iqr=spread, lower=q1 - k * spread, upper=q3 + k * spread, k=k, n=int(data.size))


def outlier_mask(values: object, bounds: IqrBounds) -> np.ndarray:
    """True where a value lies outside the fences. Missing values are never outliers."""
    data = np.asarray(values, dtype="float64")
    with np.errstate(invalid="ignore"):
        return np.isfinite(data) & ((data < bounds.lower) | (data > bounds.upper))
