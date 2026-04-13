"""
cctvQL Alert Rules Engine
--------------------------
Natural-language alert rules that trigger notifications when
CCTV events match configured conditions.

Example rules:
  "Notify me when a person is detected at the front door after 10pm"
  "Alert if any car enters the parking zone between 2am and 5am"
  "Send webhook when package detected on driveway camera"

Rules are stored in-memory (and optionally persisted to alerts.json).
A background task polls the active adapter every N seconds and fires
webhooks/callbacks when conditions are met.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default look-back window when polling for new events (seconds).
_LOOKBACK_SECONDS = 60


@dataclass
class AlertRule:
    """A single alert rule derived from a natural-language description."""

    id: str  # UUID
    name: str  # human-readable name
    description: str  # original natural language description
    camera_name: str | None  # None = all cameras
    label: str | None  # "person", "car", etc.
    zone: str | None  # zone filter
    time_start: str | None  # "22:00" HH:MM — window start
    time_end: str | None  # "06:00" HH:MM — window end (may wrap midnight)
    webhook_url: str | None  # POST JSON when triggered
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_triggered: datetime | None = None
    trigger_count: int = 0


class AlertEngine:
    """
    Background engine that polls the active CCTV adapter on a fixed interval,
    evaluates every enabled AlertRule against recent events, and fires webhooks
    when a rule matches.

    Args:
        adapter_registry: The AdapterRegistry class (not instance) — the engine
                          calls ``AdapterRegistry.get_active()`` on each poll so
                          it always targets the current active adapter.
        poll_interval:    Seconds between polls. Default 30.
    """

    def __init__(
        self,
        adapter_registry: type,  # type: AdapterRegistryType
        poll_interval: int = 30,
    ) -> None:
        self._registry = adapter_registry
        self._poll_interval = poll_interval
        self._rules: dict[str, AlertRule] = {}
        self._seen_event_ids: set[str] = set()
        self._task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_rule(self, rule: AlertRule) -> AlertRule:
        """Register a new alert rule and return it."""
        self._rules[rule.id] = rule
        logger.info("AlertEngine: added rule '%s' (%s)", rule.name, rule.id)
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        """Delete a rule by ID. Returns True if it existed."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            logger.info("AlertEngine: removed rule %s", rule_id)
            return True
        return False

    def get_rules(self) -> list[AlertRule]:
        """Return all rules, newest first."""
        return sorted(self._rules.values(), key=lambda r: r.created_at, reverse=True)

    def get_rule(self, rule_id: str) -> AlertRule | None:
        """Return a single rule by ID, or None."""
        return self._rules.get(rule_id)

    def update_rule(self, rule_id: str, **kwargs) -> AlertRule | None:
        """Patch fields on an existing rule. Returns the updated rule or None."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return None
        for key, value in kwargs.items():
            if hasattr(rule, key):
                setattr(rule, key, value)
        return rule

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="cctvql-alert-engine")
        logger.info(
            "AlertEngine started (poll_interval=%ds, rules=%d)",
            self._poll_interval,
            len(self._rules),
        )

    async def stop(self) -> None:
        """Stop the background polling loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AlertEngine stopped.")

    # ------------------------------------------------------------------
    # Internal polling logic
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Repeatedly call _check_rules until stopped."""
        while self._running:
            try:
                await self._check_rules()
            except Exception as exc:  # noqa: BLE001
                logger.error("AlertEngine poll error: %s", exc, exc_info=True)
            await asyncio.sleep(self._poll_interval)

    async def _check_rules(self) -> None:
        """
        Fetch events from the last _LOOKBACK_SECONDS window via the active
        adapter, then evaluate every enabled rule against each unseen event.
        """
        enabled_rules = [r for r in self._rules.values() if r.enabled]
        if not enabled_rules:
            return

        try:
            adapter = self._registry.get_active()
        except RuntimeError:
            logger.debug("AlertEngine: no active adapter configured, skipping poll.")
            return

        try:
            from datetime import timedelta

            since = datetime.now() - timedelta(seconds=_LOOKBACK_SECONDS + self._poll_interval)
            events = await adapter.get_events(start_time=since, limit=100)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AlertEngine: failed to fetch events: %s", exc)
            return

        for event in events:
            if event.id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event.id)

            for rule in enabled_rules:
                if self._event_matches_rule(rule, event):
                    await self._fire_alert(rule, event)

        # Prevent unbounded growth — keep only the last 10,000 event IDs.
        if len(self._seen_event_ids) > 10_000:
            # Discard oldest half (sets are unordered; this is a rough trim).
            trimmed = list(self._seen_event_ids)[5_000:]
            self._seen_event_ids = set(trimmed)

    async def _fire_alert(self, rule: AlertRule, event) -> None:
        """Send a webhook POST and update rule statistics."""
        rule.last_triggered = datetime.now()
        rule.trigger_count += 1

        payload = {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "event": {
                "id": event.id,
                "camera_name": event.camera_name,
                "camera_id": event.camera_id,
                "event_type": (
                    event.event_type.value
                    if hasattr(event.event_type, "value")
                    else str(event.event_type)
                ),
                "start_time": event.start_time.isoformat(),
                "end_time": event.end_time.isoformat() if event.end_time else None,
                "objects": [{"label": o.label, "confidence": o.confidence} for o in event.objects],
                "zones": event.zones,
                "snapshot_url": event.snapshot_url,
                "clip_url": event.clip_url,
            },
            "triggered_at": rule.last_triggered.isoformat(),
        }

        logger.info(
            "AlertEngine: rule '%s' triggered by event %s on %s",
            rule.name,
            event.id,
            event.camera_name,
        )

        if rule.webhook_url:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(rule.webhook_url, json=payload)
                    resp.raise_for_status()
                    logger.debug(
                        "AlertEngine: webhook delivered to %s (status %d)",
                        rule.webhook_url,
                        resp.status_code,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "AlertEngine: webhook delivery failed for rule '%s': %s",
                    rule.name,
                    exc,
                )

    # ------------------------------------------------------------------
    # Matching logic
    # ------------------------------------------------------------------

    def _event_matches_rule(self, rule: AlertRule, event) -> bool:
        """Return True if *event* satisfies all conditions in *rule*."""
        # Camera filter.
        if rule.camera_name and rule.camera_name.lower() not in event.camera_name.lower():
            return False

        # Label filter — check against detected objects.
        if rule.label:
            labels = [o.label.lower() for o in event.objects]
            if rule.label.lower() not in labels:
                return False

        # Zone filter.
        if rule.zone:
            zone_names = [z.lower() for z in event.zones]
            if rule.zone.lower() not in zone_names:
                return False

        # Time-window filter.
        if rule.time_start or rule.time_end:
            if not self._matches_time_window(rule, event):
                return False

        return True

    def _matches_time_window(self, rule: AlertRule, event) -> bool:
        """
        Return True if the event's start_time falls within the rule's
        [time_start, time_end] window.  The window may wrap midnight
        (e.g. "22:00" to "06:00").
        """
        event_time: time = event.start_time.time()

        start: time | None = _parse_hhmm(rule.time_start)
        end: time | None = _parse_hhmm(rule.time_end)

        if start is None and end is None:
            return True
        if start is None:
            # Only an end boundary: event must be before end.
            return event_time <= end  # type: ignore[operator]
        if end is None:
            # Only a start boundary: event must be after start.
            return event_time >= start

        # Both boundaries present.
        if start <= end:
            # Normal window, e.g. "08:00"–"18:00".
            return start <= event_time <= end
        else:
            # Wraps midnight, e.g. "22:00"–"06:00".
            return event_time >= start or event_time <= end


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_hhmm(value: str | None) -> time | None:
    """Parse a "HH:MM" string into a datetime.time, or return None."""
    if not value:
        return None
    try:
        parts = value.strip().split(":")
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        logger.warning("AlertEngine: could not parse time '%s'; ignoring.", value)
        return None


def make_rule_from_context(
    name: str,
    description: str,
    camera_name: str | None = None,
    label: str | None = None,
    zone: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    webhook_url: str | None = None,
) -> AlertRule:
    """
    Convenience factory used by the QueryRouter's set_alert handler to build
    an AlertRule from NLP-extracted fields.
    """
    return AlertRule(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        camera_name=camera_name,
        label=label,
        zone=zone,
        time_start=time_start,
        time_end=time_end,
        webhook_url=webhook_url,
    )
