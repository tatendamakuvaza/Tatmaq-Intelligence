"""Which step runs next. Pure functions of the state, so every path can be unit-tested.

    preflight -> planning -> acquisition -> cleaning -> statistics -> verification -> reporting -> finalise
                    ^                          |             ^              |
                    +--- re-plan (once) -------+             +-- redo (once)+

Any step that fails goes straight to ``finalise``, which records the outcome.
"""

from __future__ import annotations

from .state import AnalysisState

MAX_REPLANS = 1
MAX_STATISTICS_ATTEMPTS = 2

FINALISE = "finalise"


def _unless_failed(state: AnalysisState, next_step: str) -> str:
    return FINALISE if state.get("status") == "failed" else next_step


def after_preflight(state: AnalysisState) -> str:
    return _unless_failed(state, "planning")


def after_planning(state: AnalysisState) -> str:
    return _unless_failed(state, "acquisition")


def after_acquisition(state: AnalysisState) -> str:
    return _unless_failed(state, "cleaning")


def after_cleaning(state: AnalysisState) -> str:
    """Validation found part of the plan infeasible: send it back to the Chief to re-plan."""
    if state.get("status") == "failed":
        return FINALISE
    infeasible = (state.get("cleaning_result") or {}).get("outputs", {}).get("infeasible", [])
    return "planning" if infeasible else "statistics"


def after_statistics(state: AnalysisState) -> str:
    return _unless_failed(state, "verification")


def after_verification(state: AnalysisState) -> str:
    """Results that fail reconciliation are recomputed once, then the job fails: never reported."""
    if state.get("status") == "failed":
        return FINALISE
    if (state.get("verification_result") or {}).get("outputs", {}).get("passed"):
        return "reporting"
    return "statistics"


def after_ingest_step(state: AnalysisState, next_step: str) -> str:
    return _unless_failed(state, next_step)
