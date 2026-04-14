"""
cctvQL Notification Base
-------------------------
Abstract interface for all notification channel implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class NotificationPayload:
    """Notification message payload."""

    title: str
    body: str
    event_id: str | None = None
    camera_name: str | None = None
    snapshot_url: str | None = None


class BaseNotifier(ABC):
    """Abstract base class for notification channel implementations."""

    name: str

    @abstractmethod
    async def send(self, payload: NotificationPayload) -> None:
        """Send a notification via this channel."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if this notifier has all required config."""
        ...
