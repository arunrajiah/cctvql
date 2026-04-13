"""
cctvQL — Ollama LLM Backend
----------------------------
Runs fully locally. No data leaves the user's network.
Requires Ollama to be running: https://ollama.com
"""

from __future__ import annotations

import logging

import httpx

from .base import BaseLLM, LLMMessage, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3"


class OllamaBackend(BaseLLM):
    """
    LLM backend powered by a local Ollama instance.

    Args:
        host:  Ollama server URL (default: http://localhost:11434)
        model: Model name to use  (default: llama3)

    Usage:
        backend = OllamaBackend(model="llama3")
        LLMRegistry.register(backend)
        LLMRegistry.set_active("ollama")
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def name(self) -> str:
        return "ollama"

    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        url = f"{self.host}/api/chat"
        logger.debug("Ollama request to %s (model=%s)", url, self.model)

        response = await self._client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        content = data.get("message", {}).get("content", "")
        return LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )

    async def health_check(self) -> bool:
        try:
            r = await self._client.get(f"{self.host}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Return available model names from this Ollama instance."""
        r = await self._client.get(f"{self.host}/api/tags")
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
