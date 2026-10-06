"""
Tests for FrigateAdapter (cctvql.adapters.frigate).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from cctvql.adapters.frigate import FrigateAdapter
from cctvql.core.schema import BoundingBox, CameraStatus, DetectedObject, EventType


@pytest.fixture
def adapter():
    return FrigateAdapter(host="http://192.168.1.100:5000")


# ---------------------------------------------------------------------------
# list_cameras
# ---------------------------------------------------------------------------


async def test_list_cameras_parses_config_and_stats(adapter):
    config = {
        "cameras": {
            "front_door": {
                "detect": {"width": 1280, "height": 720, "fps": 5},
                "zones": {
                    "porch": {"coordinates": "0.1,0.2,0.3,0.4"},
                    "driveway": {"coordinates": "0.5,0.6,0.7,0.8"},
                },
            },
            "backyard": {
                "detect": {"width": 1920, "height": 1080, "fps": 10},
                "zones": {},
            },
        }
    }
    stats = {
        "cameras": {
            "front_door": {"camera_fps": 5.0},
            "backyard": {"camera_fps": 0.0},
        }
    }
    adapter._get = AsyncMock(return_value=config)
    adapter._get_stats = AsyncMock(return_value=stats)

    cameras = await adapter.list_cameras()

    adapter._get.assert_called_once_with("/api/config")
    adapter._get_stats.assert_awaited_once()
    assert len(cameras) == 2

    front = next(c for c in cameras if c.id == "front_door")
    assert front.name == "front_door"
    assert front.status == CameraStatus.ONLINE
    assert front.zones == ["porch", "driveway"]
    assert front.snapshot_url == "http://192.168.1.100:5000/api/front_door/latest.jpg"
    assert front.stream_url == "http://192.168.1.100:5000/live/front_door"
    assert front.metadata["detect"] == {"width": 1280, "height": 720, "fps": 5}

    backyard = next(c for c in cameras if c.id == "backyard")
    assert backyard.name == "backyard"
    assert backyard.status == CameraStatus.OFFLINE
    assert backyard.zones == []
    assert backyard.snapshot_url == "http://192.168.1.100:5000/api/backyard/latest.jpg"
    assert backyard.stream_url == "http://192.168.1.100:5000/live/backyard"
    assert backyard.metadata["detect"] == {"width": 1920, "height": 1080, "fps": 10}


# ---------------------------------------------------------------------------
# _parse_event helper
# ---------------------------------------------------------------------------


def test_parse_event_maps_object_detection_fields(adapter):
    event = adapter._parse_event(
        {
            "id": "event-123",
            "camera": "front_door",
            "label": "person",
            "score": 0.92,
            "box": [0.1, 0.2, 0.3, 0.4],
            "current_zones": ["porch"],
            "start_time": 1_700_000_000,
            "end_time": 1_700_000_030,
            "has_clip": True,
        }
    )

    assert event.id == "event-123"
    assert event.camera_id == "front_door"
    assert event.camera_name == "front_door"
    assert event.event_type == EventType.OBJECT_DETECTED
    assert event.start_time == datetime.fromtimestamp(1_700_000_000)
    assert event.end_time == datetime.fromtimestamp(1_700_000_030)
    assert event.zones == ["porch"]
    assert event.snapshot_url == "http://192.168.1.100:5000/api/events/event-123/snapshot.jpg"
    assert event.clip_url == "http://192.168.1.100:5000/api/events/event-123/clip.mp4"
    assert event.thumbnail_url == "http://192.168.1.100:5000/api/events/event-123/thumbnail.jpg"
    assert event.metadata == {"has_clip": True}
    assert event.objects == [
        DetectedObject(
            label="person",
            confidence=0.92,
            bounding_box=BoundingBox(x_min=0.1, y_min=0.2, x_max=0.3, y_max=0.4),
        )
    ]


def test_parse_event_uses_top_score_when_score_is_none(adapter):
    event = adapter._parse_event(
        {
            "id": "event-456",
            "camera": "driveway",
            "label": "car",
            "score": None,
            "top_score": 0.81,
            "box": [10, 20, 30, 40],
            "current_zones": ["driveway"],
            "start_time": 1_700_000_000,
            "has_clip": False,
        }
    )

    assert event.event_type == EventType.OBJECT_DETECTED
    assert event.objects == [
        DetectedObject(
            label="car",
            confidence=0.81,
            bounding_box=BoundingBox(x_min=10, y_min=20, x_max=30, y_max=40),
        )
    ]
    assert event.clip_url is None
    assert event.snapshot_url == "http://192.168.1.100:5000/api/events/event-456/snapshot.jpg"
    assert event.thumbnail_url == "http://192.168.1.100:5000/api/events/event-456/thumbnail.jpg"
    assert event.metadata == {"has_clip": False}


def test_parse_event_without_label_is_motion(adapter):
    event = adapter._parse_event(
        {
            "id": "event-789",
            "camera": "backyard",
            "label": "",
            "score": 0.5,
            "current_zones": ["yard"],
            "start_time": 1_700_000_000,
            "has_clip": False,
        }
    )

    assert event.id == "event-789"
    assert event.camera_id == "backyard"
    assert event.camera_name == "backyard"
    assert event.event_type == EventType.MOTION
    assert event.objects == []
    assert event.zones == ["yard"]
    assert event.clip_url is None
    assert event.metadata == {"has_clip": False}


# ---------------------------------------------------------------------------
# _parse_coords helper
# ---------------------------------------------------------------------------


def test_parse_coords_valid_points():
    result = FrigateAdapter._parse_coords("0.1,0.2,0.3,0.4")

    assert result == [(0.1, 0.2), (0.3, 0.4)]


def test_parse_coords_empty_returns_none():
    assert FrigateAdapter._parse_coords("") is None


def test_parse_coords_malformed_returns_none():
    assert FrigateAdapter._parse_coords("0.1,not-a-number,0.3,0.4") is None
