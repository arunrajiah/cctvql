"""
cctvQL Anomaly Detector
------------------------
Detects statistically unusual activity in CCTV event streams using a
per-camera, per-hour-of-day baseline built from recent history.

No external ML dependencies — uses pure-Python statistics (mean, std).

Algorithm
---------
1. Split events into two windows:
   - *baseline* window  : older history used to compute expected activity
   - *observe* window   : the period we are checking for anomalies

2. For each camera, bucket baseline events by hour-of-day (0–23) and compute
   mean and standard deviation of event counts.

3. For each 1-hour bucket in the observe window, compute a z-score:
       z = (observed_count - mean) / std

4. Flag buckets as anomalies when |z| > threshold (default 2.0).
   - z > threshold  → "spike"   (more activity than normal)
   - z < -threshold → "silence" (less activity than normal, when baseline > 0)

Severity bands
--------------
  |z| in [threshold, 2*threshold)  → "low"
  |z| in [2*threshold, 3*threshold) → "medium"
  |z| >= 3*threshold                → "high"
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cctvql.core.schema import Event

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class AnomalyResult:
    """A single anomalous period on a camera."""

    camera: str
    period_start: datetime
    period_end: datetime
    event_count: int
    expected_count: float  # mean count for this hour-of-day in the baseline
    z_score: float
    anomaly_type: str  # "spike" | "silence"
    severity: str  # "low" | "medium" | "high"
    top_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "camera": self.camera,
            "period_start": self.period_start.strftime("%Y-%m-%dT%H:%M"),
            "period_end": self.period_end.strftime("%Y-%m-%dT%H:%M"),
            "event_count": self.event_count,
            "expected_count": round(self.expected_count, 2),
            "z_score": round(self.z_score, 2),
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "top_labels": self.top_labels,
        }

    def to_summary(self) -> str:
        direction = "📈 spike" if self.anomaly_type == "spike" else "🔇 silence"
        label_str = f" ({', '.join(self.top_labels[:3])})" if self.top_labels else ""
        return (
            f"[{self.severity.upper()}] {direction} on **{self.camera}** "
            f"at {self.period_start.strftime('%H:%M')} — "
            f"{self.event_count} events (expected ~{self.expected_count:.1f}){label_str}"
        )


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class AnomalyDetector:
    """
    Statistical anomaly detector for CCTV event streams.

    Args:
        threshold:    Z-score threshold above which a bucket is anomalous (default 2.0).
        min_baseline: Minimum number of baseline data-points required before flagging
                      silence anomalies for a camera (default 3).
    """

    def __init__(self, threshold: float = 2.0, min_baseline: int = 3) -> None:
        self.threshold = threshold
        self.min_baseline = min_baseline

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        observe_events: list[Event],
        baseline_events: list[Event],
        observe_start: datetime,
        observe_end: datetime,
    ) -> list[AnomalyResult]:
        """
        Run anomaly detection.

        Args:
            observe_events:  Events in the period being checked.
            baseline_events: Historical events used to build the normal baseline.
            observe_start:   Start of the observe window (UTC-aware or naive).
            observe_end:     End of the observe window.

        Returns:
            List of AnomalyResult, sorted by severity (high → low) then time.
        """
        # Build baseline: per camera → per hour-of-day → list of counts
        baseline = self._build_baseline(baseline_events)

        # Bucket observe_events into 1-hour slots per camera
        observe_buckets = self._bucket_events(observe_events, observe_start, observe_end)

        results: list[AnomalyResult] = []

        for camera, hour_buckets in observe_buckets.items():
            cam_baseline = baseline.get(camera, {})
            for bucket_dt, events_in_bucket in hour_buckets.items():
                hour = bucket_dt.hour
                counts = cam_baseline.get(hour, [])
                mean, std = self._stats(counts)

                observed = len(events_in_bucket)

                # Skip if no baseline data at all (new camera, new hour-of-day)
                if not counts:
                    continue

                # Compute z-score
                if std == 0:
                    # No variance in baseline — any non-zero deviation is anomalous
                    if observed == mean:
                        continue
                    z = float("inf") if observed > mean else float("-inf")
                    z = math.copysign(self.threshold * 3, z)  # map to "high" severity
                else:
                    z = (observed - mean) / std

                if abs(z) <= self.threshold:
                    continue  # within normal range

                # Must have enough baseline days before flagging silence
                if z < -self.threshold and len(counts) < self.min_baseline:
                    continue

                anomaly_type = "spike" if z > 0 else "silence"
                severity = self._severity(abs(z))

                top_labels = self._top_labels(events_in_bucket)

                results.append(
                    AnomalyResult(
                        camera=camera,
                        period_start=bucket_dt,
                        period_end=bucket_dt + timedelta(hours=1),
                        event_count=observed,
                        expected_count=mean,
                        z_score=round(z, 2),
                        anomaly_type=anomaly_type,
                        severity=severity,
                        top_labels=top_labels,
                    )
                )

        # Also check for cameras that had zero events in a bucket that normally has activity
        results.extend(self._detect_silence(observe_buckets, baseline, observe_start, observe_end))

        # Sort: high → medium → low, then chronologically
        severity_order = {"high": 0, "medium": 1, "low": 2}
        results.sort(key=lambda r: (severity_order[r.severity], r.period_start))
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_baseline(self, events: list[Event]) -> dict[str, dict[int, list[int]]]:
        """
        Group baseline events by camera → hour-of-day → list[count_per_day_bucket].

        We use daily buckets keyed by (date, hour) so that each unique
        calendar-hour in the baseline contributes exactly one count.
        """
        # camera → (date, hour) → count
        raw: dict[str, dict[tuple, int]] = {}
        for evt in events:
            cam = evt.camera_name
            ts = _ensure_naive(evt.start_time)
            key = (ts.date(), ts.hour)
            raw.setdefault(cam, {}).setdefault(key, 0)
            raw[cam][key] += 1

        # Convert to camera → hour → list[count]
        result: dict[str, dict[int, list[int]]] = {}
        for cam, day_buckets in raw.items():
            result[cam] = {}
            for (_, hour), count in day_buckets.items():
                result[cam].setdefault(hour, []).append(count)

        return result

    def _bucket_events(
        self,
        events: list[Event],
        start: datetime,
        end: datetime,
    ) -> dict[str, dict[datetime, list[Event]]]:
        """
        Group events by camera → floored-to-hour datetime → list[Event].
        """
        buckets: dict[str, dict[datetime, list[Event]]] = {}
        for evt in events:
            cam = evt.camera_name
            ts = _ensure_naive(evt.start_time)
            bucket = ts.replace(minute=0, second=0, microsecond=0)
            buckets.setdefault(cam, {}).setdefault(bucket, []).append(evt)
        return buckets

    def _detect_silence(
        self,
        observe_buckets: dict[str, dict[datetime, list[Event]]],
        baseline: dict[str, dict[int, list[int]]],
        observe_start: datetime,
        observe_end: datetime,
    ) -> list[AnomalyResult]:
        """
        For each camera that has a strong baseline, check whether any hours
        in the observe window had *zero* events when we normally expect activity.
        """
        results: list[AnomalyResult] = []
        observe_start_n = _ensure_naive(observe_start)
        observe_end_n = _ensure_naive(observe_end)

        for camera, hour_map in baseline.items():
            for hour, counts in hour_map.items():
                if len(counts) < self.min_baseline:
                    continue
                mean, std = self._stats(counts)
                if mean < 1.0:
                    # Normally quiet — zero events is not unusual
                    continue

                # Find all buckets in the observe window matching this hour-of-day
                current = observe_start_n.replace(minute=0, second=0, microsecond=0)
                while current <= observe_end_n:
                    if current.hour == hour:
                        cam_buckets = observe_buckets.get(camera, {})
                        observed = len(cam_buckets.get(current, []))
                        if observed == 0:
                            # Zero events during an hour that normally has ~mean events
                            if std == 0:
                                z = -self.threshold * 3  # definitely anomalous
                            else:
                                z = (0 - mean) / std
                            if z < -self.threshold:
                                results.append(
                                    AnomalyResult(
                                        camera=camera,
                                        period_start=current,
                                        period_end=current + timedelta(hours=1),
                                        event_count=0,
                                        expected_count=mean,
                                        z_score=round(z, 2),
                                        anomaly_type="silence",
                                        severity=self._severity(abs(z)),
                                        top_labels=[],
                                    )
                                )
                    current += timedelta(hours=1)

        return results

    @staticmethod
    def _stats(counts: list[int]) -> tuple[float, float]:
        """Return (mean, std) for a list of counts. Returns (0, 0) if empty."""
        if not counts:
            return 0.0, 0.0
        n = len(counts)
        mean = sum(counts) / n
        if n < 2:
            return mean, 0.0
        variance = sum((x - mean) ** 2 for x in counts) / (n - 1)
        return mean, math.sqrt(variance)

    def _severity(self, abs_z: float) -> str:
        t = self.threshold
        if abs_z >= 3 * t:
            return "high"
        if abs_z >= 2 * t:
            return "medium"
        return "low"

    @staticmethod
    def _top_labels(events: list[Event]) -> list[str]:
        """Return the most common labels across events, deduplicated."""
        from collections import Counter

        labels = [o.label for e in events for o in (e.objects or [])]
        if not labels:
            return []
        return [label for label, _ in Counter(labels).most_common(3)]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _ensure_naive(dt: datetime) -> datetime:
    """Strip timezone info so naive and aware datetimes can be compared."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt
