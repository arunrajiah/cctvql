"""
cctvQL — Milestone XProtect Adapter
-------------------------------------
Connects to Milestone XProtect VMS via its REST API (OAuth 2.0 bearer token).

Auth model: OAuth2 Resource Owner Password Credentials flow against the
Milestone Identity Provider (IDP), then Bearer token on /api/rest/v1/*.

API reference:
  https://doc.developer.milestonesys.com/mipsdkrestapi/
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from cctvql.adapters.base import BaseAdapter
from cctvql.core.schema import (
    Camera,
    CameraStatus,
    Clip,
    Event,
    EventType,
    SystemInfo,
)

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[\w\-]+$")


def _safe_odata_id(value: str) -> str:
    """Reject values that could escape an OData string literal."""
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"Unsafe id for OData filter: {value!r}")
    return value


class MilestoneAdapter(BaseAdapter):
    """
    Adapter for Milestone XProtect VMS via its REST API.

    Args:
        host:         Base URL of the Management Server, e.g. https://vms.example.com
        username:     Basic/Windows user with XProtect access
        password:     Account password
        client_id:    OAuth client id (default: GrantValidatorClient)
        grant_type:   OAuth grant type (default: password)
        api_timeout:  HTTP request timeout in seconds

    Usage:
        adapter = MilestoneAdapter(
            host="https://vms.example.com",
            username="admin",
            password="pass",
        )
        await adapter.connect()
    """

    def __init__(
        self,
        host: str = "https://vms.example.com",
        username: str = "admin",
        password: str = "",
        client_id: str = "GrantValidatorClient",
        grant_type: str = "password",
        api_timeout: float = 30.0,
        ssl_verify: bool = True,
    ) -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.client_id = client_id
        self.grant_type = grant_type
        self._token: str | None = None
        self._client = httpx.AsyncClient(timeout=api_timeout, verify=ssl_verify)

    @property
    def name(self) -> str:
        return "milestone"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Fetch an access token from /IDP/connect/token."""
        try:
            r = await self._client.post(
                f"{self.host}/IDP/connect/token",
                data={
                    "grant_type": self.grant_type,
                    "username": self.username,
                    "password": self.password,
                    "client_id": self.client_id,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            data = r.json()
            self._token = data.get("access_token")
            if not self._token:
                logger.error("Milestone IDP response missing access_token: %s", data)
                return False
            logger.info("Connected to Milestone XProtect at %s", self.host)
            return True
        except Exception as exc:
            logger.error("Failed to authenticate with Milestone IDP: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Close the HTTP client. Tokens expire server-side on their own."""
        self._token = None
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("Milestone adapter is not connected; call connect() first.")
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    async def _get(self, path: str, **params: Any) -> dict[str, Any]:
        """GET /api/rest/v1/<path> as JSON, with one automatic token refresh on 401."""
        url = f"{self.host}/api/rest/v1/{path.lstrip('/')}"
        filtered = {k: v for k, v in params.items() if v is not None}
        r = await self._client.get(url, headers=self._headers(), params=filtered)
        if r.status_code == 401 and await self.connect():
            r = await self._client.get(url, headers=self._headers(), params=filtered)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        """List cameras via GET /api/rest/v1/cameras."""
        try:
            data = await self._get("cameras")
            cameras: list[Camera] = []
            for cam in data.get("array", []) or data.get("items", []):
                cam_id = str(cam.get("id") or "")
                enabled = cam.get("enabled", True)
                status = CameraStatus.ONLINE if enabled else CameraStatus.OFFLINE
                cameras.append(
                    Camera(
                        id=cam_id,
                        name=cam.get("displayName") or cam.get("name") or f"Camera {cam_id}",
                        status=status,
                        snapshot_url=(
                            f"{self.host}/api/rest/v1/cameras/{cam_id}/thumbnail"
                            if cam_id
                            else None
                        ),
                        metadata={
                            "source": "milestone",
                            "description": cam.get("description"),
                            "hardware_id": cam.get("hardwareId"),
                            "channel": cam.get("channel"),
                        },
                    )
                )
            return cameras
        except Exception as exc:
            logger.error("Failed to list Milestone cameras: %s", exc)
            return []

    async def get_camera(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> Camera | None:
        """Retrieve a single camera by id or name."""
        if camera_id:
            try:
                raw = await self._get(f"cameras/{camera_id}")
                data = raw.get("data", raw)
                return Camera(
                    id=str(data.get("id") or camera_id),
                    name=data.get("displayName") or data.get("name") or f"Camera {camera_id}",
                    status=(
                        CameraStatus.ONLINE if data.get("enabled", True) else CameraStatus.OFFLINE
                    ),
                    snapshot_url=f"{self.host}/api/rest/v1/cameras/{camera_id}/thumbnail",
                    metadata={"source": "milestone"},
                )
            except Exception as exc:
                logger.debug("Milestone get_camera by id failed: %s", exc)

        for cam in await self.list_cameras():
            if camera_name and cam.name.lower() == camera_name.lower():
                return cam
        return None

    # ------------------------------------------------------------------
    # Events (alarms)
    # ------------------------------------------------------------------

    async def get_events(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        label: str | None = None,
        zone: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Event]:
        """Fetch alarms via GET /api/rest/v1/alarms."""
        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        params: dict[str, Any] = {"$top": limit}
        filters: list[str] = []
        if camera_id:
            filters.append(f"sourceId eq '{_safe_odata_id(camera_id)}'")
        if start_time:
            filters.append(f"timestamp ge {start_time.isoformat()}")
        if end_time:
            filters.append(f"timestamp le {end_time.isoformat()}")
        if filters:
            params["$filter"] = " and ".join(filters)

        try:
            data = await self._get("alarms", **params)
            events: list[Event] = []
            for alarm in data.get("array", []) or data.get("items", []):
                ev_cam_id = str(alarm.get("sourceId") or camera_id or "")
                ts = alarm.get("timestamp")
                events.append(
                    Event(
                        id=str(alarm.get("id") or ""),
                        camera_id=ev_cam_id,
                        camera_name=alarm.get("sourceName") or f"Camera {ev_cam_id}",
                        event_type=self._map_event_type(alarm.get("category")),
                        start_time=self._parse_iso(ts) if ts else datetime.now(tz=timezone.utc),
                        end_time=None,
                        metadata={
                            "source": "milestone",
                            "priority": alarm.get("priority"),
                            "state": alarm.get("state"),
                            "message": alarm.get("message"),
                        },
                    )
                )
            return events
        except Exception as exc:
            logger.error("Failed to fetch Milestone alarms: %s", exc)
            return []

    async def get_event(self, event_id: str) -> Event | None:
        """Look up a specific alarm by ID."""
        try:
            data = await self._get(f"alarms/{event_id}")
            alarm = data.get("data", data)
            cam_id = str(alarm.get("sourceId") or "")
            ts = alarm.get("timestamp")
            return Event(
                id=str(alarm.get("id") or event_id),
                camera_id=cam_id,
                camera_name=alarm.get("sourceName") or f"Camera {cam_id}",
                event_type=self._map_event_type(alarm.get("category")),
                start_time=self._parse_iso(ts) if ts else datetime.now(tz=timezone.utc),
                metadata={"source": "milestone"},
            )
        except Exception as exc:
            logger.debug("Milestone get_event failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Clips (bookmarks / investigations)
    # ------------------------------------------------------------------

    async def get_clips(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Clip]:
        """Fetch bookmarks via GET /api/rest/v1/bookmarks."""
        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        params: dict[str, Any] = {"$top": limit}
        filters: list[str] = []
        if camera_id:
            filters.append(f"cameraId eq '{_safe_odata_id(camera_id)}'")
        if start_time:
            filters.append(f"startTime ge {start_time.isoformat()}")
        if end_time:
            filters.append(f"endTime le {end_time.isoformat()}")
        if filters:
            params["$filter"] = " and ".join(filters)

        try:
            data = await self._get("bookmarks", **params)
            clips: list[Clip] = []
            for bm in data.get("array", []) or data.get("items", []):
                bm_cam = str(bm.get("cameraId") or camera_id or "")
                start = bm.get("startTime") or bm.get("timeBegin")
                stop = bm.get("endTime") or bm.get("timeEnd") or start
                clips.append(
                    Clip(
                        id=str(bm.get("id") or ""),
                        camera_id=bm_cam,
                        camera_name=bm.get("cameraName") or f"Camera {bm_cam}",
                        start_time=self._parse_iso(start) if start else datetime.now(tz=timezone.utc),
                        end_time=self._parse_iso(stop) if stop else datetime.now(tz=timezone.utc),
                        metadata={
                            "source": "milestone",
                            "header": bm.get("header"),
                            "description": bm.get("description"),
                        },
                    )
                )
            return clips
        except Exception as exc:
            logger.error("Failed to fetch Milestone bookmarks: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        """Return thumbnail endpoint URL for a camera."""
        if not camera_id and camera_name:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id
        if not camera_id:
            return None
        return f"{self.host}/api/rest/v1/cameras/{camera_id}/thumbnail"

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo | None:
        """Retrieve system info via GET /api/rest/v1/site."""
        try:
            data = await self._get("site")
            site = data.get("data", data)
            cameras = await self.list_cameras()
            return SystemInfo(
                system_name=site.get("displayName") or "Milestone XProtect",
                version=site.get("productVersion") or site.get("version"),
                camera_count=len(cameras),
                metadata={
                    "source": "milestone",
                    "product_code": site.get("productCode"),
                    "site_id": site.get("id"),
                },
            )
        except Exception as exc:
            logger.error("Failed to get Milestone system info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if /api/rest/v1/site responds with HTTP 200."""
        try:
            r = await self._client.get(
                f"{self.host}/api/rest/v1/site",
                headers=self._headers() if self._token else {},
            )
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_event_type(category: Any) -> EventType:
        """Map Milestone alarm category to cctvQL EventType."""
        cat = str(category or "").lower()
        if "motion" in cat:
            return EventType.MOTION
        if "object" in cat or "analytics" in cat:
            return EventType.OBJECT_DETECTED
        if "tamper" in cat:
            return EventType.TAMPER
        if "audio" in cat:
            return EventType.AUDIO
        return EventType.UNKNOWN

    @staticmethod
    def _parse_iso(ts: str) -> datetime:
        """Parse a Milestone ISO 8601 timestamp (handles Z suffix)."""
        try:
            return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return datetime.now(tz=timezone.utc)
