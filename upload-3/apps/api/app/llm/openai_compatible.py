"""Any provider that speaks the OpenAI Chat Completions format.

That covers OpenAI itself and, by changing AI_BASE_URL, most other hosted and local
models (OpenRouter, Groq, Together, DeepSeek, Gemini's OpenAI-compatible endpoint,
Ollama, ...). Only fields every such provider accepts are sent: no temperature and no
token-limit parameter, whose names and allowed values differ between vendors.
"""

from __future__ import annotations

import httpx

from .base import LLMError, LLMResponse, LLMTemporaryError, parse_json_object, raise_for_status

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleClient:
    provider = "openai_compatible"

    def __init__(
        self, *, api_key: str, model: str, base_url: str = "", timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:  # fmt: skip
        self.model = model
        self._url = f"{(base_url or DEFAULT_BASE_URL).rstrip('/')}/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout, self._transport = timeout, transport

    async def complete_json(self, *, system: str, user: str, max_output_tokens: int = 2000) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(self._url, headers=self._headers, json=payload)
        except httpx.HTTPError as error:
            raise LLMTemporaryError(f"could not reach the AI provider: {error}") from error
        raise_for_status(response.status_code, response.text)
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMError("unexpected response shape from the AI provider") from error
        usage = body.get("usage") or {}
        return LLMResponse(
            data=parse_json_object(content or ""),
            model=str(body.get("model") or self.model),
            tokens_input=int(usage.get("prompt_tokens") or 0),
            tokens_output=int(usage.get("completion_tokens") or 0),
        )
