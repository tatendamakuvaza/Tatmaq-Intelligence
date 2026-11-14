"""Quality verification: results are reconciled before anything is reported.

This is the step between calculation and reporting (specification 4.3). It applies
the tests an auditor would: parts add up to the whole, profit equals sales less cost,
every row is accounted for, and the headline totals agree with a second calculation
made a different way (plain floating-point sums in pandas, against the engine's exact
decimal arithmetic). If any check fails, the findings are not approved and no report
is written.

It is deterministic code, not an AI agent.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any

import pandas as pd

from analytics_core.financial import gross_margin_pct
from analytics_core.validation import Check, close_to_float, identity, parts_equal_total, rows_balance, within

from ..agents.statistical_analysis.agent import split_by_currency
from .spec import AnalysisSpec


def _float_measure(frame: pd.DataFrame, measure: dict[str, Any]) -> pd.Series:
    if measure.get("column"):
        return frame[measure["column"]].astype("float64")
    left, right = measure["multiply"]
    return frame[left].astype("float64") * frame[right].astype("float64")


def _sales_checks(frame: pd.DataFrame, audit: dict[str, Any]) -> list[Check]:
    total = Decimal(audit["total"])
    recalculated = float(_float_measure(frame, audit["measure"]).sum(skipna=True))
    checks = [
        close_to_float("Total sales agrees with an independent recalculation", total, recalculated),
        rows_balance("Every row is either in total sales or reported as left out",
                     audit["rows_used"], audit["rows_missing"], len(frame)),
    ]  # fmt: skip
    if "monthly" in audit:
        parts = [Decimal(value) for _, value in audit["monthly"]] + [Decimal(audit["undated"])]
        checks.append(parts_equal_total("Monthly sales (plus undated rows) add up to total sales", parts, total))
    for dimension, groups in audit["dimensions"].items():
        checks.append(parts_equal_total(f"Sales by {dimension} add up to total sales",
                                        [Decimal(value) for _, value in groups], total))  # fmt: skip
    return checks


def _profit_checks(frame: pd.DataFrame, audit: dict[str, Any], date_column: str | None) -> list[Check]:
    revenue, cost = Decimal(audit["revenue"]), Decimal(audit["cost"])
    profit = Decimal(audit["gross_profit"])
    margin = Decimal(audit["margin_pct"]) if audit["margin_pct"] is not None else None
    sales, costs = _float_measure(frame, audit["revenue_measure"]), _float_measure(frame, audit["cost_measure"])
    both = sales.notna() & costs.notna()
    checks = [
        identity("Gross profit equals sales less cost of sales", revenue - cost, profit),
        identity("Gross margin equals gross profit divided by sales", gross_margin_pct(revenue, cost), margin),
        within("Gross margin is not above 100%", margin, None, Decimal(100)),
        close_to_float("Sales used for profit agree with an independent recalculation", revenue, float(sales[both].sum())),
        close_to_float("Cost of sales agrees with an independent recalculation", cost, float(costs[both].sum())),
        rows_balance("Every row is either in the profit figures or reported as left out",
                     audit["rows_used"], audit["rows_excluded"], len(frame)),
    ]  # fmt: skip
    for dimension, groups in audit["dimensions"].items():
        checks.append(parts_equal_total(f"Gross profit by {dimension} adds up to total gross profit",
                                        [Decimal(r) - Decimal(c) for _, r, c in groups], profit))  # fmt: skip
    undated = bool(date_column) and bool(frame.loc[both, date_column].isna().any())
    if "monthly" in audit and not undated:
        checks.append(parts_equal_total("Monthly gross profit adds up to total gross profit",
                                        [Decimal(r) - Decimal(c) for _, r, c in audit["monthly"]], profit))  # fmt: skip
    return checks


def verify_results(
    frame: pd.DataFrame, spec: AnalysisSpec, outputs: dict[str, Any], findings: list[dict[str, Any]],
    evidence: list[dict[str, Any]], *, default_currency: str | None, dataset_version_id: str, dataset_sha256: str,
) -> dict[str, Any]:  # fmt: skip
    """Run every reconciliation check. ``passed`` is True only if all of them pass."""
    segments = {segment.key: segment for segment in split_by_currency(frame, spec.currency_column, default_currency)[0]}
    profit_date = next((op.date for op in spec.operations if op.type == "profitability"), None)
    multiple = len(outputs["segments"]) > 1
    results: list[dict[str, Any]] = []

    def record(checks: list[Check], scope: str | None) -> None:
        for check in checks:
            name = f"{scope}: {check.name}" if scope and multiple else check.name
            results.append({**asdict(check), "name": name})

    for described in outputs["segments"]:
        key = described["key"]
        segment = segments.get(key)
        if segment is None:
            record([Check("Each reported segment exists in the data", False, f"no rows for '{key}'")], None)
            continue
        audit = outputs["audit"].get(key, {})
        record([Check("Row count matches the dataset", described["rows"] == len(segment.frame),
                      f"{described['rows']} reported vs {len(segment.frame)} in the data")], described["label"])  # fmt: skip
        if "sales" in audit:
            record(_sales_checks(segment.frame, audit["sales"]), described["label"])
        if "profitability" in audit:
            record(_profit_checks(segment.frame, audit["profitability"], profit_date), described["label"])

    refs = {item["ref"] for item in evidence}
    cited = {finding["evidence_ref"] for finding in findings}
    for described in outputs["segments"]:
        cited.update(block["evidence_ref"] for group in ("kpis", "charts", "tables") for block in described[group])
    missing = sorted(cited - refs)
    record([
        Check("Every finding, figure, chart and table cites an evidence record", not missing,
              "all citations resolve" if not missing else f"unresolved: {', '.join(missing)}"),
        Check("Every evidence record names the dataset version and its fingerprint",
              all(str(item["dataset_version_id"]) == dataset_version_id and item["dataset_sha256"] == dataset_sha256
                  for item in evidence),
              f"{len(evidence)} evidence records checked against version {dataset_version_id[:8]}"),
        Check("At least one finding was produced", bool(findings), f"{len(findings)} findings"),
    ], None)  # fmt: skip
    return {"passed": all(result["passed"] for result in results), "checks": results}
