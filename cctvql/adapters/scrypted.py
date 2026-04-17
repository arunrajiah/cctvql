"""
cctvQL — Scrypted Adapter
---------------------------
Connects to a Scrypted server via its HTTP API.

Scrypted exposes a component-style REST API and per-device endpoints under
`/endpoint/@scrypted/core/public/`. This adapter talks to the subset
needed to enumerate cameras, fetch snapshots, and list recordings.

Auth model: long-lived API token passed as `Authorization: Bearer ...`.
Generate one from Scrypted's Settings → Users → API tokens.

API reference: https://docs.scrypted.app/development.html
"""

from __future__ import annotations

import logging
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


# Scrypted device interfaces that identify a camera-like device
_CAMERA_INTERFACES = {"Camera", "VideoCamera", "VideoCameraConfiguration"}


class ScryptedAdapter(BaseAdapter):
    """
    Adapter for Scrypted NVR / smart home camera platform.

    Args:
        host:         Base URL of the Scrypted server, e.g. https://scrypted.local:10443
        api_token:    Long-lived API token (Bearer)
        username:     Fallback username for login-based auth (optional)
        password:     Fallback password (optional)
        api_timeout:  HTTP request timeout in seconds

    Usage:
        adapter = ScryptedAdapter(host="https://scrypted.local:10443", api_token="...")
        await adapter.connect()
    """

    def __init__(
        self,
        host: str = "https://scrypted.local:10443",
        api_token: str = "",
        username: str = "",
        password: str = "",
        api_timeout: float = 30.0,
        ssl_verify: bool = True,
    ) -> None:
        self.host = host.rstrip("/")
        self.api_token = api_token
        self.username = username
        self.password = password
        self._client = httpx.AsyncClient(timeout=api_timeout, verify=ssl_verify)
        self._connected = False

    @property
    def name(self) -> str:
        return "scrypted"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Verify the server is reachable and the token is accepted."""
        try:
            r = await self._client.get(
                f"{self.host}/endpoint/@scrypted/core/public/info",
                headers=self._headers(),
            )
            # Some Scrypted versions return 404 on /info but 200 on /login
            if r.status_code == 404:
                r = await self._client.get(
                    f"{self.host}/login",
                    headers=self._headers(),
                )
            r.raise_for_status()
            self._connected = True
            logger.info("Connected to Scrypted at %s", self.host)
            return True
        except Exception as exc:
            logger.error("Failed to connect to Scrypted: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Close the underlying HTTP client."""
        self._connected = False
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def _get_json(self, path: str, **params: Any) -> Any:
        r = await self._client.get(
            f"{self.host}{path}",
            headers=self._headers(),
            params={k: v for k, v in params.items() if v is not None},
        )
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        """List devices with Camera/VideoCamera interfaces."""
        try:
            devices = await self._get_json("/endpoint/@scrypted/core/public/devices")
            items = devices.get("devices", devices) if isinstance(devices, dict) else devices

            cameras: list[Camera] = []
            for dev in items or []:
                interfaces = set(dev.get("interfaces") or [])
                if not interfaces & _CAMERA_INTERFACES:
                    continue
                dev_id = str(dev.get("id") or dev.get("nativeId") or "")
                online = dev.get("online", True)
                cameras.append(
                    Camera(
                        id=dev_id,
                        name=dev.get("name") or f"Device {dev_id}",
                        status=CameraStatus.ONLINE if online else CameraStatus.OFFLINE,
                        snapshot_url=(
                            f"{self.host}/endpoint/@scrypted/core/public/device/{dev_id}/snapshot"
                        ),
                        stream_url=dev.get("rtspUrl"),
                        metadata={
                            "source": "scrypted",
                            "type": dev.get("type"),
                            "interfaces": list(interfaces),
                            "plugin": dev.get("pluginId"),
                        },
                    )
                )
            return cameras
        except Exception as exc:
            logger.error("Failed to list Scrypted cameras: %s", exc)
            return []

    async def get_camera(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> Camera | None:
        """Retrieve a single camera by id or name."""
        for cam in await self.list_cameras():
            if camera_id and cam.id == camera_id:
                return cam
            if camera_name and cam.name.lower() == camera_name.lower():
                return cam
        return None

    # ------------------------------------------------------------------
    # Events
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
        """Fetch motion/object events from the Scrypted NVR plugin."""
        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        params: dict[str, Any] = {"limit": limit}
        if camera_id:
            params["device"] = camera_id
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time:
            params["endTime"] = int(end_time.timestamp() * 1000)
        if label:
            params["class"] = label

        try:
            data = await self._get_json(
                "/endpoint/@scrypted/nvr/public/events",
                **params,
            )
            items = data.get("events", data) if isinstance(data, dict) else data

            events: list[Event] = []
            for ev in items or []:
                ev_cam = str(ev.get("device") or ev.get("deviceId") or camera_id or "")
                start_ms = ev.get("startTime") or ev.get("timestamp") or 0
                end_ms = ev.get("endTime")
                events.append(
                    Event(
                        id=str(ev.get("id") or f"{ev_cam}-{start_ms}"),
                        camera_id=ev_cam,
                        camera_name=ev.get("deviceName") or f"Device {ev_cam}",
                        event_type=self._map_event_type(ev.get("type") or ev.get("class")),
                        start_time=datetime.fromtimestamp(int(start_ms) / 1000, tz=timezone.utc),
                        end_time=(
                            datetime.fromtimestamp(int(end_ms) / 1000, tz=timezone.utc)
                            if end_ms
                            else None
                        ),
                        metadata={
                            "source": "scrypted",
                            "class": ev.get("class"),
                            "score": ev.get("score"),
                        },
                    )
                )
            return events
        except Exception as exc:
            logger.error("Failed to fetch Scrypted events: %s", exc)
            return []

    async def get_event(self, event_id: str) -> Event | None:
        """Look up a specific event by ID from recent events."""
        for ev in await self.get_events(limit=200):
            if ev.id == event_id:
                return ev
        return None

    # ------------------------------------------------------------------
    # Clips (NVR recordings)
    # ------------------------------------------------------------------

    async def get_clips(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Clip]:
        """Fetch recordings via the Scrypted NVR plugin's recordings endpoint."""
        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        params: dict[str, Any] = {"limit": limit}
        if camera_id:
            params["device"] = camera_id
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time:
            params["endTime"] = int(end_time.timestamp() * 1000)

        try:
            data = await self._get_json(
                "/endpoint/@scrypted/nvr/public/recordings",
                **params,
            )
            items = data.get("recordings", data) if isinstance(data, dict) else data

            clips: list[Clip] = []
            for rec in items or []:
                rec_cam = str(rec.get("device") or camera_id or "")
                rec_id = str(rec.get("id") or "")
                start_ms = rec.get("startTime") or 0
                end_ms = rec.get("endTime") or start_ms
                clips.append(
                    Clip(
                        id=rec_id,
                        camera_id=rec_cam,
                        camera_name=rec.get("deviceName") or f"Device {rec_cam}",
                        start_time=datetime.fromtimestamp(int(start_ms) / 1000, tz=timezone.utc),
                        end_time=datetime.fromtimestamp(int(end_ms) / 1000, tz=timezone.utc),
                        download_url=rec.get("url"),
                        size_bytes=rec.get("size"),
                        metadata={"source": "scrypted"},
                    )
                )
            return clips
        except Exception as exc:
            logger.error("Failed to fetch Scrypted recordings: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        """Return the per-device snapshot URL."""
        if not camera_id and camera_name:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id
        if not camera_id:
            return None
        return f"{self.host}/endpoint/@scrypted/core/public/device/{camera_id}/snapshot"

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo | None:
        """Retrieve system info via /endpoint/@scrypted/core/public/info."""
        try:
            info = await self._get_json("/endpoint/@scrypted/core/public/info")
            cameras = await self.list_cameras()
            return SystemInfo(
                system_name=info.get("serverName") or "Scrypted",
                version=info.get("version"),
                camera_count=len(cameras),
                metadata={
                    "source": "scrypted",
                    "server_id": info.get("serverId"),
                    "nodeVersion": info.get("nodeVersion"),
                },
            )
        except Exception as exc:
            logger.error("Failed to get Scrypted system info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if the server responds on /endpoint/@scrypted/core/public/info."""
        try:
            r = await self._client.get(
                f"{self.host}/endpoint/@scrypted/core/public/info",
                headers=self._headers(),
            )
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # PTZ control
    # ------------------------------------------------------------------

    async def ptz_move(self, camera_name: str, action: str, speed: int = 50) -> bool:
        """Issue a PTZ command via /endpoint/@scrypted/core/public/device/<id>/ptz."""
        cam = await self.get_camera(camera_name=camera_name)
        if not cam:
            return False
        try:
            r = await self._client.post(
                f"{self.host}/endpoint/@scrypted/core/public/device/{cam.id}/ptz",
                headers=self._headers(),
                json={"command": action, "speed": speed / 100.0},
            )
            return r.status_code in (200, 204)
        except Exception as exc:
            logger.warning("Scrypted PTZ move failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_event_type(type_str: Any) -> EventType:
        """Map Scrypted event types/classes to cctvQL EventType."""
        t = str(type_str or "").lower()
        if "motion" in t:
            return EventType.MOTION
        if any(cls in t for cls in ("person", "vehicle", "animal", "package", "face")):
            return EventType.OBJECT_DETECTED
        if "audio" in t:
            return EventType.AUDIO
        if "tamper" in t:
            return EventType.TAMPER
        return EventType.UNKNOWN
