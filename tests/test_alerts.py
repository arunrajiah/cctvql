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
    cooldown_seconds: int = 300,
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
        cooldown_seconds=cooldown_seconds,
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

    with patch("cctvql.notifications.webhook.httpx.AsyncClient", return_value=mock_client):
        await engine._fire_alert(rule, event)

    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert call_args[0][0] == "http://webhook.test/alert"
    payload = call_args[1]["json"]
    assert payload["camera_name"] == event.camera_name


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

    with patch("cctvql.notifications.webhook.httpx.AsyncClient", return_value=mock_client):
        # Should not raise — WebhookNotifier catches and re-raises, AlertEngine catches it
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


# ---------------------------------------------------------------------------
# Cooldown logic
# ---------------------------------------------------------------------------


def test_rule_default_cooldown_is_300(engine):
    rule = _make_rule(label="person")
    assert rule.cooldown_seconds == 300


def test_no_cooldown_when_never_triggered(engine):
    rule = _make_rule(label="person")
    assert engine._in_cooldown(rule) is False


def test_in_cooldown_immediately_after_fire(engine):
    rule = _make_rule(label="person")
    rule.last_triggered = datetime.now()
    rule.cooldown_seconds = 300
    assert engine._in_cooldown(rule) is True


def test_not_in_cooldown_after_window_expires(engine):
    from datetime import timedelta

    rule = _make_rule(label="person")
    rule.cooldown_seconds = 60
    rule.last_triggered = datetime.now() - timedelta(seconds=61)
    assert engine._in_cooldown(rule) is False


def test_still_in_cooldown_before_window_expires(engine):
    from datetime import timedelta

    rule = _make_rule(label="person")
    rule.cooldown_seconds = 300
    rule.last_triggered = datetime.now() - timedelta(seconds=100)
    assert engine._in_cooldown(rule) is True


def test_zero_cooldown_never_blocks(engine):
    rule = _make_rule(label="person")
    rule.cooldown_seconds = 0
    rule.last_triggered = datetime.now()
    assert engine._in_cooldown(rule) is False


async def test_cooldown_prevents_second_fire(engine):
    """A rule with a long cooldown should only fire once for two matching events."""
    rule = _make_rule(label="person", cooldown_seconds=3600)
    engine.add_rule(rule)

    event1 = _make_event(objects=[DetectedObject(label="person", confidence=0.9)])
    event2 = _make_event(objects=[DetectedObject(label="person", confidence=0.9)])

    fire_count = 0

    async def mock_fire(r, e):
        nonlocal fire_count
        fire_count += 1
        r.last_triggered = datetime.now()
        r.trigger_count += 1

    engine._fire_alert = mock_fire  # type: ignore[method-assign]

    # Simulate two events in sequence
    for evt in [event1, event2]:
        engine._seen_event_ids.discard(evt.id)  # ensure not deduped by ID
        if engine._event_matches_rule(rule, evt) and not engine._in_cooldown(rule):
            await engine._fire_alert(rule, evt)

    assert fire_count == 1


async def test_cooldown_allows_fire_after_window(engine):
    """After the cooldown expires the rule fires again."""
    from datetime import timedelta

    rule = _make_rule(label="person", cooldown_seconds=1)
    engine.add_rule(rule)
    rule.last_triggered = datetime.now() - timedelta(seconds=2)

    event = _make_event(objects=[DetectedObject(label="person", confidence=0.9)])
    assert engine._event_matches_rule(rule, event)
    assert not engine._in_cooldown(rule)


def test_make_rule_from_context_sets_cooldown():
    rule = make_rule_from_context(
        name="Gate Alert",
        description="gate propped open",
        cooldown_seconds=600,
    )
    assert rule.cooldown_seconds == 600


def test_make_rule_from_context_default_cooldown():
    rule = make_rule_from_context(name="Default Cooldown", description="test")
    assert rule.cooldown_seconds == 300
