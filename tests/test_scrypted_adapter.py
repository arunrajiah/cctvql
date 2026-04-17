"""
Tests for ScryptedAdapter (cctvql.adapters.scrypted).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.scrypted import ScryptedAdapter
from cctvql.core.schema import CameraStatus, EventType


def _mock_json_response(data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=data)
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


@pytest.fixture
def adapter():
    return ScryptedAdapter(
        host="https://scrypted.local:10443",
        api_token="test-token",
    )


def test_name_property(adapter):
    assert adapter.name == "scrypted"


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


async def test_connect_success(adapter):
    adapter._client.get = AsyncMock(return_value=_mock_json_response({"serverName": "home"}))
    assert await adapter.connect() is True
    assert adapter._connected is True


async def test_connect_failure(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("connection refused"))
    assert await adapter.connect() is False


# ---------------------------------------------------------------------------
# headers
# ---------------------------------------------------------------------------


def test_headers_include_bearer_token(adapter):
    headers = adapter._headers()
    assert headers["Authorization"] == "Bearer test-token"


def test_headers_without_token_omit_auth():
    adapter = ScryptedAdapter(host="https://x", api_token="")
    assert "Authorization" not in adapter._headers()


# ---------------------------------------------------------------------------
# list_cameras
# ---------------------------------------------------------------------------


async def test_list_cameras_filters_by_interface(adapter):
    payload = {
        "devices": [
            {
                "id": "dev-1",
                "name": "Front Camera",
                "interfaces": ["Camera", "MotionSensor"],
                "online": True,
                "rtspUrl": "rtsp://front",
            },
            {
                "id": "dev-2",
                "name": "Kitchen Light",  # not a camera
                "interfaces": ["OnOff", "Brightness"],
                "online": True,
            },
            {
                "id": "dev-3",
                "name": "Doorbell",
                "interfaces": ["VideoCamera", "BinarySensor"],
                "online": False,
            },
        ]
    }
    adapter._client.get = AsyncMock(return_value=_mock_json_response(payload))

    cameras = await adapter.list_cameras()
    names = {c.name for c in cameras}
    assert names == {"Front Camera", "Doorbell"}

    front = next(c for c in cameras if c.name == "Front Camera")
    assert front.status == CameraStatus.ONLINE
    assert front.stream_url == "rtsp://front"
    assert "/device/dev-1/snapshot" in front.snapshot_url

    doorbell = next(c for c in cameras if c.name == "Doorbell")
    assert doorbell.status == CameraStatus.OFFLINE


async def test_list_cameras_returns_empty_on_error(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("network error"))
    assert await adapter.list_cameras() == []


# ---------------------------------------------------------------------------
# snapshot URL
# ---------------------------------------------------------------------------


async def test_get_snapshot_url_by_id(adapter):
    url = await adapter.get_snapshot_url(camera_id="dev-9")
    assert url.endswith("/endpoint/@scrypted/core/public/device/dev-9/snapshot")


async def test_get_snapshot_url_returns_none_without_id(adapter):
    adapter._client.get = AsyncMock(return_value=_mock_json_response({"devices": []}))
    assert await adapter.get_snapshot_url(camera_name="Nonexistent") is None


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


async def test_get_events_parses_response(adapter):
    payload = {
        "events": [
            {
                "id": "ev-1",
                "device": "dev-1",
                "deviceName": "Front Camera",
                "type": "motion",
                "startTime": 1_700_000_000_000,
                "endTime": 1_700_000_005_000,
                "score": 0.92,
            },
            {
                "id": "ev-2",
                "device": "dev-1",
                "deviceName": "Front Camera",
                "type": "person",
                "startTime": 1_700_000_010_000,
                "class": "person",
            },
        ]
    }
    adapter._client.get = AsyncMock(return_value=_mock_json_response(payload))

    events = await adapter.get_events(camera_id="dev-1")
    assert len(events) == 2
    assert events[0].event_type == EventType.MOTION
    assert events[1].event_type == EventType.OBJECT_DETECTED


async def test_event_type_mapping():
    assert ScryptedAdapter._map_event_type("motion") == EventType.MOTION
    assert ScryptedAdapter._map_event_type("person") == EventType.OBJECT_DETECTED
    assert ScryptedAdapter._map_event_type("vehicle detected") == EventType.OBJECT_DETECTED
    assert ScryptedAdapter._map_event_type("audio threshold") == EventType.AUDIO
    assert ScryptedAdapter._map_event_type("tamper") == EventType.TAMPER
    assert ScryptedAdapter._map_event_type(None) == EventType.UNKNOWN


# ---------------------------------------------------------------------------
# health check
# ---------------------------------------------------------------------------


async def test_health_check_ok(adapter):
    adapter._client.get = AsyncMock(return_value=_mock_json_response({"ok": True}))
    assert await adapter.health_check() is True


async def test_health_check_exception(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("timeout"))
    assert await adapter.health_check() is False


# ---------------------------------------------------------------------------
# PTZ
# ---------------------------------------------------------------------------


async def test_ptz_move_no_camera_returns_false(adapter):
    adapter._client.get = AsyncMock(return_value=_mock_json_response({"devices": []}))
    assert await adapter.ptz_move("missing", "left") is False
