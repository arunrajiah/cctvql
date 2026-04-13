"""
cctvQL — OpenAI LLM Backend
----------------------------
Uses the OpenAI Chat Completions API.
Set OPENAI_API_KEY environment variable or pass api_key directly.
"""

from __future__ import annotations

import logging
import os

import httpx

from .base import BaseLLM, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIBackend(BaseLLM):
    """
    LLM backend powered by OpenAI's API.

    Args:
        api_key: OpenAI API key (falls back to OPENAI_API_KEY env var)
        model:   Model name (default: gpt-4o-mini)
        base_url: Override for OpenAI-compatible endpoints (e.g. LM Studio, Together AI)

    Usage:
        backend = OpenAIBackend()  # reads OPENAI_API_KEY from env
        LLMRegistry.register(backend)
        LLMRegistry.set_active("openai")
    """

    BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model = model
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "openai"

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
            raise RuntimeError("OpenAI API key not set. Set OPENAI_API_KEY or pass api_key.")

        # Build the vision message: image first, then the text prompt from the last user message
        text_content = next((m.content for m in reversed(messages) if m.role == "user"), "")
        vision_message = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image_media_type};base64,{image_b64}",
                    },
                },
                {
                    "type": "text",
                    "text": text_content,
                },
            ],
        }

        # Include any system / prior assistant turns, replacing the last user turn
        prior = [{"role": m.role, "content": m.content} for m in messages if m.role != "user"]

        payload = {
            "model": self.model,
            "messages": prior + [vision_message],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{self.base_url}/chat/completions"
        logger.debug("OpenAI vision request to %s (model=%s)", url, self.model)

        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        from .base import LLMResponse  # local import avoids circular at module level

        return LLMResponse(
            content=choice,
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("OpenAI API key not set. Set OPENAI_API_KEY or pass api_key.")

        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        url = f"{self.base_url}/chat/completions"
        logger.debug("OpenAI request to %s (model=%s)", url, self.model)

        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice,
            model=self.model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def health_check(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/models", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False
