"""Arena AI gateway (OpenAI-compatible Chat Completions).

Arena's developer preview exposes an OpenAI-compatible endpoint. The API key and
the models it may call are controlled by the Arena workspace; TATMAQ does not
hard-code a model list. By default this client targets the public Arena gateway.
"""

from __future__ import annotations

import httpx

from .openai_compatible import OpenAICompatibleClient

DEFAULT_BASE_URL = "https://api.arena.ai/v1"


class ArenaClient(OpenAICompatibleClient):
    provider = "arena"

    def __init__(
        self, *, api_key: str, model: str, base_url: str = "", timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:  # fmt: skip
        root = (base_url or DEFAULT_BASE_URL).rstrip("/")
        # Accept the gateway root as well as the /v1 root.
        if root == "https://api.arena.ai":
            root = f"{root}/v1"
        # Some gateway models do not accept response_format; the prompts already
        # require a single JSON object, and parse_json_object tolerates fences.
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=root,
            timeout=timeout,
            transport=transport,
            json_mode=False,
        )
