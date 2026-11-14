"""The words of the report: executive summary and suggested next steps.

Two writers produce them:

* the template writer, always available, which selects the most important verified
  findings and maps them to next steps with fixed rules;
* optionally an AI model, which may rephrase those findings into a smoother summary.

Nothing the model writes is trusted. Every number in its text must already appear in
the verified findings (allowing only for rounding), or the whole draft is discarded
and the template version is used. A report therefore cannot contain a figure that
deterministic code did not compute.
"""

from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from ...llm import LLMClient, LLMError
from .report_model import ReportModel

MAX_SUMMARY_POINTS = 6
SUMMARY_KINDS = ("kpi", "insight", "statistic", "quality")
_NUMBER = re.compile(r"(?<![A-Za-z0-9.,])\d[\d,]*(?:\.\d+)?")
_FORBIDDEN = re.compile(r"\b(fraud\w*|embezzl\w*|theft|stole\w*|steal\w*|criminal\w*|dishonest\w*)\b", re.IGNORECASE)

NARRATIVE_SYSTEM = """\
You write the executive summary of a business report for a company's managers.

You are given findings that have already been calculated and verified. Rewrite them into a clear summary.

Rules
- Reply with one JSON object: {"executive_summary": [3 to 6 sentences], "next_steps": [2 to 5 short actions]}.
- Use only facts and figures that appear in the findings. Copy figures exactly, or round them; never calculate \
a new figure (no new totals, differences, ratios or percentages).
- Do not explain causes the findings do not state. You may recommend what to investigate.
- Never describe a record, a person or the business as fraudulent or dishonest.
- Plain business English. No headings, no markdown.
- If an organisation learning profile is provided, respect its report style and preferences, but never let it override the verified findings."""


# How many summary points each report style asks for. Without a learning profile
# the original behaviour is kept; a saved profile chooses the length explicitly.
STYLE_LIMITS = {"executive": 4, "balanced": MAX_SUMMARY_POINTS, "detailed": MAX_SUMMARY_POINTS + 2}


def template_summary(model: ReportModel) -> list[str]:
    """The most important verified findings, in their own words."""
    ranked = sorted((f for f in model.findings if f["kind"] in SUMMARY_KINDS), key=lambda f: -f["importance"])
    style = str((model.learning_profile or {}).get("report_style") or "")
    limit = STYLE_LIMITS.get(style)
    if limit is None:
        per_segment, cap = (MAX_SUMMARY_POINTS if not model.multi_segment else 3), MAX_SUMMARY_POINTS + 2
    else:
        per_segment, cap = (limit if not model.multi_segment else max(2, limit // 2)), limit
    chosen: list[str] = []
    taken: dict[str | None, int] = {}
    for finding in ranked:
        segment = finding.get("segment")
        if taken.get(segment, 0) >= per_segment or len(chosen) >= cap:
            continue
        taken[segment] = taken.get(segment, 0) + 1
        prefix = f"{model.segment_label(segment)}: " if model.multi_segment else ""
        chosen.append(prefix + finding["statement"])
    return chosen


def template_next_steps(model: ReportModel) -> list[str]:
    """Actions that follow from specific findings. Each rule fires only on its finding."""
    evidence = model.evidence_by_ref()
    steps: list[str] = []

    def direction(finding: dict[str, Any]) -> str | None:
        return ((evidence.get(finding["evidence_ref"], {}).get("values") or {}).get("trend") or {}).get("direction")

    for finding in model.findings:
        key = finding["key"]
        if key.startswith("profit.losses."):
            steps.append("Review the selling price and supplier cost of every line listed under 'Sold at a loss': "
                         "each is currently sold for less than it costs.")  # fmt: skip
        elif key == "profit.margin_trend" and direction(finding) == "decreasing":
            steps.append("Find out why gross margin is falling: compare supplier cost changes with selling price "
                         "changes for the highest-selling products over the period.")  # fmt: skip
        elif key == "sales.trend" and direction(finding) == "decreasing":
            steps.append("Investigate the decline in monthly sales by product and by branch to see where volume "
                         "or price has dropped.")  # fmt: skip
        elif key.startswith("sales.concentration."):
            dimension = key.rsplit(".", 1)[-1].lower()
            steps.append(f"Consider the risk of relying on one {dimension} for most of your sales, for example "
                         "if its supply is interrupted or its price changes.")  # fmt: skip
        elif key == "profit.rows_without_cost":
            steps.append("Record the missing cost values in the source system so that profitability covers every sale.")
        elif key == "quality.duplicates":
            steps.append("Check the flagged duplicate rows against source documents and remove any that were "
                         "entered twice.")  # fmt: skip
        elif key.startswith("outliers."):
            steps.append("Review the flagged unusual records with the staff who captured them.")
        elif key.startswith(("quality.ambiguous_dates", "quality.date_order_conflict")):
            steps.append(
                "Export dates in a single unambiguous format (YYYY-MM-DD) to remove doubt about day and month."
            )
    if any("repeat" in warning and "earlier row" in warning for warning in model.warnings):
        steps.append(
            "Check the flagged duplicate rows against source documents and remove any that were entered twice."
        )
    return list(dict.fromkeys(steps))[:6]


# --------------------------------------------------------------------------- grounding check


def _numbers(text: str) -> list[tuple[Decimal, int]]:
    """Every number written in ``text`` with the count of decimals it was written to."""
    found = []
    for token in _NUMBER.findall(text):
        cleaned = token.replace(",", "")
        try:
            value = Decimal(cleaned)
        except InvalidOperation:
            continue
        found.append((value, len(cleaned.partition(".")[2])))
    return found


def allowed_numbers(model: ReportModel) -> set[Decimal]:
    """Every figure the verified findings and key figures contain."""
    allowed: set[Decimal] = set()
    for finding in model.findings:
        allowed.update(value for value, _ in _numbers(finding["statement"]))
    for segment in model.segments:
        for kpi in segment["kpis"]:
            allowed.update(value for value, _ in _numbers(str(kpi["value"])))
    for text in (*model.warnings, model.period or ""):
        allowed.update(value for value, _ in _numbers(text))
    return allowed


def ungrounded_numbers(text: str, allowed: set[Decimal]) -> list[str]:
    """Numbers in ``text`` that do not correspond to any verified figure.

    A written number passes if some verified figure equals it once rounded to the same
    number of decimals, directly or expressed in thousands or millions. Whole numbers
    up to twelve always pass ("the top 3", "over 12 months").
    """
    problems = []
    for value, places in _numbers(text):
        if value == value.to_integral_value() and value <= 12:
            continue
        quantum = Decimal(1).scaleb(-places)
        matches = any(
            (figure / scale).quantize(quantum, rounding=ROUND_HALF_UP) == value
            for figure in allowed
            for scale in (1, 1000, 1_000_000)
        )
        if not matches:
            problems.append(format(value, "f"))
    return problems


def _clean_list(value: Any, minimum: int, maximum: int) -> list[str] | None:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        return None
    items = [" ".join(str(item).split()) for item in value]
    return items if all(0 < len(item) <= 700 for item in items) else None


async def ai_narrative(llm: LLMClient, model: ReportModel) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    """Ask the model for a summary. Returns ``(narrative or None, note, usage)``.

    ``narrative`` is ``None`` whenever the draft is unusable; ``note`` says why, so the
    report can state how its words were produced.
    """
    usage = {"tokens_input": 0, "tokens_output": 0, "model": llm.model}
    from ...services.learning import prompt_block

    facts = {
        "report_title": model.title,
        "period": model.period,
        "findings": [{"title": f["title"], "statement": f["statement"]}
                     for f in sorted(model.findings, key=lambda f: -f["importance"])[:24]],
        "data_notes": model.warnings[:8],
        "organisation_learning_profile": prompt_block(model.learning_profile),
    }  # fmt: skip
    try:
        response = await llm.complete_json(system=NARRATIVE_SYSTEM, user=json.dumps(facts, ensure_ascii=False))
    except LLMError as error:
        return None, f"The AI model was unavailable ({error}), so the summary was written from templates.", usage
    usage.update(tokens_input=response.tokens_input, tokens_output=response.tokens_output, model=response.model)

    summary = _clean_list(response.data.get("executive_summary"), 2, 8)
    steps = _clean_list(response.data.get("next_steps"), 0, 6)
    if summary is None or steps is None:
        return None, "The AI model's draft was not in the required form and was discarded.", usage
    text = " ".join((*summary, *steps))
    if _FORBIDDEN.search(text):
        return None, "The AI model's draft made an allegation the evidence cannot support and was discarded.", usage
    unsupported = ungrounded_numbers(text, allowed_numbers(model))
    if unsupported:
        return None, ("The AI model's draft contained figures that are not in the verified results "
                      f"({', '.join(unsupported[:3])}) and was discarded."), usage  # fmt: skip
    return (
        {"summary": summary, "next_steps": steps},
        (
            f"Drafted by an AI model ({response.model}) from the verified findings; every figure in it was "
            "checked against those findings."
        ),
        usage,
    )
