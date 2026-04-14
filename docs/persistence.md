# Session Persistence & Event Log

cctvQL uses SQLite (via `aiosqlite`) to persist conversation history and log CCTV events across server restarts.

---

## What Is Persisted

| Data | Table | Description |
|------|-------|-------------|
| Conversation sessions | `sessions` | Session IDs and last-active timestamps |
| Chat messages | `messages` | Full conversation history per session |
| CCTV events | `events_log` | Every event received from the adapter |
| Fired alerts | `fired_alerts` | Record of every alert rule that fired |

---

## Configuration

### Database path

By default, cctvQL writes to `cctvql.db` in the current working directory.

Override this via environment variable:
```bash
export CCTVQL_DB_PATH=/data/cctvql.db
```

Or via `docker-compose.yml`:
```yaml
services:
  cctvql:
    environment:
      CCTVQL_DB_PATH: /data/cctvql.db
    volumes:
      - cctvql_data:/data
```

> There is currently no `database:` key in `config.yaml` — the path is set via the env var only.

### Health monitor poll interval

The health monitor polls all cameras at a configurable interval (default: 60 seconds):
```bash
export CCTVQL_HEALTH_POLL_INTERVAL=30
```

---

## Session History

When the database is connected, conversation history is saved to SQLite and survives server restarts.

**How it works:**
1. Every `/query` request uses a `session_id` (provided by the caller, or auto-generated)
2. The user message and the assistant response are both saved to the `messages` table
3. On subsequent requests with the same `session_id`, the full conversation history is loaded and sent to the LLM as context
4. `DELETE /sessions/{session_id}` removes the history from both the in-memory cache and the database

**Without a database:** session history is stored in-memory only and is lost when the server restarts. This is the default when `CCTVQL_DB_PATH` is not set and `aiosqlite` is unavailable.

---

## Event Log

Every event received from the CCTV adapter is written to the `events_log` table.

**Schema:**
```sql
CREATE TABLE events_log (
    id          TEXT PRIMARY KEY,
    adapter_name TEXT NOT NULL,
    camera_name  TEXT NOT NULL,
    label        TEXT,
    zone         TEXT,
    score        REAL,
    snapshot_url TEXT,
    clip_url     TEXT,
    ts           TEXT NOT NULL
);
```

**Querying events:**
```bash
# Via REST API
curl "http://localhost:8000/events?camera=Front+Door&label=person&limit=50"

# Export to CSV
curl "http://localhost:8000/events/export" -o events.csv

# Export to JSON
curl "http://localhost:8000/events/export?fmt=json" -o events.json

# Filtered export
curl "http://localhost:8000/events/export?camera=Front+Door&label=person" -o front_door_persons.csv
```

**Direct SQLite access:**
```bash
sqlite3 cctvql.db "SELECT camera_name, label, score, ts FROM events_log ORDER BY ts DESC LIMIT 20;"
```

---

## Fired Alerts Log

Each time an alert rule fires, a record is written to `fired_alerts`:

```sql
CREATE TABLE fired_alerts (
    id       TEXT PRIMARY KEY,
    rule_id  TEXT NOT NULL,
    event_id TEXT NOT NULL,
    ts       TEXT NOT NULL
);
```

This provides a full audit trail of which rules fired and when.

---

## Backup & Maintenance

**Backup:**
```bash
# Simple copy
cp cctvql.db cctvql.db.bak

# Online backup (safe while server is running)
sqlite3 cctvql.db ".backup cctvql_backup.db"
```

**Pruning old events** (direct SQL):
```bash
# Delete events older than 90 days
sqlite3 cctvql.db "DELETE FROM events_log WHERE ts < datetime('now', '-90 days');"
sqlite3 cctvql.db "VACUUM;"
```

**Reset everything:**
```bash
# Stop the server first, then
rm cctvql.db
# cctvQL will recreate the schema on next startup
```

---

## Docker Deployment with Persistence

Mount a named volume so data survives container restarts and upgrades:

```yaml
# docker-compose.yml
services:
  cctvql:
    build: .
    environment:
      CCTVQL_DB_PATH: /data/cctvql.db
      CCTVQL_HEALTH_POLL_INTERVAL: "60"
    volumes:
      - ./config/config.yaml:/app/config/config.yaml:ro
      - cctvql_data:/data

volumes:
  cctvql_data:
```

---

## Database Schema Overview

```sql
-- Conversation sessions
CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    last_active TEXT NOT NULL
);

-- Per-session messages
CREATE TABLE messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role       TEXT NOT NULL,   -- "user" | "assistant"
    content    TEXT NOT NULL,
    ts         TEXT NOT NULL
);

-- CCTV event log
CREATE TABLE events_log (
    id           TEXT PRIMARY KEY,
    adapter_name TEXT NOT NULL,
    camera_name  TEXT NOT NULL,
    label        TEXT,
    zone         TEXT,
    score        REAL,
    snapshot_url TEXT,
    clip_url     TEXT,
    ts           TEXT NOT NULL
);

-- Alert firing history
CREATE TABLE fired_alerts (
    id       TEXT PRIMARY KEY,
    rule_id  TEXT NOT NULL,
    event_id TEXT NOT NULL,
    ts       TEXT NOT NULL
);
```
