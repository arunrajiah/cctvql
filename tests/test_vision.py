"""
Tests for VisionAnalyzer (cctvql.core.vision).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cctvql.core.vision import VisionAnalyzer
from cctvql.llm.base import LLMMessage, LLMResponse
from cctvql.core.schema import (
    DetectedObject,
    Event,
    EventType,
)
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_vision_llm(response_text: str = "A person walking") -> MagicMock:
    """Return a mock LLM that supports vision."""
    mock_llm = MagicMock()
    mock_llm.name = "mock"
    mock_llm.supports_vision = True
    mock_llm.complete_with_image = AsyncMock(
        return_value=LLMResponse(content=response_text, model="mock")
    )
    mock_llm.complete = AsyncMock(return_value=LLMResponse(content=response_text, model="mock"))
    return mock_llm


def _make_text_only_llm(response_text: str = "No vision available") -> MagicMock:
    """Return a mock LLM that does NOT support vision."""
    mock_llm = MagicMock()
    mock_llm.name = "text-only"
    mock_llm.supports_vision = False
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(content=response_text, model="text-only")
    )
    return mock_llm


def _mock_http_response(
    content: bytes = b"fake_image_bytes", content_type: str = "image/jpeg"
) -> MagicMock:
    """Return a mock httpx response with image content."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = content
    mock_response.headers = {"content-type": content_type}
    return mock_response


@pytest.fixture
def vision_llm():
    return _make_vision_llm()


@pytest.fixture
def analyzer(vision_llm):
    return VisionAnalyzer(llm=vision_llm)


# ---------------------------------------------------------------------------
# describe_snapshot tests
# ---------------------------------------------------------------------------


async def test_describe_snapshot_with_vision_llm(analyzer, vision_llm):
    """Vision LLM: fetches image and calls complete_with_image."""
    mock_resp = _mock_http_response(b"fake_image_bytes", "image/jpeg")

    with patch.object(analyzer._http, "get", new=AsyncMock(return_value=mock_resp)):
        result = await analyzer.describe_snapshot("http://cam/snap.jpg")

    assert result == "A person walking"
    vision_llm.complete_with_image.assert_called_once()
    # text-only complete should NOT have been called
    vision_llm.complete.assert_not_called()


async def test_describe_snapshot_fallback_on_fetch_failure(analyzer, vision_llm):
    """When image fetch raises, falls back to text-only complete()."""
    with patch.object(analyzer._http, "get", new=AsyncMock(side_effect=Exception("network error"))):
        result = await analyzer.describe_snapshot("http://cam/snap.jpg")

    assert result == "A person walking"
    # Must have called text-only complete, not complete_with_image
    vision_llm.complete.assert_called_once()
    vision_llm.complete_with_image.assert_not_called()
    # Fallback message should mention the URL
    call_args = vision_llm.complete.call_args
    messages = call_args[0][0]  # first positional arg = messages list
    assert any("http://cam/snap.jpg" in msg.content for msg in messages)


async def test_describe_snapshot_no_vision_support():
    """Non-vision LLM returns a message indicating vision is unavailable."""
    llm = _make_text_only_llm()
    analyzer = VisionAnalyzer(llm=llm)
    result = await analyzer.describe_snapshot("http://cam/snap.jpg")

    assert "Vision analysis is not available" in result
    assert "text-only" in result  # mentions the backend name
    assert "http://cam/snap.jpg" in result
    # No HTTP fetch should occur
    llm.complete.assert_not_called()
    llm.complete_with_image.assert_not_called()


# ---------------------------------------------------------------------------
# analyze_event tests
# ---------------------------------------------------------------------------


def _make_event(
    camera_name: str = "Front Door",
    objects: list[DetectedObject] | None = None,
    snapshot_url: str | None = "http://cam/snap.jpg",
    zones: list[str] | None = None,
) -> Event:
    return Event(
        id="evt_001",
        camera_id="cam_01",
        camera_name=camera_name,
        event_type=EventType.OBJECT_DETECTED,
        start_time=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        objects=objects or [DetectedObject(label="person", confidence=0.95)],
        zones=zones or ["porch"],
        snapshot_url=snapshot_url,
    )


async def test_analyze_event_builds_context_prompt(vision_llm):
    """Prompt sent to LLM must mention camera name and detected objects."""
    analyzer = VisionAnalyzer(llm=vision_llm)
    mock_adapter = MagicMock()
    event = _make_event(
        camera_name="Backyard",
        objects=[DetectedObject(label="car", confidence=0.87)],
    )

    mock_resp = _mock_http_response()
    with patch.object(analyzer._http, "get", new=AsyncMock(return_value=mock_resp)):
        result = await analyzer.analyze_event(event, mock_adapter)

    assert result == "A person walking"
    vision_llm.complete_with_image.assert_called_once()

    # Inspect the prompt that was built
    call_args = vision_llm.complete_with_image.call_args
    messages: list[LLMMessage] = call_args[0][0]
    prompt_text = " ".join(m.content for m in messages)
    assert "Backyard" in prompt_text
    assert "car" in prompt_text


async def test_analyze_event_uses_adapter_snapshot_url_fallback():
    """If event has no snapshot URL, adapter.get_snapshot_url is called."""
    vision_llm = _make_vision_llm()
    analyzer = VisionAnalyzer(llm=vision_llm)

    mock_adapter = MagicMock()
    mock_adapter.get_snapshot_url = AsyncMock(return_value="http://adapter/snap.jpg")

    event = _make_event(snapshot_url=None)

    mock_resp = _mock_http_response()
    with patch.object(analyzer._http, "get", new=AsyncMock(return_value=mock_resp)):
        result = await analyzer.analyze_event(event, mock_adapter)

    mock_adapter.get_snapshot_url.assert_called_once()
    assert result == "A person walking"


async def test_analyze_event_no_snapshot_no_vision():
    """Event with no snapshot and non-vision LLM returns text-only summary."""
    llm = _make_text_only_llm()
    analyzer = VisionAnalyzer(llm=llm)

    mock_adapter = MagicMock()
    mock_adapter.get_snapshot_url = AsyncMock(return_value=None)

    event = _make_event(snapshot_url=None)
    result = await analyzer.analyze_event(event, mock_adapter)

    assert "Front Door" in result
    assert "No snapshot available" in result


# ---------------------------------------------------------------------------
# compare_snapshots tests
# ---------------------------------------------------------------------------


async def test_compare_snapshots(vision_llm):
    """Both images are fetched and described; compare returns LLM output."""
    analyzer = VisionAnalyzer(llm=vision_llm)

    call_count = 0
    image_urls: list[str] = []

    async def fake_get(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        image_urls.append(url)
        return _mock_http_response(b"image_data_" + str(call_count).encode())

    with patch.object(analyzer._http, "get", new=fake_get):
        result = await analyzer.compare_snapshots(
            "http://cam/snap1.jpg",
            "http://cam/snap2.jpg",
        )

    assert result == "A person walking"
    assert call_count == 2
    assert "http://cam/snap1.jpg" in image_urls
    assert "http://cam/snap2.jpg" in image_urls
    # Two individual describe calls + one compare call
    assert vision_llm.complete_with_image.call_count == 2
    vision_llm.complete.assert_called_once()


async def test_compare_snapshots_no_vision():
    """Non-vision LLM returns appropriate unavailability message."""
    llm = _make_text_only_llm()
    analyzer = VisionAnalyzer(llm=llm)
    result = await analyzer.compare_snapshots("http://cam/a.jpg", "http://cam/b.jpg")
    assert "Vision analysis is not available" in result
    assert "Cannot compare" in result


async def test_compare_snapshots_both_fail(vision_llm):
    """If both image fetches fail, returns a descriptive error message."""
    analyzer = VisionAnalyzer(llm=vision_llm)

    with patch.object(analyzer._http, "get", new=AsyncMock(side_effect=Exception("timeout"))):
        result = await analyzer.compare_snapshots(
            "http://cam/snap1.jpg",
            "http://cam/snap2.jpg",
        )

    assert "Could not fetch either image" in result


async def test_compare_snapshots_first_fails(vision_llm):
    """First image fails → falls back to describing second image only."""
    analyzer = VisionAnalyzer(llm=vision_llm)
    call_count = 0

    async def fake_get(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("first image fetch failed")
        return _mock_http_response()

    with patch.object(analyzer._http, "get", new=fake_get):
        result = await analyzer.compare_snapshots(
            "http://cam/snap1.jpg",
            "http://cam/snap2.jpg",
        )

    assert result == "A person walking"
    vision_llm.complete_with_image.assert_called_once()
