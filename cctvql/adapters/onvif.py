"""
cctvQL — ONVIF Adapter
-----------------------
Generic adapter for any ONVIF-compliant IP camera or NVR.
ONVIF is supported by most major brands: Hikvision, Dahua, Axis,
Bosch, Hanwha, Sony, and thousands of others.

Requires: onvif-zeep  (pip install onvif-zeep)
Docs: https://www.onvif.org/profiles/

Supported ONVIF Profiles:
  - Profile S: Live streaming, PTZ
  - Profile G: Recording and replay (clips)
  - Profile T: Advanced video streaming
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

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


class ONVIFAdapter(BaseAdapter):
    """
    Generic ONVIF adapter. Connects to a single ONVIF device (NVR or camera).

    Args:
        host:     IP/hostname of the ONVIF device
        port:     ONVIF service port (default 80)
        username: ONVIF credentials
        password: ONVIF credentials
        wsdl_dir: Path to ONVIF WSDL files (optional, uses bundled wsdl from onvif-zeep)

    Usage:
        adapter = ONVIFAdapter(host="192.168.1.200", username="admin", password="pass")
        await adapter.connect()
    """

    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str = "admin",
        password: str = "",
        wsdl_dir: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.wsdl_dir = wsdl_dir
        self._camera: Any = None          # onvif.ONVIFCamera
        self._media_service: Any = None
        self._device_service: Any = None
        self._profiles: list[Any] = []

    @property
    def name(self) -> str:
        return "onvif"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        try:
            import asyncio

            from onvif import ONVIFCamera

            kwargs: dict = dict(
                host=self.host,
                port=self.port,
                user=self.username,
                passwd=self.password,
            )
            if self.wsdl_dir:
                kwargs["wsdl_dir"] = self.wsdl_dir

            # onvif-zeep is partially sync; run in executor for async compat
            loop = asyncio.get_event_loop()
            self._camera = await loop.run_in_executor(
                None, lambda: ONVIFCamera(**kwargs)
            )

            self._media_service = await loop.run_in_executor(
                None, self._camera.create_media_service
            )
            self._device_service = await loop.run_in_executor(
                None, self._camera.create_devicemgmt_service
            )

            self._profiles = await loop.run_in_executor(
                None, self._media_service.GetProfiles
            )

            logger.info(
                "Connected to ONVIF device at %s:%d (%d profiles)",
                self.host, self.port, len(self._profiles),
            )
            return True

        except ImportError:
            logger.error(
                "onvif-zeep not installed. Run: pip install onvif-zeep"
            )
            return False
        except Exception as exc:
            logger.error("ONVIF connect failed: %s", exc)
            return False

    async def disconnect(self) -> None:
        self._camera = None
        self._media_service = None
        self._profiles = []

    # ------------------------------------------------------------------
    # Cameras — ONVIF profiles map to camera channels
    # ------------------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        if not self._profiles:
            return []

        cameras = []
        for idx, profile in enumerate(self._profiles):
            token = profile.token
            name = getattr(profile, "Name", f"Channel {idx + 1}")

            snapshot_url = await self._get_snapshot_url_for_token(token)
            stream_url = await self._get_stream_url_for_token(token)

            cameras.append(Camera(
                id=token,
                name=name,
                status=CameraStatus.ONLINE,
                snapshot_url=snapshot_url,
                stream_url=stream_url,
                metadata={"profile_token": token, "source": "onvif"},
            ))
        return cameras

    async def get_camera(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> Camera | None:
        cameras = await self.list_cameras()
        for cam in cameras:
            if camera_id and cam.id == camera_id:
                return cam
            if camera_name and cam.name.lower() == camera_name.lower():
                return cam
        return None

    # ------------------------------------------------------------------
    # Events — via ONVIF Event Service
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
        """
        ONVIF event retrieval via PullPoint subscription.
        Note: Not all ONVIF devices support full event history.
        Profile G devices support recording search.
        """
        try:
            import asyncio
            loop = asyncio.get_event_loop()

            event_service = await loop.run_in_executor(
                None, self._camera.create_events_service
            )
            await loop.run_in_executor(
                None, event_service.CreatePullPointSubscription,
                {"InitialTerminationTime": "PT1M"},
            )
            pull_service = await loop.run_in_executor(
                None, self._camera.create_pullpoint_service
            )
            messages = await loop.run_in_executor(
                None,
                lambda: pull_service.PullMessages({
                    "MessageLimit": limit,
                    "Timeout": "PT5S",
                })
            )

            events = []
            for msg in getattr(messages, "NotificationMessage", []):
                event = self._parse_onvif_event(msg, camera_id or camera_name or self.host)
                events.append(event)

            return events[:limit]

        except Exception as exc:
            logger.warning("ONVIF event pull failed: %s", exc)
            return []

    async def get_event(self, event_id: str) -> Event | None:
        # ONVIF doesn't have a single-event lookup — not universally supported
        return None

    # ------------------------------------------------------------------
    # Clips — Profile G recording search
    # ------------------------------------------------------------------

    async def get_clips(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Clip]:
        """
        Search for recordings via ONVIF Profile G (Recording Search service).
        Falls back to empty list if device doesn't support Profile G.
        """
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            search_service = await loop.run_in_executor(
                None, self._camera.create_recording_service
            )
            now = datetime.now(timezone.utc)
            search_params = {
                "SearchScope": {},
                "StartPoint": (start_time or now).isoformat(),
                "EndPoint": (end_time or now).isoformat(),
                "MaxResults": limit,
            }
            result = await loop.run_in_executor(
                None, lambda: search_service.FindRecordings(search_params)
            )
            clips = []
            token = result.SearchToken if hasattr(result, "SearchToken") else None
            if token:
                recordings = await loop.run_in_executor(
                    None,
                    lambda: search_service.GetRecordingSearchResults({
                        "SearchToken": token,
                        "MaxResults": limit,
                        "WaitTime": "PT5S",
                    })
                )
                for rec in getattr(recordings, "RecordingInformation", []):
                    clips.append(self._parse_recording(rec))
            return clips
        except Exception as exc:
            logger.debug("ONVIF recording search not supported: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        cam = await self.get_camera(camera_id=camera_id, camera_name=camera_name)
        if cam:
            return cam.snapshot_url
        if self._profiles:
            return await self._get_snapshot_url_for_token(self._profiles[0].token)
        return None

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo | None:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                None, self._device_service.GetDeviceInformation
            )
            return SystemInfo(
                system_name=(
                    f"{getattr(info, 'Manufacturer', 'ONVIF')} {getattr(info, 'Model', 'Device')}"
                ),
                version=getattr(info, "FirmwareVersion", None),
                camera_count=len(self._profiles),
                metadata={
                    "serial": getattr(info, "SerialNumber", ""),
                    "hardware_id": getattr(info, "HardwareId", ""),
                },
            )
        except Exception as exc:
            logger.error("ONVIF device info failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_snapshot_url_for_token(self, token: str) -> str | None:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            uri = await loop.run_in_executor(
                None,
                lambda: self._media_service.GetSnapshotUri({"ProfileToken": token})
            )
            return getattr(uri, "Uri", None)
        except Exception:
            return None

    async def _get_stream_url_for_token(self, token: str) -> str | None:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            uri = await loop.run_in_executor(
                None,
                lambda: self._media_service.GetStreamUri({
                    "StreamSetup": {
                        "Stream": "RTP-Unicast",
                        "Transport": {"Protocol": "RTSP"},
                    },
                    "ProfileToken": token,
                })
            )
            return getattr(uri, "Uri", None)
        except Exception:
            return None

    def _parse_onvif_event(self, msg: Any, camera_ref: str) -> Event:
        now = datetime.now()
        return Event(
            id=str(id(msg)),
            camera_id=camera_ref,
            camera_name=camera_ref,
            event_type=EventType.UNKNOWN,
            start_time=now,
            metadata={"raw": str(msg)},
        )

    def _parse_recording(self, rec: Any) -> Clip:
        token = getattr(rec, "RecordingToken", str(id(rec)))
        earliest = getattr(rec, "EarliestRecording", datetime.now())
        latest = getattr(rec, "LatestRecording", datetime.now())
        return Clip(
            id=token,
            camera_id=self.host,
            camera_name=f"{self.host} — Recording",
            start_time=earliest if isinstance(earliest, datetime) else datetime.now(),
            end_time=latest if isinstance(latest, datetime) else datetime.now(),
            metadata={"recording_token": token},
        )

    async def health_check(self) -> bool:
        return self._camera is not None
