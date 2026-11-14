"""Agent 05 - Report Generation.

Builds one report model from the approved findings and renders it as PDF, Excel and
HTML. The agent cannot read datasets: its toolbox holds the optional AI model (for
wording only) and a writer for report files. What it knows is what verification
approved.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from ...llm import LLMClient
from ..base import AgentError, AgentResult, AgentTask, ArtifactRef, BaseAgent, Metrics
from ..base.permissions import TOOL_ARTIFACT_WRITE, TOOL_LLM
from .excel_generator import render_xlsx
from .executive_summary import ai_narrative, template_next_steps, template_summary
from .html_generator import render_html
from .pdf_generator import render_pdf
from .report_model import build_model

FORMATS = (
    ("pdf", "report_pdf", "application/pdf", render_pdf),
    ("xlsx", "report_xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", render_xlsx),
    ("html", "report_html", "text/html; charset=utf-8", render_html),
)


class ReportGenerationAgent(BaseAgent):
    agent_key = "report_generation"

    async def execute(self, task: AgentTask) -> AgentResult:
        if task.action != "generate_report":
            raise AgentError(f"The report generation agent has no action called '{task.action}'.")
        started = time.monotonic()
        model = build_model(task.inputs)
        if not model.findings:
            raise AgentError("There are no approved findings, so no report was written.")

        model.summary = template_summary(model)
        model.next_steps = template_next_steps(model)
        warnings: list[str] = []
        tokens_in = tokens_out = 0
        model_name = None
        llm: LLMClient | None = self.tools.get(TOOL_LLM)
        if llm is not None:
            narrative, note, usage = await ai_narrative(llm, model)
            tokens_in, tokens_out, model_name = usage["tokens_input"], usage["tokens_output"], usage["model"]
            if narrative is not None:
                model.summary = narrative["summary"]
                model.next_steps = narrative["next_steps"] or model.next_steps
                model.narrative_source = note
            else:
                warnings.append(note)

        store = self.tools.get(TOOL_ARTIFACT_WRITE)
        artifacts: list[ArtifactRef] = []
        with tempfile.TemporaryDirectory(prefix="report-") as folder:
            for extension, artifact_type, content_type, render in FORMATS:
                path = Path(folder) / f"report.{extension}"
                render(model, path)
                key = task.dataset_refs["report_paths"][extension]
                size, digest = store(key, path, content_type)
                artifacts.append(ArtifactRef(
                    artifact_type=artifact_type, title=model.title, filename=f"{model.file_stem}.{extension}",
                    content_type=content_type, storage_path=key, size_bytes=size, sha256=digest,
                ))  # fmt: skip

        return AgentResult(
            agent_key="report_generation",
            status="completed",
            summary=f"Wrote '{model.title}' as PDF, Excel and HTML from {len(model.findings)} approved findings "
                    f"and {len(model.evidence)} evidence records.",
            warnings=tuple(warnings),
            artifacts=tuple(artifacts),
            evidence_refs=tuple(record["ref"] for record in model.evidence),
            metrics=Metrics(execution_time_ms=int((time.monotonic() - started) * 1000),
                            records_processed=len(model.findings), tokens_input=tokens_in, tokens_output=tokens_out,
                            model_name=model_name),
            outputs={"executive_summary": model.summary, "next_steps": model.next_steps,
                     "narrative_source": model.narrative_source, "title": model.title},
        )  # fmt: skip
