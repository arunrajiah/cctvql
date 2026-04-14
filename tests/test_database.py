"""
Tests for the Database persistence layer and SessionStore.
Uses in-memory SQLite (:memory:) so no files are created on disk.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cctvql.core.database import Database
from cctvql.core.schema import DetectedObject, Event, EventType
from cctvql.core.session_store import SessionStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    database = Database(db_path=":memory:")
    await database.connect()
    yield database
    await database.disconnect()


@pytest.fixture
async def store(db):
    return SessionStore(db)


# ---------------------------------------------------------------------------
# Database — tables created
# ---------------------------------------------------------------------------


async def test_connect_creates_tables(db):
    """Tables should exist after connect()."""
    async with db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
        tables = {row["name"] for row in await cur.fetchall()}
    assert {"sessions", "messages", "events_log", "fired_alerts"}.issubset(tables)


# ---------------------------------------------------------------------------
# Session messages
# ---------------------------------------------------------------------------


async def test_save_and_retrieve_messages(db):
    await db.save_message("sess1", "user", "Hello")
    await db.save_message("sess1", "assistant", "Hi there")

    msgs = await db.get_session_messages("sess1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "Hi there"


async def test_messages_ordered_by_timestamp(db):
    await db.save_message("sess2", "user", "first")
    await db.save_message("sess2", "assistant", "second")
    await db.save_message("sess2", "user", "third")

    msgs = await db.get_session_messages("sess2")
    contents = [m["content"] for m in msgs]
    assert contents == ["first", "second", "third"]


async def test_session_upsert_on_second_message(db):
    await db.save_message("sess3", "user", "msg1")
    await db.save_message("sess3", "user", "msg2")  # should not raise UNIQUE conflict

    msgs = await db.get_session_messages("sess3")
    assert len(msgs) == 2


async def test_delete_session_messages(db):
    await db.save_message("sess4", "user", "to be deleted")
    await db.delete_session_messages("sess4")

    msgs = await db.get_session_messages("sess4")
    assert msgs == []


async def test_get_messages_empty_session(db):
    msgs = await db.get_session_messages("nonexistent_session")
    assert msgs == []


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


def _make_event(camera: str = "Front Door", label: str = "person") -> Event:
    return Event(
        id="evt_test_001",
        camera_id="cam1",
        camera_name=camera,
        event_type=EventType.MOTION,
        start_time=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        objects=[DetectedObject(label=label, confidence=0.92)],
        zones=["porch"],
    )


async def test_log_event(db):
    event = _make_event()
    await db.log_event(event, adapter_name="demo")

    rows = await db.get_events(limit=10)
    assert len(rows) == 1
    assert rows[0]["camera_name"] == "Front Door"
    assert rows[0]["label"] == "person"
    assert rows[0]["adapter_name"] == "demo"


async def test_log_event_no_objects(db):
    event = Event(
        id="evt_no_obj",
        camera_id="cam1",
        camera_name="Garage",
        event_type=EventType.MOTION,
        start_time=datetime(2026, 4, 14, 11, 0, 0, tzinfo=timezone.utc),
    )
    await db.log_event(event, adapter_name="demo")

    rows = await db.get_events(limit=10)
    assert any(r["camera_name"] == "Garage" for r in rows)


async def test_get_events_filter_camera(db):
    await db.log_event(_make_event("Front Door", "person"), "demo")
    await db.log_event(_make_event("Backyard", "car"), "demo")

    rows = await db.get_events(camera="Front Door")
    assert all(r["camera_name"] == "Front Door" for r in rows)


async def test_get_events_filter_label(db):
    await db.log_event(_make_event("Front Door", "person"), "demo")
    await db.log_event(_make_event("Garage", "car"), "demo")

    rows = await db.get_events(label="car")
    assert all(r["label"] == "car" for r in rows)


async def test_get_events_limit(db):
    for i in range(5):
        e = _make_event()
        e.id = f"evt_{i}"
        await db.log_event(e, "demo")

    rows = await db.get_events(limit=3)
    assert len(rows) == 3


async def test_export_events_csv(db):
    await db.log_event(_make_event(), "demo")
    csv_str = await db.export_events_csv()

    lines = csv_str.strip().splitlines()
    assert lines[0].startswith("id,")
    assert len(lines) >= 2  # header + data


async def test_export_events_csv_empty(db):
    csv_str = await db.export_events_csv()
    lines = csv_str.strip().splitlines()
    assert len(lines) == 1  # header only


# ---------------------------------------------------------------------------
# Fired alerts log
# ---------------------------------------------------------------------------


async def test_log_fired_alert(db):
    await db.log_fired_alert("rule_001", "evt_001")

    async with db._conn.execute("SELECT * FROM fired_alerts") as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["rule_id"] == "rule_001"
    assert rows[0]["event_id"] == "evt_001"


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


async def test_session_store_add_and_get_history(store):
    await store.add_message("s1", "user", "What cameras do I have?")
    await store.add_message("s1", "assistant", "You have 4 cameras.")

    history = await store.get_history("s1")
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "What cameras do I have?"}
    assert history[1] == {"role": "assistant", "content": "You have 4 cameras."}


async def test_session_store_clear(store):
    await store.add_message("s2", "user", "hello")
    await store.clear_session("s2")

    history = await store.get_history("s2")
    assert history == []


async def test_session_store_separate_sessions(store):
    await store.add_message("sa", "user", "session A message")
    await store.add_message("sb", "user", "session B message")

    ha = await store.get_history("sa")
    hb = await store.get_history("sb")
    assert len(ha) == 1
    assert len(hb) == 1
    assert ha[0]["content"] == "session A message"
    assert hb[0]["content"] == "session B message"


async def test_session_store_empty_history(store):
    history = await store.get_history("nonexistent")
    assert history == []
