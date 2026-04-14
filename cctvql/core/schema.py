"""
cctvQL Core Schema
------------------
Vendor-agnostic data models shared across all adapters.
All adapters must normalize their output to these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CameraStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class ObjectLabel(str, Enum):
    PERSON = "person"
    CAR = "car"
    TRUCK = "truck"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
    DOG = "dog"
    CAT = "cat"
    PACKAGE = "package"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    MOTION = "motion"
    OBJECT_DETECTED = "object_detected"
    LINE_CROSSING = "line_crossing"
    ZONE_ENTER = "zone_enter"
    ZONE_EXIT = "zone_exit"
    AUDIO = "audio"
    TAMPER = "tamper"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------


@dataclass
class Camera:
    """Represents a single camera in the system."""

    id: str
    name: str
    status: CameraStatus = CameraStatus.UNKNOWN
    location: str | None = None
    snapshot_url: str | None = None
    stream_url: str | None = None
    zones: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"Camera({self.name}, status={self.status.value})"


@dataclass
class BoundingBox:
    """Normalized bounding box [0.0, 1.0] for detected objects."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass
class DetectedObject:
    """A single object detected within an event frame."""

    label: str
    confidence: float
    bounding_box: BoundingBox | None = None

    def __str__(self) -> str:
        return f"{self.label} ({self.confidence:.0%})"


@dataclass
class Event:
    """
    A detection or motion event from any CCTV system.
    Normalized across all adapters.
    """

    id: str
    camera_id: str
    camera_name: str
    event_type: EventType
    start_time: datetime
    end_time: datetime | None = None
    objects: list[DetectedObject] = field(default_factory=list)
    zones: list[str] = field(default_factory=list)
    snapshot_url: str | None = None
    clip_url: str | None = None
    thumbnail_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float | None:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def primary_label(self) -> str | None:
        if self.objects:
            return max(self.objects, key=lambda o: o.confidence).label
        return None

    def to_summary(self) -> str:
        label_str = f" — {self.primary_label}" if self.primary_label else ""
        zone_str = f" in {', '.join(self.zones)}" if self.zones else ""
        time_str = self.start_time.strftime("%Y-%m-%d %H:%M:%S")
        return f"[{time_str}] {self.camera_name}{label_str}{zone_str}"

    def __str__(self) -> str:
        return self.to_summary()


@dataclass
class Clip:
    """A recorded video clip from a camera."""

    id: str
    camera_id: str
    camera_name: str
    start_time: datetime
    end_time: datetime
    download_url: str | None = None
    thumbnail_url: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()


@dataclass
class Zone:
    """A named region or logical zone within a camera's view."""

    id: str
    name: str
    camera_id: str
    coordinates: list[tuple[float, float]] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemInfo:
    """High-level info about the connected CCTV system."""

    system_name: str
    version: str | None = None
    camera_count: int = 0
    uptime_seconds: int | None = None
    storage_used_bytes: int | None = None
    storage_total_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Query / Response wrappers
# ---------------------------------------------------------------------------


@dataclass
class QueryContext:
    """
    Parsed intent from a natural language query,
    handed off from the NLP engine to the query router.
    """

    intent: str  # e.g. "get_events", "list_cameras"
    camera_id: str | None = None
    camera_name: str | None = None
    label: str | None = None
    zone: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = 20
    raw_query: str = ""
    event_id: str | None = None
    session_id: str = "default"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryResult:
    """Structured result returned to the NLP engine after executing a query."""

    success: bool
    intent: str
    data: Any = None  # list[Event] | list[Camera] | etc.
    error: str | None = None
    summary: str | None = None  # Pre-formatted human-readable summary


# Re-export AnomalyResult here for convenience so callers only need one import
from cctvql.core.anomaly import AnomalyResult as AnomalyResult  # noqa: E402, F401
