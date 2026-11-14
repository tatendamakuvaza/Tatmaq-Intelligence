"""Turning a request into a validated analysis plan, with rules and no AI model.

This planner is always available. It is what runs when no AI provider is configured,
and what the system falls back to whenever an AI-written plan fails validation, so a
customer can always get an analysis.

It reads two things: the words of the request (to recognise what is being asked for)
and the dataset's column dictionary (to decide what the data can support). It never
sees a row of customer data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...analytics.spec import (
    MAX_DIMENSIONS,
    OPERATION_TITLES,
    AnalysisSpec,
    Correlation,
    DataQuality,
    DescriptiveStatistics,
    Measure,
    Operation,
    Outliers,
    Profitability,
    Regression,
    SalesOverview,
    Trend,
)  # fmt: skip

MEASURE_ROLES = ("revenue", "cost", "quantity", "unit_price", "unit_cost", "measure")
DIMENSION_ROLES = ("product", "category", "region", "customer", "salesperson")
MAX_DIMENSION_VALUES = 5000
MAX_STAT_COLUMNS = 8
MAX_PREDICTORS = 4

INTENT_PATTERNS = {
    "profitability": r"\b(profit\w*|margin\w*|mark-?ups?|loss(?:es)?|loss-making)\b",
    "sales": r"\b(sales?|revenue|turnover|income|sell\w*|sold|perform\w*)\b",
    "trend": r"\b(trend\w*|over time|growth|grow\w*|declin\w*|increas\w*|decreas\w*|monthly|"
             r"month[- ](?:by|on)[- ]month|season\w*|(?:past|last) \d+ months)\b",
    "descriptive": r"\b(describ\w*|descriptive|summary statistics|statistic\w*|average|mean|median|distribution|"
                   r"spread|varian\w*|standard deviation|percentile\w*)\b",
    "correlation": r"\b(correlat\w*|relationships?|related|associat\w*)\b",
    "regression": r"\b(regress\w*|predict\w*|drivers?|drives?|effect of|impact of|influenc\w*|depends? on)\b",
    "outliers": r"\b(outliers?|unusual|anomal\w*|suspicious|abnormal|irregular\w*)\b",
    "data_quality": r"\b(data quality|quality of (?:the|my|our) data|clean\w*|duplicat\w*|missing (?:values|data))\b",
}  # fmt: skip

ANALYSIS_TYPE_INTENTS = {
    "sales": {"sales"},
    "profitability": {"sales", "profitability"},
    "statistical": {"descriptive", "correlation"},
    "data_quality": {"data_quality"},
}

#: Words in a request that point at a kind of dimension ("which branches...").
DIMENSION_WORDS = {
    "product": r"\b(products?|items?|skus?|lines?)\b",
    "category": r"\b(categor\w+|departments?|groups?)\b",
    "region": r"\b(branch\w*|regions?|stores?|shops?|outlets?|locations?|cities|city|areas?)\b",
    "customer": r"\b(customers?|clients?|accounts?|buyers?)\b",
    "salesperson": r"\b(sales ?(?:people|persons?|reps?)|reps?|cashiers?|staff)\b",
}

AGENT_ACTIONS = {
    "chief_intelligence": {"plan_analysis"},
    "data_acquisition": {"import_and_profile", "verify_and_load"},
    "data_cleaning": {"clean_and_validate", "validate_for_analysis"},
    "statistical_analysis": {"run_analysis"},
    "quality_verification": {"verify_results"},
    "report_generation": {"generate_report"},
}


class PlanningError(Exception):
    """No analysis can be planned. The message tells the customer what is missing."""


@dataclass(frozen=True)
class Column:
    name: str
    kind: str
    role: str
    distinct_count: int = 0
    non_null: int = 0


@dataclass
class PlanOutcome:
    spec: AnalysisSpec
    notes: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)


def to_columns(profile_columns: list[dict[str, Any]]) -> list[Column]:
    return [Column(name=c["name"], kind=c["kind"], role=c.get("role") or "", distinct_count=c.get("distinct_count") or 0,
                   non_null=c.get("non_null") or 0) for c in profile_columns]  # fmt: skip


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def detect_intents(prompt: str, column_names: tuple[str, ...] = ()) -> list[str]:
    """What the request asks for.

    Column names are blanked out first: in "is quantity correlated with sales amount?"
    the word "sales" names a column, it does not ask for a sales analysis.
    """
    text = _normalise(prompt)
    for name in sorted(column_names, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(_normalise(name))}\b", " ", text) if _normalise(name) else text
    return [intent for intent, pattern in INTENT_PATTERNS.items() if re.search(pattern, text)]


_TARGET_AFTER = re.compile(
    r"\b(predict\w*|drives?|drivers? of|explains?|influenc\w*|affects?|(?:effect|impact) of .*? on)\b"
)
_TARGET_BEFORE = re.compile(r"\bdepends? on\b")


def regression_target(prompt: str, mentions: list[tuple[int, str]]) -> str | None:
    """Which named column a request wants explained: "what predicts X", "effect of A on X", "X depends on A"."""
    text = _normalise(prompt)
    if match := _TARGET_AFTER.search(text):
        following = [name for position, name in mentions if position >= match.end()]
        if following:
            return following[0]
    if match := _TARGET_BEFORE.search(text):
        preceding = [name for position, name in mentions if position < match.start()]
        if preceding:
            return preceding[-1]
    return None


class _Dataset:
    """What the column dictionary says the data can support."""

    def __init__(self, columns: list[Column], prompt: str) -> None:
        self.columns = columns
        self._prompt = _normalise(prompt)
        self._raw_prompt = prompt.lower()
        self._by_role = {column.role: column for column in columns if column.role}

    def role(self, role: str, kind: str) -> str | None:
        column = self._by_role.get(role)
        return column.name if column and column.kind == kind and column.non_null else None

    @property
    def date(self) -> str | None:
        return self.role("date", "date")

    @property
    def measures(self) -> list[str]:
        return [c.name for c in self.columns if c.kind == "number" and c.role in MEASURE_ROLES and c.non_null]

    def mentions(self) -> list[tuple[int, str]]:
        """Numeric columns the request names outright, with where in the request each appears."""
        found = []
        for name in self.measures:
            if match := re.search(rf"\b{re.escape(_normalise(name))}\b", self._prompt):
                found.append((match.start(), name))
        return sorted(found)

    def mentioned_measures(self) -> list[str]:
        return [name for _, name in self.mentions()]

    def revenue(self) -> Measure | None:
        if column := self.role("revenue", "number"):
            return Measure(column=column)
        quantity, price = self.role("quantity", "number"), self.role("unit_price", "number")
        return Measure(multiply=(quantity, price)) if quantity and price else None

    def cost(self) -> Measure | None:
        if column := self.role("cost", "number"):
            return Measure(column=column)
        quantity, unit_cost = self.role("quantity", "number"), self.role("unit_cost", "number")
        return Measure(multiply=(quantity, unit_cost)) if quantity and unit_cost else None

    def dimensions(self) -> tuple[str, ...]:
        """Grouping columns, with any the request asks about moved to the front."""
        usable = [self._by_role[role] for role in DIMENSION_ROLES
                  if role in self._by_role and self._by_role[role].kind == "text"
                  and 2 <= self._by_role[role].distinct_count <= MAX_DIMENSION_VALUES]  # fmt: skip
        asked = [c for c in usable if re.search(DIMENSION_WORDS[c.role], self._raw_prompt)
                 or re.search(rf"\b{re.escape(_normalise(c.name))}\b", self._prompt)]  # fmt: skip
        ordered = asked + [c for c in usable if c not in asked]
        return tuple(c.name for c in ordered[:MAX_DIMENSIONS])


def plan_with_rules(
    prompt: str, analysis_type: str, columns: list[Column], excluded: frozenset[str] = frozenset()
) -> PlanOutcome:
    data = _Dataset(columns, prompt)
    intents = (sorted(ANALYSIS_TYPE_INTENTS[analysis_type]) if analysis_type in ANALYSIS_TYPE_INTENTS
               else detect_intents(prompt, tuple(column.name for column in columns)))  # fmt: skip
    wanted = set(intents)
    notes: list[str] = []
    operations: list[Operation] = []

    revenue, cost, date = data.revenue(), data.cost(), data.date
    measures, named = data.measures, data.mentioned_measures()
    dimensions = data.dimensions()

    if not wanted:  # nothing recognisable in the request: give the most useful analysis the data supports
        wanted = {"sales", "profitability"} if revenue else {"descriptive", "correlation"}
        if not revenue and not measures:
            wanted = {"data_quality"}

    money_requested = wanted & {"sales", "profitability"} or ("trend" in wanted and revenue)
    if money_requested:
        if revenue:
            operations.append(SalesOverview(revenue=revenue, date=date, dimensions=dimensions,
                                            quantity=data.role("quantity", "number"),
                                            document=data.role("identifier", "text")))  # fmt: skip
        else:
            notes.append("A sales analysis needs a sales amount column, or a quantity and a unit price. "
                         "None could be identified in this dataset.")  # fmt: skip
    if "profitability" in wanted:
        if revenue and cost:
            operations.append(Profitability(revenue=revenue, cost=cost, date=date, dimensions=dimensions))
        elif revenue:
            notes.append("Profitability could not be analysed: the dataset has no cost column "
                         "(such as 'Cost of Sales', 'COGS' or 'Unit Cost').")  # fmt: skip
    if "trend" in wanted and not revenue:
        target = (named or measures or [None])[0]
        if target and date:
            operations.append(Trend(measure=target, date=date))
        else:
            notes.append("A trend needs a date column and a numeric column; this dataset does not have both.")
    if "descriptive" in wanted:
        chosen = (named + [name for name in measures if name not in named])[:MAX_STAT_COLUMNS]
        if chosen:
            operations.append(DescriptiveStatistics(columns=tuple(chosen)))
        else:
            notes.append("Descriptive statistics need at least one numeric column; none was found.")
    if "correlation" in wanted:
        chosen = (named if len(named) >= 2 else measures)[:MAX_STAT_COLUMNS]
        if len(chosen) >= 2:
            operations.append(Correlation(columns=tuple(chosen)))
        else:
            notes.append("Correlation needs at least two numeric columns.")
    if "regression" in wanted:
        target = (
            regression_target(prompt, data.mentions())
            or (named[-1] if named else None)
            or (revenue.column if revenue and revenue.column else (measures or [None])[0])
        )
        others = [name for name in named if name != target]
        predictors = [name for name in (others or measures) if name != target][:MAX_PREDICTORS]
        if target and predictors:
            operations.append(Regression(target=target, predictors=tuple(predictors)))
        else:
            notes.append("Regression needs a numeric column to explain and at least one other numeric column.")
    if "outliers" in wanted:
        target = (
            (named[0] if named else None)
            or (revenue.column if revenue else None)
            or (measures[0] if measures else None)
        )
        if target:
            operations.append(Outliers(column=target))
        else:
            notes.append("Looking for unusual values needs a numeric column; none was found.")
    if "data_quality" in wanted:
        operations.append(DataQuality())

    operations = [operation for operation in operations if operation.type not in excluded]
    if not operations:
        raise PlanningError(_cannot_plan_message(columns, notes))

    kinds = [operation.type for operation in operations]
    currency = data.role("currency", "text")
    return PlanOutcome(
        spec=AnalysisSpec(objective=_objective(kinds), report_title=_report_title(kinds),
                          operations=tuple(operations), currency_column=currency),
        notes=notes, intents=sorted(wanted),
    )  # fmt: skip


def _objective(kinds: list[str]) -> str:
    titles = [OPERATION_TITLES[kind].lower() for kind in kinds]
    joined = titles[0] if len(titles) == 1 else f"{', '.join(titles[:-1])} and {titles[-1]}"
    return f"Analyse {joined}."


def _report_title(kinds: list[str]) -> str:
    present = set(kinds)
    if {"sales_overview", "profitability"} <= present:
        return "Sales and Profitability Report"
    if "sales_overview" in present:
        return "Sales Performance Report"
    if present == {"data_quality"}:
        return "Data Quality Report"
    if present <= {"descriptive_statistics", "correlation", "regression", "trend", "outliers", "data_quality"}:
        return "Statistical Analysis Report"
    return "Business Performance Report"


def _cannot_plan_message(columns: list[Column], notes: list[str]) -> str:
    recognised = ", ".join(f"'{c.name}' ({c.role.replace('_', ' ') or c.kind})" for c in columns[:12])
    reason = " ".join(notes) or "The request could not be matched to an analysis this dataset supports."
    return (f"{reason} The columns found were: {recognised}. Rename the relevant column headings "
            "(for example 'Sales Amount', 'Cost of Sales', 'Date', 'Product') and upload the file again, "
            "or ask for a different analysis.")  # fmt: skip


def build_execution_plan() -> list[dict[str, Any]]:
    """The ordered task list for an analysis job, with dependencies."""
    steps = [
        ("chief_intelligence", "plan_analysis"),
        ("data_acquisition", "verify_and_load"),
        ("data_cleaning", "validate_for_analysis"),
        ("statistical_analysis", "run_analysis"),
        ("quality_verification", "verify_results"),
        ("report_generation", "generate_report"),
    ]
    return [{"sequence": number, "agent": agent, "action": action, "depends_on": [number - 1] if number > 1 else []}
            for number, (agent, action) in enumerate(steps, start=1)]  # fmt: skip


def validate_plan(plan: list[dict[str, Any]]) -> list[str]:
    """Reasons a task plan must not be executed. Empty means it is safe to run."""
    problems: list[str] = []
    seen: set[int] = set()
    for task in plan:
        sequence, agent, action = task.get("sequence"), task.get("agent"), task.get("action")
        if not isinstance(sequence, int) or sequence in seen:
            problems.append(f"task sequence {sequence!r} is missing or repeated")
            continue
        if agent not in AGENT_ACTIONS:
            problems.append(f"task {sequence}: unknown agent '{agent}'")
        elif action not in AGENT_ACTIONS[agent]:
            problems.append(f"task {sequence}: agent '{agent}' has no action '{action}'")
        for dependency in task.get("depends_on", []):
            if dependency not in seen:
                problems.append(f"task {sequence}: depends on task {dependency}, which does not come before it")
        seen.add(sequence)
    return problems
