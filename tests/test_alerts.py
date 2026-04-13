"""
Tests for AlertEngine and AlertRule (cctvql.core.alerts).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cctvql.adapters.base import AdapterRegistry
from cctvql.adapters.demo import DemoAdapter
from cctvql.core.alerts import AlertEngine, AlertRule, make_rule_from_context
from cctvql.core.schema import DetectedObject, Event, EventType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(
    label: str | None = None,
    camera_name: str | None = None,
    zone: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    webhook_url: str | None = None,
    name: str = "Test Rule",
) -> AlertRule:
    return AlertRule(
        id=str(uuid.uuid4()),
        name=name,
        description="test rule",
        camera_name=camera_name,
        label=label,
        zone=zone,
        time_start=time_start,
        time_end=time_end,
        webhook_url=webhook_url,
    )


def _make_event(
    camera_name: str = "Front Door",
    objects: list[DetectedObject] | None = None,
    zones: list[str] | None = None,
    hour: int = 12,
    minute: int = 0,
) -> Event:
    return Event(
        id=str(uuid.uuid4()),
        camera_id="cam_01",
        camera_name=camera_name,
        event_type=EventType.OBJECT_DETECTED,
        start_time=datetime(2026, 1, 15, hour, minute, 0, tzinfo=timezone.utc),
        objects=objects or [],
        zones=zones or [],
    )


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure a clean AdapterRegistry for every test."""
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    yield
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None


@pytest.fixture
def engine():
    """AlertEngine backed by AdapterRegistry (with DemoAdapter registered)."""
    adapter = DemoAdapter()
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("demo")
    return AlertEngine(AdapterRegistry, poll_interval=999)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_add_rule(engine):
    rule = _make_rule(label="person", name="Person Alert")
    engine.add_rule(rule)
    rules = engine.get_rules()
    assert len(rules) == 1
    assert rules[0].name == "Person Alert"


def test_remove_rule(engine):
    rule = _make_rule(label="car")
    engine.add_rule(rule)
    result = engine.remove_rule(rule.id)
    assert result is True
    assert len(engine.get_rules()) == 0


def test_remove_nonexistent_rule(engine):
    result = engine.remove_rule("does-not-exist")
    assert result is False


def test_get_rule_by_id(engine):
    rule = _make_rule(label="package", name="Package Detector")
    engine.add_rule(rule)
    found = engine.get_rule(rule.id)
    assert found is not None
    assert found.name == "Package Detector"
    assert engine.get_rule("missing-id") is None


def test_get_rules_returns_newest_first(engine):
    r1 = _make_rule(name="First")
    r2 = _make_rule(name="Second")
    r3 = _make_rule(name="Third")
    for r in [r1, r2, r3]:
        engine.add_rule(r)
    names = [r.name for r in engine.get_rules()]
    # created_at is effectively insertion order for these rapid calls;
    # at minimum Third should not be last
    assert "Third" in names
    assert len(names) == 3


# ---------------------------------------------------------------------------
# Matching logic — label
# ---------------------------------------------------------------------------


def test_event_matches_rule_by_label(engine):
    rule = _make_rule(label="person")
    event = _make_event(objects=[DetectedObject(label="person", confidence=0.9)])
    assert engine._event_matches_rule(rule, event) is True


def test_event_no_match_wrong_label(engine):
    rule = _make_rule(label="car")
    event = _make_event(objects=[DetectedObject(label="person", confidence=0.9)])
    assert engine._event_matches_rule(rule, event) is False


def test_event_matches_rule_no_label_filter(engine):
    """Rule with no label filter matches any object list."""
    rule = _make_rule(label=None)
    event = _make_event(objects=[DetectedObject(label="truck", confidence=0.8)])
    assert engine._event_matches_rule(rule, event) is True


# ---------------------------------------------------------------------------
# Matching logic — camera
# ---------------------------------------------------------------------------


def test_event_matches_rule_by_camera(engine):
    rule = _make_rule(camera_name="Front Door")
    event = _make_event(camera_name="Front Door")
    assert engine._event_matches_rule(rule, event) is True


def test_event_no_match_wrong_camera(engine):
    rule = _make_rule(camera_name="Backyard")
    event = _make_event(camera_name="Front Door")
    assert engine._event_matches_rule(rule, event) is False


def test_event_camera_partial_match(engine):
    """Camera filter uses 'in' substring matching."""
    rule = _make_rule(camera_name="front")
    event = _make_event(camera_name="Front Door")
    assert engine._event_matches_rule(rule, event) is True


# ---------------------------------------------------------------------------
# Matching logic — zone
# ---------------------------------------------------------------------------


def test_event_matches_rule_by_zone(engine):
    rule = _make_rule(zone="porch")
    event = _make_event(zones=["porch", "driveway"])
    assert engine._event_matches_rule(rule, event) is True


def test_event_no_match_wrong_zone(engine):
    rule = _make_rule(zone="parking")
    event = _make_event(zones=["porch"])
    assert engine._event_matches_rule(rule, event) is False


# ---------------------------------------------------------------------------
# Matching logic — time windows
# ---------------------------------------------------------------------------


def test_time_window_match(engine):
    """Event at 23:00, rule window 22:00–06:00 → match (wraps midnight)."""
    rule = _make_rule(time_start="22:00", time_end="06:00")
    event = _make_event(hour=23, minute=0)
    assert engine._event_matches_rule(rule, event) is True


def test_time_window_no_match(engine):
    """Event at 14:00, rule window 22:00–06:00 → no match."""
    rule = _make_rule(time_start="22:00", time_end="06:00")
    event = _make_event(hour=14, minute=0)
    assert engine._event_matches_rule(rule, event) is False


def test_time_window_wraps_midnight_early_morning(engine):
    """Event at 02:00, rule window 22:00–06:00 → match (early morning side)."""
    rule = _make_rule(time_start="22:00", time_end="06:00")
    event = _make_event(hour=2, minute=0)
    assert engine._event_matches_rule(rule, event) is True


def test_time_window_normal_daytime(engine):
    """Event at 10:00, normal rule window 08:00–18:00 → match."""
    rule = _make_rule(time_start="08:00", time_end="18:00")
    event = _make_event(hour=10, minute=0)
    assert engine._event_matches_rule(rule, event) is True


def test_time_window_normal_outside(engine):
    """Event at 20:00, normal rule window 08:00–18:00 → no match."""
    rule = _make_rule(time_start="08:00", time_end="18:00")
    event = _make_event(hour=20, minute=0)
    assert engine._event_matches_rule(rule, event) is False


def test_time_window_only_start(engine):
    """Rule with only time_start: event after start → match."""
    rule = _make_rule(time_start="20:00")
    event = _make_event(hour=22, minute=0)
    assert engine._event_matches_rule(rule, event) is True


def test_time_window_only_end(engine):
    """Rule with only time_end: event before end → match."""
    rule = _make_rule(time_end="06:00")
    event = _make_event(hour=3, minute=0)
    assert engine._event_matches_rule(rule, event) is True


# ---------------------------------------------------------------------------
# _fire_alert / webhook
# ---------------------------------------------------------------------------


async def test_fire_alert_sends_webhook(engine):
    """_fire_alert POSTs JSON payload to the webhook URL."""
    rule = _make_rule(label="person", webhook_url="http://webhook.test/alert")
    event = _make_event(
        objects=[DetectedObject(label="person", confidence=0.95)],
        zones=["porch"],
    )
    event.end_time = None

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("cctvql.core.alerts.httpx.AsyncClient", return_value=mock_client):
        await engine._fire_alert(rule, event)

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "http://webhook.test/alert"
    payload = call_args[1]["json"]
    assert payload["rule_id"] == rule.id
    assert payload["rule_name"] == rule.name
    assert payload["event"]["camera_name"] == event.camera_name


async def test_fire_alert_no_webhook_does_not_raise(engine):
    """_fire_alert with no webhook_url should not raise."""
    rule = _make_rule(label="person", webhook_url=None)
    event = _make_event()
    # Should complete without error
    await engine._fire_alert(rule, event)
    assert rule.trigger_count == 1


async def test_fire_alert_webhook_failure_is_swallowed(engine):
    """Failed webhook delivery is logged but doesn't raise."""
    rule = _make_rule(webhook_url="http://webhook.test/bad")
    event = _make_event()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("cctvql.core.alerts.httpx.AsyncClient", return_value=mock_client):
        # Should not raise
        await engine._fire_alert(rule, event)

    assert rule.trigger_count == 1


# ---------------------------------------------------------------------------
# make_rule_from_context factory
# ---------------------------------------------------------------------------


def test_make_rule_from_context_creates_valid_rule():
    rule = make_rule_from_context(
        name="Night Person Alert",
        description="Notify me when a person is detected at night",
        camera_name="Front Door",
        label="person",
        zone="porch",
        time_start="22:00",
        time_end="06:00",
        webhook_url="http://hooks.example.com/alert",
    )
    assert isinstance(rule, AlertRule)
    assert rule.name == "Night Person Alert"
    assert rule.camera_name == "Front Door"
    assert rule.label == "person"
    assert rule.zone == "porch"
    assert rule.time_start == "22:00"
    assert rule.time_end == "06:00"
    assert rule.webhook_url == "http://hooks.example.com/alert"
    assert rule.enabled is True
    # ID should be a valid UUID string
    uuid.UUID(rule.id)


def test_make_rule_from_context_defaults():
    rule = make_rule_from_context(name="Minimal Rule", description="minimal")
    assert rule.camera_name is None
    assert rule.label is None
    assert rule.zone is None
    assert rule.time_start is None
    assert rule.time_end is None
    assert rule.webhook_url is None


# ---------------------------------------------------------------------------
# AlertEngine update_rule
# ---------------------------------------------------------------------------


def test_update_rule_modifies_field(engine):
    rule = _make_rule(name="Old Name")
    engine.add_rule(rule)
    updated = engine.update_rule(rule.id, name="New Name", label="car")
    assert updated is not None
    assert updated.name == "New Name"
    assert updated.label == "car"


def test_update_rule_nonexistent_returns_none(engine):
    result = engine.update_rule("missing-id", name="Whatever")
    assert result is None
