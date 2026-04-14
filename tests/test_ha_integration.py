"""
Tests for the cctvQL Home Assistant custom integration.

Tests the CctvqlClient (coordinator.py) in isolation using respx to mock
HTTP responses — no Home Assistant installation required.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub homeassistant modules so we can import the integration without HA
# ---------------------------------------------------------------------------
_HA_STUBS = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.data_entry_flow",
    "voluptuous",
]
for _stub in _HA_STUBS:
    if _stub not in sys.modules:
        sys.modules[_stub] = MagicMock()

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402

from custom_components.cctvql.const import DOMAIN, PTZ_ACTIONS  # noqa: E402
from custom_components.cctvql.coordinator import CctvqlClient  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = "http://localhost:8000"

HEALTH_PAYLOAD = {
    "status": "ok",
    "adapter": "demo",
    "llm": "mock",
    "adapter_ok": True,
    "llm_ok": True,
}

CAMERAS_PAYLOAD = [
    {"id": "cam_front_door", "name": "Front Door", "status": "online", "zones": ["porch"]},
    {"id": "cam_backyard", "name": "Backyard", "status": "online", "zones": []},
]

CAMERA_HEALTH_PAYLOAD = [
    {
        "camera_id": "cam_front_door",
        "camera_name": "Front Door",
        "status": "online",
        "latency_ms": 42,
    },
    {
        "camera_id": "cam_backyard",
        "camera_name": "Backyard",
        "status": "online",
        "latency_ms": 37,
    },
]

EVENTS_PAYLOAD = [
    {
        "id": "evt_001",
        "camera": "Front Door",
        "type": "object_detected",
        "start_time": "2026-04-14T09:00:00",
        "objects": [{"label": "person", "confidence": 0.94}],
        "zones": ["porch"],
        "snapshot_url": None,
        "clip_url": None,
    }
]

QUERY_PAYLOAD = {
    "answer": "Yes — 1 person detected.",
    "intent": "get_events",
    "session_id": "homeassistant",
}


# ---------------------------------------------------------------------------
# CctvqlClient — basic HTTP fetching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_client_health():
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json=HEALTH_PAYLOAD))
    client = CctvqlClient("localhost", 8000)
    result = await client.health()
    assert result["status"] == "ok"
    assert result["adapter"] == "demo"


@pytest.mark.asyncio
@respx.mock
async def test_client_cameras():
    respx.get(f"{BASE}/cameras").mock(return_value=httpx.Response(200, json=CAMERAS_PAYLOAD))
    client = CctvqlClient("localhost", 8000)
    cameras = await client.cameras()
    assert len(cameras) == 2
    assert cameras[0]["name"] == "Front Door"


@pytest.mark.asyncio
@respx.mock
async def test_client_camera_health():
    respx.get(f"{BASE}/health/cameras").mock(
        return_value=httpx.Response(200, json=CAMERA_HEALTH_PAYLOAD)
    )
    client = CctvqlClient("localhost", 8000)
    result = await client.camera_health()
    assert len(result) == 2
    assert all(c["status"] == "online" for c in result)


@pytest.mark.asyncio
@respx.mock
async def test_client_events():
    respx.get(f"{BASE}/events").mock(return_value=httpx.Response(200, json=EVENTS_PAYLOAD))
    client = CctvqlClient("localhost", 8000)
    events = await client.events()
    assert len(events) == 1
    assert events[0]["camera"] == "Front Door"


@pytest.mark.asyncio
@respx.mock
async def test_client_fetch_all():
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json=HEALTH_PAYLOAD))
    respx.get(f"{BASE}/cameras").mock(return_value=httpx.Response(200, json=CAMERAS_PAYLOAD))
    respx.get(f"{BASE}/health/cameras").mock(
        return_value=httpx.Response(200, json=CAMERA_HEALTH_PAYLOAD)
    )
    respx.get(f"{BASE}/events").mock(return_value=httpx.Response(200, json=EVENTS_PAYLOAD))

    client = CctvqlClient("localhost", 8000)
    data = await client.fetch_all()

    assert "health" in data
    assert "cameras" in data
    assert "camera_health" in data
    assert "events" in data
    assert data["health"]["status"] == "ok"
    assert len(data["cameras"]) == 2


# ---------------------------------------------------------------------------
# API key header forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_client_sends_api_key_header():
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json=HEALTH_PAYLOAD)
    )
    client = CctvqlClient("localhost", 8000, api_key="secret-key")
    await client.health()
    assert route.called
    assert route.calls[0].request.headers.get("x-api-key") == "secret-key"


@pytest.mark.asyncio
@respx.mock
async def test_client_no_api_key_when_not_set():
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json=HEALTH_PAYLOAD)
    )
    client = CctvqlClient("localhost", 8000)
    await client.health()
    assert "x-api-key" not in route.calls[0].request.headers


# ---------------------------------------------------------------------------
# Query service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_client_query():
    route = respx.post(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json=QUERY_PAYLOAD)
    )
    client = CctvqlClient("localhost", 8000)
    result = await client.query("Any motion today?")
    assert result["answer"] == "Yes — 1 person detected."
    assert result["intent"] == "get_events"
    body = route.calls[0].request.content
    import json
    payload = json.loads(body)
    assert payload["query"] == "Any motion today?"
    assert payload["session_id"] == "homeassistant"


@pytest.mark.asyncio
@respx.mock
async def test_client_query_custom_session():
    route = respx.post(f"{BASE}/query").mock(
        return_value=httpx.Response(200, json=QUERY_PAYLOAD)
    )
    client = CctvqlClient("localhost", 8000)
    await client.query("Show cameras", session_id="my-session")
    import json
    payload = json.loads(route.calls[0].request.content)
    assert payload["session_id"] == "my-session"


# ---------------------------------------------------------------------------
# PTZ
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_client_ptz_left():
    route = respx.post(f"{BASE}/cameras/cam_front_door/ptz").mock(
        return_value=httpx.Response(200, json={"status": "ok", "action": "left"})
    )
    client = CctvqlClient("localhost", 8000)
    result = await client.ptz("cam_front_door", action="left", speed=30)
    assert result["status"] == "ok"
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "left"
    assert body["speed"] == 30


@pytest.mark.asyncio
@respx.mock
async def test_client_ptz_preset():
    route = respx.post(f"{BASE}/cameras/cam_front_door/ptz").mock(
        return_value=httpx.Response(200, json={"status": "ok", "action": "preset"})
    )
    client = CctvqlClient("localhost", 8000)
    await client.ptz("cam_front_door", action="preset", preset_id=2)
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "preset"
    assert body["preset_id"] == 2


# ---------------------------------------------------------------------------
# Clear session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_client_clear_session():
    route = respx.delete(f"{BASE}/sessions/homeassistant").mock(
        return_value=httpx.Response(200, json={"status": "cleared", "session_id": "homeassistant"})
    )
    client = CctvqlClient("localhost", 8000)
    result = await client.clear_session()
    assert result["status"] == "cleared"
    assert route.called


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_client_http_error_raises():
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(503))
    client = CctvqlClient("localhost", 8000)
    with pytest.raises(httpx.HTTPStatusError):
        await client.health()


@pytest.mark.asyncio
@respx.mock
async def test_client_connection_error_raises():
    respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("refused"))
    client = CctvqlClient("localhost", 8000)
    with pytest.raises(httpx.ConnectError):
        await client.health()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_ptz_actions_complete():
    """All expected PTZ actions are present in the constant."""
    expected = {"left", "right", "up", "down", "zoom_in", "zoom_out", "home", "preset"}
    assert expected == set(PTZ_ACTIONS)


def test_domain_constant():
    assert DOMAIN == "cctvql"
