"""
Tests for the FastAPI REST API (cctvql.interfaces.rest_api).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cctvql.adapters.base import AdapterRegistry
from cctvql.adapters.demo import DemoAdapter
from cctvql.llm.base import LLMRegistry, LLMResponse

# ---------------------------------------------------------------------------
# Setup / teardown registries before each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_registries():
    # Clear registries
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None

    # Register demo adapter
    adapter = DemoAdapter()
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("demo")

    # Register mock LLM
    mock_llm = MagicMock()
    mock_llm.name = "mock"
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"intent":"list_cameras","limit":20,"explanation":"list"}',
            model="mock",
        )
    )
    mock_llm.health_check = AsyncMock(return_value=True)
    LLMRegistry.register(mock_llm)
    LLMRegistry.set_active("mock")

    yield

    # Cleanup
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None


@pytest.fixture
async def client():
    """Create an async httpx client using ASGITransport to talk to the FastAPI app."""
    from cctvql.interfaces.rest_api import _sessions, app

    _sessions.clear()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert data["adapter"] == "demo"
    assert data["llm"] == "mock"
    assert "adapter_ok" in data
    assert "llm_ok" in data


async def test_list_cameras(client):
    resp = await client.get("/cameras")
    assert resp.status_code == 200
    cameras = resp.json()
    assert isinstance(cameras, list)
    assert len(cameras) == 4
    # Check expected fields
    cam = cameras[0]
    assert "id" in cam
    assert "name" in cam
    assert "status" in cam
    assert "zones" in cam


async def test_get_events(client):
    resp = await client.get("/events")
    assert resp.status_code == 200
    events = resp.json()
    assert isinstance(events, list)
    assert len(events) > 0
    # Check expected fields
    evt = events[0]
    assert "id" in evt
    assert "camera" in evt
    assert "type" in evt
    assert "start_time" in evt
    assert "objects" in evt


async def test_get_events_with_filters(client):
    resp = await client.get("/events", params={"camera": "Backyard", "limit": 5})
    assert resp.status_code == 200
    events = resp.json()
    assert isinstance(events, list)
    assert len(events) <= 5
    for evt in events:
        assert evt["camera"].lower() == "backyard"


async def test_query_endpoint(client):
    resp = await client.post("/query", json={"query": "show me all cameras"})
    # The mock LLM returns a JSON string that NLPEngine will parse
    # and QueryRouter will handle the list_cameras intent
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "intent" in data
    assert "session_id" in data


async def test_clear_session(client):
    # First create a session via a query
    await client.post("/query", json={"query": "hi", "session_id": "test_session"})
    # Now clear it
    resp = await client.delete("/sessions/test_session")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cleared"
    assert data["session_id"] == "test_session"


async def test_metrics_endpoint(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    # Should contain prometheus-format metrics
    assert "cctvql_queries_total" in text
    assert "cctvql_active_sessions" in text
    assert "cctvql_adapter_status" in text
    assert "cctvql_llm_status" in text
    # Content type should be plain text
    assert "text/plain" in resp.headers.get("content-type", "")
