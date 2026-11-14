"""Agent 01 - Chief Intelligence.

Turns a request into an :class:`AnalysisSpec` and the ordered task plan for the other
agents. With an AI model configured, the model proposes the specification; either way
the specification is validated against the dataset's actual columns, and the built-in
rule planner is used whenever the model is unavailable or its plan is rejected.

The agent's toolbox contains the AI model and nothing else: no dataset reader, no
storage. It plans from the column dictionary alone.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from ...analytics.spec import OPERATION_TITLES, AnalysisSpec, spec_problems
from ...llm import LLMClient, LLMError
from ..base import AgentError, AgentResult, AgentTask, BaseAgent, Metrics
from ..base.permissions import TOOL_LLM
from .planner import PlanningError, PlanOutcome, build_execution_plan, plan_with_rules, to_columns, validate_plan
from .prompts import PLANNER_SYSTEM, planner_user_message


class ChiefIntelligenceAgent(BaseAgent):
    agent_key = "chief_intelligence"

    async def execute(self, task: AgentTask) -> AgentResult:
        if task.action != "plan_analysis":
            raise AgentError(f"The chief intelligence agent has no action called '{task.action}'.")
        started = time.monotonic()
        profile_columns: list[dict[str, Any]] = task.inputs["columns"]
        analysis_type = task.inputs.get("analysis_type", "automatic")
        excluded = frozenset(task.inputs.get("excluded_operations", []))
        column_kinds = {column["name"]: column["kind"] for column in profile_columns}

        notes: list[str] = []
        planner, tokens_in, tokens_out, model_name = "rules", 0, 0, None
        outcome: PlanOutcome | None = None

        llm: LLMClient | None = self.tools.get(TOOL_LLM)
        if llm is not None:
            try:
                response = await llm.complete_json(
                    system=PLANNER_SYSTEM,
                    user=planner_user_message(task.user_instruction, analysis_type, profile_columns, sorted(excluded)),
                )
                tokens_in, tokens_out, model_name = response.tokens_input, response.tokens_output, response.model
                spec = AnalysisSpec.model_validate(response.data)
                problems = spec_problems(spec, column_kinds)
                problems += [f"'{op.type}' was excluded" for op in spec.operations if op.type in excluded]
                if problems:
                    notes.append("The AI model's plan did not fit the dataset and was not used "
                                 f"({problems[0]}); the built-in planner was used instead.")  # fmt: skip
                else:
                    outcome, planner = PlanOutcome(spec=spec), "ai"
            except ValidationError:
                notes.append("The AI model's plan was not a valid analysis specification and was not used; "
                             "the built-in planner was used instead.")  # fmt: skip
            except LLMError as error:
                notes.append(f"The AI model was unavailable ({error}); the built-in planner was used instead.")

        if outcome is None:
            try:
                outcome = plan_with_rules(task.user_instruction, analysis_type, to_columns(profile_columns), excluded)
            except PlanningError as error:
                raise AgentError(str(error)) from error
            problems = spec_problems(outcome.spec, column_kinds)
            if problems:  # the rule planner only uses typed roles, so this indicates a defect, not bad data
                raise AgentError(f"The analysis plan could not be validated: {problems[0]}")
        unmet = list(outcome.notes)  # parts of the request the dataset cannot support
        notes = unmet + notes

        plan = build_execution_plan()
        if plan_problems := validate_plan(plan):
            raise AgentError(f"The task plan is not valid: {plan_problems[0]}")

        titles = [OPERATION_TITLES[operation.type].lower() for operation in outcome.spec.operations]
        listed = titles[0] if len(titles) == 1 else f"{', '.join(titles[:-1])} and {titles[-1]}"
        source = f"the AI model ({model_name})" if planner == "ai" else "the built-in planner"
        return AgentResult(
            agent_key="chief_intelligence",
            status="completed",
            summary=f"Planned {len(titles)} analys{'is' if len(titles) == 1 else 'es'} ({listed}) and "
                    f"{len(plan)} tasks, using {source}. The plan was validated against the dataset's columns.",
            warnings=tuple(notes),
            metrics=Metrics(execution_time_ms=int((time.monotonic() - started) * 1000), tokens_input=tokens_in,
                            tokens_output=tokens_out, model_name=model_name),
            outputs={
                "analysis_spec": outcome.spec.model_dump(mode="json"),
                "execution_plan": plan,
                "planner": planner,
                "intents": outcome.intents,
                "unmet_requests": unmet,
            },
        )  # fmt: skip
