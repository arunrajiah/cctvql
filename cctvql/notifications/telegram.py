"""
cctvQL Telegram Notifier
-------------------------
Sends notifications via Telegram Bot API.
"""

from __future__ import annotations

import logging

import httpx

from cctvql.notifications.base import BaseNotifier, NotificationPayload

logger = logging.getLogger(__name__)


class TelegramNotifier(BaseNotifier):
    """
    Sends Telegram messages via the Bot API.

    Args:
        bot_token: Telegram bot token from @BotFather.
        chat_id:   Target chat ID (user or group).
    """

    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, payload: NotificationPayload) -> None:
        """Send a message via Telegram Bot API sendMessage endpoint."""
        text = f"\U0001f6a8 {payload.title}\n{payload.body}"
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = {"chat_id": self.chat_id, "text": text}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=data)
                resp.raise_for_status()
                logger.debug("Telegram message sent to chat %s", self.chat_id)
        except Exception as exc:
            logger.warning("Telegram delivery failed: %s", exc)
            raise
