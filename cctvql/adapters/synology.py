"""
cctvQL — Synology Surveillance Station Adapter
-----------------------------------------------
Connects to a Synology NAS running Surveillance Station via the
Synology Web API (SYNO.API.* and SYNO.SurveillanceStation.*).

Auth model: session-based. We call SYNO.API.Auth login on connect()
and reuse the returned session ID (sid) in subsequent requests.

API reference: https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/SurveillanceStation/All/enu/Surveillance_Station_Web_API.pdf
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


class SynologyAdapter(BaseAdapter):
    """
    Adapter for Synology Surveillance Station.

    Args:
        host:        Base URL of the NAS, e.g. http://192.168.1.10:5000
        username:    Account with Surveillance Station access
        password:    Account password
        session:     Session name sent to SYNO.API.Auth (default: SurveillanceStation)
        api_timeout: HTTP request timeout in seconds

    Usage:
        adapter = SynologyAdapter(
            host="http://192.168.1.10:5000",
            username="admin",
            password="pass",
        )
        await adapter.connect()
    """

    def __init__(
        self,
        host: str = "http://192.168.1.10:5000",
        username: str = "admin",
        password: str = "",
        session: str = "SurveillanceStation",
        api_timeout: float = 30.0,
        ssl_verify: bool = True,
    ) -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.session = session
        self._sid: str | None = None
        self._client = httpx.AsyncClient(timeout=api_timeout, verify=ssl_verify)

    @property
    def name(self) -> str:
        return "synology"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Log in via SYNO.API.Auth and cache the session ID."""
        try:
            r = await self._client.get(
                f"{self.host}/webapi/auth.cgi",
                params={
                    "api": "SYNO.API.Auth",
                    "version": "6",
                    "method": "login",
                    "account": self.username,
                    "passwd": self.password,
                    "session": self.session,
                    "format": "sid",
                },
            )
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                logger.error("Synology login failed: %s", data.get("error"))
                return False
            self._sid = data["data"]["sid"]
            logger.info("Connected to Synology Surveillance Station at %s", self.host)
            return True
        except Exception as exc:
            logger.error("Failed to connect to Synology: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Log out and close the HTTP client."""
        if self._sid:
            try:
                await self._client.get(
                    f"{self.host}/webapi/auth.cgi",
                    params={
                        "api": "SYNO.API.Auth",
                        "version": "6",
                        "method": "logout",
                        "session": self.session,
                        "_sid": self._sid,
                    },
                )
            except Exception as exc:
                logger.debug("Synology logout failed: %s", exc)
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal request helper
    # ------------------------------------------------------------------

    async def _api(
        self,
        api: str,
        method: str,
        version: int,
        **params: Any,
    ) -> dict[str, Any]:
        """Issue an authenticated SYNO.SurveillanceStation.* request."""
        if not self._sid:
            raise RuntimeError("Synology adapter is not connected; call connect() first.")

        query = {
            "api": api,
            "version": str(version),
            "method": method,
            "_sid": self._sid,
            **{k: str(v) for k, v in params.items() if v is not None},
        }
        r = await self._client.get(f"{self.host}/webapi/entry.cgi", params=query)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        """List cameras via SYNO.SurveillanceStation.Camera / List."""
        try:
            data = await self._api("SYNO.SurveillanceStation.Camera", "List", 9)
            if not data.get("success"):
                return []
            cameras: list[Camera] = []
            for cam in data.get("data", {}).get("cameras", []):
                cam_id = str(cam.get("id") or cam.get("camera_id") or "")
                status = (
                    CameraStatus.ONLINE
                    if cam.get("status") in (1, "1", "Normal")
                    else CameraStatus.OFFLINE
                )
                cameras.append(
                    Camera(
                        id=cam_id,
                        name=cam.get("newName") or cam.get("name") or f"Camera {cam_id}",
                        status=status,
                        snapshot_url=None,  # auth injected at request-time via get_snapshot_url()
                        stream_url=cam.get("rtspPath") or cam.get("rtsp_path"),
                        metadata={
                            "source": "synology",
                            "model": cam.get("model"),
                            "vendor": cam.get("vendor"),
                            "ip": cam.get("ip"),
                        },
                    )
                )
            return cameras
        except Exception as exc:
            logger.error("Failed to list Synology cameras: %s", exc)
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
        """Fetch events via SYNO.SurveillanceStation.Event / List."""
        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        params: dict[str, Any] = {"limit": limit}
        if camera_id:
            params["cameraIds"] = camera_id
        if start_time:
            params["fromTime"] = int(start_time.timestamp())
        if end_time:
            params["toTime"] = int(end_time.timestamp())

        try:
            data = await self._api("SYNO.SurveillanceStation.Event", "List", 5, **params)
            if not data.get("success"):
                return []

            events: list[Event] = []
            for ev in data.get("data", {}).get("events", []):
                ev_cam_id = str(ev.get("camera_id") or ev.get("cameraId") or camera_id or "")
                start_ts = ev.get("startTime") or ev.get("start_time") or 0
                stop_ts = ev.get("stopTime") or ev.get("stop_time")
                events.append(
                    Event(
                        id=str(ev.get("id") or ev.get("eventId") or ""),
                        camera_id=ev_cam_id,
                        camera_name=ev.get("camera_name") or f"Camera {ev_cam_id}",
                        event_type=self._map_event_type(ev.get("reason")),
                        start_time=datetime.fromtimestamp(int(start_ts), tz=timezone.utc),
                        end_time=datetime.fromtimestamp(int(stop_ts), tz=timezone.utc) if stop_ts else None,
                        metadata={
                            "source": "synology",
                            "reason": ev.get("reason"),
                            "archived": ev.get("archived"),
                        },
                    )
                )
            return events
        except Exception as exc:
            logger.error("Failed to fetch Synology events: %s", exc)
            return []

    async def get_event(self, event_id: str) -> Event | None:
        """Look up a specific event by ID via SYNO.SurveillanceStation.Event / GetInfo."""
        try:
            data = await self._api("SYNO.SurveillanceStation.Event", "GetInfo", 5, id=event_id)
            if not data.get("success"):
                return None
            ev = data.get("data", {}).get("event") or data.get("data", {})
            ev_cam_id = str(ev.get("camera_id") or ev.get("cameraId") or "")
            start_ts = ev.get("startTime") or ev.get("start_time") or 0
            stop_ts = ev.get("stopTime") or ev.get("stop_time")
            return Event(
                id=str(ev.get("id") or event_id),
                camera_id=ev_cam_id,
                camera_name=ev.get("camera_name") or f"Camera {ev_cam_id}",
                event_type=self._map_event_type(ev.get("reason")),
                start_time=datetime.fromtimestamp(int(start_ts), tz=timezone.utc),
                end_time=datetime.fromtimestamp(int(stop_ts), tz=timezone.utc) if stop_ts else None,
                metadata={"source": "synology", "reason": ev.get("reason")},
            )
        except Exception as exc:
            logger.debug("Synology get_event failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Clips (recordings)
    # ------------------------------------------------------------------

    async def get_clips(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Clip]:
        """Fetch recordings via SYNO.SurveillanceStation.Recording / List."""
        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        params: dict[str, Any] = {"limit": limit}
        if camera_id:
            params["cameraIds"] = camera_id
        if start_time:
            params["fromTime"] = int(start_time.timestamp())
        if end_time:
            params["toTime"] = int(end_time.timestamp())

        try:
            data = await self._api("SYNO.SurveillanceStation.Recording", "List", 6, **params)
            if not data.get("success"):
                return []

            clips: list[Clip] = []
            for rec in data.get("data", {}).get("recordings", []):
                rec_cam_id = str(rec.get("camera_id") or rec.get("cameraId") or camera_id or "")
                rec_id = str(rec.get("id") or rec.get("recId") or "")
                start_ts = rec.get("startTime") or rec.get("start_time") or 0
                stop_ts = rec.get("stopTime") or rec.get("stop_time") or start_ts
                download = (
                    f"{self.host}/webapi/entry.cgi?api=SYNO.SurveillanceStation.Recording"
                    f"&method=Download&version=6&id={rec_id}"
                    # Callers must append &_sid=<sid> — not embedded here to avoid token leakage.
                )
                clips.append(
                    Clip(
                        id=rec_id,
                        camera_id=rec_cam_id,
                        camera_name=rec.get("camera_name") or f"Camera {rec_cam_id}",
                        start_time=datetime.fromtimestamp(int(start_ts), tz=timezone.utc),
                        end_time=datetime.fromtimestamp(int(stop_ts), tz=timezone.utc),
                        download_url=download,
                        size_bytes=rec.get("size"),
                        metadata={"source": "synology", "reason": rec.get("reason")},
                    )
                )
            return clips
        except Exception as exc:
            logger.error("Failed to fetch Synology recordings: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        """Return the GetSnapshot URL for a camera."""
        if not camera_id and camera_name:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id
        if not camera_id:
            return None
        sid = self._sid or ""
        return (
            f"{self.host}/webapi/entry.cgi?api=SYNO.SurveillanceStation.Camera"
            f"&method=GetSnapshot&version=9&id={camera_id}&_sid={sid}"
        )

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo | None:
        """Retrieve system info via SYNO.SurveillanceStation.Info / GetInfo."""
        try:
            data = await self._api("SYNO.SurveillanceStation.Info", "GetInfo", 8)
            if not data.get("success"):
                return None
            info = data.get("data", {})
            cameras = await self.list_cameras()
            return SystemInfo(
                system_name=info.get("hostname") or "Synology Surveillance Station",
                version=info.get("version", {}).get("build") or info.get("version"),
                camera_count=len(cameras),
                metadata={
                    "source": "synology",
                    "path": info.get("path"),
                    "cms_enabled": info.get("cms_enabled"),
                },
            )
        except Exception as exc:
            logger.error("Failed to get Synology system info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if the SYNO.API.Info query endpoint responds."""
        try:
            r = await self._client.get(
                f"{self.host}/webapi/query.cgi",
                params={"api": "SYNO.API.Info", "version": "1", "method": "query"},
            )
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_event_type(reason: Any) -> EventType:
        """Map Synology event reason codes to cctvQL EventType."""
        # Synology reason codes (abbreviated): 1=continuous, 2=motion,
        # 3=digital input, 4=manual, 5=external, 6=analytics, 7=audio
        mapping = {
            2: EventType.MOTION,
            6: EventType.OBJECT_DETECTED,
            7: EventType.AUDIO,
        }
        try:
            return mapping.get(int(reason), EventType.UNKNOWN)
        except (TypeError, ValueError):
            return EventType.UNKNOWN
