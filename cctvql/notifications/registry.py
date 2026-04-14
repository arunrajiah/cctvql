"""
cctvQL Notifier Registry
-------------------------
Central registry for notification channels. Broadcasts alerts concurrently
to all configured notifiers.
"""

from __future__ import annotations

import asyncio
import logging

from cctvql.notifications.base import BaseNotifier, NotificationPayload

logger = logging.getLogger(__name__)


class NotifierRegistry:
    """Registry of notification channels."""

    _notifiers: list[BaseNotifier] = []

    @classmethod
    def register(cls, notifier: BaseNotifier) -> None:
        """Register a notification channel."""
        cls._notifiers.append(notifier)
        logger.debug("NotifierRegistry: registered notifier '%s'", notifier.name)

    @classmethod
    def all(cls) -> list[BaseNotifier]:
        """Return all registered notifiers."""
        return list(cls._notifiers)

    @classmethod
    def clear(cls) -> None:
        """Remove all registered notifiers."""
        cls._notifiers = []

    @classmethod
    async def broadcast(cls, payload: NotificationPayload) -> None:
        """
        Send the payload concurrently to all configured notifiers.
        Exceptions from individual notifiers are caught and logged.
        """
        configured = [n for n in cls._notifiers if n.is_configured()]
        if not configured:
            logger.debug("NotifierRegistry: no configured notifiers to broadcast to.")
            return

        async def _send(notifier: BaseNotifier) -> None:
            try:
                await notifier.send(payload)
            except Exception as exc:
                logger.warning("NotifierRegistry: notifier '%s' failed: %s", notifier.name, exc)

        await asyncio.gather(*[_send(n) for n in configured], return_exceptions=True)
