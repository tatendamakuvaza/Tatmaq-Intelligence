"""The agent catalogue: what each agent is for, and where its code lives.

Descriptions are plain data so the API can show the team without importing the
analytics stack. Agent classes are imported only when a worker needs to run one.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from .agent import BaseAgent
from .permissions import AGENT_PERMISSIONS, Toolbox


@dataclass(frozen=True)
class AgentDescriptor:
    key: str
    number: int
    name: str
    role: str
    summary: str
    responsibilities: tuple[str, ...]
    restrictions: tuple[str, ...]
    uses_ai_model: bool
    implementation: str  # "module:Class"

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(sorted(AGENT_PERMISSIONS[self.key]))


AGENTS: tuple[AgentDescriptor, ...] = (
    AgentDescriptor(
        key="chief_intelligence", number=1, name="Chief Intelligence Agent", role="Orchestrator",
        summary="Understands the request and turns it into a validated plan of work for the other agents.",
        responsibilities=(
            "Identify the analytical objective", "Choose the analyses the dataset can support",
            "Map the request onto actual columns", "Sequence tasks and their dependencies",
            "Re-plan when validation rejects part of a plan", "Combine results and submit them for verification",
        ),
        restrictions=(
            "Sees column names and types only, never customer rows", "Cannot produce figures",
            "Cannot bypass access controls", "Cannot label a transaction as fraud",
        ),
        uses_ai_model=True, implementation="app.agents.chief_intelligence.agent:ChiefIntelligenceAgent",
    ),
    AgentDescriptor(
        key="data_acquisition", number=2, name="Data Acquisition Agent", role="Data ingestion",
        summary="Reads the uploaded file, works out its structure and records its fingerprint.",
        responsibilities=(
            "Read XLSX and CSV files", "Find the worksheet and header row", "Identify column types and business roles",
            "Build the column dictionary and data profile", "Record the SHA-256 hash of the file",
        ),
        restrictions=("Never modifies the uploaded file", "Rejects files over the size and row limits"),
        uses_ai_model=False, implementation="app.agents.data_acquisition.agent:DataAcquisitionAgent",
    ),
    AgentDescriptor(
        key="data_cleaning", number=3, name="Data Cleaning Agent", role="Data preparation",
        summary="Standardises formats and flags problems, logging every change it makes.",
        responsibilities=(
            "Standardise dates, numbers and category spellings", "Detect missing and invalid values",
            "Flag duplicate records and outliers", "Check the data can support the planned analysis",
            "Keep a log of every transformation",
        ),
        restrictions=(
            "Never deletes records", "Never replaces a missing value with zero",
            "Leaves the original data recoverable",
        ),
        uses_ai_model=False, implementation="app.agents.data_cleaning.agent:DataCleaningAgent",
    ),
    AgentDescriptor(
        key="statistical_analysis", number=4, name="Statistical Analysis Agent", role="Analytical engine",
        summary="Performs the calculations with deterministic code and attaches evidence to every result.",
        responsibilities=(
            "Sales and profitability in exact decimal arithmetic", "Descriptive statistics",
            "Correlation and regression", "Trend analysis", "Outlier detection",
            "Record formulas, parameters and source rows",
        ),
        restrictions=(
            "Has no access to an AI model: every figure is computed", "Read-only access to datasets",
            "Runs only the operations in the validated plan",
        ),
        uses_ai_model=False, implementation="app.agents.statistical_analysis.agent:StatisticalAnalysisAgent",
    ),
    AgentDescriptor(
        key="report_generation", number=5, name="Report Generation Agent", role="Reporting",
        summary="Turns verified findings into PDF, Excel and HTML reports.",
        responsibilities=(
            "Write the executive summary", "Present key figures, charts and tables",
            "Document assumptions and limitations", "List the evidence behind each finding",
        ),
        restrictions=(
            "Uses approved findings only", "Any AI-written sentence containing a figure that is not in the "
            "verified results is discarded", "Cannot read datasets",
        ),
        uses_ai_model=True, implementation="app.agents.report_generation.agent:ReportGenerationAgent",
    ),
)  # fmt: skip

_BY_KEY = {agent.key: agent for agent in AGENTS}


def describe(agent_key: str) -> AgentDescriptor:
    return _BY_KEY[agent_key]


def agent_name(agent_key: str) -> str:
    return _BY_KEY[agent_key].name if agent_key in _BY_KEY else agent_key.replace("_", " ").title()


def agent_role(agent_key: str) -> str:
    return _BY_KEY[agent_key].role if agent_key in _BY_KEY else "Verification"


def load_agent(agent_key: str, tools: Toolbox) -> BaseAgent:
    """Import and instantiate an agent. Raises ``KeyError`` for an unknown key."""
    module_name, _, class_name = _BY_KEY[agent_key].implementation.partition(":")
    agent_class = getattr(import_module(module_name), class_name)
    return agent_class(tools)
