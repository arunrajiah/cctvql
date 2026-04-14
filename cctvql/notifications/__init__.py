"""cctvQL notification channels."""

from cctvql.notifications.base import BaseNotifier, NotificationPayload
from cctvql.notifications.email_notifier import EmailNotifier
from cctvql.notifications.ntfy import NtfyNotifier
from cctvql.notifications.registry import NotifierRegistry
from cctvql.notifications.slack import SlackNotifier
from cctvql.notifications.telegram import TelegramNotifier
from cctvql.notifications.webhook import WebhookNotifier

__all__ = [
    "BaseNotifier",
    "NotificationPayload",
    "WebhookNotifier",
    "TelegramNotifier",
    "SlackNotifier",
    "EmailNotifier",
    "NtfyNotifier",
    "NotifierRegistry",
]
