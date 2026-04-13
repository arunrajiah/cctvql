"""
cctvQL — Dahua CGI/HTTP Adapter
---------------------------------
Connects to a Dahua NVR via its HTTP CGI interface.
Dahua SDK docs: http://<host>/cgi-bin/

Supports:
  - Device type and firmware version queries
  - Channel/camera enumeration
  - Recording search via recordFinder
  - Snapshots per channel
  - System info aggregation
  - Health checks
"""

from __future__ import annotations

import logging
from datetime import datetime
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


def _parse_dahua(text: str) -> dict[str, str]:
    """
    Parse a Dahua CGI key=value response body into a dictionary.

    Example input::

        table.DeviceType=NVR4104HS-P-4KS3
        table.SoftwareVersion=V2.820.00KI003.0
        Error.Code=0

    Returns a flat dict with the raw keys preserved.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


class DahuaAdapter(BaseAdapter):
    """
    Adapter for Dahua NVR via the HTTP CGI API.

    Args:
        host:          NVR hostname or IP address (without http://)
        port:          HTTP port (default: 80)
        username:      CGI username (default: admin)
        password:      CGI password
        channel_count: Number of channels to enumerate (default: 4)
        api_timeout:   HTTP request timeout in seconds

    Usage:
        adapter = DahuaAdapter(host="192.168.1.108", username="admin", password="pass")
        await adapter.connect()
    """

    def __init__(
        self,
        host: str = "192.168.1.100",
        port: int = 80,
        username: str = "admin",
        password: str = "",
        channel_count: int = 4,
        api_timeout: float = 30.0,
    ) -> None:
        # Normalise host — strip any scheme the caller may have passed
        host = host.replace("http://", "").replace("https://", "").rstrip("/")
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.username = username
        self.password = password
        self.channel_count = channel_count
        self._auth = httpx.DigestAuth(username, password)
        self._client = httpx.AsyncClient(
            auth=self._auth,
            timeout=api_timeout,
        )
        self._device_type: str = ""

    @property
    def name(self) -> str:
        return "dahua"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect and verify by querying the device type CGI endpoint."""
        try:
            r = await self._client.get(
                f"{self.base_url}/cgi-bin/magicBox.cgi",
                params={"action": "getDeviceType"},
            )
            r.raise_for_status()
            data = _parse_dahua(r.text)
            self._device_type = data.get("type", data.get("table.DeviceType", ""))
            logger.info("Connected to Dahua NVR (type=%s) at %s", self._device_type, self.base_url)
            return True
        except Exception as exc:
            logger.error("Failed to connect to Dahua NVR: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        """
        Enumerate channels 1..channel_count.

        Dahua does not have a single endpoint that lists all channels with their
        status, so we probe each channel's snapshot URL and mark it ONLINE if it
        responds with a 200. Falls back to UNKNOWN on error.
        """
        cameras: list[Camera] = []
        for ch in range(1, self.channel_count + 1):
            ch_str = str(ch)
            snapshot_url = f"{self.base_url}/cgi-bin/snapshot.cgi?channel={ch}"

            # Probe the channel — a 200 means the channel is active
            status = CameraStatus.UNKNOWN
            try:
                r = await self._client.get(snapshot_url, timeout=5.0)
                if r.status_code == 200:
                    status = CameraStatus.ONLINE
                elif r.status_code in (404, 503):
                    status = CameraStatus.OFFLINE
            except Exception:
                pass

            cameras.append(
                Camera(
                    id=ch_str,
                    name=f"Channel {ch}",
                    status=status,
                    snapshot_url=snapshot_url,
                    metadata={"channel": ch},
                )
            )
        return cameras

    async def get_camera(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> Camera | None:
        """Retrieve a single camera by ID or name."""
        cameras = await self.list_cameras()
        for cam in cameras:
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
        """
        Fetch motion/detection events via recordFinder.cgi.

        Dahua's recordFinder returns video file records; each record is treated
        as a motion event here, since Dahua NVRs typically record on motion.
        EventType is set to MOTION for all results.
        """
        now = datetime.now()
        t_start = start_time or datetime(now.year, now.month, now.day, 0, 0, 0)
        t_end = end_time or now

        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        # Dahua channels are 0-indexed in some APIs; recordFinder uses 1-based
        channel = int(camera_id) if camera_id and camera_id.isdigit() else 0

        params: dict[str, Any] = {
            "action": "find",
            "channel": channel,
            "startTime": self._fmt_time(t_start),
            "endTime": self._fmt_time(t_end),
            "count": limit,
            "fileType": "dav",
        }

        events: list[Event] = []
        try:
            r = await self._client.get(
                f"{self.base_url}/cgi-bin/recordFinder.cgi",
                params=params,
            )
            r.raise_for_status()
            records = self._parse_record_finder(r.text)
            for idx, rec in enumerate(records[:limit]):
                start_dt = self._parse_dahua_time(rec.get("StartTime", ""))
                end_dt = self._parse_dahua_time(rec.get("EndTime", ""))
                cam_id = str(rec.get("Channel", camera_id or "0"))
                event_id = f"dahua-evt-{cam_id}-{idx}-{int(start_dt.timestamp())}"

                events.append(
                    Event(
                        id=event_id,
                        camera_id=cam_id,
                        camera_name=f"Channel {cam_id}",
                        event_type=EventType.MOTION,
                        start_time=start_dt,
                        end_time=end_dt if end_dt != start_dt else None,
                        metadata={k: v for k, v in rec.items()},
                    )
                )
        except Exception as exc:
            logger.error("Dahua event search failed: %s", exc)

        return events

    async def get_event(self, event_id: str) -> Event | None:
        """
        Single-event lookup is not supported by the Dahua CGI API.
        Returns None always.
        """
        logger.debug("Dahua does not support single-event lookup by ID.")
        return None

    # ------------------------------------------------------------------
    # Clips
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
        Fetch recorded video clips via recordFinder.cgi.

        Returned download URLs point to the Dahua playback stream URI.
        Note: Actual .dav file download requires a separate authenticated
        request to /cgi-bin/RPC_Loadfile/ with the file path.
        """
        now = datetime.now()
        t_start = start_time or datetime(now.year, now.month, now.day, 0, 0, 0)
        t_end = end_time or now

        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        channel = int(camera_id) if camera_id and camera_id.isdigit() else 0

        params: dict[str, Any] = {
            "action": "find",
            "channel": channel,
            "startTime": self._fmt_time(t_start),
            "endTime": self._fmt_time(t_end),
            "count": limit,
            "fileType": "dav",
        }

        clips: list[Clip] = []
        try:
            r = await self._client.get(
                f"{self.base_url}/cgi-bin/recordFinder.cgi",
                params=params,
            )
            r.raise_for_status()
            records = self._parse_record_finder(r.text)
            for idx, rec in enumerate(records[:limit]):
                start_dt = self._parse_dahua_time(rec.get("StartTime", ""))
                end_dt = self._parse_dahua_time(rec.get("EndTime", ""))
                cam_id = str(rec.get("Channel", camera_id or "0"))
                clip_id = f"dahua-clip-{cam_id}-{idx}-{int(start_dt.timestamp())}"
                file_path = rec.get("FilePath", "")

                # Build a download URL using the Dahua loadfile endpoint
                download_url: str | None = None
                if file_path:
                    download_url = f"{self.base_url}/cgi-bin/RPC_Loadfile{file_path}"

                clips.append(
                    Clip(
                        id=clip_id,
                        camera_id=cam_id,
                        camera_name=f"Channel {cam_id}",
                        start_time=start_dt,
                        end_time=end_dt if end_dt != start_dt else start_dt,
                        download_url=download_url,
                        size_bytes=int(rec["Size"]) if rec.get("Size", "").isdigit() else None,
                        metadata={k: v for k, v in rec.items()},
                    )
                )
        except Exception as exc:
            logger.error("Dahua clip search failed: %s", exc)

        return clips

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        """
        Return snapshot URL for /cgi-bin/snapshot.cgi?channel=<n>.

        Note: Requests to this URL require HTTP Digest authentication.
        The URL does not embed credentials; the caller must supply auth headers.
        """
        if not camera_id and camera_name:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        channel = camera_id if camera_id else "1"
        return f"{self.base_url}/cgi-bin/snapshot.cgi?channel={channel}"

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo | None:
        """
        Aggregate device type and firmware version from magicBox.cgi.
        """
        try:
            r_type = await self._client.get(
                f"{self.base_url}/cgi-bin/magicBox.cgi",
                params={"action": "getDeviceType"},
            )
            r_type.raise_for_status()
            type_data = _parse_dahua(r_type.text)

            r_ver = await self._client.get(
                f"{self.base_url}/cgi-bin/magicBox.cgi",
                params={"action": "getSoftwareVersion"},
            )
            r_ver.raise_for_status()
            ver_data = _parse_dahua(r_ver.text)

            device_type = type_data.get("type") or type_data.get("table.DeviceType") or "Dahua NVR"
            firmware = ver_data.get("version") or ver_data.get("table.SoftwareVersion") or None

            return SystemInfo(
                system_name=device_type,
                version=firmware,
                camera_count=self.channel_count,
                metadata={
                    "host": self.base_url,
                    "device_type": device_type,
                    "firmware": firmware,
                },
            )
        except Exception as exc:
            logger.error("Failed to get Dahua system info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if magicBox.cgi?action=getDeviceType responds with HTTP 200."""
        try:
            r = await self._client.get(
                f"{self.base_url}/cgi-bin/magicBox.cgi",
                params={"action": "getDeviceType"},
            )
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_time(dt: datetime) -> str:
        """Format datetime as Dahua CGI time string: 2024-01-15 08:30:00."""
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _parse_dahua_time(time_str: str) -> datetime:
        """Parse Dahua time string into a datetime object."""
        if not time_str:
            return datetime.now()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        logger.warning("Could not parse Dahua time string: %s", time_str)
        return datetime.now()

    @staticmethod
    def _parse_record_finder(text: str) -> list[dict[str, str]]:
        """
        Parse Dahua recordFinder.cgi response into a list of record dicts.

        The response looks like::

            found=3
            records[0].Channel=0
            records[0].StartTime=2024-01-15 08:00:00
            records[0].EndTime=2024-01-15 08:05:00
            records[0].FilePath=/mnt/dvr/2024-01-15/08.00.00-08.05.00[M][0@0][0].dav
            records[0].Size=12345678
            ...
        """
        raw = _parse_dahua(text)
        records: dict[int, dict[str, str]] = {}

        for key, value in raw.items():
            # Match keys like records[0].Channel
            if not key.startswith("records["):
                continue
            bracket_end = key.index("]")
            try:
                idx = int(key[8:bracket_end])
            except ValueError:
                continue
            field = key[bracket_end + 2 :]  # skip "]."
            records.setdefault(idx, {})[field] = value

        return [records[i] for i in sorted(records)]
