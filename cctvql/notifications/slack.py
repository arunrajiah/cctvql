"""
cctvQL Slack Notifier
----------------------
Sends notifications via Slack incoming webhooks.
"""

from __future__ import annotations

import logging

import httpx

from cctvql.notifications.base import BaseNotifier, NotificationPayload

logger = logging.getLogger(__name__)


class SlackNotifier(BaseNotifier):
    """
    Sends Slack messages via an incoming webhook URL.

    Args:
        webhook_url: Slack incoming webhook URL.
    """

    name = "slack"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    async def send(self, payload: NotificationPayload) -> None:
        """POST message to Slack incoming webhook."""
        fields = []
        if payload.camera_name:
            fields.append({"title": "Camera", "value": payload.camera_name, "short": True})
        if payload.event_id:
            fields.append({"title": "Event ID", "value": payload.event_id, "short": True})

        data = {
            "text": f"*{payload.title}*\n{payload.body}",
            "attachments": [
                {
                    "color": "danger",
                    "fields": fields,
                    "image_url": payload.snapshot_url,
                }
            ]
            if fields or payload.snapshot_url
            else [],
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=data)
                resp.raise_for_status()
                logger.debug("Slack message sent")
        except Exception as exc:
            logger.warning("Slack delivery failed: %s", exc)
            raise
