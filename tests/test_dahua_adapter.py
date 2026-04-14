"""
Tests for DahuaAdapter (cctvql.adapters.dahua).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.dahua import DahuaAdapter, _parse_dahua

# ---------------------------------------------------------------------------
# HTTP mock helper
# ---------------------------------------------------------------------------


def _mock_text_response(text: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# Sample responses
# ---------------------------------------------------------------------------

_DEVICE_TYPE_RESPONSE = "table.DeviceType=NVR4104"
_SOFTWARE_VERSION_RESPONSE = "table.SoftwareVersion=V2.820.00KI003.0"
_RECORD_FINDER_RESPONSE = """\
found=2
records[0].Channel=1
records[0].StartTime=2026-01-15 08:00:00
records[0].EndTime=2026-01-15 08:05:00
records[0].FilePath=/mnt/dvr/2026-01-15/08.00.00-08.05.00[M][0@0][0].dav
records[0].Size=12345678
records[1].Channel=2
records[1].StartTime=2026-01-15 09:00:00
records[1].EndTime=2026-01-15 09:03:00
records[1].FilePath=/mnt/dvr/2026-01-15/09.00.00-09.03.00[M][0@0][0].dav
records[1].Size=7654321
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter():
    return DahuaAdapter(
        host="192.168.1.108",
        port=80,
        username="admin",
        password="test_pass",
        channel_count=4,
    )


# ---------------------------------------------------------------------------
# name property
# ---------------------------------------------------------------------------


def test_name_property(adapter):
    assert adapter.name == "dahua"


# ---------------------------------------------------------------------------
# _parse_dahua module-level helper
# ---------------------------------------------------------------------------


def test_parse_dahua_helper_basic():
    text = "table.DeviceType=NVR4104HS-P-4KS3\ntable.SoftwareVersion=V2.820.00KI003.0\nError.Code=0"
    result = _parse_dahua(text)
    assert result["table.DeviceType"] == "NVR4104HS-P-4KS3"
    assert result["table.SoftwareVersion"] == "V2.820.00KI003.0"
    assert result["Error.Code"] == "0"


def test_parse_dahua_helper_ignores_comments_and_blanks():
    text = "# this is a comment\n\nkey=value\n"
    result = _parse_dahua(text)
    assert list(result.keys()) == ["key"]
    assert result["key"] == "value"


def test_parse_dahua_helper_value_with_equals():
    """Values that contain '=' should preserve everything after the first '='."""
    text = "url=http://example.com/path?a=1&b=2"
    result = _parse_dahua(text)
    assert result["url"] == "http://example.com/path?a=1&b=2"


def test_parse_dahua_helper_empty_input():
    result = _parse_dahua("")
    assert result == {}


def test_parse_dahua_helper_strips_whitespace():
    text = "  key  =  value  "
    result = _parse_dahua(text)
    assert result["key"] == "value"


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


async def test_connect_success(adapter):
    resp = _mock_text_response(_DEVICE_TYPE_RESPONSE)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.connect()

    assert result is True
    adapter._client.get.assert_called_once()


async def test_connect_success_populates_device_type(adapter):
    resp = _mock_text_response(_DEVICE_TYPE_RESPONSE)
    adapter._client.get = AsyncMock(return_value=resp)

    await adapter.connect()

    # _device_type should be populated from the response
    assert "NVR4104" in adapter._device_type or adapter._device_type != ""


async def test_connect_failure(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("connection refused"))

    result = await adapter.connect()

    assert result is False


async def test_connect_http_error(adapter):
    resp = _mock_text_response("Unauthorized", status_code=401)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.connect()

    assert result is False


# ---------------------------------------------------------------------------
# get_snapshot_url
# ---------------------------------------------------------------------------


async def test_get_snapshot_url_returns_correct_url_by_id(adapter):
    url = await adapter.get_snapshot_url(camera_id="2")

    assert url is not None
    assert "snapshot.cgi" in url
    assert "channel=2" in url
    assert adapter.base_url in url


async def test_get_snapshot_url_defaults_to_channel_1(adapter):
    url = await adapter.get_snapshot_url()

    assert url is not None
    assert "channel=1" in url


async def test_get_snapshot_url_by_name(adapter):
    """Resolves by name: mocks list_cameras via channel probing."""
    # list_cameras probes snapshot URLs per channel; mock all as 200
    snapshot_resp = _mock_text_response("", status_code=200)
    adapter._client.get = AsyncMock(return_value=snapshot_resp)

    url = await adapter.get_snapshot_url(camera_name="Channel 2")

    assert url is not None
    assert "channel=2" in url


# ---------------------------------------------------------------------------
# get_system_info
# ---------------------------------------------------------------------------


async def test_get_system_info_parses_response(adapter):
    type_resp = _mock_text_response(_DEVICE_TYPE_RESPONSE)
    ver_resp = _mock_text_response(_SOFTWARE_VERSION_RESPONSE)
    adapter._client.get = AsyncMock(side_effect=[type_resp, ver_resp])

    info = await adapter.get_system_info()

    assert info is not None
    assert "NVR4104" in info.system_name
    assert info.version is not None
    assert "V2.820" in info.version
    assert info.camera_count == 4  # matches channel_count


async def test_get_system_info_returns_none_on_error(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("timeout"))

    info = await adapter.get_system_info()

    assert info is None


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


async def test_health_check_ok(adapter):
    resp = _mock_text_response(_DEVICE_TYPE_RESPONSE, status_code=200)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.health_check()

    assert result is True


async def test_health_check_fail_exception(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("timeout"))

    result = await adapter.health_check()

    assert result is False


async def test_health_check_fail_bad_status(adapter):
    resp = _mock_text_response("error", status_code=503)
    adapter._client.get = AsyncMock(return_value=resp)

    result = await adapter.health_check()

    assert result is False


# ---------------------------------------------------------------------------
# get_events
# ---------------------------------------------------------------------------


async def test_get_events_parses_records(adapter):
    resp = _mock_text_response(_RECORD_FINDER_RESPONSE)
    adapter._client.get = AsyncMock(return_value=resp)

    events = await adapter.get_events()

    assert len(events) == 2
    assert events[0].camera_id == "1"
    assert events[0].start_time.hour == 8
    assert events[1].camera_id == "2"
    assert events[1].start_time.hour == 9


async def test_get_events_returns_empty_on_failure(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("network error"))

    events = await adapter.get_events()

    assert events == []


async def test_get_events_respects_limit(adapter):
    resp = _mock_text_response(_RECORD_FINDER_RESPONSE)
    adapter._client.get = AsyncMock(return_value=resp)

    events = await adapter.get_events(limit=1)

    assert len(events) <= 1


# ---------------------------------------------------------------------------
# get_clips
# ---------------------------------------------------------------------------


async def test_get_clips_parses_records(adapter):
    resp = _mock_text_response(_RECORD_FINDER_RESPONSE)
    adapter._client.get = AsyncMock(return_value=resp)

    clips = await adapter.get_clips()

    assert len(clips) == 2
    assert clips[0].download_url is not None
    assert "RPC_Loadfile" in clips[0].download_url
    assert clips[0].size_bytes == 12345678


async def test_get_clips_returns_empty_on_failure(adapter):
    adapter._client.get = AsyncMock(side_effect=Exception("timeout"))

    clips = await adapter.get_clips()

    assert clips == []


# ---------------------------------------------------------------------------
# _parse_record_finder helper
# ---------------------------------------------------------------------------


def test_parse_record_finder_static():
    records = DahuaAdapter._parse_record_finder(_RECORD_FINDER_RESPONSE)
    assert len(records) == 2
    assert records[0]["Channel"] == "1"
    assert records[0]["StartTime"] == "2026-01-15 08:00:00"
    assert records[0]["FilePath"].endswith(".dav")
    assert records[1]["Channel"] == "2"


def test_parse_record_finder_empty():
    records = DahuaAdapter._parse_record_finder("found=0\n")
    assert records == []


# ---------------------------------------------------------------------------
# host normalisation
# ---------------------------------------------------------------------------


def test_host_normalisation_strips_scheme():
    adapter = DahuaAdapter(host="http://192.168.1.10", port=8080)
    assert adapter.host == "192.168.1.10"
    assert adapter.base_url == "http://192.168.1.10:8080"


def test_host_normalisation_no_scheme():
    adapter = DahuaAdapter(host="192.168.1.10", port=80)
    assert adapter.host == "192.168.1.10"
    assert adapter.base_url == "http://192.168.1.10:80"


# ---------------------------------------------------------------------------
# _parse_dahua_time helper
# ---------------------------------------------------------------------------


def test_parse_dahua_time_standard_format():
    result = DahuaAdapter._parse_dahua_time("2026-01-15 08:30:00")
    assert result.year == 2026
    assert result.hour == 8
    assert result.minute == 30


def test_parse_dahua_time_iso_format():
    result = DahuaAdapter._parse_dahua_time("2026-01-15T08:30:00")
    assert result.year == 2026
    assert result.hour == 8


def test_parse_dahua_time_empty_returns_datetime():
    from datetime import datetime

    result = DahuaAdapter._parse_dahua_time("")
    assert isinstance(result, datetime)
