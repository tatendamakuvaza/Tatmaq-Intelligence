"""The provider-independent AI interface.

Agents depend on :class:`LLMClient`, never on a vendor SDK, so changing provider is a
configuration change. The interface is deliberately narrow: send instructions, get
JSON back. The model is asked to *understand* (which analysis does this request
need?) and to *explain* (what do these verified results mean?). It is never asked to
calculate, and nothing it returns is trusted until it has been validated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol


class LLMError(Exception):
    """The model could not be reached or returned something unusable."""


class LLMTemporaryError(LLMError):
    """Rate limit, timeout or server error: worth retrying."""


@dataclass(frozen=True)
class LLMResponse:
    data: dict[str, Any]
    model: str
    tokens_input: int = 0
    tokens_output: int = 0


class LLMClient(Protocol):
    provider: str
    model: str

    async def complete_json(self, *, system: str, user: str, max_output_tokens: int = 2000) -> LLMResponse:
        """Return the model's reply parsed as a JSON object."""
        ...


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from a model reply, tolerating code fences and stray prose."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("the model did not return JSON") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise LLMError("the model returned malformed JSON") from error
    if not isinstance(value, dict):
        raise LLMError("the model returned JSON that is not an object")
    return value


def raise_for_status(status_code: int, body: str) -> None:
    if status_code < 400:
        return
    detail = body[:300]
    if status_code in (408, 409, 429) or status_code >= 500:
        raise LLMTemporaryError(f"AI provider returned {status_code}: {detail}")
    raise LLMError(f"AI provider returned {status_code}: {detail}")
