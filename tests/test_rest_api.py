"""
Tests for the FastAPI REST API (cctvql.interfaces.rest_api).
Covers all endpoints including new wiring: health/cameras, events/export, PTZ,
session persistence, and notification bootstrap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cctvql.adapters.base import AdapterRegistry
from cctvql.adapters.demo import DemoAdapter
from cctvql.llm.base import LLMRegistry, LLMResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_registries():
    """Reset adapter + LLM registries and wire demo/mock before each test."""
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None

    adapter = DemoAdapter()
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("demo")

    mock_llm = MagicMock()
    mock_llm.name = "mock"
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"intent":"list_cameras","limit":20,"explanation":"list"}',
            model="mock",
        )
    )
    mock_llm.health_check = AsyncMock(return_value=True)
    LLMRegistry.register(mock_llm)
    LLMRegistry.set_active("mock")

    yield

    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None


@pytest.fixture
async def client():
    """Async httpx client wired to the FastAPI ASGI app."""
    import cctvql.interfaces.rest_api as api_module

    # Reset module-level state
    api_module._in_memory_sessions.clear()
    api_module._db = None
    api_module._session_store = None
    api_module._alert_engine = None
    api_module._health_monitor = None

    # Provide a running alert engine so alert endpoints work
    from cctvql.core.alerts import AlertEngine

    engine = AlertEngine(AdapterRegistry)
    await engine.start()
    api_module._alert_engine = engine

    # Provide a health monitor with empty state
    from cctvql.core.health_monitor import HealthMonitor
    from cctvql.notifications.registry import NotifierRegistry

    monitor = HealthMonitor(AdapterRegistry, NotifierRegistry, poll_interval=9999)
    await monitor.start()
    api_module._health_monitor = monitor

    transport = httpx.ASGITransport(app=api_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await engine.stop()
    await monitor.stop()
    api_module._in_memory_sessions.clear()


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert data["adapter"] == "demo"
    assert data["llm"] == "mock"
    assert "adapter_ok" in data
    assert "llm_ok" in data


async def test_camera_health_endpoint(client):
    resp = await client.get("/health/cameras")
    assert resp.status_code == 200
    # Monitor has no data yet (poll interval 9999s), so returns empty list
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Camera endpoints
# ---------------------------------------------------------------------------


async def test_list_cameras(client):
    resp = await client.get("/cameras")
    assert resp.status_code == 200
    cameras = resp.json()
    assert len(cameras) == 4
    cam = cameras[0]
    for field in ("id", "name", "status", "zones"):
        assert field in cam


async def test_ptz_move_unsupported_adapter(client):
    """Demo adapter returns False for PTZ — should get 501."""
    resp = await client.post("/cameras/cam_front_door/ptz", json={"action": "left", "speed": 50})
    assert resp.status_code == 501
    assert "not supported" in resp.json()["detail"].lower()


async def test_ptz_move_camera_not_found(client):
    resp = await client.post("/cameras/nonexistent_cam/ptz", json={"action": "left", "speed": 50})
    assert resp.status_code == 404


async def test_ptz_invalid_action(client):
    resp = await client.post("/cameras/cam_front_door/ptz", json={"action": "fly", "speed": 50})
    assert resp.status_code == 422


async def test_ptz_preset_no_preset_id(client):
    resp = await client.post("/cameras/cam_front_door/ptz", json={"action": "preset"})
    assert resp.status_code == 422


async def test_list_ptz_presets(client):
    resp = await client.get("/cameras/cam_front_door/ptz/presets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Events endpoints
# ---------------------------------------------------------------------------


async def test_get_events(client):
    resp = await client.get("/events")
    assert resp.status_code == 200
    events = resp.json()
    assert isinstance(events, list)
    assert len(events) > 0
    evt = events[0]
    for field in ("id", "camera", "type", "start_time", "objects"):
        assert field in evt


async def test_get_events_with_filters(client):
    resp = await client.get("/events", params={"camera": "Backyard", "limit": 5})
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) <= 5
    for evt in events:
        assert evt["camera"].lower() == "backyard"


async def test_export_events_csv(client):
    resp = await client.get("/events/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert "attachment" in resp.headers.get("content-disposition", "")
    # CSV should have header row
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("id,camera,type")
    assert len(lines) > 1  # header + at least one row


async def test_export_events_json(client):
    resp = await client.get("/events/export", params={"fmt": "json"})
    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


async def test_export_events_csv_filtered(client):
    resp = await client.get("/events/export", params={"camera": "Front Door", "label": "person"})
    assert resp.status_code == 200
    lines = resp.text.strip().splitlines()
    # All data rows should be Front Door
    for line in lines[1:]:
        assert "Front Door" in line


# ---------------------------------------------------------------------------
# Query endpoint
# ---------------------------------------------------------------------------


async def test_query_endpoint(client):
    resp = await client.post("/query", json={"query": "show me all cameras"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "intent" in data
    assert "session_id" in data


async def test_query_uses_session_id(client):
    resp = await client.post("/query", json={"query": "show cameras", "session_id": "my_session"})
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "my_session"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


async def test_clear_session(client):
    await client.post("/query", json={"query": "hi", "session_id": "sess_clear"})
    resp = await client.delete("/sessions/sess_clear")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cleared"


async def test_clear_nonexistent_session(client):
    """Clearing a session that doesn't exist should still return 200."""
    resp = await client.delete("/sessions/doesnt_exist")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------


async def test_list_alerts_empty(client):
    resp = await client.get("/alerts")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_and_get_alert(client):
    body = {
        "name": "Night Person Alert",
        "description": "Alert when person detected after 10pm",
        "camera_name": "Front Door",
        "label": "person",
        "time_start": "22:00",
        "time_end": "06:00",
        "webhook_url": "https://example.com/hook",
    }
    create_resp = await client.post("/alerts", json=body)
    assert create_resp.status_code == 201
    rule = create_resp.json()
    assert rule["name"] == "Night Person Alert"
    assert rule["camera_name"] == "Front Door"
    assert rule["enabled"] is True
    rule_id = rule["id"]

    get_resp = await client.get(f"/alerts/{rule_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == rule_id


async def test_update_alert_enabled(client):
    body = {"name": "Test Alert", "description": "test"}
    create = await client.post("/alerts", json=body)
    rule_id = create.json()["id"]

    patch_resp = await client.patch(f"/alerts/{rule_id}", json={"enabled": False})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["enabled"] is False


async def test_delete_alert(client):
    body = {"name": "Temp Alert", "description": "temp"}
    create = await client.post("/alerts", json=body)
    rule_id = create.json()["id"]

    del_resp = await client.delete(f"/alerts/{rule_id}")
    assert del_resp.status_code == 200

    get_resp = await client.get(f"/alerts/{rule_id}")
    assert get_resp.status_code == 404


async def test_get_nonexistent_alert(client):
    resp = await client.get("/alerts/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


async def test_metrics_endpoint(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "cctvql_queries_total" in text
    assert "cctvql_active_sessions" in text
    assert "cctvql_adapter_status" in text
    assert "cctvql_llm_status" in text
    assert "cctvql_cameras_online" in text
    assert "cctvql_cameras_offline" in text
    assert "cctvql_alert_rules_total" in text
    assert "text/plain" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Bootstrap notifications
# ---------------------------------------------------------------------------


def test_bootstrap_registers_webhook_notifier():
    from cctvql._bootstrap import _setup_notifications
    from cctvql.notifications.registry import NotifierRegistry

    NotifierRegistry.clear()
    _setup_notifications({"webhooks": [{"url": "http://test.local/hook"}]})
    assert len(NotifierRegistry.all()) == 1
    assert NotifierRegistry.all()[0].name == "webhook"
    NotifierRegistry.clear()


def test_bootstrap_registers_telegram_notifier():
    from cctvql._bootstrap import _setup_notifications
    from cctvql.notifications.registry import NotifierRegistry

    NotifierRegistry.clear()
    _setup_notifications({"telegram": {"bot_token": "123:abc", "chat_id": "-1001234"}})
    assert len(NotifierRegistry.all()) == 1
    assert NotifierRegistry.all()[0].name == "telegram"
    NotifierRegistry.clear()


def test_bootstrap_registers_slack_notifier():
    from cctvql._bootstrap import _setup_notifications
    from cctvql.notifications.registry import NotifierRegistry

    NotifierRegistry.clear()
    _setup_notifications({"slack": {"webhook_url": "https://hooks.slack.com/services/test"}})
    assert len(NotifierRegistry.all()) == 1
    assert NotifierRegistry.all()[0].name == "slack"
    NotifierRegistry.clear()


def test_bootstrap_registers_ntfy_notifier():
    from cctvql._bootstrap import _setup_notifications
    from cctvql.notifications.registry import NotifierRegistry

    NotifierRegistry.clear()
    _setup_notifications({"ntfy": {"topic": "my-alerts"}})
    assert len(NotifierRegistry.all()) == 1
    assert NotifierRegistry.all()[0].name == "ntfy"
    NotifierRegistry.clear()


def test_bootstrap_empty_notifications_does_nothing():
    from cctvql._bootstrap import _setup_notifications
    from cctvql.notifications.registry import NotifierRegistry

    NotifierRegistry.clear()
    _setup_notifications({})
    assert NotifierRegistry.all() == []


def test_bootstrap_multi_channel_registration():
    from cctvql._bootstrap import _setup_notifications
    from cctvql.notifications.registry import NotifierRegistry

    NotifierRegistry.clear()
    _setup_notifications(
        {
            "webhooks": [{"url": "https://a.example.com"}],
            "telegram": {"bot_token": "tok", "chat_id": "123"},
            "ntfy": {"topic": "alerts"},
        }
    )
    assert len(NotifierRegistry.all()) == 3
    NotifierRegistry.clear()


# ---------------------------------------------------------------------------
# Database / SessionStore wiring
# ---------------------------------------------------------------------------


async def test_session_store_wired_when_db_available():
    """When _session_store is set on the module, NLPEngine receives it."""
    import cctvql.interfaces.rest_api as api_module
    from cctvql.core.database import Database
    from cctvql.core.session_store import SessionStore

    # Simulate a wired session store
    db = Database(db_path=":memory:")
    await db.connect()
    store = SessionStore(db)
    api_module._session_store = store
    api_module._in_memory_sessions.clear()

    nlp = api_module._get_nlp_for_session("test_wired")
    assert nlp._session_store is store

    await db.disconnect()
    api_module._session_store = None
    api_module._in_memory_sessions.clear()


async def test_session_store_none_when_db_unavailable():
    """When _session_store is None, NLPEngine is created without one."""
    import cctvql.interfaces.rest_api as api_module

    api_module._session_store = None
    api_module._in_memory_sessions.clear()

    nlp = api_module._get_nlp_for_session("test_no_db")
    assert nlp._session_store is None

    api_module._in_memory_sessions.clear()
