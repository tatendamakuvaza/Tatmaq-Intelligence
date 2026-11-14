"""Ordinary least squares regression (simple and multiple)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

#: Above this condition number the predictors overlap enough to make coefficients unstable.
CONDITION_NUMBER_WARNING = 1000.0


class RegressionError(ValueError):
    """The regression cannot be estimated from the data supplied."""


def ols(frame: pd.DataFrame, target: str, predictors: Sequence[str]) -> dict[str, Any]:
    """Fit ``target = b0 + b1*x1 + ... + e`` on rows where every variable is present."""
    import statsmodels.api as sm  # deferred: statsmodels is slow to import

    if not predictors:
        raise RegressionError("at least one predictor is required")
    if target in predictors:
        raise RegressionError("the target cannot also be a predictor")

    used = frame[[target, *predictors]].dropna()
    n, k = len(used), len(predictors)
    if n < k + 2:
        raise RegressionError(f"{n} complete rows are too few to estimate {k} predictor(s)")
    y = used[target].to_numpy(dtype="float64")
    if np.ptp(y) == 0:
        raise RegressionError(f"'{target}' does not vary")
    constant = [name for name in predictors if np.ptp(used[name].to_numpy(dtype="float64")) == 0]
    if constant:
        raise RegressionError(f"predictor(s) do not vary: {', '.join(constant)}")

    design = sm.add_constant(used[list(predictors)].astype("float64"), has_constant="add")
    fit = sm.OLS(y, design).fit()
    intervals = fit.conf_int(alpha=0.05)
    names = ["intercept", *predictors]
    coefficients = [
        {
            "term": name,
            "coefficient": float(fit.params.iloc[i]),
            "std_error": float(fit.bse.iloc[i]),
            "t": float(fit.tvalues.iloc[i]),
            "p_value": float(fit.pvalues.iloc[i]),
            "ci_low": float(intervals.iloc[i, 0]),
            "ci_high": float(intervals.iloc[i, 1]),
        }
        for i, name in enumerate(names)
    ]
    condition_number = float(fit.condition_number)
    warnings: list[str] = []
    if k > 1 and condition_number > CONDITION_NUMBER_WARNING:
        warnings.append(
            "The predictors are strongly related to each other (or on very different scales), "
            "so individual coefficients may be unreliable."
        )
    return {
        "target": target,
        "predictors": list(predictors),
        "n": n,
        "rows_dropped": len(frame) - n,
        "coefficients": coefficients,
        "r_squared": float(fit.rsquared),
        "adj_r_squared": float(fit.rsquared_adj),
        "f_statistic": float(fit.fvalue),
        "f_p_value": float(fit.f_pvalue),
        "residual_std_error": float(np.sqrt(fit.scale)),
        "condition_number": condition_number,
        "warnings": warnings,
    }
