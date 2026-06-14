"""
cctvQL Mobile Push Notifier — Firebase Cloud Messaging (FCM)
------------------------------------------------------------
Sends alert notifications to registered mobile devices via the
Firebase Cloud Messaging HTTP v1 API.

Configuration (in config.yaml):
  notifications:
    - type: push
      fcm_project_id: "my-firebase-project"
      fcm_service_account_key: "/path/to/serviceAccountKey.json"
      # OR supply the key JSON inline:
      # fcm_service_account_key_json: |
      #   { "type": "service_account", ... }

The notifier reads registered device tokens from the cctvQL database
(pushed there via ``POST /push/register``).  On each alert it fans out
to all stored tokens, de-registering any that FCM reports as invalid.

If ``google-auth`` is not installed (``pip install cctvql[push]``), the
notifier logs a warning and skips delivery silently.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from cctvql.notifications.base import BaseNotifier

logger = logging.getLogger(__name__)

_FCM_SEND_URL = (
    "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
)

# Scopes required by the FCM HTTP v1 API
_FCM_SCOPES = ["https://www.googleapis.com/auth/firebase.messaging"]


class PushNotifier(BaseNotifier):
    """
    Firebase Cloud Messaging push notifier for cctvQL mobile clients.

    Args:
        fcm_project_id:            Your Firebase project ID.
        fcm_service_account_key:   Path to the service-account JSON key file.
        fcm_service_account_key_json:
                                   Service-account JSON key content as a string
                                   (alternative to a file path).
        db:                        Open ``cctvql.core.database.Database``
                                   instance used to look up registered tokens.
    """

    name = "push"

    def __init__(
        self,
        fcm_project_id: str,
        fcm_service_account_key: str | None = None,
        fcm_service_account_key_json: str | None = None,
        db: Any = None,
    ) -> None:
        self._project_id = fcm_project_id
        self._key_path = fcm_service_account_key
        self._key_json = fcm_service_account_key_json
        self._db = db
        self._credentials: Any = None  # google.oauth2.service_account.Credentials

    # ------------------------------------------------------------------
    # BaseNotifier interface
    # ------------------------------------------------------------------

    async def send(self, subject: str, body: str, **kwargs: Any) -> None:
        """
        Push an alert to all registered mobile devices.

        Args:
            subject: Short notification title.
            body:    Notification body text.
            kwargs:  Optional extras forwarded as FCM ``data`` payload:
                     camera, event_id, snapshot_url, severity.
        """
        tokens = await self._get_tokens()
        if not tokens:
            logger.debug("PushNotifier: no registered device tokens — skipping.")
            return

        access_token = await self._get_access_token()
        if access_token is None:
            return  # error already logged

        send_url = _FCM_SEND_URL.format(project_id=self._project_id)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Build optional data payload from kwargs
        data_payload: dict[str, str] = {}
        for key in ("camera", "event_id", "snapshot_url", "severity", "rule_id"):
            if key in kwargs and kwargs[key] is not None:
                data_payload[key] = str(kwargs[key])

        invalid_tokens: list[str] = []

        async with httpx.AsyncClient(timeout=15.0) as client:
            for token in tokens:
                payload = {
                    "message": {
                        "token": token,
                        "notification": {
                            "title": subject,
                            "body": body,
                        },
                        "data": data_payload,
                        "android": {
                            "priority": "high",
                            "notification": {"sound": "default"},
                        },
                        "apns": {
                            "payload": {
                                "aps": {
                                    "sound": "default",
                                    "badge": 1,
                                }
                            }
                        },
                    }
                }

                try:
                    resp = await client.post(send_url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        logger.debug("Push sent to token …%s", token[-8:])
                    elif resp.status_code in (400, 404):
                        # Token is invalid / unregistered — clean up
                        error_body = resp.json()
                        err_status = (
                            error_body.get("error", {})
                            .get("details", [{}])[0]
                            .get("errorCode", "")
                        )
                        if err_status in ("UNREGISTERED", "INVALID_ARGUMENT"):
                            logger.info(
                                "FCM: token …%s is invalid/unregistered — removing.",
                                token[-8:],
                            )
                            invalid_tokens.append(token)
                        else:
                            logger.warning(
                                "FCM push to …%s failed (%s): %s",
                                token[-8:],
                                resp.status_code,
                                resp.text,
                            )
                    else:
                        logger.warning(
                            "FCM push to …%s failed (%s): %s",
                            token[-8:],
                            resp.status_code,
                            resp.text,
                        )
                except Exception as exc:
                    logger.warning("FCM push error for token …%s: %s", token[-8:], exc)

        # Remove stale tokens
        if invalid_tokens and self._db is not None:
            for tok in invalid_tokens:
                await self._db.delete_push_token(tok)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_tokens(self) -> list[str]:
        """Fetch all registered device tokens from the database."""
        if self._db is None:
            return []
        try:
            rows = await self._db.list_push_tokens()
            return [row["token"] for row in rows]
        except Exception as exc:
            logger.warning("Could not load push tokens from DB: %s", exc)
            return []

    async def _get_access_token(self) -> str | None:
        """
        Obtain a short-lived OAuth2 Bearer token for the FCM HTTP v1 API.

        Uses ``google-auth`` service-account credentials.  Returns None
        (and logs a warning) when the library is not installed.
        """
        try:
            from google.oauth2 import service_account  # type: ignore[import]
            import google.auth.transport.requests  # type: ignore[import]
        except ImportError:
            logger.warning(
                "google-auth is not installed — push notifications disabled. "
                "Install with: pip install cctvql[push]"
            )
            return None

        if self._credentials is None:
            try:
                if self._key_json:
                    info = json.loads(self._key_json)
                    self._credentials = (
                        service_account.Credentials.from_service_account_info(
                            info, scopes=_FCM_SCOPES
                        )
                    )
                elif self._key_path:
                    self._credentials = (
                        service_account.Credentials.from_service_account_file(
                            self._key_path, scopes=_FCM_SCOPES
                        )
                    )
                else:
                    logger.error(
                        "PushNotifier: no FCM service account key configured. "
                        "Set fcm_service_account_key or fcm_service_account_key_json."
                    )
                    return None
            except Exception as exc:
                logger.error("PushNotifier: failed to load service account credentials: %s", exc)
                return None

        # Refresh token if expired
        request = google.auth.transport.requests.Request()
        try:
            self._credentials.refresh(request)
        except Exception as exc:
            logger.error("PushNotifier: token refresh failed: %s", exc)
            self._credentials = None  # reset so next call re-loads
            return None

        return self._credentials.token
