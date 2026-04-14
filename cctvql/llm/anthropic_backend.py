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
                "x-api-key": str(self.api_key),
                "anthropic-version": self.API_VERSION,
                "Content-Type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def supports_vision(self) -> bool:
        return True

    async def complete_with_image(
        self,
        messages: list[LLMMessage],
        image_b64: str,
        image_media_type: str = "image/jpeg",
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("Anthropic API key not set. Set ANTHROPIC_API_KEY or pass api_key.")

        # Separate system message
        system_content = ""
        conversation: list[dict] = []
        for m in messages:
            if m.role == "system":
                system_content = m.content
            elif m.role != "user":
                conversation.append({"role": m.role, "content": m.content})

        # The last user message becomes a multi-part content block with the image
        text_content = next((m.content for m in reversed(messages) if m.role == "user"), "")
        vision_message = {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type,
                        "data": image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": text_content,
                },
            ],
        }

        payload: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversation + [vision_message],
        }
        if system_content:
            payload["system"] = system_content

        url = f"{self.BASE_URL}/messages"
        logger.debug("Anthropic vision request to %s (model=%s)", url, self.model)

        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        content = data["content"][0]["text"]
        usage = data.get("usage", {})

        from .base import LLMResponse  # local import avoids circular at module level

        return LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
        )

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
