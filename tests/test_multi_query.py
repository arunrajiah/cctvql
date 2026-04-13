"""
Tests for MultiSystemRouter (cctvql.core.multi_query).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.base import AdapterRegistry
from cctvql.adapters.demo import DemoAdapter
from cctvql.core.multi_query import MultiSystemRouter
from cctvql.core.schema import (
    Camera,
    CameraStatus,
    DetectedObject,
    Event,
    EventType,
    QueryContext,
)
from cctvql.llm.base import LLMResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset AdapterRegistry state between every test."""
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    yield
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None


def _make_mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.name = "mock"
    llm.complete = AsyncMock(return_value=LLMResponse(content="ok", model="mock"))
    llm.supports_vision = False
    return llm


def _make_mock_adapter(
    name: str, cameras: list | None = None, events: list | None = None
) -> MagicMock:
    """Build a MagicMock adapter with the given name."""
    adapter = MagicMock()
    adapter.name = name
    adapter.list_cameras = AsyncMock(return_value=cameras or [])
    adapter.get_events = AsyncMock(return_value=events or [])
    adapter.get_clips = AsyncMock(return_value=[])
    adapter.get_camera = AsyncMock(return_value=None)
    return adapter


def _make_camera(cam_id: str, name: str) -> Camera:
    return Camera(
        id=cam_id,
        name=name,
        status=CameraStatus.ONLINE,
    )


def _make_event(evt_id: str, camera_name: str, hour: int = 10) -> Event:
    return Event(
        id=evt_id,
        camera_id="cam_01",
        camera_name=camera_name,
        event_type=EventType.MOTION,
        start_time=datetime(2026, 1, 15, hour, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def router():
    return MultiSystemRouter(llm=_make_mock_llm())


# ---------------------------------------------------------------------------
# No adapters registered
# ---------------------------------------------------------------------------


async def test_route_no_adapters_returns_helpful_message(router):
    ctx = QueryContext(intent="list_cameras")
    result = await router.route(ctx)
    assert "No adapters are registered" in result


# ---------------------------------------------------------------------------
# list_cameras — fan-out
# ---------------------------------------------------------------------------


async def test_route_list_cameras_merges_results(router):
    """Cameras from both adapters appear in the merged result."""
    cam_a = _make_camera("cam_a1", "Camera Alpha 1")
    cam_b = _make_camera("cam_b1", "Camera Beta 1")

    adapter_a = _make_mock_adapter("system_a", cameras=[cam_a])
    adapter_b = _make_mock_adapter("system_b", cameras=[cam_b])

    AdapterRegistry.register(adapter_a)
    AdapterRegistry.register(adapter_b)
    AdapterRegistry.set_active("system_a")

    ctx = QueryContext(intent="list_cameras")
    result = await router.route(ctx)

    assert "Camera Alpha 1" in result
    assert "Camera Beta 1" in result
    assert "system_a" in result
    assert "system_b" in result


async def test_route_list_cameras_total_count(router):
    """Result header reflects total camera count across all systems."""
    cameras_a = [_make_camera(f"a{i}", f"Alpha {i}") for i in range(3)]
    cameras_b = [_make_camera(f"b{i}", f"Beta {i}") for i in range(2)]

    AdapterRegistry.register(_make_mock_adapter("system_a", cameras=cameras_a))
    AdapterRegistry.register(_make_mock_adapter("system_b", cameras=cameras_b))
    AdapterRegistry.set_active("system_a")

    ctx = QueryContext(intent="list_cameras")
    result = await router.route(ctx)
    assert "5" in result  # "Found 5 camera(s)"


# ---------------------------------------------------------------------------
# get_events — fan-out + deduplication
# ---------------------------------------------------------------------------


async def test_route_get_events_merges_results(router):
    """Events from both systems appear in the merged response."""
    evt_a = _make_event("evt_a1", "Front Door", hour=10)
    evt_b = _make_event("evt_b1", "Garage Cam", hour=11)

    AdapterRegistry.register(_make_mock_adapter("system_a", events=[evt_a]))
    AdapterRegistry.register(_make_mock_adapter("system_b", events=[evt_b]))
    AdapterRegistry.set_active("system_a")

    ctx = QueryContext(intent="get_events")
    result = await router.route(ctx)

    assert "Front Door" in result
    assert "Garage Cam" in result


async def test_route_get_events_deduplicates(router):
    """Events with same (camera_name, start_time) only appear once."""
    shared_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    evt1 = Event(
        id="dup_a",
        camera_id="cam1",
        camera_name="Front Door",
        event_type=EventType.MOTION,
        start_time=shared_time,
    )
    evt2 = Event(
        id="dup_b",
        camera_id="cam1",
        camera_name="Front Door",
        event_type=EventType.MOTION,
        start_time=shared_time,
    )

    AdapterRegistry.register(_make_mock_adapter("system_a", events=[evt1]))
    AdapterRegistry.register(_make_mock_adapter("system_b", events=[evt2]))
    AdapterRegistry.set_active("system_a")

    ctx = QueryContext(intent="get_events")
    result = await router.route(ctx)

    # Deduplication: "Found 1 event(s)" not 2
    assert "Found **1**" in result


# ---------------------------------------------------------------------------
# Failure resilience
# ---------------------------------------------------------------------------


async def test_route_handles_adapter_failure_gracefully(router):
    """One adapter failing does not block results from the other."""
    good_event = _make_event("evt_good", "Backyard")
    good_adapter = _make_mock_adapter("good_system", events=[good_event])

    bad_adapter = MagicMock()
    bad_adapter.name = "bad_system"
    bad_adapter.get_events = AsyncMock(side_effect=RuntimeError("NVR offline"))
    bad_adapter.list_cameras = AsyncMock(side_effect=RuntimeError("NVR offline"))

    AdapterRegistry.register(good_adapter)
    AdapterRegistry.register(bad_adapter)
    AdapterRegistry.set_active("good_system")

    ctx = QueryContext(intent="get_events")
    result = await router.route(ctx)

    # Good system's event still appears
    assert "Backyard" in result
    # Error section mentions the failing system
    assert "bad_system" in result


async def test_route_all_adapters_fail_returns_error_message(router):
    """All adapters failing returns a clear 'no data' message."""
    adapter_a = MagicMock()
    adapter_a.name = "sys_a"
    adapter_a.get_events = AsyncMock(side_effect=Exception("timeout"))

    AdapterRegistry.register(adapter_a)
    AdapterRegistry.set_active("sys_a")

    ctx = QueryContext(intent="get_events")
    result = await router.route(ctx)
    assert "No data returned" in result or "sys_a" in result


# ---------------------------------------------------------------------------
# Single-system intents — active adapter only
# ---------------------------------------------------------------------------


async def test_single_system_intents_use_active_adapter():
    """get_snapshot intent routes to active adapter only (QueryRouter path)."""
    llm = _make_mock_llm()
    router = MultiSystemRouter(llm=llm)

    demo_a = DemoAdapter()
    await demo_a.connect()

    mock_b = _make_mock_adapter("system_b", cameras=[_make_camera("b1", "Beta")])

    AdapterRegistry.register(demo_a)
    AdapterRegistry.register(mock_b)
    AdapterRegistry.set_active("demo")

    ctx = QueryContext(intent="get_snapshot", camera_name="Front Door")
    result = await router.route(ctx)

    # Result should include the note about multi-system query
    assert "_Note:" in result
    # system_b adapter methods should not have been called for get_snapshot
    mock_b.get_events.assert_not_called()
    mock_b.list_cameras.assert_not_called()


async def test_get_system_info_uses_active_adapter_only():
    """get_system_info uses active adapter and appends multi-system note."""
    llm = _make_mock_llm()
    router = MultiSystemRouter(llm=llm)

    demo_a = DemoAdapter()
    await demo_a.connect()

    mock_b = _make_mock_adapter("system_b")

    AdapterRegistry.register(demo_a)
    AdapterRegistry.register(mock_b)
    AdapterRegistry.set_active("demo")

    ctx = QueryContext(intent="get_system_info")
    result = await router.route(ctx)

    assert "_Note:" in result
    mock_b.get_events.assert_not_called()


# ---------------------------------------------------------------------------
# Unknown intent
# ---------------------------------------------------------------------------


async def test_unknown_intent_returns_empty_success(router):
    """Unknown intent is handled gracefully — no crash."""
    adapter = _make_mock_adapter("sys_a")
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("sys_a")

    ctx = QueryContext(intent="totally_unknown_intent")
    # Should not raise
    result = await router.route(ctx)
    assert isinstance(result, str)
