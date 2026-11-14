import numpy as np
import pandas as pd
import pytest

from analytics_core.statistics import (
    RegressionError,
    correlation_pairs,
    describe,
    iqr_bounds,
    linear_trend,
    ols,
    outlier_mask,
    strength_label,
)  # fmt: skip

# x = 1..5, y = 2,4,5,4,5: Sxy = 6, Sxx = 10, Syy = 6 (worked by hand)
X = [1.0, 2.0, 3.0, 4.0, 5.0]
Y = [2.0, 4.0, 5.0, 4.0, 5.0]


def test_descriptive_statistics_against_hand_calculation():
    result = describe([2, 4, 4, 4, 5, 5, 7, 9])
    assert (result["count"], result["mean"], result["median"], result["mode"]) == (8, 5.0, 4.5, [4.0])
    assert result["variance"] == pytest.approx(32 / 7)  # sample variance, divisor n - 1
    assert result["std"] == pytest.approx((32 / 7) ** 0.5)
    assert (result["p25"], result["p75"], result["iqr"]) == (4.0, 5.5, 1.5)
    assert (result["min"], result["max"]) == (2.0, 9.0)


def test_descriptive_statistics_edge_cases():
    assert describe([]) == {"count": 0}
    assert describe([np.nan, None]) == {"count": 0}
    single = describe([3.0])
    assert single["variance"] is None and single["std"] is None and single["mode"] is None
    assert describe([1.0, 2.0, 3.0])["mode"] is None  # nothing repeats: no mode


def test_pearson_correlation_against_hand_calculation():
    pairs, skipped = correlation_pairs(pd.DataFrame({"x": X, "y": Y}), ["x", "y"])
    assert skipped == []
    assert pairs[0]["r"] == pytest.approx(6 / 60**0.5)  # 0.7746
    assert pairs[0]["covariance"] == pytest.approx(6 / 4)
    assert (pairs[0]["n"], pairs[0]["strength"], pairs[0]["direction"]) == (5, "very strong", "positive")


def test_correlation_uses_shared_rows_and_explains_what_it_skips():
    frame = pd.DataFrame(
        {"a": [1, 2, 3, 4, np.nan], "b": [2, 4, 6, 8, 10], "c": [7, 7, 7, 7, 7], "d": [1, np.nan, np.nan, np.nan, 2]}
    )
    pairs, skipped = correlation_pairs(frame, ["a", "b", "c", "d"])
    assert [(p["x"], p["y"], p["n"]) for p in pairs] == [("a", "b", 4)]
    assert pairs[0]["r"] == pytest.approx(1.0)
    reasons = {(s["x"], s["y"]): s["reason"] for s in skipped}
    assert reasons[("a", "c")] == "'c' does not vary"
    assert reasons[("b", "d")] == "only 2 rows have both values"


def test_spearman_ranks_a_monotonic_curve_as_perfect():
    frame = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [1, 8, 27, 64, 125]})
    pairs, _ = correlation_pairs(frame, ["x", "y"], method="spearman")
    assert pairs[0]["r"] == pytest.approx(1.0)


def test_strength_labels():
    assert [strength_label(r) for r in (0.05, -0.2, 0.4, -0.6, 0.9)] == [
        "negligible",
        "weak",
        "moderate",
        "strong",
        "very strong",
    ]


def test_simple_regression_against_hand_calculation():
    result = ols(pd.DataFrame({"x": X, "y": Y}), "y", ["x"])
    by_term = {c["term"]: c for c in result["coefficients"]}
    assert by_term["x"]["coefficient"] == pytest.approx(0.6)  # Sxy / Sxx
    assert by_term["intercept"]["coefficient"] == pytest.approx(2.2)  # 4 - 0.6 x 3
    assert result["r_squared"] == pytest.approx(0.6)
    assert result["n"] == 5


def test_multiple_regression_recovers_known_coefficients():
    rng = np.random.default_rng(7)
    a, b = rng.normal(size=60), rng.normal(size=60)
    frame = pd.DataFrame({"a": a, "b": b, "y": 1.0 + 2.0 * a - 3.0 * b})
    frame.loc[0, "a"] = np.nan
    result = ols(frame, "y", ["a", "b"])
    coefficients = {c["term"]: c["coefficient"] for c in result["coefficients"]}
    assert coefficients == pytest.approx({"intercept": 1.0, "a": 2.0, "b": -3.0})
    assert result["r_squared"] == pytest.approx(1.0)
    assert (result["n"], result["rows_dropped"]) == (59, 1)


def test_regression_refuses_what_cannot_be_estimated():
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "k": [5.0] * 4, "y": [1.0, 2.0, 2.5, 4.0]})
    with pytest.raises(RegressionError, match="do not vary"):
        ols(frame, "y", ["k"])
    with pytest.raises(RegressionError, match="too few"):
        ols(frame.head(2), "y", ["x"])
    with pytest.raises(RegressionError, match="cannot also be a predictor"):
        ols(frame, "y", ["y"])


def test_trend_direction_requires_statistical_evidence():
    rising = linear_trend([10, 12, 13, 15, 16, 18, 21, 22])
    assert rising["direction"] == "increasing" and rising["tested"] and rising["slope"] > 0
    falling = linear_trend([22, 21, 18, 16, 15, 13, 12, 10])
    assert falling["direction"] == "decreasing" and falling["p_value"] < 0.05
    noisy = linear_trend([5, 3, 6, 4, 5, 3, 6, 4])
    assert noisy["direction"] == "no_significant_trend"


def test_trend_is_not_tested_on_too_little_data():
    short = linear_trend([1, 2, 3, 4])
    assert short["direction"] == "insufficient_data" and not short["tested"]
    assert short["slope"] == pytest.approx(1.0)  # still described
    assert linear_trend([1, 2])["slope"] is None
    assert linear_trend([4, 4, 4, 4, 4, 4])["direction"] == "flat"


def test_trend_slope_against_hand_calculation():
    assert linear_trend([*Y, 6.0])["slope"] == pytest.approx(11 / 17.5)  # Sxy = 11, Sxx = 17.5


def test_iqr_fences():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]
    bounds = iqr_bounds(values)
    assert (bounds.q1, bounds.q3, bounds.iqr) == (3.5, 8.5, 5.0)
    assert (bounds.lower, bounds.upper) == (-4.0, 16.0)
    assert outlier_mask([*values, np.nan], bounds).tolist() == [False] * 10 + [True, False]
    assert iqr_bounds([1, 2, 3]) is None
