"""
cctvQL Email Notifier
----------------------
Sends notifications via SMTP using aiosmtplib.
"""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from cctvql.notifications.base import BaseNotifier, NotificationPayload

logger = logging.getLogger(__name__)


class EmailNotifier(BaseNotifier):
    """
    Sends email notifications via SMTP.

    Args:
        smtp_host:   SMTP server hostname.
        smtp_port:   SMTP server port (default: 587).
        username:    SMTP authentication username.
        password:    SMTP authentication password.
        from_addr:   Sender email address.
        to_addrs:    List of recipient email addresses.
        use_tls:     Use STARTTLS (default: True).
    """

    name = "email"

    def __init__(
        self,
        smtp_host: str,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: list[str],
        smtp_port: int = 587,
        use_tls: bool = True,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls

    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.username and self.from_addr and self.to_addrs)

    async def send(self, payload: NotificationPayload) -> None:
        """Send an email notification via SMTP."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = payload.title
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)

        body_lines = [payload.body]
        if payload.camera_name:
            body_lines.append(f"Camera: {payload.camera_name}")
        if payload.event_id:
            body_lines.append(f"Event ID: {payload.event_id}")
        if payload.snapshot_url:
            body_lines.append(f"Snapshot: {payload.snapshot_url}")

        text_body = "\n".join(body_lines)
        msg.attach(MIMEText(text_body, "plain"))

        try:
            import aiosmtplib  # optional dependency

            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )
            logger.debug("Email sent to %s", self.to_addrs)
        except Exception as exc:
            logger.warning("Email delivery failed: %s", exc)
            raise
