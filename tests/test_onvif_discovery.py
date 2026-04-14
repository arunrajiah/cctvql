"""
Tests for ONVIF WS-Discovery (cctvql.adapters.onvif_discovery).

All tests are purely unit tests — no real network access.
The UDP socket is mocked so these work in any CI environment.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cctvql.adapters.onvif_discovery import (
    DiscoveredDevice,
    _extract_text_between,
    _parse_probe_match,
    discover_and_format,
    discover_onvif_devices,
)

# ---------------------------------------------------------------------------
# Sample WS-Discovery ProbeMatch XML (as a real camera would return)
# ---------------------------------------------------------------------------

PROBE_MATCH_SINGLE = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <s:Header>
    <a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</a:Action>
  </s:Header>
  <s:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <a:EndpointReference>
          <a:Address>urn:uuid:aabbccdd-1234-5678-abcd-000000000001</a:Address>
        </a:EndpointReference>
        <d:Types>dn:NetworkVideoTransmitter</d:Types>
        <d:Scopes>
          onvif://www.onvif.org/type/video_encoder
          onvif://www.onvif.org/hardware/DS-2CD2T43G2-2I
          onvif://www.onvif.org/name/FrontDoorCam
          onvif://www.onvif.org/location/city/london
        </d:Scopes>
        <d:XAddrs>http://192.168.1.101:80/onvif/device_service</d:XAddrs>
        <d:MetadataVersion>1</d:MetadataVersion>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </s:Body>
</s:Envelope>"""

PROBE_MATCH_MULTI = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <s:Body>
    <d:ProbeMatches>
      <d:ProbeMatch>
        <d:Types>dn:NetworkVideoTransmitter</d:Types>
        <d:Scopes>onvif://www.onvif.org/name/Camera1</d:Scopes>
        <d:XAddrs>http://192.168.1.201:80/onvif/device_service</d:XAddrs>
      </d:ProbeMatch>
      <d:ProbeMatch>
        <d:Types>dn:NetworkVideoTransmitter</d:Types>
        <d:Scopes>onvif://www.onvif.org/name/Camera2</d:Scopes>
        <d:XAddrs>http://192.168.1.202:8080/onvif/device_service</d:XAddrs>
      </d:ProbeMatch>
    </d:ProbeMatches>
  </s:Body>
</s:Envelope>"""

PROBE_MATCH_EMPTY = """<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body><d:ProbeMatches/></s:Body>
</s:Envelope>"""


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------


def test_extract_text_between_single():
    xml = "<d:XAddrs>http://192.168.1.101:80/onvif/device_service</d:XAddrs>"
    result = _extract_text_between(xml, "XAddrs")
    assert result == ["http://192.168.1.101:80/onvif/device_service"]


def test_extract_text_between_multiple():
    xml = "<Scopes>scope1 scope2</Scopes><Scopes>scope3</Scopes>"
    result = _extract_text_between(xml, "Scopes")
    assert len(result) == 2


def test_extract_text_between_missing():
    result = _extract_text_between("<Root/>", "XAddrs")
    assert result == []


# ---------------------------------------------------------------------------
# _parse_probe_match — single device
# ---------------------------------------------------------------------------


def test_parse_probe_match_single():
    devices = _parse_probe_match(PROBE_MATCH_SINGLE)
    assert len(devices) == 1
    d = devices[0]
    assert d.address == "http://192.168.1.101:80/onvif/device_service"
    assert "NetworkVideoTransmitter" in d.types
    assert any("FrontDoorCam" in s for s in d.scopes)


def test_parse_probe_match_name_from_scope():
    devices = _parse_probe_match(PROBE_MATCH_SINGLE)
    assert devices[0].name == "FrontDoorCam"


def test_parse_probe_match_hardware_from_scope():
    devices = _parse_probe_match(PROBE_MATCH_SINGLE)
    assert devices[0].hardware == "DS-2CD2T43G2-2I"


def test_parse_probe_match_host_port():
    devices = _parse_probe_match(PROBE_MATCH_SINGLE)
    d = devices[0]
    assert d.host == "192.168.1.101"
    assert d.port == 80


# ---------------------------------------------------------------------------
# _parse_probe_match — multiple devices
# ---------------------------------------------------------------------------


def test_parse_probe_match_multi():
    devices = _parse_probe_match(PROBE_MATCH_MULTI)
    assert len(devices) == 2
    names = {d.name for d in devices}
    assert "Camera1" in names
    assert "Camera2" in names


def test_parse_probe_match_multi_ports():
    devices = _parse_probe_match(PROBE_MATCH_MULTI)
    by_name = {d.name: d for d in devices}
    assert by_name["Camera2"].port == 8080


def test_parse_probe_match_empty():
    devices = _parse_probe_match(PROBE_MATCH_EMPTY)
    assert devices == []


# ---------------------------------------------------------------------------
# DiscoveredDevice — to_dict and fallback name
# ---------------------------------------------------------------------------


def test_discovered_device_to_dict():
    d = DiscoveredDevice(
        address="http://192.168.1.101:80/onvif/device_service",
        types=["NetworkVideoTransmitter"],
        scopes=["onvif://www.onvif.org/name/MyCam"],
    )
    data = d.to_dict()
    assert data["address"] == "http://192.168.1.101:80/onvif/device_service"
    assert data["host"] == "192.168.1.101"
    assert data["port"] == 80
    assert data["name"] == "MyCam"
    assert data["types"] == ["NetworkVideoTransmitter"]


def test_discovered_device_name_fallback_to_ip():
    """When no name scope is present, fall back to IP."""
    d = DiscoveredDevice(
        address="http://10.0.0.5:80/onvif/device_service",
        types=[],
        scopes=[],
    )
    assert d.name == "10.0.0.5"


def test_discovered_device_name_url_encoded():
    """Percent-encoded spaces in scope names are decoded."""
    d = DiscoveredDevice(
        address="http://10.0.0.6/onvif/device",
        types=[],
        scopes=["onvif://www.onvif.org/name/My%20Camera"],
    )
    assert d.name == "My Camera"


def test_discovered_device_no_hardware():
    d = DiscoveredDevice(address="http://10.0.0.7/onvif", types=[], scopes=[])
    assert d.hardware is None


# ---------------------------------------------------------------------------
# discover_onvif_devices — mocked UDP socket
# ---------------------------------------------------------------------------


def _make_mock_socket(responses: list[bytes]):
    """Build a mock socket that returns responses one-by-one then raises timeout."""

    mock_sock = MagicMock()
    mock_sock.__enter__ = lambda s: s
    mock_sock.__exit__ = MagicMock(return_value=False)

    recv_calls = iter(responses)

    def fake_recvfrom(size):
        try:
            return next(recv_calls), ("192.168.1.101", 3702)
        except StopIteration:
            raise TimeoutError()

    mock_sock.recvfrom.side_effect = fake_recvfrom
    return mock_sock


@pytest.mark.asyncio
async def test_discover_finds_one_device():
    with patch("cctvql.adapters.onvif_discovery.socket.socket") as mock_socket_cls:
        mock_sock = _make_mock_socket([PROBE_MATCH_SINGLE.encode()])
        mock_socket_cls.return_value = mock_sock

        devices = await discover_onvif_devices(timeout=0.1)

    assert len(devices) == 1
    assert devices[0].host == "192.168.1.101"
    assert devices[0].name == "FrontDoorCam"


@pytest.mark.asyncio
async def test_discover_deduplicates_same_address():
    """Receiving the same ProbeMatch twice should yield only one device."""
    same_response = PROBE_MATCH_SINGLE.encode()
    with patch("cctvql.adapters.onvif_discovery.socket.socket") as mock_socket_cls:
        mock_sock = _make_mock_socket([same_response, same_response])
        mock_socket_cls.return_value = mock_sock

        devices = await discover_onvif_devices(timeout=0.1)

    assert len(devices) == 1


@pytest.mark.asyncio
async def test_discover_empty_network():
    with patch("cctvql.adapters.onvif_discovery.socket.socket") as mock_socket_cls:
        mock_sock = _make_mock_socket([])
        mock_socket_cls.return_value = mock_sock

        devices = await discover_onvif_devices(timeout=0.1)

    assert devices == []


@pytest.mark.asyncio
async def test_discover_network_error_returns_empty():
    """OSError on socket creation should return empty list gracefully."""

    with patch("cctvql.adapters.onvif_discovery.socket.socket") as mock_socket_cls:
        mock_socket_cls.side_effect = OSError("Network unreachable")
        devices = await discover_onvif_devices(timeout=0.1)

    assert devices == []


@pytest.mark.asyncio
async def test_discover_and_format_returns_dicts():
    with patch("cctvql.adapters.onvif_discovery.socket.socket") as mock_socket_cls:
        mock_sock = _make_mock_socket([PROBE_MATCH_MULTI.encode()])
        mock_socket_cls.return_value = mock_sock

        result = await discover_and_format(timeout=0.1)

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(r, dict) for r in result)
    assert all("host" in r and "address" in r and "name" in r for r in result)
