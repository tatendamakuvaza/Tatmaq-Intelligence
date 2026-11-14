"""Descriptive statistics, correlation, regression, trends and outliers."""

from .correlation import correlation_pairs, strength_label
from .descriptive import describe
from .outliers import EXTREME_K, STANDARD_K, IqrBounds, iqr_bounds, outlier_mask
from .regression import RegressionError, ols
from .trends import ALPHA, MIN_POINTS_FOR_TEST, linear_trend

__all__ = [
    "ALPHA",
    "EXTREME_K",
    "MIN_POINTS_FOR_TEST",
    "STANDARD_K",
    "IqrBounds",
    "RegressionError",
    "correlation_pairs",
    "describe",
    "iqr_bounds",
    "linear_trend",
    "ols",
    "outlier_mask",
    "strength_label",
]
