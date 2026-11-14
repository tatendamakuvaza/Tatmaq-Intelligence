"""Linear regression (ordinary least squares)."""

from __future__ import annotations

from typing import Any

from analytics_core.statistics import ALPHA, RegressionError, ols

from ...analytics import formatting as fmt
from ...analytics.spec import Regression
from .builder import OperationSkipped, SegmentBuilder
from .correlation import p_text

CAUTION = "These are associations in this dataset, not proof of cause and effect."


def run(operation: Regression, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    try:
        result = ols(frame, operation.target, list(operation.predictors))
    except RegressionError as error:
        raise OperationSkipped(str(error)) from error

    target = operation.target
    equation = " + ".join(f"b{i} x '{name}'" for i, name in enumerate(operation.predictors, start=1))
    ref = builder.add_evidence(
        operation="regression", columns=(target, *operation.predictors),
        formula=f"ordinary least squares: '{target}' = b0 + {equation} + error; rows with any missing value dropped",
        parameters={"alpha": ALPHA, "confidence_interval": "95%"},
        rows_total=len(frame), rows_used=result["n"], exclusions={"missing value in a model column": result["rows_dropped"]},
        values=result,
    )  # fmt: skip
    builder.add_table(
        "regression", f"Regression of {target}",
        [("term", "Term", "text"), ("coefficient", "Coefficient", "number4"), ("std_error", "Std error", "number4"),
         ("t", "t", "number"), ("p", "p-value", "text"), ("ci_low", "95% CI low", "number4"),
         ("ci_high", "95% CI high", "number4")],
        [{**{key: c[key] for key in ("term", "coefficient", "std_error", "t", "ci_low", "ci_high")},
          "p": p_text(c["p_value"])} for c in result["coefficients"]],
        ref, note=f"R\u00b2 = {result['r_squared']:.3f}, adjusted R\u00b2 = {result['adj_r_squared']:.3f}, "
                  f"n = {result['n']:,}. {CAUTION}",
    )  # fmt: skip

    sentences = []
    for coefficient in result["coefficients"][1:]:
        name, value, p = coefficient["term"], coefficient["coefficient"], coefficient["p_value"]
        if p < ALPHA:
            others = ", holding the other predictors constant" if len(operation.predictors) > 1 else ""
            sentences.append(
                f"Each one-unit increase in '{name}' is associated with {'an increase' if value > 0 else 'a decrease'} "
                f"of {fmt.number(abs(value), 4)} in '{target}'{others} ({fmt.p_value(p)})."
            )
        else:
            sentences.append(
                f"'{name}' has no statistically significant association with '{target}' ({fmt.p_value(p)})."
            )
    predictors = fmt.join_names([f"'{name}'" for name in operation.predictors])
    builder.add_finding(
        "regression.model", "statistic", f"What moves with {target}",
        f"A linear model of '{target}' on {predictors} explains {result['r_squared']:.1%} of the variation in "
        f"'{target}' (adjusted R\u00b2 = {result['adj_r_squared']:.3f}, n = {result['n']:,}, overall F-test "
        f"{fmt.p_value(result['f_p_value'])}). {' '.join(sentences)} {CAUTION}", ref, 64,
    )  # fmt: skip
    builder.notes.extend(result["warnings"])
