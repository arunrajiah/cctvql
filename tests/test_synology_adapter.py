"""
Tests for SynologyAdapter (cctvql.adapters.synology).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.synology import SynologyAdapter
from cctvql.core.schema import CameraStatus, EventType


def _mock_json_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=data)
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


@pytest.fixture
def adapter():
    return SynologyAdapter(
        host="http://192.168.1.10:5000",
        username="admin",
        password="test_pass",
    )


def test_name_property(adapter):
    assert adapter.name == "synology"


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


async def test_connect_success(adapter):
    adapter._client.get = AsyncMock(
        return_value=_mock_json_response({"success": True, "data": {"sid": "abc123xyz"}})
    )

    assert await adapter.connect() is True
    assert adapter._sid == "abc123xyz"


async def test_connect_failure_api_error(adapter):
    adapter._client.get = AsyncMock(
        return_value=_mock_json_response({"success": False, "error": {"code": 400}})
    )

    assert await adapter.connect() is False
    assert adapter._sid is None


async def test_connect_failure_exception(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("connection refused"))

    assert await adapter.connect() is False


# ---------------------------------------------------------------------------
# list_cameras
# ---------------------------------------------------------------------------


async def test_list_cameras_parses_response(adapter):
    adapter._sid = "session-id"
    payload = {
        "success": True,
        "data": {
            "cameras": [
                {
                    "id": 1,
                    "newName": "Front Door",
                    "status": 1,
                    "model": "DS-2CD",
                    "vendor": "Hikvision",
                    "ip": "192.168.1.50",
                    "rtspPath": "rtsp://cam1/live",
                },
                {
                    "id": 2,
                    "newName": "Backyard",
                    "status": 0,
                    "model": "Generic",
                },
            ]
        },
    }
    adapter._client.get = AsyncMock(return_value=_mock_json_response(payload))

    cameras = await adapter.list_cameras()
    assert len(cameras) == 2
    front = next(c for c in cameras if c.name == "Front Door")
    assert front.id == "1"
    assert front.status == CameraStatus.ONLINE
    assert front.stream_url == "rtsp://cam1/live"
    assert front.metadata["source"] == "synology"

    back = next(c for c in cameras if c.name == "Backyard")
    assert back.status == CameraStatus.OFFLINE


async def test_list_cameras_returns_empty_on_error(adapter):
    adapter._sid = "session-id"
    adapter._client.get = AsyncMock(side_effect=Exception("network error"))
    assert await adapter.list_cameras() == []


async def test_list_cameras_requires_connect(adapter):
    # No _sid set — should raise internally but surface as empty list
    adapter._client.get = AsyncMock()
    assert await adapter.list_cameras() == []


# ---------------------------------------------------------------------------
# get_snapshot_url
# ---------------------------------------------------------------------------


async def test_get_snapshot_url_by_id(adapter):
    adapter._sid = "SID"
    url = await adapter.get_snapshot_url(camera_id="5")
    assert url is not None
    assert "id=5" in url
    assert "_sid=SID" in url
    assert "GetSnapshot" in url


async def test_get_snapshot_url_returns_none_without_id_or_name(adapter):
    adapter._sid = "SID"
    assert await adapter.get_snapshot_url() is None


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------


async def test_get_events_parses_response(adapter):
    adapter._sid = "SID"
    payload = {
        "success": True,
        "data": {
            "events": [
                {
                    "id": 42,
                    "camera_id": 1,
                    "camera_name": "Front Door",
                    "reason": 2,
                    "startTime": 1_700_000_000,
                    "stopTime": 1_700_000_030,
                }
            ]
        },
    }
    adapter._client.get = AsyncMock(return_value=_mock_json_response(payload))

    events = await adapter.get_events()
    assert len(events) == 1
    assert events[0].event_type == EventType.MOTION
    assert events[0].camera_name == "Front Door"


# ---------------------------------------------------------------------------
# event type mapping
# ---------------------------------------------------------------------------


def test_event_type_mapping():
    assert SynologyAdapter._map_event_type(2) == EventType.MOTION
    assert SynologyAdapter._map_event_type(6) == EventType.OBJECT_DETECTED
    assert SynologyAdapter._map_event_type(7) == EventType.AUDIO
    assert SynologyAdapter._map_event_type(99) == EventType.UNKNOWN
    assert SynologyAdapter._map_event_type(None) == EventType.UNKNOWN


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


async def test_health_check_ok(adapter):
    adapter._client.get = AsyncMock(return_value=_mock_json_response({"success": True}))
    assert await adapter.health_check() is True


async def test_health_check_fails_on_exception(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("timeout"))
    assert await adapter.health_check() is False
