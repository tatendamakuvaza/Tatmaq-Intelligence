"""Correlation between numeric columns."""

from __future__ import annotations

from typing import Any

from analytics_core.statistics import ALPHA, correlation_pairs
from analytics_core.statistics.correlation import STRENGTH_BANDS

from ...analytics import formatting as fmt
from ...analytics.spec import Correlation
from .builder import TOP_N, OperationSkipped, SegmentBuilder

CAUTION = ("Correlation measures how closely two columns move together. It does not show that one causes "
           "the other, and columns calculated from each other are correlated by construction.")  # fmt: skip


def p_text(value: float) -> str:
    return "< 0.001" if value < 0.001 else f"{value:.3f}"


def run(operation: Correlation, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    pairs, skipped = correlation_pairs(frame, list(operation.columns), operation.method)
    if not pairs:
        raise OperationSkipped("no pair of columns has enough shared, varying values to correlate")

    method = "Pearson" if operation.method == "pearson" else "Spearman rank"
    significant = [pair for pair in pairs if pair["p_value"] < ALPHA]
    ref = builder.add_evidence(
        operation="correlation", columns=operation.columns,
        formula=f"{method} correlation coefficient r for each pair, using rows where both values are present; "
                "two-sided p-value for r = 0",
        parameters={"method": operation.method, "alpha": ALPHA, "multiple_comparison_adjustment": "none",
                    "strength_labels": {label: f"|r| < {upper}" for upper, label in STRENGTH_BANDS} | {"very strong": "|r| >= 0.7"}},
        rows_total=len(frame),
        values={"pairs": pairs, "skipped": skipped},
    )  # fmt: skip
    builder.add_table(
        "correlation", f"{method} correlations",
        [("x", "Variable 1", "text"), ("y", "Variable 2", "text"), ("r", "r", "number4"),
         ("r_squared", "r\u00b2", "number4"), ("p", "p-value", "text"), ("n", "Rows", "integer"),
         ("strength", "Strength", "text")],
        [{"x": p["x"], "y": p["y"], "r": p["r"], "r_squared": p["r_squared"], "p": p_text(p["p_value"]),
          "n": p["n"], "strength": f"{p['strength']} {p['direction']}"} for p in pairs[:TOP_N]],
        ref, note=CAUTION,
    )  # fmt: skip
    top = pairs[0]
    builder.add_finding(
        "correlation.strongest", "statistic", "Strongest relationship",
        f"The strongest relationship is between '{top['x']}' and '{top['y']}': a {top['strength']} "
        f"{top['direction']} correlation ({method} r = {top['r']:.2f}, {fmt.p_value(top['p_value'])}, "
        f"n = {top['n']:,}). Of {fmt.count_of(len(pairs), 'pair')} tested, {len(significant)} "
        f"{'is' if len(significant) == 1 else 'are'} statistically significant at the 5% level "
        f"(no adjustment for multiple comparisons). {CAUTION}", ref, 62,
    )  # fmt: skip
    for item in skipped:
        builder.notes.append(f"Correlation of '{item['x']}' with '{item['y']}' was not computed: {item['reason']}.")
