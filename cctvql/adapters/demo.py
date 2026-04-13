"""
cctvQL Demo Adapter
-------------------
A mock adapter that provides realistic sample data for testing and
demonstration purposes.  No real CCTV hardware or network connection
is required — all cameras, events, clips, zones, and system info are
generated deterministically so that results are reproducible across runs.

Usage:
    Set ``adapter: demo`` in your config.yaml (or pass ``--adapter demo``
    on the CLI) to activate this adapter.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cctvql.adapters.base import BaseAdapter
from cctvql.core.schema import (
    BoundingBox,
    Camera,
    CameraStatus,
    Clip,
    DetectedObject,
    Event,
    EventType,
    ObjectLabel,
    SystemInfo,
    Zone,
)

# ---------------------------------------------------------------------------
# Fixed reference time — all demo timestamps are relative to this anchor so
# the data set is fully deterministic.
# ---------------------------------------------------------------------------
_ANCHOR = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Static demo data
# ---------------------------------------------------------------------------

_CAMERAS: list[Camera] = [
    Camera(
        id="cam_front_door",
        name="Front Door",
        status=CameraStatus.ONLINE,
        location="Front porch",
        snapshot_url="http://demo.local/snapshots/front_door.jpg",
        stream_url="rtsp://demo.local/streams/front_door",
        zones=["porch", "walkway"],
    ),
    Camera(
        id="cam_backyard",
        name="Backyard",
        status=CameraStatus.ONLINE,
        location="Rear garden",
        snapshot_url="http://demo.local/snapshots/backyard.jpg",
        stream_url="rtsp://demo.local/streams/backyard",
        zones=["patio", "lawn", "pool"],
    ),
    Camera(
        id="cam_garage",
        name="Garage",
        status=CameraStatus.ONLINE,
        location="Garage interior",
        snapshot_url="http://demo.local/snapshots/garage.jpg",
        stream_url="rtsp://demo.local/streams/garage",
        zones=["driveway_entrance", "parking"],
    ),
    Camera(
        id="cam_driveway",
        name="Driveway",
        status=CameraStatus.ONLINE,
        location="Driveway exterior",
        snapshot_url="http://demo.local/snapshots/driveway.jpg",
        stream_url="rtsp://demo.local/streams/driveway",
        zones=["street", "driveway"],
    ),
]

_ZONES: list[Zone] = [
    # Front Door zones
    Zone(id="zone_porch", name="porch", camera_id="cam_front_door",
         coordinates=[(0.1, 0.3), (0.9, 0.3), (0.9, 0.9), (0.1, 0.9)]),
    Zone(id="zone_walkway", name="walkway", camera_id="cam_front_door",
         coordinates=[(0.3, 0.0), (0.7, 0.0), (0.7, 0.4), (0.3, 0.4)]),
    # Backyard zones
    Zone(id="zone_patio", name="patio", camera_id="cam_backyard",
         coordinates=[(0.0, 0.5), (0.5, 0.5), (0.5, 1.0), (0.0, 1.0)]),
    Zone(id="zone_lawn", name="lawn", camera_id="cam_backyard",
         coordinates=[(0.5, 0.2), (1.0, 0.2), (1.0, 0.8), (0.5, 0.8)]),
    Zone(id="zone_pool", name="pool", camera_id="cam_backyard",
         coordinates=[(0.2, 0.0), (0.8, 0.0), (0.8, 0.3), (0.2, 0.3)]),
    # Garage zones
    Zone(id="zone_driveway_entrance", name="driveway_entrance", camera_id="cam_garage",
         coordinates=[(0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)]),
    Zone(id="zone_parking", name="parking", camera_id="cam_garage",
         coordinates=[(0.1, 0.4), (0.9, 0.4), (0.9, 1.0), (0.1, 1.0)]),
    # Driveway zones
    Zone(id="zone_street", name="street", camera_id="cam_driveway",
         coordinates=[(0.0, 0.0), (1.0, 0.0), (1.0, 0.3), (0.0, 0.3)]),
    Zone(id="zone_driveway", name="driveway", camera_id="cam_driveway",
         coordinates=[(0.2, 0.3), (0.8, 0.3), (0.8, 1.0), (0.2, 1.0)]),
]


def _t(hours_ago: float, minutes: float = 0) -> datetime:
    """Return a datetime *hours_ago* hours before the anchor."""
    return _ANCHOR - timedelta(hours=hours_ago, minutes=minutes)


_EVENTS: list[Event] = [
    # --- Front Door events ---
    Event(
        id="evt_001", camera_id="cam_front_door", camera_name="Front Door",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(1), end_time=_t(1) + timedelta(seconds=12),
        objects=[DetectedObject(label=ObjectLabel.PERSON, confidence=0.97,
                                bounding_box=BoundingBox(0.30, 0.25, 0.65, 0.90))],
        zones=["porch"],
        snapshot_url="http://demo.local/events/evt_001/snapshot.jpg",
    ),
    Event(
        id="evt_002", camera_id="cam_front_door", camera_name="Front Door",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(3, 15), end_time=_t(3, 15) + timedelta(seconds=8),
        objects=[DetectedObject(label=ObjectLabel.PACKAGE, confidence=0.91,
                                bounding_box=BoundingBox(0.40, 0.60, 0.60, 0.85))],
        zones=["porch"],
        snapshot_url="http://demo.local/events/evt_002/snapshot.jpg",
    ),
    Event(
        id="evt_003", camera_id="cam_front_door", camera_name="Front Door",
        event_type=EventType.ZONE_ENTER,
        start_time=_t(5, 30), end_time=_t(5, 30) + timedelta(seconds=20),
        objects=[DetectedObject(label=ObjectLabel.PERSON, confidence=0.85,
                                bounding_box=BoundingBox(0.10, 0.20, 0.45, 0.88))],
        zones=["walkway"],
        snapshot_url="http://demo.local/events/evt_003/snapshot.jpg",
    ),
    Event(
        id="evt_004", camera_id="cam_front_door", camera_name="Front Door",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(8), end_time=_t(8) + timedelta(seconds=5),
        objects=[DetectedObject(label=ObjectLabel.CAT, confidence=0.72,
                                bounding_box=BoundingBox(0.55, 0.70, 0.75, 0.95))],
        zones=["porch"],
        snapshot_url="http://demo.local/events/evt_004/snapshot.jpg",
    ),
    Event(
        id="evt_005", camera_id="cam_front_door", camera_name="Front Door",
        event_type=EventType.MOTION,
        start_time=_t(12), end_time=_t(12) + timedelta(seconds=3),
        objects=[],
        zones=["walkway"],
    ),
    # --- Backyard events ---
    Event(
        id="evt_006", camera_id="cam_backyard", camera_name="Backyard",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(0, 45), end_time=_t(0, 45) + timedelta(seconds=30),
        objects=[DetectedObject(label=ObjectLabel.DOG, confidence=0.94,
                                bounding_box=BoundingBox(0.20, 0.40, 0.55, 0.85))],
        zones=["lawn"],
        snapshot_url="http://demo.local/events/evt_006/snapshot.jpg",
    ),
    Event(
        id="evt_007", camera_id="cam_backyard", camera_name="Backyard",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(2, 10), end_time=_t(2, 10) + timedelta(seconds=18),
        objects=[DetectedObject(label=ObjectLabel.PERSON, confidence=0.96,
                                bounding_box=BoundingBox(0.15, 0.30, 0.50, 0.92))],
        zones=["patio"],
        snapshot_url="http://demo.local/events/evt_007/snapshot.jpg",
    ),
    Event(
        id="evt_008", camera_id="cam_backyard", camera_name="Backyard",
        event_type=EventType.ZONE_ENTER,
        start_time=_t(4), end_time=_t(4) + timedelta(seconds=45),
        objects=[DetectedObject(label=ObjectLabel.DOG, confidence=0.88,
                                bounding_box=BoundingBox(0.30, 0.10, 0.70, 0.50))],
        zones=["pool"],
        snapshot_url="http://demo.local/events/evt_008/snapshot.jpg",
    ),
    Event(
        id="evt_009", camera_id="cam_backyard", camera_name="Backyard",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(7, 20), end_time=_t(7, 20) + timedelta(seconds=10),
        objects=[
            DetectedObject(label=ObjectLabel.PERSON, confidence=0.93,
                           bounding_box=BoundingBox(0.05, 0.25, 0.35, 0.90)),
            DetectedObject(label=ObjectLabel.DOG, confidence=0.89,
                           bounding_box=BoundingBox(0.40, 0.50, 0.65, 0.85)),
        ],
        zones=["lawn"],
        snapshot_url="http://demo.local/events/evt_009/snapshot.jpg",
    ),
    Event(
        id="evt_010", camera_id="cam_backyard", camera_name="Backyard",
        event_type=EventType.MOTION,
        start_time=_t(10), end_time=_t(10) + timedelta(seconds=6),
        objects=[],
        zones=["patio"],
    ),
    # --- Garage events ---
    Event(
        id="evt_011", camera_id="cam_garage", camera_name="Garage",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(0, 30), end_time=_t(0, 30) + timedelta(seconds=25),
        objects=[DetectedObject(label=ObjectLabel.CAR, confidence=0.99,
                                bounding_box=BoundingBox(0.10, 0.20, 0.90, 0.85))],
        zones=["parking"],
        snapshot_url="http://demo.local/events/evt_011/snapshot.jpg",
    ),
    Event(
        id="evt_012", camera_id="cam_garage", camera_name="Garage",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(2, 50), end_time=_t(2, 50) + timedelta(seconds=15),
        objects=[DetectedObject(label=ObjectLabel.PERSON, confidence=0.90,
                                bounding_box=BoundingBox(0.35, 0.30, 0.60, 0.95))],
        zones=["driveway_entrance"],
        snapshot_url="http://demo.local/events/evt_012/snapshot.jpg",
    ),
    Event(
        id="evt_013", camera_id="cam_garage", camera_name="Garage",
        event_type=EventType.ZONE_EXIT,
        start_time=_t(6), end_time=_t(6) + timedelta(seconds=20),
        objects=[DetectedObject(label=ObjectLabel.CAR, confidence=0.97,
                                bounding_box=BoundingBox(0.05, 0.15, 0.85, 0.80))],
        zones=["parking"],
        snapshot_url="http://demo.local/events/evt_013/snapshot.jpg",
    ),
    Event(
        id="evt_014", camera_id="cam_garage", camera_name="Garage",
        event_type=EventType.MOTION,
        start_time=_t(9, 10), end_time=_t(9, 10) + timedelta(seconds=4),
        objects=[],
        zones=["driveway_entrance"],
    ),
    Event(
        id="evt_015", camera_id="cam_garage", camera_name="Garage",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(14), end_time=_t(14) + timedelta(seconds=10),
        objects=[DetectedObject(label=ObjectLabel.BICYCLE, confidence=0.82,
                                bounding_box=BoundingBox(0.25, 0.35, 0.55, 0.80))],
        zones=["parking"],
        snapshot_url="http://demo.local/events/evt_015/snapshot.jpg",
    ),
    # --- Driveway events ---
    Event(
        id="evt_016", camera_id="cam_driveway", camera_name="Driveway",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(0, 15), end_time=_t(0, 15) + timedelta(seconds=14),
        objects=[DetectedObject(label=ObjectLabel.CAR, confidence=0.98,
                                bounding_box=BoundingBox(0.15, 0.10, 0.85, 0.70))],
        zones=["driveway"],
        snapshot_url="http://demo.local/events/evt_016/snapshot.jpg",
    ),
    Event(
        id="evt_017", camera_id="cam_driveway", camera_name="Driveway",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(1, 40), end_time=_t(1, 40) + timedelta(seconds=9),
        objects=[DetectedObject(label=ObjectLabel.PERSON, confidence=0.92,
                                bounding_box=BoundingBox(0.40, 0.20, 0.60, 0.90))],
        zones=["driveway"],
        snapshot_url="http://demo.local/events/evt_017/snapshot.jpg",
    ),
    Event(
        id="evt_018", camera_id="cam_driveway", camera_name="Driveway",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(4, 30), end_time=_t(4, 30) + timedelta(seconds=22),
        objects=[DetectedObject(label=ObjectLabel.TRUCK, confidence=0.95,
                                bounding_box=BoundingBox(0.05, 0.05, 0.95, 0.75))],
        zones=["street"],
        snapshot_url="http://demo.local/events/evt_018/snapshot.jpg",
    ),
    Event(
        id="evt_019", camera_id="cam_driveway", camera_name="Driveway",
        event_type=EventType.OBJECT_DETECTED,
        start_time=_t(6, 45), end_time=_t(6, 45) + timedelta(seconds=11),
        objects=[DetectedObject(label=ObjectLabel.PACKAGE, confidence=0.87,
                                bounding_box=BoundingBox(0.35, 0.55, 0.55, 0.80))],
        zones=["driveway"],
        snapshot_url="http://demo.local/events/evt_019/snapshot.jpg",
    ),
    Event(
        id="evt_020", camera_id="cam_driveway", camera_name="Driveway",
        event_type=EventType.LINE_CROSSING,
        start_time=_t(11, 30), end_time=_t(11, 30) + timedelta(seconds=7),
        objects=[DetectedObject(label=ObjectLabel.MOTORCYCLE, confidence=0.80,
                                bounding_box=BoundingBox(0.20, 0.15, 0.70, 0.65))],
        zones=["street"],
        snapshot_url="http://demo.local/events/evt_020/snapshot.jpg",
    ),
]

_CLIPS: list[Clip] = [
    Clip(
        id="clip_001", camera_id="cam_front_door", camera_name="Front Door",
        start_time=_t(1), end_time=_t(1) + timedelta(minutes=2),
        download_url="http://demo.local/clips/clip_001.mp4",
        thumbnail_url="http://demo.local/clips/clip_001_thumb.jpg",
        size_bytes=15_200_000,
    ),
    Clip(
        id="clip_002", camera_id="cam_backyard", camera_name="Backyard",
        start_time=_t(2, 10), end_time=_t(2, 10) + timedelta(minutes=3),
        download_url="http://demo.local/clips/clip_002.mp4",
        thumbnail_url="http://demo.local/clips/clip_002_thumb.jpg",
        size_bytes=22_400_000,
    ),
    Clip(
        id="clip_003", camera_id="cam_garage", camera_name="Garage",
        start_time=_t(0, 30), end_time=_t(0, 30) + timedelta(minutes=1, seconds=30),
        download_url="http://demo.local/clips/clip_003.mp4",
        thumbnail_url="http://demo.local/clips/clip_003_thumb.jpg",
        size_bytes=11_800_000,
    ),
    Clip(
        id="clip_004", camera_id="cam_driveway", camera_name="Driveway",
        start_time=_t(4, 30), end_time=_t(4, 30) + timedelta(minutes=2, seconds=45),
        download_url="http://demo.local/clips/clip_004.mp4",
        thumbnail_url="http://demo.local/clips/clip_004_thumb.jpg",
        size_bytes=19_600_000,
    ),
    Clip(
        id="clip_005", camera_id="cam_driveway", camera_name="Driveway",
        start_time=_t(6, 45), end_time=_t(6, 45) + timedelta(minutes=1),
        download_url="http://demo.local/clips/clip_005.mp4",
        thumbnail_url="http://demo.local/clips/clip_005_thumb.jpg",
        size_bytes=8_500_000,
    ),
]

_SYSTEM_INFO = SystemInfo(
    system_name="cctvQL Demo System",
    version="0.1.0-demo",
    camera_count=len(_CAMERAS),
    uptime_seconds=86400,  # 24 hours
    storage_used_bytes=256 * 1024 * 1024 * 1024,   # 256 GB
    storage_total_bytes=1024 * 1024 * 1024 * 1024,  # 1 TB
    metadata={"mode": "demo", "deterministic": True},
)


# ---------------------------------------------------------------------------
# Adapter implementation
# ---------------------------------------------------------------------------

class DemoAdapter(BaseAdapter):
    """
    Mock adapter for testing and demonstration.

    All data is hardcoded and deterministic — no network calls are made.
    This lets users explore cctvQL queries, build UIs, and write tests
    without any real CCTV hardware.
    """

    _connected: bool = False

    # -- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "demo"

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    # -- cameras -----------------------------------------------------------

    async def list_cameras(self) -> list[Camera]:
        return list(_CAMERAS)

    async def get_camera(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> Camera | None:
        for cam in _CAMERAS:
            if camera_id and cam.id == camera_id:
                return cam
            if camera_name and cam.name.lower() == camera_name.lower():
                return cam
        return None

    # -- events ------------------------------------------------------------

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
        results: list[Event] = []
        for evt in _EVENTS:
            if camera_id and evt.camera_id != camera_id:
                continue
            if camera_name and evt.camera_name.lower() != camera_name.lower():
                continue
            if label:
                label_lower = label.lower()
                if not any(
                    obj.label.lower() == label_lower
                    if isinstance(obj.label, str)
                    else obj.label.value.lower() == label_lower
                    for obj in evt.objects
                ):
                    continue
            if zone and zone.lower() not in [z.lower() for z in evt.zones]:
                continue
            if start_time and evt.start_time < start_time:
                continue
            if end_time and evt.start_time > end_time:
                continue
            results.append(evt)
        # Sort by start_time descending (most recent first)
        results.sort(key=lambda e: e.start_time, reverse=True)
        return results[:limit]

    async def get_event(self, event_id: str) -> Event | None:
        for evt in _EVENTS:
            if evt.id == event_id:
                return evt
        return None

    # -- clips -------------------------------------------------------------

    async def get_clips(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Clip]:
        results: list[Clip] = []
        for clip in _CLIPS:
            if camera_id and clip.camera_id != camera_id:
                continue
            if camera_name and clip.camera_name.lower() != camera_name.lower():
                continue
            if start_time and clip.start_time < start_time:
                continue
            if end_time and clip.start_time > end_time:
                continue
            results.append(clip)
        results.sort(key=lambda c: c.start_time, reverse=True)
        return results[:limit]

    # -- snapshots ---------------------------------------------------------

    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        cam = await self.get_camera(camera_id=camera_id, camera_name=camera_name)
        return cam.snapshot_url if cam else None

    # -- system info -------------------------------------------------------

    async def get_system_info(self) -> SystemInfo | None:
        return _SYSTEM_INFO

    # -- zones -------------------------------------------------------------

    async def list_zones(self, camera_id: str | None = None) -> list[Zone]:
        if camera_id:
            return [z for z in _ZONES if z.camera_id == camera_id]
        return list(_ZONES)

    # -- health ------------------------------------------------------------

    async def health_check(self) -> bool:
        return True
