"""
cctvQL — Anthropic LLM Backend
--------------------------------
Uses the Anthropic Messages API.
Set ANTHROPIC_API_KEY environment variable or pass api_key directly.
"""

from __future__ import annotations

import logging
import os

import httpx

from .base import BaseLLM, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class AnthropicBackend(BaseLLM):
    """
    LLM backend powered by Anthropic's API.

    Args:
        api_key: Anthropic API key (falls back to ANTHROPIC_API_KEY env var)
        model:   Model name (default: claude-haiku-4-5-20251001 for cost efficiency)

    Usage:
        backend = AnthropicBackend()
        LLMRegistry.register(backend)
        LLMRegistry.set_active("anthropic")
    """

    BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
                "Content-Type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "anthropic"

    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("Anthropic API key not set. Set ANTHROPIC_API_KEY or pass api_key.")

        # Separate system message from conversation turns
        system_content = ""
        conversation = []
        for m in messages:
            if m.role == "system":
                system_content = m.content
            else:
                conversation.append({"role": m.role, "content": m.content})

        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversation,
        }
        if system_content:
            payload["system"] = system_content

        url = f"{self.BASE_URL}/messages"
        logger.debug("Anthropic request to %s (model=%s)", url, self.model)

        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        content = data["content"][0]["text"]
        usage = data.get("usage", {})

        return LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
        )

    async def health_check(self) -> bool:
        return bool(self.api_key)
