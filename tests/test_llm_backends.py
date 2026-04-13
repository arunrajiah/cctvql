"""
Tests for all three LLM backends with mocked HTTP.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.llm.anthropic_backend import AnthropicBackend
from cctvql.llm.base import LLMMessage
from cctvql.llm.ollama_backend import OllamaBackend
from cctvql.llm.openai_backend import OpenAIBackend

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(json_data: dict, status_code: int = 200):
    """Create a mock httpx response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


SAMPLE_MESSAGES = [LLMMessage(role="user", content="Hello")]


# ===========================================================================
# OllamaBackend
# ===========================================================================


class TestOllamaBackend:
    def test_name(self):
        backend = OllamaBackend()
        assert backend.name == "ollama"

    async def test_complete_success(self):
        backend = OllamaBackend()
        mock_resp = _mock_response(
            {
                "message": {"content": "Hi there!"},
                "prompt_eval_count": 10,
                "eval_count": 5,
            }
        )
        backend._client.post = AsyncMock(return_value=mock_resp)

        result = await backend.complete(SAMPLE_MESSAGES)
        assert result.content == "Hi there!"
        assert result.model == "llama3"
        assert result.prompt_tokens == 10
        assert result.completion_tokens == 5

    async def test_complete_error_handling(self):
        backend = OllamaBackend()
        error_resp = _mock_response({}, status_code=500)
        backend._client.post = AsyncMock(return_value=error_resp)

        with pytest.raises(Exception):
            await backend.complete(SAMPLE_MESSAGES)

    async def test_health_check(self):
        backend = OllamaBackend()
        mock_resp = _mock_response({"models": []})
        backend._client.get = AsyncMock(return_value=mock_resp)

        result = await backend.health_check()
        assert result is True

    async def test_health_check_failure(self):
        backend = OllamaBackend()
        backend._client.get = AsyncMock(side_effect=Exception("connection refused"))

        result = await backend.health_check()
        assert result is False


# ===========================================================================
# OpenAIBackend
# ===========================================================================


class TestOpenAIBackend:
    def test_name(self):
        backend = OpenAIBackend(api_key="test-key")
        assert backend.name == "openai"

    async def test_complete_success(self):
        backend = OpenAIBackend(api_key="test-key")
        mock_resp = _mock_response(
            {
                "choices": [{"message": {"content": "OpenAI says hello"}}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 8},
            }
        )
        backend._client.post = AsyncMock(return_value=mock_resp)

        result = await backend.complete(SAMPLE_MESSAGES)
        assert result.content == "OpenAI says hello"
        assert result.model == "gpt-4o-mini"
        assert result.prompt_tokens == 15
        assert result.completion_tokens == 8

    async def test_complete_error_handling(self):
        backend = OpenAIBackend(api_key="test-key")
        error_resp = _mock_response({}, status_code=429)
        backend._client.post = AsyncMock(return_value=error_resp)

        with pytest.raises(Exception):
            await backend.complete(SAMPLE_MESSAGES)

    async def test_missing_api_key_raises(self):
        backend = OpenAIBackend(api_key="")
        with pytest.raises(RuntimeError, match="OpenAI API key not set"):
            await backend.complete(SAMPLE_MESSAGES)

    async def test_health_check(self):
        backend = OpenAIBackend(api_key="test-key")
        mock_resp = _mock_response({"data": []})
        backend._client.get = AsyncMock(return_value=mock_resp)

        result = await backend.health_check()
        assert result is True

    async def test_health_check_failure(self):
        backend = OpenAIBackend(api_key="test-key")
        backend._client.get = AsyncMock(side_effect=Exception("network error"))

        result = await backend.health_check()
        assert result is False


# ===========================================================================
# AnthropicBackend
# ===========================================================================


class TestAnthropicBackend:
    def test_name(self):
        backend = AnthropicBackend(api_key="test-key")
        assert backend.name == "anthropic"

    async def test_complete_success(self):
        backend = AnthropicBackend(api_key="test-key")
        mock_resp = _mock_response(
            {
                "content": [{"text": "Claude says hello"}],
                "usage": {"input_tokens": 20, "output_tokens": 10},
            }
        )
        backend._client.post = AsyncMock(return_value=mock_resp)

        result = await backend.complete(SAMPLE_MESSAGES)
        assert result.content == "Claude says hello"
        assert result.model == "claude-haiku-4-5-20251001"
        assert result.prompt_tokens == 20
        assert result.completion_tokens == 10

    async def test_complete_with_system_message(self):
        backend = AnthropicBackend(api_key="test-key")
        mock_resp = _mock_response(
            {
                "content": [{"text": "response with system"}],
                "usage": {"input_tokens": 25, "output_tokens": 12},
            }
        )
        backend._client.post = AsyncMock(return_value=mock_resp)

        messages = [
            LLMMessage(role="system", content="You are helpful."),
            LLMMessage(role="user", content="Hello"),
        ]
        result = await backend.complete(messages)
        assert result.content == "response with system"

        # Verify the system message was separated from conversation
        call_kwargs = backend._client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["system"] == "You are helpful."
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    async def test_complete_error_handling(self):
        backend = AnthropicBackend(api_key="test-key")
        error_resp = _mock_response({}, status_code=500)
        backend._client.post = AsyncMock(return_value=error_resp)

        with pytest.raises(Exception):
            await backend.complete(SAMPLE_MESSAGES)

    async def test_missing_api_key_raises(self):
        backend = AnthropicBackend(api_key="")
        with pytest.raises(RuntimeError, match="Anthropic API key not set"):
            await backend.complete(SAMPLE_MESSAGES)

    async def test_health_check_with_key(self):
        backend = AnthropicBackend(api_key="test-key")
        result = await backend.health_check()
        assert result is True

    async def test_health_check_without_key(self):
        backend = AnthropicBackend(api_key="")
        result = await backend.health_check()
        assert result is False
