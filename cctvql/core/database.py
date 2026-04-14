"""
cctvQL Persistence Layer
------------------------
SQLite-backed async database using aiosqlite.

Tables:
  sessions(id, created_at, last_active)
  messages(id, session_id, role, content, ts)
  events_log(id, adapter_name, camera_name, label, zone, score, snapshot_url, clip_url, ts)
  fired_alerts(id, rule_id, event_id, ts)
"""

from __future__ import annotations

import csv
import io
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from cctvql.core.schema import Event

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "cctvql.db"


class Database:
    """Async SQLite database for cctvQL persistence."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path: str = db_path or os.environ.get("CCTVQL_DB_PATH") or _DEFAULT_DB_PATH
        self._conn: Any = None  # aiosqlite.Connection when connected

    async def connect(self) -> None:
        """Open aiosqlite connection and create tables if they don't exist."""
        import aiosqlite  # optional dependency — pip install cctvql[db]

        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info("Database connected: %s", self.db_path)

    async def disconnect(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database disconnected.")

    async def _create_tables(self) -> None:
        """Create all tables on first use."""
        assert self._conn is not None
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS events_log (
                id TEXT PRIMARY KEY,
                adapter_name TEXT NOT NULL,
                camera_name TEXT NOT NULL,
                label TEXT,
                zone TEXT,
                score REAL,
                snapshot_url TEXT,
                clip_url TEXT,
                ts TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS fired_alerts (
                id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                ts TEXT NOT NULL
            );
            """
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Session messages
    # ------------------------------------------------------------------

    async def get_session_messages(self, session_id: str) -> list[dict]:
        """Return all messages for a session, ordered by timestamp."""
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT role, content, ts FROM messages WHERE session_id = ? ORDER BY ts ASC",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"role": row["role"], "content": row["content"], "ts": row["ts"]} for row in rows]

    async def save_message(self, session_id: str, role: str, content: str) -> None:
        """Persist a message, creating the session record if needed."""
        assert self._conn is not None
        now = datetime.utcnow().isoformat()
        msg_id = str(uuid.uuid4())

        # Upsert session
        await self._conn.execute(
            """
            INSERT INTO sessions (id, created_at, last_active)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET last_active = excluded.last_active
            """,
            (session_id, now, now),
        )

        await self._conn.execute(
            "INSERT INTO messages (id, session_id, role, content, ts) VALUES (?, ?, ?, ?, ?)",
            (msg_id, session_id, role, content, now),
        )
        await self._conn.commit()

    async def delete_session_messages(self, session_id: str) -> None:
        """Delete all messages for a session."""
        assert self._conn is not None
        await self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Event log
    # ------------------------------------------------------------------

    async def log_event(self, event: Event, adapter_name: str) -> None:
        """Log a CCTV event to the events_log table."""
        assert self._conn is not None
        now = datetime.utcnow().isoformat()
        event_id = str(uuid.uuid4())

        # Extract primary label and confidence
        label: str | None = None
        score: float | None = None
        if event.objects:
            best = max(event.objects, key=lambda o: o.confidence)
            label = best.label
            score = best.confidence

        zone = event.zones[0] if event.zones else None

        await self._conn.execute(
            """
            INSERT INTO events_log
                (id, adapter_name, camera_name, label, zone, score, snapshot_url, clip_url, ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                adapter_name,
                event.camera_name,
                label,
                zone,
                score,
                event.snapshot_url,
                event.clip_url,
                now,
            ),
        )
        await self._conn.commit()

    async def log_fired_alert(self, rule_id: str, event_id: str) -> None:
        """Record that an alert rule was fired for a given event."""
        assert self._conn is not None
        fired_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        await self._conn.execute(
            "INSERT INTO fired_alerts (id, rule_id, event_id, ts) VALUES (?, ?, ?, ?)",
            (fired_id, rule_id, event_id, now),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_events(
        self,
        limit: int = 100,
        camera: str | None = None,
        label: str | None = None,
    ) -> list[dict]:
        """Fetch logged events with optional filters."""
        assert self._conn is not None
        query = "SELECT * FROM events_log WHERE 1=1"
        params: list = []
        if camera:
            query += " AND camera_name LIKE ?"
            params.append(f"%{camera}%")
        if label:
            query += " AND label = ?"
            params.append(label)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def export_events_csv(
        self,
        camera: str | None = None,
        label: str | None = None,
        limit: int = 1000,
    ) -> str:
        """Return logged events as a CSV string."""
        events = await self.get_events(limit=limit, camera=camera, label=label)
        if not events:
            return "id,adapter_name,camera_name,label,zone,score,snapshot_url,clip_url,ts\n"

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(events[0].keys()))
        writer.writeheader()
        writer.writerows(events)
        return buf.getvalue()
