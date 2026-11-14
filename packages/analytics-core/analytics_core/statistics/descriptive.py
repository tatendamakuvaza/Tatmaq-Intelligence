"""Descriptive statistics for one numeric variable."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats


def describe(values: object) -> dict[str, Any]:
    """Count, centre, spread and percentiles of the finite values in ``values``.

    Variance and standard deviation are *sample* statistics (divisor n - 1). The mode
    is reported only when a value actually repeats; for continuous measurements where
    every value is distinct there is no meaningful mode and ``None`` is returned.
    """
    data = np.asarray(values, dtype="float64")
    data = data[np.isfinite(data)]
    n = int(data.size)
    if n == 0:
        return {"count": 0}

    distinct, counts = np.unique(data, return_counts=True)
    top = int(counts.max())
    mode = [float(v) for v in distinct[counts == top][:3]] if top > 1 else None
    p5, p25, p50, p75, p95 = (float(q) for q in np.percentile(data, [5, 25, 50, 75, 95]))
    variance = float(np.var(data, ddof=1)) if n > 1 else None
    std = float(np.std(data, ddof=1)) if n > 1 else None
    skewness = None
    if n > 2 and std:
        skewness = float(stats.skew(data, bias=False))

    return {
        "count": n,
        "sum": float(data.sum()),
        "mean": float(data.mean()),
        "median": p50,
        "mode": mode,
        "mode_count": top if top > 1 else None,
        "variance": variance,
        "std": std,
        "min": float(data.min()),
        "max": float(data.max()),
        "p5": p5,
        "p25": p25,
        "p75": p75,
        "p95": p95,
        "iqr": p75 - p25,
        "skewness": skewness,
        "coefficient_of_variation": (std / abs(float(data.mean()))) if std and data.mean() != 0 else None,
    }
