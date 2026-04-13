"""
cctvQL LLM Base
---------------
Abstract interface for LLM backends.
Implement this to add any new provider (Ollama, OpenAI, Anthropic, etc.)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMMessage:
    role: str    # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class BaseLLM(ABC):
    """
    Abstract base class for all LLM backends.

    To add a new provider:
        1. Subclass BaseLLM
        2. Implement `complete()` and `name`
        3. Register in LLMRegistry
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this backend."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """
        Send a list of messages and return a completion.

        Args:
            messages:    Conversation history (system + user + assistant turns)
            temperature: Sampling temperature. Lower = more deterministic.
            max_tokens:  Max tokens to generate.

        Returns:
            LLMResponse with the generated text.
        """
        ...

    async def health_check(self) -> bool:
        """Return True if the backend is reachable. Override for custom checks."""
        return True


class LLMRegistry:
    """
    Simple registry mapping provider names to LLM instances.
    Allows runtime selection of the active backend.
    """

    _backends: dict[str, BaseLLM] = {}
    _active: str | None = None

    @classmethod
    def register(cls, backend: BaseLLM) -> None:
        cls._backends[backend.name] = backend

    @classmethod
    def set_active(cls, name: str) -> None:
        if name not in cls._backends:
            raise ValueError(f"Backend '{name}' not registered. Available: {list(cls._backends)}")
        cls._active = name

    @classmethod
    def get_active(cls) -> BaseLLM:
        if not cls._active or cls._active not in cls._backends:
            raise RuntimeError("No active LLM backend configured.")
        return cls._backends[cls._active]

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._backends.keys())
