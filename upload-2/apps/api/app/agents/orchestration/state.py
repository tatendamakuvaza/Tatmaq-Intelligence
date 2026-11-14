"""The state passed between workflow steps (specification section 6.2).

It carries identifiers, the plan and each agent's structured result. It never carries
customer rows: agents load data through their tools, by reference.
"""

from __future__ import annotations

from typing import Any, TypedDict


class AnalysisState(TypedDict, total=False):
    job_id: str
    organisation_id: str
    user_prompt: str
    dataset_id: str
    dataset_version_id: str
    analysis_type: str
    execution_plan: list[dict[str, Any]]
    analysis_spec: dict[str, Any]
    planning_result: dict[str, Any]
    acquisition_result: dict[str, Any]
    cleaning_result: dict[str, Any]
    statistical_result: dict[str, Any]
    verification_result: dict[str, Any]
    report_result: dict[str, Any]
    excluded_operations: list[str]
    replans: int
    statistics_attempts: int
    errors: list[dict[str, Any]]
    status: str  # running | failed


def failed(state: AnalysisState, stage: str, message: str) -> dict[str, Any]:
    """The state update for a step that cannot continue."""
    return {"status": "failed", "errors": [*state.get("errors", []), {"stage": stage, "message": message}]}
