"""Anthropic's Messages API."""

from __future__ import annotations

import httpx

from .base import LLMError, LLMResponse, LLMTemporaryError, parse_json_object, raise_for_status

DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


class AnthropicClient:
    provider = "anthropic"

    def __init__(
        self, *, api_key: str, model: str, base_url: str = "", timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:  # fmt: skip
        self.model = model
        self._url = f"{(base_url or DEFAULT_BASE_URL).rstrip('/')}/v1/messages"
        self._headers = {"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        self._timeout, self._transport = timeout, transport

    async def complete_json(self, *, system: str, user: str, max_output_tokens: int = 2000) -> LLMResponse:
        payload = {
            "model": self.model,
            "max_tokens": max_output_tokens,
            "system": f"{system}\n\nReply with a single JSON object and nothing else.",
            "messages": [{"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(self._url, headers=self._headers, json=payload)
        except httpx.HTTPError as error:
            raise LLMTemporaryError(f"could not reach the AI provider: {error}") from error
        raise_for_status(response.status_code, response.text)
        try:
            body = response.json()
            text = "".join(block.get("text", "") for block in body["content"] if block.get("type") == "text")
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise LLMError("unexpected response shape from the AI provider") from error
        usage = body.get("usage") or {}
        return LLMResponse(
            data=parse_json_object(text),
            model=str(body.get("model") or self.model),
            tokens_input=int(usage.get("input_tokens") or 0),
            tokens_output=int(usage.get("output_tokens") or 0),
        )
