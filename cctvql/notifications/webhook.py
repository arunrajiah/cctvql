"""
cctvQL Webhook Notifier
------------------------
Sends notifications via HTTP POST to a configured webhook URL.
"""

from __future__ import annotations

import logging

import httpx

from cctvql.notifications.base import BaseNotifier, NotificationPayload

logger = logging.getLogger(__name__)


class WebhookNotifier(BaseNotifier):
    """
    Sends a JSON POST to a webhook URL.

    Args:
        url: The webhook endpoint URL.
    """

    name = "webhook"

    def __init__(self, url: str) -> None:
        self.url = url

    def is_configured(self) -> bool:
        return bool(self.url)

    async def send(self, payload: NotificationPayload) -> None:
        """POST JSON payload to the configured webhook URL."""
        data = {
            "title": payload.title,
            "body": payload.body,
            "event_id": payload.event_id,
            "camera_name": payload.camera_name,
            "snapshot_url": payload.snapshot_url,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.url, json=data)
                resp.raise_for_status()
                logger.debug("Webhook delivered to %s (status %d)", self.url, resp.status_code)
        except Exception as exc:
            logger.warning("Webhook delivery failed for %s: %s", self.url, exc)
            raise
