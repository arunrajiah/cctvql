"""
Shared fixtures for cctvQL test suite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from cctvql.adapters.demo import DemoAdapter
from cctvql.core.nlp_engine import NLPEngine
from cctvql.core.query_router import QueryRouter
from cctvql.core.schema import (
    BoundingBox,
    Camera,
    CameraStatus,
    Clip,
    DetectedObject,
    Event,
    EventType,
)
from cctvql.llm.base import BaseLLM, LLMResponse


@pytest.fixture
def mock_llm():
    """A MagicMock that implements BaseLLM interface with AsyncMock complete()."""
    llm = MagicMock(spec=BaseLLM)
    llm.name = "mock"
    llm.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"intent":"list_cameras","limit":20,"explanation":"list cameras"}',
            model="mock",
        )
    )
    llm.health_check = AsyncMock(return_value=True)
    return llm


@pytest.fixture
async def demo_adapter():
    """Instantiate and connect a DemoAdapter."""
    adapter = DemoAdapter()
    await adapter.connect()
    return adapter


@pytest.fixture
def sample_camera():
    """A pre-built Camera schema object."""
    return Camera(
        id="cam_test",
        name="Test Camera",
        status=CameraStatus.ONLINE,
        location="Test Location",
        snapshot_url="http://test/snapshot.jpg",
        stream_url="rtsp://test/stream",
        zones=["zone_a", "zone_b"],
    )


@pytest.fixture
def sample_event():
    """A pre-built Event schema object."""
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return Event(
        id="evt_test",
        camera_id="cam_test",
        camera_name="Test Camera",
        event_type=EventType.OBJECT_DETECTED,
        start_time=now,
        end_time=now + timedelta(seconds=10),
        objects=[
            DetectedObject(
                label="person",
                confidence=0.95,
                bounding_box=BoundingBox(0.1, 0.2, 0.5, 0.8),
            ),
        ],
        zones=["zone_a"],
        snapshot_url="http://test/events/evt_test/snap.jpg",
    )


@pytest.fixture
def sample_clip():
    """A pre-built Clip schema object."""
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return Clip(
        id="clip_test",
        camera_id="cam_test",
        camera_name="Test Camera",
        start_time=now,
        end_time=now + timedelta(minutes=2),
        download_url="http://test/clips/clip_test.mp4",
        size_bytes=10_000_000,
    )


@pytest.fixture
def nlp_engine(mock_llm):
    """NLPEngine wired to mock_llm."""
    return NLPEngine(mock_llm)


@pytest.fixture
async def query_router(demo_adapter, mock_llm):
    """QueryRouter wired to demo_adapter and mock_llm."""
    return QueryRouter(demo_adapter, mock_llm)
