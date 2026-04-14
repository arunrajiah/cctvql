"""
cctvQL ntfy Notifier
---------------------
Sends notifications via ntfy.sh (or a self-hosted ntfy instance).
"""

from __future__ import annotations

import logging

import httpx

from cctvql.notifications.base import BaseNotifier, NotificationPayload

logger = logging.getLogger(__name__)


class NtfyNotifier(BaseNotifier):
    """
    Sends push notifications via ntfy.sh.

    Args:
        topic:  ntfy topic name (acts as the channel/password).
        server: ntfy server URL (default: https://ntfy.sh).
    """

    name = "ntfy"

    def __init__(self, topic: str, server: str = "https://ntfy.sh") -> None:
        self.topic = topic
        self.server = server.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.topic)

    async def send(self, payload: NotificationPayload) -> None:
        """POST a push notification to ntfy."""
        url = f"{self.server}/{self.topic}"
        headers = {
            "Title": payload.title,
            "Priority": "high",
        }
        if payload.snapshot_url:
            headers["Attach"] = payload.snapshot_url

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=payload.body.encode(), headers=headers)
                resp.raise_for_status()
                logger.debug("ntfy notification sent to topic %s", self.topic)
        except Exception as exc:
            logger.warning("ntfy delivery failed: %s", exc)
            raise
