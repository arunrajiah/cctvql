"""
Tests for HikvisionAdapter (cctvql.adapters.hikvision).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.hikvision import HikvisionAdapter
from cctvql.core.schema import CameraStatus


# ---------------------------------------------------------------------------
# Sample XML fixtures
# ---------------------------------------------------------------------------

_DEVICE_INFO_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <deviceName>Hikvision Test NVR</deviceName>
  <model>DS-7608NI-K2</model>
  <firmwareVersion>V4.62.210</firmwareVersion>
  <serialNumber>DS-7608NI000000000</serialNumber>
</DeviceInfo>
"""

_CHANNEL_LIST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<InputProxyChannelList xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <InputProxyChannel>
    <id>1</id>
    <name>Front Door</name>
    <online>true</online>
  </InputProxyChannel>
  <InputProxyChannel>
    <id>2</id>
    <name>Backyard</name>
    <online>false</online>
  </InputProxyChannel>
</InputProxyChannelList>
"""

_EMPTY_SEARCH_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<CMSearchResult xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <numOfMatches>0</numOfMatches>
  <totalMatches>0</totalMatches>
  <matchList/>
</CMSearchResult>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(text: str = "", status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


@pytest.fixture
def adapter():
    return HikvisionAdapter(
        host="http://192.168.1.64",
        username="admin",
        password="test_pass",
    )


# ---------------------------------------------------------------------------
# name property
# ---------------------------------------------------------------------------


def test_name_property(adapter):
    assert adapter.name == "hikvision"


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


async def test_connect_success(adapter):
    resp = _mock_response(text=_DEVICE_INFO_XML)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.connect()

    assert result is True
    adapter._client.get.assert_called_once()
    assert adapter._device_info["deviceName"] == "Hikvision Test NVR"
    assert adapter._device_info["model"] == "DS-7608NI-K2"
    assert adapter._device_info["firmwareVersion"] == "V4.62.210"
    assert adapter._device_info["serialNumber"] == "DS-7608NI000000000"


async def test_connect_failure(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("connection refused"))

    result = await adapter.connect()

    assert result is False


async def test_connect_http_error(adapter):
    resp = _mock_response(status_code=401)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.connect()

    assert result is False


# ---------------------------------------------------------------------------
# list_cameras
# ---------------------------------------------------------------------------


async def test_list_cameras_parses_xml(adapter):
    resp = _mock_response(text=_CHANNEL_LIST_XML)
    adapter._client.get = AsyncMock(return_value=resp)

    cameras = await adapter.list_cameras()

    assert len(cameras) == 2

    front = next(c for c in cameras if c.name == "Front Door")
    assert front.id == "1"
    assert front.status == CameraStatus.ONLINE
    assert "01" in front.snapshot_url  # channel 01 main stream

    backyard = next(c for c in cameras if c.name == "Backyard")
    assert backyard.id == "2"
    assert backyard.status == CameraStatus.UNKNOWN


async def test_list_cameras_returns_empty_on_error(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("network error"))

    cameras = await adapter.list_cameras()

    assert cameras == []


async def test_list_cameras_uses_channel_count_hint_when_empty():
    """If API returns no channels and channel_count hint is set, stubs are created."""
    adapter = HikvisionAdapter(
        host="http://192.168.1.64",
        username="admin",
        password="",
        channel_count=4,
    )
    empty_xml = """\
<?xml version="1.0"?>
<InputProxyChannelList xmlns="http://www.hikvision.com/ver20/XMLSchema"/>
"""
    resp = _mock_response(text=empty_xml)
    adapter._client.get = AsyncMock(return_value=resp)

    cameras = await adapter.list_cameras()

    assert len(cameras) == 4
    assert cameras[0].name == "Channel 1"


# ---------------------------------------------------------------------------
# get_snapshot_url
# ---------------------------------------------------------------------------


async def test_get_snapshot_url_format_by_id(adapter):
    url = await adapter.get_snapshot_url(camera_id="3")

    assert url is not None
    assert "0301" in url  # channel 03, stream 01
    assert "picture" in url
    assert adapter.host in url


async def test_get_snapshot_url_defaults_to_channel_1(adapter):
    url = await adapter.get_snapshot_url()

    assert url is not None
    assert "0101" in url


async def test_get_snapshot_url_by_name(adapter):
    """Resolves camera by name then builds URL from its ID."""
    list_resp = _mock_response(text=_CHANNEL_LIST_XML)
    adapter._client.get = AsyncMock(return_value=list_resp)

    url = await adapter.get_snapshot_url(camera_name="Front Door")

    assert url is not None
    assert "0101" in url


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


async def test_health_check_ok(adapter):
    resp = _mock_response(text=_DEVICE_INFO_XML, status_code=200)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.health_check()

    assert result is True


async def test_health_check_fail_exception(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("timeout"))

    result = await adapter.health_check()

    assert result is False


async def test_health_check_fail_bad_status(adapter):
    resp = _mock_response(status_code=503)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.health_check()

    assert result is False


# ---------------------------------------------------------------------------
# get_events — XML search
# ---------------------------------------------------------------------------


async def test_get_events_returns_empty_on_search_failure(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("network error"))
    adapter._client.post = AsyncMock(side_effect=Exception("network error"))

    events = await adapter.get_events()

    assert events == []


async def test_get_events_parses_match_elements(adapter):
    search_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<CMSearchResult xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <numOfMatches>1</numOfMatches>
  <matchList>
    <matchElement>
      <sourceID>01</sourceID>
      <startTime>2026-01-15T10:00:00+00:00</startTime>
      <endTime>2026-01-15T10:00:30+00:00</endTime>
    </matchElement>
  </matchList>
</CMSearchResult>
"""
    # get_events calls list_cameras first if camera_name is given; we skip that
    post_resp = _mock_response(text=search_xml)
    adapter._client.post = AsyncMock(return_value=post_resp)

    events = await adapter.get_events(camera_id="1")

    assert len(events) == 1
    assert events[0].camera_id == "1"
    assert events[0].start_time.hour == 10


# ---------------------------------------------------------------------------
# _fmt_time helper
# ---------------------------------------------------------------------------


def test_fmt_time():
    from datetime import datetime

    dt = datetime(2026, 1, 15, 8, 30, 0)
    result = HikvisionAdapter._fmt_time(dt)
    assert result == "2026-01-15T08:30:00+00:00"


# ---------------------------------------------------------------------------
# _parse_isapi_time helper
# ---------------------------------------------------------------------------


def test_parse_isapi_time_standard():
    from datetime import datetime

    result = HikvisionAdapter._parse_isapi_time("2026-01-15T10:00:00+00:00")
    assert result.year == 2026
    assert result.month == 1
    assert result.day == 15
    assert result.hour == 10


def test_parse_isapi_time_z_suffix():
    result = HikvisionAdapter._parse_isapi_time("2026-06-01T14:30:00Z")
    assert result.year == 2026
    assert result.hour == 14


def test_parse_isapi_time_empty_returns_now():
    from datetime import datetime

    result = HikvisionAdapter._parse_isapi_time("")
    assert isinstance(result, datetime)
