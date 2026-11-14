"""Provider-independent access to an AI model. ``build_llm`` returns ``None`` when none is configured."""

from ..core.config import Settings
from .anthropic import AnthropicClient
from .base import LLMClient, LLMError, LLMResponse, LLMTemporaryError, parse_json_object
from .openai_compatible import OpenAICompatibleClient

__all__ = [
    "AnthropicClient",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "LLMTemporaryError",
    "OpenAICompatibleClient",
    "build_llm",
    "parse_json_object",
]


def build_llm(settings: Settings) -> LLMClient | None:
    """The configured model, or ``None``: every agent has a deterministic path that needs no model."""
    common = {
        "api_key": settings.ai_api_key, "model": settings.ai_model,
        "base_url": settings.ai_base_url, "timeout": settings.ai_timeout_seconds,
    }  # fmt: skip
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleClient(**common)
    if settings.ai_provider == "anthropic":
        return AnthropicClient(**common)
    return None
