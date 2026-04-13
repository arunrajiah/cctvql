"""Tests for NLP engine intent parsing."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.core.nlp_engine import NLPEngine
from cctvql.core.schema import QueryContext
from cctvql.llm.base import LLMResponse


def make_mock_llm(json_response: str):
    llm = MagicMock()
    llm.name = "mock"
    llm.complete = AsyncMock(
        return_value=LLMResponse(content=json_response, model="mock")
    )
    return llm


@pytest.mark.asyncio
async def test_parse_list_cameras():
    llm = make_mock_llm('{"intent": "list_cameras", "limit": 20, "explanation": "list all"}')
    engine = NLPEngine(llm)
    ctx = await engine.parse("Show me all cameras")
    assert ctx.intent == "list_cameras"


@pytest.mark.asyncio
async def test_parse_get_events_with_label():
    llm = make_mock_llm(
        '{"intent": "get_events", "camera_name": "driveway", '
        '"label": "person", "start_time": "2026-04-13T00:00:00", '
        '"end_time": null, "limit": 20, "explanation": "person on driveway"}'
    )
    engine = NLPEngine(llm)
    ctx = await engine.parse("Was there a person on the driveway camera today?")
    assert ctx.intent == "get_events"
    assert ctx.camera_name == "driveway"
    assert ctx.label == "person"
    assert isinstance(ctx.start_time, datetime)


@pytest.mark.asyncio
async def test_parse_with_markdown_json():
    """LLM sometimes wraps JSON in markdown code blocks."""
    response = '```json\n{"intent": "get_system_info", "limit": 20, "explanation": "system info"}\n```'
    llm = make_mock_llm(response)
    engine = NLPEngine(llm)
    ctx = await engine.parse("How is the system doing?")
    assert ctx.intent == "get_system_info"


@pytest.mark.asyncio
async def test_parse_unknown_intent():
    llm = make_mock_llm('{"intent": "unknown", "limit": 20, "explanation": "unclear"}')
    engine = NLPEngine(llm)
    ctx = await engine.parse("What is the meaning of life?")
    assert ctx.intent == "unknown"


@pytest.mark.asyncio
async def test_reset_clears_history():
    llm = make_mock_llm('{"intent": "list_cameras", "limit": 20, "explanation": ""}')
    engine = NLPEngine(llm)
    await engine.parse("Show cameras")
    assert len(engine.history) > 0
    engine.reset()
    assert len(engine.history) == 0


@pytest.mark.asyncio
async def test_parse_fallback_on_invalid_json():
    llm = make_mock_llm("This is not JSON at all!")
    engine = NLPEngine(llm)
    ctx = await engine.parse("Any motion last night?")
    assert ctx.intent == "unknown"
    assert ctx.raw_query == "Any motion last night?"
