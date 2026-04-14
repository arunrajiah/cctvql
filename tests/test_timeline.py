"""
Tests for GET /events/timeline and GET /timeline endpoints.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cctvql.adapters.base import AdapterRegistry
from cctvql.adapters.demo import DemoAdapter
from cctvql.llm.base import LLMRegistry, LLMResponse

# ---------------------------------------------------------------------------
# Fixtures (mirror test_rest_api.py setup)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_registries():
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None

    adapter = DemoAdapter()
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("demo")

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

    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None


@pytest.fixture
async def client():
    import cctvql.interfaces.rest_api as api_module
    from cctvql.core.alerts import AlertEngine
    from cctvql.core.health_monitor import HealthMonitor
    from cctvql.notifications.registry import NotifierRegistry

    api_module._in_memory_sessions.clear()
    api_module._db = None
    api_module._session_store = None

    engine = AlertEngine(AdapterRegistry)
    await engine.start()
    api_module._alert_engine = engine

    monitor = HealthMonitor(AdapterRegistry, NotifierRegistry, poll_interval=9999)
    await monitor.start()
    api_module._health_monitor = monitor

    transport = httpx.ASGITransport(app=api_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await engine.stop()
    await monitor.stop()
    api_module._in_memory_sessions.clear()


# ---------------------------------------------------------------------------
# GET /timeline — HTML page
# ---------------------------------------------------------------------------


async def test_timeline_page_returns_html(client):
    resp = await client.get("/timeline")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "cctvQL" in resp.text
    assert "Timeline" in resp.text


async def test_timeline_page_has_range_buttons(client):
    resp = await client.get("/timeline")
    assert resp.status_code == 200
    assert 'data-hours="24"' in resp.text
    assert 'data-hours="168"' in resp.text


async def test_timeline_page_links_back_to_chat(client):
    resp = await client.get("/timeline")
    assert 'href="/"' in resp.text


# ---------------------------------------------------------------------------
# GET /events/timeline — JSON API
# ---------------------------------------------------------------------------


async def test_timeline_default_params(client):
    resp = await client.get("/events/timeline")
    assert resp.status_code == 200
    data = resp.json()
    assert "cameras" in data
    assert "buckets" in data
    assert "data" in data
    assert "range_start" in data
    assert "range_end" in data
    assert "bucket_minutes" in data
    assert "hours" in data


async def test_timeline_default_hours_is_24(client):
    resp = await client.get("/events/timeline")
    assert resp.json()["hours"] == 24


async def test_timeline_default_bucket_is_60_for_24h(client):
    resp = await client.get("/events/timeline")
    # Auto bucket: >6h → 60 minutes
    assert resp.json()["bucket_minutes"] == 60


async def test_timeline_bucket_is_15_for_1h(client):
    resp = await client.get("/events/timeline", params={"hours": 1})
    assert resp.json()["bucket_minutes"] == 15


async def test_timeline_bucket_is_15_for_6h(client):
    resp = await client.get("/events/timeline", params={"hours": 6})
    assert resp.json()["bucket_minutes"] == 15


async def test_timeline_explicit_bucket_minutes(client):
    resp = await client.get("/events/timeline", params={"hours": 24, "bucket_minutes": 30})
    assert resp.json()["bucket_minutes"] == 30


async def test_timeline_buckets_cover_full_window(client):
    resp = await client.get("/events/timeline", params={"hours": 24})
    data = resp.json()
    # 24h / 60min = 24 buckets (approx; may be 25 due to inclusive end)
    assert len(data["buckets"]) >= 24
    assert len(data["buckets"]) <= 26


async def test_timeline_7d_window(client):
    resp = await client.get("/events/timeline", params={"hours": 168})
    data = resp.json()
    assert data["hours"] == 168
    # 168h / 60min = 168 buckets
    assert len(data["buckets"]) >= 168


async def test_timeline_cameras_list(client):
    resp = await client.get("/events/timeline")
    data = resp.json()
    # Demo adapter has 4 cameras; at least one should appear
    assert isinstance(data["cameras"], list)


async def test_timeline_data_structure(client):
    resp = await client.get("/events/timeline")
    data = resp.json()
    grid = data["data"]
    assert isinstance(grid, dict)
    for cam_name, cam_data in grid.items():
        assert isinstance(cam_name, str)
        assert isinstance(cam_data, dict)
        for bucket_key, cell in cam_data.items():
            assert "count" in cell
            assert "labels" in cell
            assert "top_label" in cell
            assert cell["count"] > 0
            assert isinstance(cell["labels"], list)


async def test_timeline_camera_filter(client):
    resp = await client.get("/events/timeline", params={"camera": "Front Door"})
    assert resp.status_code == 200
    data = resp.json()
    # All cameras in response should be Front Door (or empty if filtered)
    for cam in data["cameras"]:
        assert cam.lower() == "front door"


async def test_timeline_hours_validation_too_low(client):
    resp = await client.get("/events/timeline", params={"hours": 0})
    assert resp.status_code == 422


async def test_timeline_hours_validation_too_high(client):
    resp = await client.get("/events/timeline", params={"hours": 999})
    assert resp.status_code == 422


async def test_timeline_bucket_minutes_validation(client):
    resp = await client.get("/events/timeline", params={"bucket_minutes": 200})
    assert resp.status_code == 422


async def test_timeline_range_timestamps_are_iso(client):
    resp = await client.get("/events/timeline")
    data = resp.json()
    # Should be parseable ISO strings like "2026-04-14T09:00"
    from datetime import datetime

    datetime.fromisoformat(data["range_start"])
    datetime.fromisoformat(data["range_end"])


async def test_timeline_range_end_after_start(client):
    resp = await client.get("/events/timeline")
    data = resp.json()
    from datetime import datetime

    start = datetime.fromisoformat(data["range_start"])
    end = datetime.fromisoformat(data["range_end"])
    assert end > start


async def test_timeline_nonexistent_camera_returns_empty(client):
    resp = await client.get("/events/timeline", params={"camera": "NoSuchCamera999"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["cameras"] == []
    assert data["data"] == {}
