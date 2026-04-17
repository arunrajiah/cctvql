"""
Tests for MilestoneAdapter (cctvql.adapters.milestone).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.milestone import MilestoneAdapter
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
    return MilestoneAdapter(
        host="https://vms.example.com",
        username="admin",
        password="test_pass",
    )


def test_name_property(adapter):
    assert adapter.name == "milestone"


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


async def test_connect_success(adapter):
    adapter._client.post = AsyncMock(
        return_value=_mock_json_response({"access_token": "token-abc", "token_type": "Bearer"})
    )

    assert await adapter.connect() is True
    assert adapter._token == "token-abc"


async def test_connect_missing_token(adapter):
    adapter._client.post = AsyncMock(return_value=_mock_json_response({"error": "invalid"}))
    assert await adapter.connect() is False


async def test_connect_network_failure(adapter):
    adapter._client.post = AsyncMock(side_effect=Exception("connection refused"))
    assert await adapter.connect() is False


# ---------------------------------------------------------------------------
# headers / auth check
# ---------------------------------------------------------------------------


def test_headers_requires_token(adapter):
    with pytest.raises(RuntimeError):
        adapter._headers()


def test_headers_with_token(adapter):
    adapter._token = "xyz"
    headers = adapter._headers()
    assert headers["Authorization"] == "Bearer xyz"


# ---------------------------------------------------------------------------
# list_cameras
# ---------------------------------------------------------------------------


async def test_list_cameras_parses_response(adapter):
    adapter._token = "tok"
    payload = {
        "array": [
            {
                "id": "cam-1",
                "displayName": "Lobby",
                "enabled": True,
                "description": "Main lobby entrance",
                "channel": 1,
            },
            {
                "id": "cam-2",
                "name": "Parking",
                "enabled": False,
            },
        ]
    }
    adapter._client.get = AsyncMock(return_value=_mock_json_response(payload))

    cameras = await adapter.list_cameras()
    assert len(cameras) == 2
    lobby = next(c for c in cameras if c.name == "Lobby")
    assert lobby.id == "cam-1"
    assert lobby.status == CameraStatus.ONLINE
    assert lobby.snapshot_url.endswith("/cameras/cam-1/thumbnail")

    parking = next(c for c in cameras if c.name == "Parking")
    assert parking.status == CameraStatus.OFFLINE


async def test_list_cameras_returns_empty_on_error(adapter):
    adapter._token = "tok"
    adapter._client.get = AsyncMock(side_effect=Exception("boom"))
    assert await adapter.list_cameras() == []


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


async def test_get_events_parses_alarms(adapter):
    adapter._token = "tok"
    payload = {
        "array": [
            {
                "id": "alm-1",
                "sourceId": "cam-1",
                "sourceName": "Lobby",
                "timestamp": "2026-04-17T10:30:00Z",
                "category": "Motion detected",
                "priority": 2,
                "state": "New",
            }
        ]
    }
    adapter._client.get = AsyncMock(return_value=_mock_json_response(payload))

    events = await adapter.get_events(camera_id="cam-1")
    assert len(events) == 1
    ev = events[0]
    assert ev.camera_id == "cam-1"
    assert ev.event_type == EventType.MOTION
    assert ev.start_time.year == 2026
    assert ev.metadata["priority"] == 2


async def test_event_type_mapping():
    assert MilestoneAdapter._map_event_type("Motion") == EventType.MOTION
    assert MilestoneAdapter._map_event_type("Object analytics") == EventType.OBJECT_DETECTED
    assert MilestoneAdapter._map_event_type("Tamper") == EventType.TAMPER
    assert MilestoneAdapter._map_event_type("Audio threshold") == EventType.AUDIO
    assert MilestoneAdapter._map_event_type("Unknown") == EventType.UNKNOWN
    assert MilestoneAdapter._map_event_type(None) == EventType.UNKNOWN


# ---------------------------------------------------------------------------
# snapshot URL
# ---------------------------------------------------------------------------


async def test_get_snapshot_url_by_id(adapter):
    adapter._token = "tok"
    url = await adapter.get_snapshot_url(camera_id="cam-5")
    assert url == "https://vms.example.com/api/rest/v1/cameras/cam-5/thumbnail"


async def test_get_snapshot_url_no_id_returns_none(adapter):
    adapter._token = "tok"
    adapter._client.get = AsyncMock(return_value=_mock_json_response({"array": []}))
    assert await adapter.get_snapshot_url(camera_name="Nonexistent") is None


# ---------------------------------------------------------------------------
# get_clips
# ---------------------------------------------------------------------------


async def test_get_clips_parses_bookmarks(adapter):
    adapter._token = "tok"
    payload = {
        "array": [
            {
                "id": "bm-1",
                "cameraId": "cam-1",
                "cameraName": "Lobby",
                "startTime": "2026-04-17T10:00:00Z",
                "endTime": "2026-04-17T10:01:00Z",
                "header": "Suspicious activity",
                "description": "Person loitering",
            }
        ]
    }
    adapter._client.get = AsyncMock(return_value=_mock_json_response(payload))

    clips = await adapter.get_clips(camera_id="cam-1")
    assert len(clips) == 1
    clip = clips[0]
    assert clip.id == "bm-1"
    assert clip.camera_id == "cam-1"
    assert clip.camera_name == "Lobby"
    assert clip.end_time > clip.start_time
    assert clip.metadata["header"] == "Suspicious activity"


async def test_get_clips_returns_empty_on_error(adapter):
    adapter._token = "tok"
    adapter._client.get = AsyncMock(side_effect=Exception("boom"))
    assert await adapter.get_clips() == []


# ---------------------------------------------------------------------------
# OData filter validation
# ---------------------------------------------------------------------------


def test_safe_odata_id_rejects_injection():
    import pytest

    from cctvql.adapters.milestone import _safe_odata_id

    with pytest.raises(ValueError):
        _safe_odata_id("cam' or '1'='1")


def test_safe_odata_id_accepts_guid():
    from cctvql.adapters.milestone import _safe_odata_id

    guid = "a0b1c2d3-e4f5-6789-abcd-ef0123456789"
    assert _safe_odata_id(guid) == guid


# ---------------------------------------------------------------------------
# ISO parser
# ---------------------------------------------------------------------------


def test_parse_iso_z_suffix():
    result = MilestoneAdapter._parse_iso("2026-01-15T10:00:00Z")
    assert result.year == 2026
    assert result.hour == 10


def test_parse_iso_bad_input_returns_now():
    from datetime import datetime

    result = MilestoneAdapter._parse_iso("not-a-date")
    assert isinstance(result, datetime)
