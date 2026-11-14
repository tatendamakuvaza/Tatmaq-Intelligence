"""Linear trend in an evenly spaced series (for example monthly totals)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import stats

ALPHA = 0.05
#: Fewer points than this and a trend is described but not tested for significance.
MIN_POINTS_FOR_TEST = 6


def linear_trend(
    series: Sequence[float], alpha: float = ALPHA, min_points: int = MIN_POINTS_FOR_TEST
) -> dict[str, Any]:
    """Least-squares line through ``series`` against its position 0, 1, 2, ...

    ``direction`` is one of:

    * ``increasing`` / ``decreasing``  the slope differs from zero at the ``alpha`` level
    * ``no_significant_trend``         a line was fitted but the slope could be chance
    * ``flat``                         every value is identical
    * ``insufficient_data``            fewer than ``min_points`` values: no test is made

    The test treats observations as independent and does not model seasonality; with
    monthly business data both caveats apply and are repeated wherever this is reported.
    """
    y = np.asarray(series, dtype="float64")
    n = int(y.size)
    result: dict[str, Any] = {
        "n": n, "alpha": alpha, "method": "ordinary least squares on period index",
        "slope": None, "intercept": None, "r_squared": None, "p_value": None, "std_error": None,
        "slope_pct_of_mean": None, "tested": False, "direction": "insufficient_data",
    }  # fmt: skip
    if n < 3 or not np.all(np.isfinite(y)):
        return result
    if np.ptp(y) == 0:
        result.update(slope=0.0, intercept=float(y[0]), r_squared=None, direction="flat")
        return result

    fit = stats.linregress(np.arange(n, dtype="float64"), y)
    mean = float(y.mean())
    result.update(
        slope=float(fit.slope),
        intercept=float(fit.intercept),
        r_squared=float(fit.rvalue**2),
        p_value=float(fit.pvalue),
        std_error=float(fit.stderr),
        slope_pct_of_mean=(float(fit.slope) / mean * 100.0) if mean else None,
    )
    if n < min_points:
        return result
    result["tested"] = True
    if fit.pvalue < alpha:
        result["direction"] = "increasing" if fit.slope > 0 else "decreasing"
    else:
        result["direction"] = "no_significant_trend"
    return result
