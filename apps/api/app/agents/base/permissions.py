"""Explicit tool permissions per agent (specification section 8.1).

An agent can only reach a tool through its :class:`Toolbox`, and the toolbox only
holds what the table below grants. The grants encode the platform's central safety
rules:

* The statistical agent has no AI model: no figure can come from a language model.
* The Chief and Report agents have no dataset reader: they work from metadata and
  from verified results, so customer rows are never placed in an AI prompt.
* Only the acquisition agent can read an original upload, and nothing can write one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TOOL_ORIGINAL_READ = "original_file.read"  # download the uploaded file (read-only)
TOOL_RAW_WRITE = "dataset.write_raw"  # store the imported table
TOOL_RAW_READ = "dataset.read_raw"  # load the imported table
TOOL_CLEANED_WRITE = "dataset.write_cleaned"  # store the cleaned table
TOOL_CLEANED_READ = "dataset.read_cleaned"  # load the cleaned table
TOOL_LLM = "llm"  # the AI model, if one is configured
TOOL_ARTIFACT_WRITE = "artifact.write"  # store a generated report

AGENT_PERMISSIONS: Mapping[str, frozenset[str]] = {
    "chief_intelligence": frozenset({TOOL_LLM}),
    "data_acquisition": frozenset({TOOL_ORIGINAL_READ, TOOL_RAW_WRITE}),
    "data_cleaning": frozenset({TOOL_RAW_READ, TOOL_CLEANED_WRITE, TOOL_CLEANED_READ}),
    "statistical_analysis": frozenset({TOOL_CLEANED_READ}),
    "report_generation": frozenset({TOOL_LLM, TOOL_ARTIFACT_WRITE}),
}


class ToolPermissionError(PermissionError):
    """An agent tried to use a tool it has not been granted."""


class Toolbox:
    """The only route from an agent to the outside world."""

    def __init__(self, agent_key: str, providers: Mapping[str, Any]) -> None:
        self.agent_key = agent_key
        self._granted = AGENT_PERMISSIONS.get(agent_key, frozenset())
        self._providers = providers

    @property
    def permitted(self) -> tuple[str, ...]:
        return tuple(sorted(self._granted))

    def get(self, tool: str) -> Any:
        if tool not in self._granted:
            raise ToolPermissionError(f"agent '{self.agent_key}' is not permitted to use '{tool}'")
        return self._providers[tool]
