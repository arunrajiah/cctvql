"""
cctvQL Camera Health Monitor
------------------------------
Periodically probes all registered adapters to check camera reachability,
updates health status, and fires notifications on status transitions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Latency threshold above which a camera is considered DEGRADED (ms)
_DEGRADED_LATENCY_MS = 5000.0


class HealthStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class CameraHealth:
    """Health record for a single camera."""

    adapter_name: str
    camera_name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: datetime | None = None
    last_seen_online: datetime | None = None
    consecutive_failures: int = 0
    latency_ms: float | None = None
    extra: dict = field(default_factory=dict)


class HealthMonitor:
    """
    Background service that polls all registered adapters for camera health.

    Args:
        adapter_registry: The AdapterRegistry class.
        notifier_registry: The NotifierRegistry class.
        poll_interval:    Seconds between polling cycles (default: 60).
    """

    def __init__(
        self,
        adapter_registry: Any,
        notifier_registry: Any,
        poll_interval: int = 60,
    ) -> None:
        self._registry = adapter_registry
        self._notifiers = notifier_registry
        self._interval = poll_interval
        self._health: dict[str, CameraHealth] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background health-check polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="cctvql-health-monitor")
        logger.info("HealthMonitor started (poll_interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("HealthMonitor stopped.")

    async def _poll_loop(self) -> None:
        """Repeat health checks every self._interval seconds."""
        while self._running:
            try:
                await self._check_all()
            except Exception as exc:
                logger.error("HealthMonitor poll error: %s", exc, exc_info=True)
            await asyncio.sleep(self._interval)

    async def _check_all(self) -> None:
        """Check all adapters and cameras."""
        adapters = {}
        try:
            # Collect all registered adapters
            if hasattr(self._registry, "_adapters"):
                adapters = dict(self._registry._adapters)
        except Exception as exc:
            logger.warning("HealthMonitor: could not read adapter registry: %s", exc)
            return

        for adapter_name, adapter in adapters.items():
            try:
                cameras = await adapter.list_cameras()
            except Exception as exc:
                logger.warning(
                    "HealthMonitor: list_cameras failed for adapter '%s': %s", adapter_name, exc
                )
                cameras = []

            for camera in cameras:
                key = f"{adapter_name}.{camera.name}"
                old_status = self._health.get(key, CameraHealth(adapter_name, camera.name)).status

                start_ts = time.monotonic()
                new_status = HealthStatus.UNKNOWN
                latency_ms: float | None = None

                try:
                    await adapter.list_cameras()
                    elapsed_ms = (time.monotonic() - start_ts) * 1000.0
                    latency_ms = elapsed_ms

                    if elapsed_ms > _DEGRADED_LATENCY_MS:
                        new_status = HealthStatus.DEGRADED
                    else:
                        new_status = HealthStatus.ONLINE
                except Exception:
                    new_status = HealthStatus.OFFLINE

                # Update record
                prev = self._health.get(
                    key, CameraHealth(adapter_name=adapter_name, camera_name=camera.name)
                )
                now = datetime.utcnow()

                if new_status == HealthStatus.OFFLINE:
                    consecutive_failures = prev.consecutive_failures + 1
                    last_seen_online = prev.last_seen_online
                else:
                    consecutive_failures = 0
                    last_seen_online = now

                self._health[key] = CameraHealth(
                    adapter_name=adapter_name,
                    camera_name=camera.name,
                    status=new_status,
                    last_check=now,
                    last_seen_online=last_seen_online,
                    consecutive_failures=consecutive_failures,
                    latency_ms=latency_ms,
                )

                # Fire notification on significant status transitions
                await self._notify_if_changed(key, old_status, new_status, camera.name)

    async def _notify_if_changed(
        self,
        key: str,
        old_status: HealthStatus,
        new_status: HealthStatus,
        camera_name: str,
    ) -> None:
        """Send a notification when a camera goes ONLINE or OFFLINE."""
        from cctvql.notifications.base import NotificationPayload

        if old_status == new_status:
            return

        if new_status == HealthStatus.OFFLINE and old_status in (
            HealthStatus.ONLINE,
            HealthStatus.DEGRADED,
        ):
            payload = NotificationPayload(
                title=f"Camera Offline: {camera_name}",
                body=f"Camera '{camera_name}' is no longer reachable.",
                camera_name=camera_name,
            )
            await self._notifiers.broadcast(payload)
            logger.warning("HealthMonitor: camera '%s' went OFFLINE", camera_name)

        elif new_status == HealthStatus.ONLINE and old_status == HealthStatus.OFFLINE:
            payload = NotificationPayload(
                title=f"Camera Online: {camera_name}",
                body=f"Camera '{camera_name}' is back online.",
                camera_name=camera_name,
            )
            await self._notifiers.broadcast(payload)
            logger.info("HealthMonitor: camera '%s' came back ONLINE", camera_name)

    def get_status(self) -> list[CameraHealth]:
        """Return all CameraHealth records."""
        return list(self._health.values())

    def get_status_dict(self) -> list[dict]:
        """Return serializable camera health status list."""
        result = []
        for h in self._health.values():
            result.append(
                {
                    "adapter_name": h.adapter_name,
                    "camera_name": h.camera_name,
                    "status": h.status.value,
                    "last_check": h.last_check.isoformat() if h.last_check else None,
                    "last_seen_online": (
                        h.last_seen_online.isoformat() if h.last_seen_online else None
                    ),
                    "consecutive_failures": h.consecutive_failures,
                    "latency_ms": h.latency_ms,
                }
            )
        return result
