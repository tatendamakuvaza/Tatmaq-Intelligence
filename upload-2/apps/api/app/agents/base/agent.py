"""The interface all five agents implement (specification section 7.1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .contracts import AgentResult, AgentTask
from .permissions import Toolbox


class AgentError(Exception):
    """An agent could not complete its task. The message is shown to the customer."""


class RetryableAgentError(AgentError):
    """A temporary failure (network, storage): safe to run the same task again."""


class BaseAgent(ABC):
    agent_key: ClassVar[str]

    def __init__(self, tools: Toolbox) -> None:
        self.tools = tools

    @abstractmethod
    async def execute(self, task: AgentTask) -> AgentResult:
        """Carry out ``task`` and return a structured result."""
