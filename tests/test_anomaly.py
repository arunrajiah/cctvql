"""
Tests for the AnomalyDetector and GET /anomalies REST endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cctvql.adapters.base import AdapterRegistry
from cctvql.adapters.demo import DemoAdapter
from cctvql.core.anomaly import AnomalyDetector, AnomalyResult
from cctvql.core.schema import Event, EventType
from cctvql.llm.base import LLMRegistry, LLMResponse

# ---------------------------------------------------------------------------
# Helpers to build synthetic events
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 4, 7, 0, 0, 0)  # Monday midnight


def _make_event(camera: str, hour: int, day_offset: int = 0, label: str = "person") -> Event:
    ts = _BASE + timedelta(days=day_offset, hours=hour)
    from cctvql.core.schema import DetectedObject

    return Event(
        id=f"evt_{camera}_{day_offset}_{hour}",
        camera_id=camera.lower(),
        camera_name=camera,
        event_type=EventType.OBJECT_DETECTED,
        start_time=ts,
        end_time=ts + timedelta(minutes=1),
        objects=[DetectedObject(label=label, confidence=0.9)],
    )


def _baseline_events(camera: str, hour: int, count_per_day: int, days: int = 7) -> list[Event]:
    """Produce a realistic baseline: ``count_per_day`` events at ``hour`` for ``days`` days."""
    events = []
    for day in range(days):
        for _ in range(count_per_day):
            events.append(_make_event(camera, hour, day_offset=day))
    return events


# ---------------------------------------------------------------------------
# Unit tests — AnomalyDetector
# ---------------------------------------------------------------------------


class TestAnomalyDetector:
    def _detector(self, threshold: float = 2.0) -> AnomalyDetector:
        return AnomalyDetector(threshold=threshold, min_baseline=3)

    def test_no_anomaly_when_activity_is_normal(self):
        """Normal activity should not be flagged."""
        baseline = _baseline_events("Cam1", hour=10, count_per_day=3, days=7)
        observe_start = _BASE + timedelta(days=7)
        observe_end = observe_start + timedelta(hours=24)
        observe = _baseline_events("Cam1", hour=10, count_per_day=3, days=1)
        # shift observe events into the observe window
        for e in observe:
            e.start_time = observe_start + timedelta(hours=10)
            e.end_time = e.start_time + timedelta(minutes=1)

        detector = self._detector()
        results = detector.detect(observe, baseline, observe_start, observe_end)
        assert len(results) == 0

    def test_spike_detected(self):
        """30 events in an hour that normally has ~3 should be a spike."""
        baseline = _baseline_events("Cam1", hour=10, count_per_day=3, days=7)
        observe_start = _BASE + timedelta(days=7)
        observe_end = observe_start + timedelta(hours=24)

        # 30 events at hour 10 in the observe window
        observe = []
        for i in range(30):
            e = _make_event("Cam1", hour=10, day_offset=0)
            e.start_time = observe_start + timedelta(hours=10, minutes=i)
            e.end_time = e.start_time + timedelta(minutes=1)
            observe.append(e)

        detector = self._detector()
        results = detector.detect(observe, baseline, observe_start, observe_end)
        spikes = [r for r in results if r.anomaly_type == "spike" and r.camera == "Cam1"]
        assert len(spikes) >= 1
        assert spikes[0].event_count == 30

    def test_spike_severity_high(self):
        """Very large spike should be rated high severity."""
        baseline = _baseline_events("Cam1", hour=10, count_per_day=2, days=7)
        observe_start = _BASE + timedelta(days=7)
        observe_end = observe_start + timedelta(hours=24)

        observe = []
        for i in range(50):
            e = _make_event("Cam1", hour=10)
            e.start_time = observe_start + timedelta(hours=10, minutes=i)
            e.end_time = e.start_time + timedelta(minutes=1)
            observe.append(e)

        detector = self._detector()
        results = detector.detect(observe, baseline, observe_start, observe_end)
        severities = {r.severity for r in results if r.anomaly_type == "spike"}
        assert "high" in severities

    def test_silence_detected(self):
        """Zero events during an hour that normally has many should flag silence."""
        # Baseline: 5 events at 14:00 every day for 7 days
        baseline = _baseline_events("Cam1", hour=14, count_per_day=5, days=7)
        observe_start = _BASE + timedelta(days=7)
        observe_end = observe_start + timedelta(hours=24)

        # Observe window has ZERO events
        detector = self._detector()
        results = detector.detect([], baseline, observe_start, observe_end)
        silence = [r for r in results if r.anomaly_type == "silence" and r.camera == "Cam1"]
        assert len(silence) >= 1

    def test_silence_not_flagged_if_normally_quiet(self):
        """Zero events at night shouldn't be anomalous if baseline is also quiet."""
        # Baseline: 0 events at 03:00 (simulate by giving no events at that hour)
        baseline = _baseline_events("Cam1", hour=14, count_per_day=1, days=7)
        observe_start = _BASE + timedelta(days=7)
        observe_end = observe_start + timedelta(hours=24)

        detector = self._detector()
        results = detector.detect([], baseline, observe_start, observe_end)
        # The 14:00 silence should be flagged, but there should be no false positive for 03:00
        for r in results:
            assert r.anomaly_type != "silence" or r.period_start.hour == 14

    def test_no_anomaly_when_no_baseline(self):
        """Without baseline data, nothing should be flagged."""
        observe_start = _BASE
        observe_end = observe_start + timedelta(hours=24)
        observe = _baseline_events("Cam1", hour=10, count_per_day=10, days=1)
        results = AnomalyDetector().detect(observe, [], observe_start, observe_end)
        assert len(results) == 0

    def test_top_labels_extracted(self):
        """top_labels should reflect the most common object labels in the spike."""
        baseline = _baseline_events("Cam1", hour=10, count_per_day=1, days=7)
        observe_start = _BASE + timedelta(days=7)
        observe_end = observe_start + timedelta(hours=24)

        observe = []
        for i in range(20):
            label = "car" if i % 3 == 0 else "person"
            e = _make_event("Cam1", hour=10, label=label)
            e.start_time = observe_start + timedelta(hours=10, minutes=i)
            e.end_time = e.start_time + timedelta(minutes=1)
            observe.append(e)

        results = AnomalyDetector().detect(observe, baseline, observe_start, observe_end)
        spikes = [r for r in results if r.anomaly_type == "spike"]
        assert len(spikes) >= 1
        assert "person" in spikes[0].top_labels

    def test_result_sorted_high_first(self):
        """Results should be sorted high → medium → low severity."""
        baseline = _baseline_events("Cam1", hour=10, count_per_day=2, days=7) + _baseline_events(
            "Cam1", hour=12, count_per_day=2, days=7
        )
        observe_start = _BASE + timedelta(days=7)
        observe_end = observe_start + timedelta(hours=24)

        observe = []
        # Massive spike at 10 (high) + small spike at 12 (low)
        for i in range(60):
            e = _make_event("Cam1", hour=10)
            e.start_time = observe_start + timedelta(hours=10, minutes=i % 60)
            e.end_time = e.start_time + timedelta(minutes=1)
            observe.append(e)
        for i in range(4):
            e = _make_event("Cam1", hour=12)
            e.start_time = observe_start + timedelta(hours=12, minutes=i)
            e.end_time = e.start_time + timedelta(minutes=1)
            observe.append(e)

        results = AnomalyDetector().detect(observe, baseline, observe_start, observe_end)
        order = {"high": 0, "medium": 1, "low": 2}
        for a, b in zip(results, results[1:]):
            assert order[a.severity] <= order[b.severity]

    def test_to_dict_keys(self):
        """AnomalyResult.to_dict() should include all required keys."""
        r = AnomalyResult(
            camera="Front Door",
            period_start=datetime(2026, 4, 14, 10),
            period_end=datetime(2026, 4, 14, 11),
            event_count=15,
            expected_count=3.0,
            z_score=4.0,
            anomaly_type="spike",
            severity="high",
            top_labels=["person"],
        )
        d = r.to_dict()
        for key in [
            "camera",
            "period_start",
            "period_end",
            "event_count",
            "expected_count",
            "z_score",
            "anomaly_type",
            "severity",
            "top_labels",
        ]:
            assert key in d

    def test_to_summary_spike(self):
        r = AnomalyResult(
            camera="Back Yard",
            period_start=datetime(2026, 4, 14, 22),
            period_end=datetime(2026, 4, 14, 23),
            event_count=20,
            expected_count=2.0,
            z_score=5.0,
            anomaly_type="spike",
            severity="high",
            top_labels=["person"],
        )
        summary = r.to_summary()
        assert "spike" in summary
        assert "Back Yard" in summary
        assert "HIGH" in summary

    def test_to_summary_silence(self):
        r = AnomalyResult(
            camera="Driveway",
            period_start=datetime(2026, 4, 14, 8),
            period_end=datetime(2026, 4, 14, 9),
            event_count=0,
            expected_count=5.0,
            z_score=-3.0,
            anomaly_type="silence",
            severity="medium",
            top_labels=[],
        )
        summary = r.to_summary()
        assert "silence" in summary
        assert "Driveway" in summary


# ---------------------------------------------------------------------------
# REST API tests — GET /anomalies
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_registries():
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None

    adapter = DemoAdapter()
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("demo")

    mock_llm = MagicMock()
    mock_llm.name = "mock"
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"intent":"list_cameras","limit":20,"explanation":"list"}',
            model="mock",
        )
    )
    mock_llm.health_check = AsyncMock(return_value=True)
    LLMRegistry.register(mock_llm)
    LLMRegistry.set_active("mock")

    yield

    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None


@pytest.fixture
async def client():
    import cctvql.interfaces.rest_api as api_module
    from cctvql.core.alerts import AlertEngine
    from cctvql.core.health_monitor import HealthMonitor
    from cctvql.notifications.registry import NotifierRegistry

    api_module._in_memory_sessions.clear()
    api_module._db = None
    api_module._session_store = None

    engine = AlertEngine(AdapterRegistry)
    await engine.start()
    api_module._alert_engine = engine

    monitor = HealthMonitor(AdapterRegistry, NotifierRegistry, poll_interval=9999)
    await monitor.start()
    api_module._health_monitor = monitor

    transport = httpx.ASGITransport(app=api_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await engine.stop()
    await monitor.stop()
    api_module._in_memory_sessions.clear()


async def test_anomalies_returns_200(client):
    resp = await client.get("/anomalies")
    assert resp.status_code == 200


async def test_anomalies_response_shape(client):
    resp = await client.get("/anomalies")
    data = resp.json()
    for key in ["observe_start", "observe_end", "baseline_days", "threshold", "total", "anomalies"]:
        assert key in data


async def test_anomalies_total_matches_list(client):
    resp = await client.get("/anomalies")
    data = resp.json()
    assert data["total"] == len(data["anomalies"])


async def test_anomalies_high_medium_low_sum(client):
    resp = await client.get("/anomalies")
    data = resp.json()
    assert data["high"] + data["medium"] + data["low"] == data["total"]


async def test_anomalies_camera_filter(client):
    resp = await client.get("/anomalies", params={"camera": "Front Door"})
    assert resp.status_code == 200
    data = resp.json()
    for anomaly in data["anomalies"]:
        assert anomaly["camera"].lower() == "front door"


async def test_anomalies_custom_hours(client):
    resp = await client.get("/anomalies", params={"hours": 6})
    assert resp.status_code == 200


async def test_anomalies_custom_baseline_days(client):
    resp = await client.get("/anomalies", params={"baseline_days": 3})
    assert resp.status_code == 200


async def test_anomalies_custom_threshold(client):
    resp = await client.get("/anomalies", params={"threshold": 1.5})
    assert resp.status_code == 200


async def test_anomalies_hours_validation_too_low(client):
    resp = await client.get("/anomalies", params={"hours": 0})
    assert resp.status_code == 422


async def test_anomalies_hours_validation_too_high(client):
    resp = await client.get("/anomalies", params={"hours": 999})
    assert resp.status_code == 422


async def test_anomalies_threshold_validation_too_low(client):
    resp = await client.get("/anomalies", params={"threshold": 0.1})
    assert resp.status_code == 422


async def test_anomalies_anomaly_dict_keys(client):
    """Each anomaly in the response must have all required fields."""
    resp = await client.get("/anomalies")
    data = resp.json()
    for anomaly in data["anomalies"]:
        for key in [
            "camera",
            "period_start",
            "period_end",
            "event_count",
            "expected_count",
            "z_score",
            "anomaly_type",
            "severity",
            "top_labels",
        ]:
            assert key in anomaly, f"Missing key '{key}' in anomaly: {anomaly}"


async def test_anomalies_severity_values(client):
    resp = await client.get("/anomalies")
    for anomaly in resp.json()["anomalies"]:
        assert anomaly["severity"] in {"low", "medium", "high"}


async def test_anomalies_type_values(client):
    resp = await client.get("/anomalies")
    for anomaly in resp.json()["anomalies"]:
        assert anomaly["anomaly_type"] in {"spike", "silence"}


async def test_anomalies_observe_timestamps_are_iso(client):
    resp = await client.get("/anomalies")
    data = resp.json()
    datetime.fromisoformat(data["observe_start"])
    datetime.fromisoformat(data["observe_end"])
