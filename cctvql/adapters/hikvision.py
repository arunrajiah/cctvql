"""
cctvQL — Hikvision ISAPI Adapter
----------------------------------
Connects to a Hikvision NVR via its ISAPI REST interface.
Hikvision ISAPI docs: http://<host>/ISAPI/

Supports:
  - Listing cameras/channels from InputProxy
  - Querying recorded video segments via CMSearchDescription
  - Snapshots per channel
  - Device and system info
  - Health checks via deviceInfo endpoint
"""

from __future__ import annotations

import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime

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

# Hikvision ISAPI XML namespace
_NS = "http://www.hikvision.com/ver20/XMLSchema"
_NS_MAP = {"hik": _NS}


def _find(element: ET.Element, tag: str) -> ET.Element | None:
    """Find a child element using the Hikvision namespace."""
    return element.find(f"{{{_NS}}}{tag}")


def _findtext(element: ET.Element, tag: str, default: str = "") -> str:
    """Get text of a child element using the Hikvision namespace."""
    el = _find(element, tag)
    return (el.text or default) if el is not None else default


class HikvisionAdapter(BaseAdapter):
    """
    Adapter for Hikvision NVR via ISAPI.

    Args:
        host:          Base URL of the NVR, e.g. http://192.168.1.64
        username:      ISAPI username (default: admin)
        password:      ISAPI password
        channel_count: Optional hint for number of channels; auto-detected if None
        api_timeout:   HTTP request timeout in seconds

    Usage:
        adapter = HikvisionAdapter(host="http://192.168.1.64", username="admin", password="pass")
        await adapter.connect()
    """

    def __init__(
        self,
        host: str = "http://192.168.1.100",
        username: str = "admin",
        password: str = "",
        channel_count: int | None = None,
        api_timeout: float = 30.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        self.channel_count = channel_count
        self._auth = httpx.DigestAuth(username, password)
        self._client = httpx.AsyncClient(
            auth=self._auth,
            timeout=api_timeout,
            verify=False,  # Many Hikvision devices use self-signed certs
        )
        self._device_info: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "hikvision"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Connect and read device info from /ISAPI/System/deviceInfo."""
        try:
            r = await self._client.get(f"{self.host}/ISAPI/System/deviceInfo")
            r.raise_for_status()
            root = ET.fromstring(r.text)
            self._device_info = {
                "model": _findtext(root, "model"),
                "serialNumber": _findtext(root, "serialNumber"),
                "firmwareVersion": _findtext(root, "firmwareVersion"),
                "deviceName": _findtext(root, "deviceName"),
                "deviceType": _findtext(root, "deviceType"),
            }
            logger.info(
                "Connected to Hikvision %s (model=%s, fw=%s) at %s",
                self._device_info.get("deviceName"),
                self._device_info.get("model"),
                self._device_info.get("firmwareVersion"),
                self.host,
            )
            return True
        except Exception as exc:
            logger.error("Failed to connect to Hikvision NVR: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        """
        List cameras from /ISAPI/ContentMgmt/InputProxy/channels.
        Parses the <InputProxyChannelList> XML response.
        """
        try:
            r = await self._client.get(f"{self.host}/ISAPI/ContentMgmt/InputProxy/channels")
            r.raise_for_status()
            root = ET.fromstring(r.text)

            cameras: list[Camera] = []
            # Elements may appear with or without namespace
            channels = root.findall(f"{{{_NS}}}InputProxyChannel") or root.findall(
                "InputProxyChannel"
            )

            for ch in channels:
                _id_el = ch.find("id")
                ch_id: str = _findtext(ch, "id") or (
                    (_id_el.text or "") if _id_el is not None else ""
                )
                _name_el = ch.find("name")
                _fallback_name = f"Channel {ch_id}"
                ch_name: str = _findtext(ch, "name") or (
                    (_name_el.text or _fallback_name) if _name_el is not None else _fallback_name
                )
                # status element may be nested under sourceInputPortDescriptor
                status_text = _findtext(ch, "online") or ""
                status = (
                    CameraStatus.ONLINE
                    if status_text.lower() in ("true", "1", "yes")
                    else CameraStatus.UNKNOWN
                )

                # Build the channel streaming ID: channel ID padded, main stream = 01
                stream_ch_id = ch_id.zfill(2) if ch_id.isdigit() else ch_id
                snapshot_url = f"{self.host}/ISAPI/Streaming/channels/{stream_ch_id}01/picture"

                cameras.append(
                    Camera(
                        id=ch_id,
                        name=ch_name,
                        status=status,
                        snapshot_url=snapshot_url,
                        stream_url=f"{self.host}/ISAPI/Streaming/channels/{stream_ch_id}01",
                        metadata={"raw_id": ch_id},
                    )
                )

            # If channel_count hint was given and no cameras found via API, build stubs
            if not cameras and self.channel_count:
                for i in range(1, self.channel_count + 1):
                    ch_id = str(i)
                    stream_ch_id = ch_id.zfill(2)
                    cameras.append(
                        Camera(
                            id=ch_id,
                            name=f"Channel {i}",
                            status=CameraStatus.UNKNOWN,
                            snapshot_url=f"{self.host}/ISAPI/Streaming/channels/{stream_ch_id}01/picture",
                            stream_url=f"{self.host}/ISAPI/Streaming/channels/{stream_ch_id}01",
                        )
                    )

            return cameras
        except Exception as exc:
            logger.error("Failed to list Hikvision cameras: %s", exc)
            return []

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
        Search for events via POST /ISAPI/ContentMgmt/search.

        Hikvision event history search uses a CMSearchDescription XML body.
        Falls back gracefully to an empty list if the NVR does not support
        event-type searches (some models only support video segment searches).
        """
        now = datetime.now()
        t_start = start_time or datetime(now.year, now.month, now.day, 0, 0, 0)
        t_end = end_time or now

        # Resolve camera ID if only name was given
        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        track_id = f"{camera_id.zfill(2)}01" if camera_id else "101"

        xml_body = self._build_search_xml(
            track_id=track_id,
            start_time=t_start,
            end_time=t_end,
            search_result_position=0,
            max_results=limit,
            content_type="metadata",  # request motion/event metadata
        )

        try:
            r = await self._client.post(
                f"{self.host}/ISAPI/ContentMgmt/search",
                content=xml_body,
                headers={"Content-Type": "application/xml"},
            )
            r.raise_for_status()
            return self._parse_search_events(r.text, camera_id or "unknown")
        except Exception as exc:
            logger.warning("Hikvision event search failed (%s); returning empty list.", exc)
            return []

    async def get_event(self, event_id: str) -> Event | None:
        """
        Look up a specific event by ID.
        Scans recent events from the last 24 hours to find a matching ID.
        """
        events = await self.get_events(limit=100)
        for ev in events:
            if ev.id == event_id:
                return ev
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
        Search for recorded video clips via POST /ISAPI/ContentMgmt/search
        using a CMSearchDescription XML body with contentType=video.
        """
        now = datetime.now()
        t_start = start_time or datetime(now.year, now.month, now.day, 0, 0, 0)
        t_end = end_time or now

        if camera_name and not camera_id:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        track_id = f"{camera_id.zfill(2)}01" if camera_id else "101"

        xml_body = self._build_search_xml(
            track_id=track_id,
            start_time=t_start,
            end_time=t_end,
            search_result_position=0,
            max_results=limit,
            content_type="video",
        )

        try:
            r = await self._client.post(
                f"{self.host}/ISAPI/ContentMgmt/search",
                content=xml_body,
                headers={"Content-Type": "application/xml"},
            )
            r.raise_for_status()
            return self._parse_search_clips(
                r.text,
                camera_id=camera_id or "unknown",
                camera_name=camera_name or camera_id or "unknown",
            )
        except Exception as exc:
            logger.error("Hikvision clip search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        """
        Return snapshot URL for /ISAPI/Streaming/channels/<id>01/picture.
        Resolves channel ID from name if needed.
        """
        if not camera_id and camera_name:
            cam = await self.get_camera(camera_name=camera_name)
            if cam:
                camera_id = cam.id

        if not camera_id:
            # Default to channel 1
            camera_id = "1"

        stream_ch_id = camera_id.zfill(2) if camera_id.isdigit() else camera_id
        return f"{self.host}/ISAPI/Streaming/channels/{stream_ch_id}01/picture"

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> SystemInfo | None:
        """
        Retrieve device info from /ISAPI/System/deviceInfo and
        system status from /ISAPI/System/status.
        """
        try:
            r_info = await self._client.get(f"{self.host}/ISAPI/System/deviceInfo")
            r_info.raise_for_status()
            root_info = ET.fromstring(r_info.text)

            model = _findtext(root_info, "model")
            firmware = _findtext(root_info, "firmwareVersion")
            device_name = _findtext(root_info, "deviceName") or "Hikvision NVR"

            # System status — optional, may not be present on all models
            uptime: int | None = None
            try:
                r_status = await self._client.get(f"{self.host}/ISAPI/System/status")
                r_status.raise_for_status()
                root_status = ET.fromstring(r_status.text)
                _findtext(root_status, "currentDeviceTime")
                # uptime is not always directly available; skip for now
            except Exception:
                pass

            cameras = await self.list_cameras()

            return SystemInfo(
                system_name=device_name,
                version=firmware or None,
                camera_count=len(cameras),
                uptime_seconds=uptime,
                metadata={
                    "model": model,
                    "firmware": firmware,
                    "host": self.host,
                },
            )
        except Exception as exc:
            logger.error("Failed to get Hikvision system info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return True if /ISAPI/System/deviceInfo responds with HTTP 200."""
        try:
            r = await self._client.get(f"{self.host}/ISAPI/System/deviceInfo")
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # PTZ control
    # ------------------------------------------------------------------

    async def ptz_move(self, camera_name: str, action: str, speed: int = 50) -> bool:
        """
        Pan/tilt/zoom via ISAPI PTZCtrl continuous endpoint.

        Args:
            camera_name: Camera name or channel ID.
            action:      left|right|up|down|zoom_in|zoom_out|stop
            speed:       1–100

        Returns:
            True if command accepted.
        """
        cam = await self.get_camera(camera_name=camera_name)
        channel = cam.id if cam else "1"
        channel = channel.zfill(2) if channel.isdigit() else channel

        # Map action to PTZ values (pan, tilt, zoom)
        action_map: dict[str, tuple[int, int, int]] = {
            "left": (-speed, 0, 0),
            "right": (speed, 0, 0),
            "up": (0, speed, 0),
            "down": (0, -speed, 0),
            "zoom_in": (0, 0, speed),
            "zoom_out": (0, 0, -speed),
            "stop": (0, 0, 0),
        }
        pan, tilt, zoom = action_map.get(action.lower(), (0, 0, 0))

        xml_body = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<PTZData xmlns="{_NS}">'
            f"<pan>{pan}</pan>"
            f"<tilt>{tilt}</tilt>"
            f"<zoom>{zoom}</zoom>"
            f"</PTZData>"
        )
        try:
            r = await self._client.put(
                f"{self.host}/ISAPI/PTZCtrl/channels/{channel}01/continuous",
                content=xml_body.encode(),
                headers={"Content-Type": "application/xml"},
            )
            return r.status_code in (200, 204)
        except Exception as exc:
            logger.warning("Hikvision PTZ move failed: %s", exc)
            return False

    async def ptz_preset(self, camera_name: str, preset_id: int) -> bool:
        """
        Go to a PTZ preset via ISAPI PTZCtrl presets/goto endpoint.

        Returns:
            True if command accepted.
        """
        cam = await self.get_camera(camera_name=camera_name)
        channel = cam.id if cam else "1"
        channel = channel.zfill(2) if channel.isdigit() else channel

        try:
            r = await self._client.put(
                f"{self.host}/ISAPI/PTZCtrl/channels/{channel}01/presets/{preset_id}/goto",
            )
            return r.status_code in (200, 204)
        except Exception as exc:
            logger.warning("Hikvision PTZ preset failed: %s", exc)
            return False

    async def get_ptz_presets(self, camera_name: str) -> list[dict]:
        """
        List PTZ presets from ISAPI.

        Returns:
            list of {"id": int, "name": str} dicts.
        """
        cam = await self.get_camera(camera_name=camera_name)
        channel = cam.id if cam else "1"
        channel = channel.zfill(2) if channel.isdigit() else channel

        try:
            r = await self._client.get(f"{self.host}/ISAPI/PTZCtrl/channels/{channel}01/presets")
            r.raise_for_status()
            root = ET.fromstring(r.text)
            presets = []
            for preset in root.findall(f".//{{{_NS}}}PTZPreset") or root.findall(".//PTZPreset"):
                preset_id_el = preset.find(f"{{{_NS}}}id") or preset.find("id")
                preset_name_el = preset.find(f"{{{_NS}}}presetName") or preset.find("presetName")
                if preset_id_el is not None:
                    presets.append(
                        {
                            "id": int(preset_id_el.text or 0),
                            "name": (preset_name_el.text if preset_name_el is not None else ""),
                        }
                    )
            return presets
        except Exception as exc:
            logger.warning("Hikvision get_ptz_presets failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_time(dt: datetime) -> str:
        """Format datetime as Hikvision ISAPI time string: 2024-01-15T08:30:00+00:00"""
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    def _build_search_xml(
        self,
        track_id: str,
        start_time: datetime,
        end_time: datetime,
        search_result_position: int,
        max_results: int,
        content_type: str = "video",
    ) -> bytes:
        """Build a CMSearchDescription XML body for ISAPI content search."""
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<CMSearchDescription xmlns="{_NS}">
  <searchID>{uuid.uuid4()}</searchID>
  <trackList>
    <trackID>{track_id}</trackID>
  </trackList>
  <timeSpanList>
    <timeSpan>
      <startTime>{self._fmt_time(start_time)}</startTime>
      <endTime>{self._fmt_time(end_time)}</endTime>
    </timeSpan>
  </timeSpanList>
  <maxResults>{max_results}</maxResults>
  <searchResultPostion>{search_result_position}</searchResultPostion>
  <metadataList>
    <metadataDescriptor>//recordType.meta.std-cgi.com/{content_type}</metadataDescriptor>
  </metadataList>
</CMSearchDescription>"""
        return xml.encode("utf-8")

    def _parse_search_events(self, xml_text: str, camera_id: str) -> list[Event]:
        """Parse CMSearchResult XML into a list of Event objects."""
        events: list[Event] = []
        try:
            root = ET.fromstring(xml_text)
            match_list = root.findall(f".//{{{_NS}}}matchElement") or root.findall(
                ".//matchElement"
            )
            for idx, match in enumerate(match_list):
                start_str = _findtext(match, "startTime") or (match.findtext("startTime") or "")
                end_str = _findtext(match, "endTime") or (match.findtext("endTime") or "")
                source_id = _findtext(match, "sourceID") or (
                    match.findtext("sourceID") or camera_id
                )

                start_dt = self._parse_isapi_time(start_str)
                end_dt = self._parse_isapi_time(end_str) if end_str else None

                event_id = f"hik-{source_id}-{idx}-{int(start_dt.timestamp())}"

                events.append(
                    Event(
                        id=event_id,
                        camera_id=camera_id,
                        camera_name=f"Channel {camera_id}",
                        event_type=EventType.MOTION,
                        start_time=start_dt,
                        end_time=end_dt,
                        metadata={"source_id": source_id},
                    )
                )
        except Exception as exc:
            logger.warning("Failed to parse Hikvision event results: %s", exc)
        return events

    def _parse_search_clips(self, xml_text: str, camera_id: str, camera_name: str) -> list[Clip]:
        """Parse CMSearchResult XML into a list of Clip objects."""
        clips: list[Clip] = []
        try:
            root = ET.fromstring(xml_text)
            match_list = root.findall(f".//{{{_NS}}}matchElement") or root.findall(
                ".//matchElement"
            )
            for idx, match in enumerate(match_list):
                start_str = _findtext(match, "startTime") or (match.findtext("startTime") or "")
                end_str = _findtext(match, "endTime") or (match.findtext("endTime") or "")
                media_segment_descriptor = _find(match, "mediaSegmentDescriptor") or match.find(
                    "mediaSegmentDescriptor"
                )
                playback_uri = ""
                if media_segment_descriptor is not None:
                    playback_uri = _findtext(media_segment_descriptor, "playbackURI") or (
                        media_segment_descriptor.findtext("playbackURI") or ""
                    )

                start_dt = self._parse_isapi_time(start_str)
                end_dt = self._parse_isapi_time(end_str) if end_str else start_dt

                clip_id = f"hik-clip-{camera_id}-{idx}-{int(start_dt.timestamp())}"

                clips.append(
                    Clip(
                        id=clip_id,
                        camera_id=camera_id,
                        camera_name=camera_name,
                        start_time=start_dt,
                        end_time=end_dt,
                        download_url=playback_uri or None,
                        metadata={"playback_uri": playback_uri},
                    )
                )
        except Exception as exc:
            logger.warning("Failed to parse Hikvision clip results: %s", exc)
        return clips

    @staticmethod
    def _parse_isapi_time(time_str: str) -> datetime:
        """Parse Hikvision ISAPI time string into a datetime object."""
        if not time_str:
            return datetime.now()
        # Handle formats: 2024-01-15T08:30:00+00:00 or 2024-01-15T08:30:00Z
        time_str = time_str.replace("Z", "+00:00")
        try:
            # Python 3.11+ handles +00:00 natively via fromisoformat
            return datetime.fromisoformat(time_str)
        except ValueError:
            pass
        # Fallback: strip timezone and parse naively
        try:
            return datetime.strptime(time_str[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            logger.warning("Could not parse Hikvision time string: %s", time_str)
            return datetime.now()
