"""
cctvQL — Frigate Adapter
-------------------------
Connects to a Frigate NVR instance via its REST API and MQTT broker.
Frigate docs: https://docs.frigate.video/integrations/api/

Supports:
  - Listing cameras and their status
  - Querying events with filters (label, camera, time range, zone)
  - Fetching recorded clips
  - Live snapshots
  - Real-time event streaming via MQTT
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Optional

import httpx

from cctvql.adapters.base import BaseAdapter
from cctvql.core.schema import (
    BoundingBox, Camera, CameraStatus, Clip, DetectedObject,
    Event, EventType, SystemInfo, Zone,
)

logger = logging.getLogger(__name__)


class FrigateAdapter(BaseAdapter):
    """
    Adapter for Frigate NVR.

    Args:
        host:         Frigate base URL, e.g. http://192.168.1.100:5000
        mqtt_host:    MQTT broker host (optional, for real-time events)
        mqtt_port:    MQTT broker port (default 1883)
        mqtt_topic_prefix: Frigate MQTT topic prefix (default 'frigate')
        api_timeout:  HTTP request timeout in seconds

    Usage:
        adapter = FrigateAdapter(host="http://192.168.1.100:5000")
        await adapter.connect()
    """

    def __init__(
        self,
        host: str = "http://localhost:5000",
        mqtt_host: Optional[str] = None,
        mqtt_port: int = 1883,
        mqtt_topic_prefix: str = "frigate",
        api_timeout: float = 30.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_topic_prefix = mqtt_topic_prefix
        self._client = httpx.AsyncClient(timeout=api_timeout)
        self._mqtt_client: Any = None
        self._event_callbacks: list[Callable[[Event], None]] = []

    @property
    def name(self) -> str:
        return "frigate"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        try:
            r = await self._client.get(f"{self.host}/api/version")
            r.raise_for_status()
            version = r.json()
            logger.info("Connected to Frigate %s at %s", version, self.host)

            if self.mqtt_host:
                await self._connect_mqtt()

            return True
        except Exception as exc:
            logger.error("Failed to connect to Frigate: %s", exc)
            return False

    async def disconnect(self) -> None:
        await self._client.aclose()
        if self._mqtt_client:
            try:
                self._mqtt_client.disconnect()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Cameras
    # ------------------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        data = await self._get("/api/config")
        cameras_cfg = data.get("cameras", {})
        stats = await self._get_stats()

        cameras: list[Camera] = []
        for cam_name, cam_cfg in cameras_cfg.items():
            cam_stats = stats.get("cameras", {}).get(cam_name, {})
            status = CameraStatus.ONLINE if cam_stats.get("camera_fps", 0) > 0 else CameraStatus.OFFLINE
            zones = list(cam_cfg.get("zones", {}).keys())

            cameras.append(Camera(
                id=cam_name,
                name=cam_name,
                status=status,
                zones=zones,
                snapshot_url=f"{self.host}/api/{cam_name}/latest.jpg",
                stream_url=f"{self.host}/live/{cam_name}",
                metadata={"detect": cam_cfg.get("detect", {})}
            ))
        return cameras

    async def get_camera(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
    ) -> Optional[Camera]:
        name = camera_name or camera_id
        cameras = await self.list_cameras()
        for cam in cameras:
            if cam.name.lower() == (name or "").lower():
                return cam
        return None

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def get_events(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
        label: Optional[str] = None,
        zone: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[Event]:
        params: dict[str, Any] = {"limit": limit}

        cam = camera_name or camera_id
        if cam:
            params["camera"] = cam
        if label:
            params["label"] = label
        if zone:
            params["zone"] = zone
        if start_time:
            params["after"] = int(start_time.timestamp())
        if end_time:
            params["before"] = int(end_time.timestamp())

        data = await self._get("/api/events", params=params)
        return [self._parse_event(e) for e in data]

    async def get_event(self, event_id: str) -> Optional[Event]:
        try:
            data = await self._get(f"/api/events/{event_id}")
            return self._parse_event(data)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Clips
    # ------------------------------------------------------------------

    async def get_clips(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[Clip]:
        # Frigate exposes clips via events with has_clip=1
        params: dict[str, Any] = {"limit": limit, "has_clip": 1}
        cam = camera_name or camera_id
        if cam:
            params["camera"] = cam
        if start_time:
            params["after"] = int(start_time.timestamp())
        if end_time:
            params["before"] = int(end_time.timestamp())

        data = await self._get("/api/events", params=params)
        clips = []
        for e in data:
            event = self._parse_event(e)
            if event.clip_url and event.end_time:
                clips.append(Clip(
                    id=event.id,
                    camera_id=event.camera_id,
                    camera_name=event.camera_name,
                    start_time=event.start_time,
                    end_time=event.end_time,
                    download_url=event.clip_url,
                    thumbnail_url=event.thumbnail_url,
                ))
        return clips

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
    ) -> Optional[str]:
        name = camera_name or camera_id
        if not name:
            return None
        return f"{self.host}/api/{name}/latest.jpg"

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    async def get_system_info(self) -> Optional[SystemInfo]:
        try:
            version_data = await self._get("/api/version")
            stats = await self._get_stats()
            config = await self._get("/api/config")

            service_stats = stats.get("service", {})
            storage = stats.get("storage", {})
            total_used = sum(v.get("used", 0) for v in storage.values())
            total_size = sum(v.get("total", 0) for v in storage.values())

            return SystemInfo(
                system_name="Frigate",
                version=str(version_data),
                camera_count=len(config.get("cameras", {})),
                storage_used_bytes=int(total_used * 1e9) if total_used else None,
                storage_total_bytes=int(total_size * 1e9) if total_size else None,
                uptime_seconds=int(service_stats.get("uptime", 0)),
            )
        except Exception as exc:
            logger.error("Could not fetch system info: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Zones
    # ------------------------------------------------------------------

    async def list_zones(self, camera_id: Optional[str] = None) -> list[Zone]:
        config = await self._get("/api/config")
        zones = []
        for cam_name, cam_cfg in config.get("cameras", {}).items():
            if camera_id and cam_name != camera_id:
                continue
            for zone_name, zone_cfg in cam_cfg.get("zones", {}).items():
                coords = zone_cfg.get("coordinates", "")
                parsed_coords = self._parse_coords(coords)
                zones.append(Zone(
                    id=f"{cam_name}_{zone_name}",
                    name=zone_name,
                    camera_id=cam_name,
                    coordinates=parsed_coords,
                ))
        return zones

    # ------------------------------------------------------------------
    # MQTT real-time events
    # ------------------------------------------------------------------

    def on_event(self, callback: Callable[[Event], None]) -> None:
        """Register a callback to receive real-time events via MQTT."""
        self._event_callbacks.append(callback)

    async def _connect_mqtt(self) -> None:
        try:
            import paho.mqtt.client as mqtt

            client = mqtt.Client()
            client.on_connect = self._on_mqtt_connect
            client.on_message = self._on_mqtt_message
            client.connect(self.mqtt_host, self.mqtt_port, 60)
            client.loop_start()
            self._mqtt_client = client
            logger.info("MQTT connected to %s:%d", self.mqtt_host, self.mqtt_port)
        except ImportError:
            logger.warning("paho-mqtt not installed. Real-time MQTT events disabled.")
        except Exception as exc:
            logger.warning("MQTT connection failed: %s", exc)

    def _on_mqtt_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        topic = f"{self.mqtt_topic_prefix}/events"
        client.subscribe(topic)
        logger.debug("Subscribed to MQTT topic: %s", topic)

    def _on_mqtt_message(self, client: Any, userdata: Any, msg: Any) -> None:
        import json
        try:
            payload = json.loads(msg.payload.decode())
            after = payload.get("after", {})
            event = self._parse_event(after)
            for cb in self._event_callbacks:
                cb(event)
        except Exception as exc:
            logger.warning("Failed to parse MQTT message: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        r = await self._client.get(f"{self.host}{path}", params=params)
        r.raise_for_status()
        return r.json()

    async def _get_stats(self) -> dict:
        try:
            return await self._get("/api/stats")
        except Exception:
            return {}

    def _parse_event(self, data: dict) -> Event:
        start_ts = data.get("start_time", 0)
        end_ts = data.get("end_time")

        # Build detected objects list
        objects = []
        label = data.get("label", "unknown")
        score = data.get("score") or data.get("top_score", 0.0)
        box = data.get("box") or data.get("region")

        bbox = None
        if box and len(box) == 4:
            bbox = BoundingBox(
                x_min=box[0], y_min=box[1],
                x_max=box[2], y_max=box[3],
            )
        if label:
            objects.append(DetectedObject(
                label=label,
                confidence=float(score),
                bounding_box=bbox,
            ))

        camera = data.get("camera", "unknown")
        event_id = data.get("id", "")
        zones = data.get("current_zones") or data.get("entered_zones") or []

        return Event(
            id=event_id,
            camera_id=camera,
            camera_name=camera,
            event_type=EventType.OBJECT_DETECTED if label else EventType.MOTION,
            start_time=datetime.fromtimestamp(float(start_ts)) if start_ts else datetime.now(),
            end_time=datetime.fromtimestamp(float(end_ts)) if end_ts else None,
            objects=objects,
            zones=zones if isinstance(zones, list) else [],
            snapshot_url=f"{self.host}/api/events/{event_id}/snapshot.jpg" if event_id else None,
            clip_url=f"{self.host}/api/events/{event_id}/clip.mp4" if event_id and data.get("has_clip") else None,
            thumbnail_url=f"{self.host}/api/events/{event_id}/thumbnail.jpg" if event_id else None,
            metadata={"has_clip": data.get("has_clip", False)},
        )

    @staticmethod
    def _parse_coords(coords_str: str) -> Optional[list[tuple[float, float]]]:
        """Parse Frigate zone coordinates string '0.1,0.2,0.3,0.4,...' into point pairs."""
        if not coords_str:
            return None
        try:
            values = [float(v) for v in str(coords_str).split(",")]
            return [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]
        except Exception:
            return None

    async def health_check(self) -> bool:
        try:
            await self._get("/api/version")
            return True
        except Exception:
            return False
