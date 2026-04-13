"""Tests for core schema models."""

from datetime import datetime

from cctvql.core.schema import (
    BoundingBox,
    Camera,
    CameraStatus,
    Clip,
    DetectedObject,
    Event,
    EventType,
    QueryContext,
)


def test_camera_defaults():
    cam = Camera(id="cam1", name="Front Door")
    assert cam.status == CameraStatus.UNKNOWN
    assert cam.zones == []
    assert str(cam) == "Camera(Front Door, status=unknown)"


def test_event_summary():
    event = Event(
        id="e1",
        camera_id="cam1",
        camera_name="Driveway",
        event_type=EventType.OBJECT_DETECTED,
        start_time=datetime(2026, 4, 13, 2, 30, 0),
        objects=[DetectedObject(label="person", confidence=0.95)],
        zones=["front_yard"],
    )
    summary = event.to_summary()
    assert "Driveway" in summary
    assert "person" in summary
    assert "front_yard" in summary


def test_event_duration():
    event = Event(
        id="e2",
        camera_id="cam1",
        camera_name="Test",
        event_type=EventType.MOTION,
        start_time=datetime(2026, 4, 13, 10, 0, 0),
        end_time=datetime(2026, 4, 13, 10, 0, 30),
    )
    assert event.duration_seconds == 30.0


def test_event_primary_label():
    event = Event(
        id="e3",
        camera_id="cam1",
        camera_name="Test",
        event_type=EventType.OBJECT_DETECTED,
        start_time=datetime.now(),
        objects=[
            DetectedObject(label="car", confidence=0.6),
            DetectedObject(label="person", confidence=0.95),
        ],
    )
    assert event.primary_label == "person"


def test_clip_duration():
    clip = Clip(
        id="c1",
        camera_id="cam1",
        camera_name="Parking",
        start_time=datetime(2026, 4, 13, 10, 0, 0),
        end_time=datetime(2026, 4, 13, 10, 1, 0),
    )
    assert clip.duration_seconds == 60.0


def test_query_context_defaults():
    ctx = QueryContext(intent="list_cameras")
    assert ctx.limit == 20
    assert ctx.camera_id is None
    assert ctx.raw_query == ""


def test_bounding_box():
    bb = BoundingBox(x_min=0.1, y_min=0.2, x_max=0.8, y_max=0.9)
    assert bb.x_max > bb.x_min
    assert bb.y_max > bb.y_min
