"""
Tests for the QueryRouter (cctvql.core.query_router).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.demo import DemoAdapter
from cctvql.core.query_router import QueryRouter
from cctvql.core.schema import QueryContext
from cctvql.llm.base import LLMResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def router():
    adapter = DemoAdapter()
    await adapter.connect()
    mock_llm = MagicMock()
    mock_llm.name = "mock"
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(content="formatted response", model="mock"),
    )
    return QueryRouter(adapter, mock_llm)


# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------

async def test_route_list_cameras(router):
    ctx = QueryContext(intent="list_cameras", raw_query="show me all cameras")
    result = await router.route(ctx)
    assert "4 camera" in result.lower() or "found 4" in result.lower()


async def test_route_get_camera(router):
    ctx = QueryContext(
        intent="get_camera",
        camera_name="Front Door",
        raw_query="show me the front door camera",
    )
    result = await router.route(ctx)
    assert "Front Door" in result


async def test_route_get_events(router):
    ctx = QueryContext(
        intent="get_events",
        raw_query="show me recent events",
    )
    result = await router.route(ctx)
    # Should list events
    assert "event" in result.lower() or "found" in result.lower()


async def test_route_get_clips(router):
    ctx = QueryContext(
        intent="get_clips",
        raw_query="show me recent clips",
    )
    result = await router.route(ctx)
    assert "clip" in result.lower() or "found" in result.lower()


async def test_route_get_snapshot(router):
    ctx = QueryContext(
        intent="get_snapshot",
        camera_name="Front Door",
        raw_query="get snapshot from front door",
    )
    result = await router.route(ctx)
    assert "snapshot" in result.lower() or "Front Door" in result


async def test_route_get_system_info(router):
    ctx = QueryContext(
        intent="get_system_info",
        raw_query="what is the system status",
    )
    result = await router.route(ctx)
    assert "demo" in result.lower() or "camera" in result.lower()


async def test_route_unknown_intent(router):
    ctx = QueryContext(
        intent="totally_unknown",
        raw_query="foobar baz",
    )
    result = await router.route(ctx)
    # Should return help text
    assert "didn't understand" in result.lower() or "you can ask" in result.lower()


async def test_route_error_handling(router):
    """When the adapter raises, the exception propagates (router does not catch)."""
    router.adapter.list_cameras = AsyncMock(side_effect=Exception("boom"))
    ctx = QueryContext(intent="list_cameras", raw_query="show cameras")
    with pytest.raises(Exception, match="boom"):
        await router.route(ctx)
