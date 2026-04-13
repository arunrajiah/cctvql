"""
Tests for the DemoAdapter (cctvql.adapters.demo).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from cctvql.adapters.demo import _ANCHOR, DemoAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def adapter():
    a = DemoAdapter()
    await a.connect()
    return a


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


async def test_connect_returns_true():
    adapter = DemoAdapter()
    result = await adapter.connect()
    assert result is True


async def test_disconnect(adapter):
    await adapter.disconnect()
    assert adapter._connected is False


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------


async def test_list_cameras_returns_four(adapter):
    cameras = await adapter.list_cameras()
    assert len(cameras) == 4


async def test_get_camera_by_name(adapter):
    cam = await adapter.get_camera(camera_name="front door")
    assert cam is not None
    assert cam.name == "Front Door"

    cam_upper = await adapter.get_camera(camera_name="FRONT DOOR")
    assert cam_upper is not None
    assert cam_upper.id == cam.id


async def test_get_camera_not_found(adapter):
    cam = await adapter.get_camera(camera_name="nonexistent")
    assert cam is None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


async def test_get_events_no_filter(adapter):
    events = await adapter.get_events()
    assert len(events) > 0
    assert len(events) <= 20  # default limit


async def test_get_events_filter_by_label(adapter):
    events = await adapter.get_events(label="person")
    assert len(events) > 0
    for evt in events:
        labels = [
            o.label.lower() if isinstance(o.label, str) else o.label.value.lower()
            for o in evt.objects
        ]
        assert "person" in labels


async def test_get_events_filter_by_camera(adapter):
    events = await adapter.get_events(camera_name="Backyard")
    assert len(events) > 0
    for evt in events:
        assert evt.camera_name.lower() == "backyard"


async def test_get_events_filter_by_zone(adapter):
    events = await adapter.get_events(zone="porch")
    assert len(events) > 0
    for evt in events:
        assert "porch" in [z.lower() for z in evt.zones]


async def test_get_events_filter_by_time_range(adapter):
    # Use a time range that captures some but not all events
    start = _ANCHOR - timedelta(hours=3)
    end = _ANCHOR - timedelta(hours=1)
    events = await adapter.get_events(start_time=start, end_time=end)
    assert len(events) > 0
    for evt in events:
        assert evt.start_time >= start
        assert evt.start_time <= end


async def test_get_events_limit(adapter):
    events = await adapter.get_events(limit=3)
    assert len(events) <= 3


async def test_get_event_by_id(adapter):
    event = await adapter.get_event("evt_001")
    assert event is not None
    assert event.id == "evt_001"


async def test_get_event_not_found(adapter):
    event = await adapter.get_event("evt_nonexistent")
    assert event is None


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------


async def test_get_clips(adapter):
    clips = await adapter.get_clips()
    assert len(clips) > 0
    for clip in clips:
        assert clip.id is not None
        assert clip.download_url is not None


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


async def test_get_snapshot_url(adapter):
    url = await adapter.get_snapshot_url(camera_name="Front Door")
    assert url is not None
    assert "front_door" in url


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------


async def test_get_system_info(adapter):
    info = await adapter.get_system_info()
    assert info is not None
    assert info.system_name is not None
    assert info.camera_count == 4


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


async def test_list_zones(adapter):
    zones = await adapter.list_zones()
    assert len(zones) > 0

    # Filter by camera
    front_zones = await adapter.list_zones(camera_id="cam_front_door")
    assert len(front_zones) > 0
    for z in front_zones:
        assert z.camera_id == "cam_front_door"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def test_health_check(adapter):
    ok = await adapter.health_check()
    assert ok is True
