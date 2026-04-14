# REST API Reference

cctvQL exposes a REST API when running in `serve` mode. All endpoints return JSON unless otherwise stated.

**Base URL:** `http://localhost:8000` (default)  
**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

---

## Authentication

Set the `CCTVQL_API_KEY` environment variable to enable API key authentication.
All requests must then include the header:

```
X-API-Key: your-api-key-here
```

If the variable is not set, all endpoints are open (suitable for private network deployments).

---

## POST /query

Submit a natural language query. Supports multi-turn conversation via `session_id`.

**Request body:**
```json
{
  "query": "Was there any motion on the driveway camera last night?",
  "session_id": "my-session"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | ✅ | Natural language question |
| `session_id` | string | ❌ | Session ID for multi-turn conversation (auto-generated if omitted) |

**Response:**
```json
{
  "answer": "Yes — 2 motion events on Driveway between 23:12 and 23:58.",
  "intent": "get_events",
  "session_id": "my-session"
}
```

**Example — multi-turn:**
```bash
# Turn 1
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Show cameras", "session_id": "s1"}'

# Turn 2 — follow-up
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Any motion on the first one today?", "session_id": "s1"}'
```

> Conversation history is persisted to SQLite when the database is configured.
> Sessions survive server restarts. See [persistence.md](persistence.md).

---

## GET /cameras

List all cameras in the connected system.

**Response:**
```json
[
  {
    "id": "front_door",
    "name": "front_door",
    "status": "online",
    "location": null,
    "zones": ["driveway", "porch"],
    "snapshot_url": "http://192.168.1.100:5000/api/front_door/latest.jpg",
    "stream_url": "http://192.168.1.100:5000/live/front_door"
  }
]
```

---

## POST /cameras/{camera_id}/ptz

Send a PTZ (Pan / Tilt / Zoom) command to a camera.

> Only adapters that support PTZ will execute the command. The demo adapter returns `501 Not Implemented`.

**Path parameter:**

| Parameter | Description |
|-----------|-------------|
| `camera_id` | Camera ID as returned by `GET /cameras` |

**Request body:**
```json
{
  "action": "left",
  "speed": 50
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action` | string | ✅ | One of: `left`, `right`, `up`, `down`, `zoom_in`, `zoom_out`, `home`, `preset` |
| `speed` | integer | ❌ | Movement speed 1–100 (default: 50) |
| `preset_id` | integer | ❌ | Required when `action` is `preset` |

**Response:**
```json
{"status": "ok", "camera_id": "front_door", "action": "left"}
```

**Error responses:**
- `404` — camera not found
- `422` — invalid action or missing `preset_id`
- `501` — PTZ not supported by the active adapter

**Examples:**
```bash
# Pan left
curl -X POST http://localhost:8000/cameras/front_door/ptz \
  -H "Content-Type: application/json" \
  -d '{"action": "left", "speed": 30}'

# Go to preset 2
curl -X POST http://localhost:8000/cameras/front_door/ptz \
  -H "Content-Type: application/json" \
  -d '{"action": "preset", "preset_id": 2}'

# Return to home position
curl -X POST http://localhost:8000/cameras/front_door/ptz \
  -H "Content-Type: application/json" \
  -d '{"action": "home"}'
```

---

## GET /cameras/{camera_id}/ptz/presets

List saved PTZ presets for a camera.

**Response:**
```json
[
  {"id": 1, "name": "Home"},
  {"id": 2, "name": "Gate"},
  {"id": 3, "name": "Driveway"}
]
```

---

## GET /events

Fetch events with optional filters.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `camera` | string | Camera name or ID (partial match) |
| `label` | string | Object label (`person`, `car`, `dog`, etc.) |
| `zone` | string | Zone name |
| `after` | integer | Unix timestamp — events after this time |
| `before` | integer | Unix timestamp — events before this time |
| `limit` | integer | Max results (1–200, default: 20) |

**Example:**
```bash
# Person detections on driveway in the last hour
curl "http://localhost:8000/events?camera=driveway&label=person&after=$(date -d '1 hour ago' +%s)"
```

**Response:**
```json
[
  {
    "id": "1abc2def",
    "camera": "driveway",
    "type": "object_detected",
    "start_time": "2026-04-13T22:14:31",
    "end_time": "2026-04-13T22:14:44",
    "objects": [
      {"label": "person", "confidence": 0.96}
    ],
    "zones": ["front_yard"],
    "snapshot_url": "http://192.168.1.100:5000/api/events/1abc2def/snapshot.jpg",
    "clip_url": "http://192.168.1.100:5000/api/events/1abc2def/clip.mp4"
  }
]
```

---

## GET /events/export

Export events as a downloadable CSV or JSON file.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fmt` | string | `csv` | Export format: `csv` or `json` |
| `camera` | string | — | Filter by camera name (partial match) |
| `label` | string | — | Filter by object label |
| `limit` | integer | 1000 | Max events to export |

**CSV export (default):**
```bash
curl "http://localhost:8000/events/export" -o events.csv
```

The CSV includes headers:
```
id,camera,type,start_time,end_time,objects,zones,snapshot_url,clip_url
```

Response headers:
```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="cctvql_events.csv"
```

**JSON export:**
```bash
curl "http://localhost:8000/events/export?fmt=json" -o events.json
```

**Filtered export:**
```bash
# Export only Front Door person detections
curl "http://localhost:8000/events/export?camera=Front+Door&label=person&limit=500" -o persons.csv
```

---

## GET /health

Check health of the adapter and LLM backend.

**Response:**
```json
{
  "status": "ok",
  "adapter": "frigate",
  "llm": "ollama",
  "adapter_ok": true,
  "llm_ok": true
}
```

`status` is `"ok"` when both adapter and LLM are healthy, `"degraded"` otherwise.

---

## GET /health/cameras

Get the latest health status for each individual camera.

The health monitor polls the adapter every `CCTVQL_HEALTH_POLL_INTERVAL` seconds (default: 60).
On first startup, the list may be empty until the first poll completes.

**Response:**
```json
[
  {
    "camera_id": "front_door",
    "camera_name": "Front Door",
    "status": "online",
    "last_checked": "2026-04-14T09:31:02",
    "latency_ms": 42
  },
  {
    "camera_id": "backyard",
    "camera_name": "Backyard",
    "status": "offline",
    "last_checked": "2026-04-14T09:31:03",
    "latency_ms": null
  }
]
```

---

## GET /discover/onvif

Discover ONVIF-compatible cameras on the local network using WS-Discovery (UDP multicast to `239.255.255.250:3702`). No external dependencies required.

Useful for bootstrapping — run this endpoint to find cameras and copy their `host`/`port` into `config.yaml`.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `timeout` | float | `3.0` | Probe wait time in seconds (0.5–10.0) |
| `interface` | string | `""` | Local interface IP to bind (default: all interfaces) |

**Example:**
```bash
curl "http://localhost:8000/discover/onvif?timeout=5"
```

**Response:**
```json
[
  {
    "address": "http://192.168.1.101:80/onvif/device_service",
    "host": "192.168.1.101",
    "port": 80,
    "name": "FrontDoorCam",
    "hardware": "DS-2CD2T43G2-2I",
    "types": ["NetworkVideoTransmitter"],
    "scopes": [
      "onvif://www.onvif.org/name/FrontDoorCam",
      "onvif://www.onvif.org/hardware/DS-2CD2T43G2-2I"
    ]
  }
]
```

Returns an empty list `[]` if no devices respond within the timeout.

**CLI equivalent:**
```bash
cctvql discover
cctvql discover --timeout 5 --yaml   # prints config.yaml snippet
```

---

## Alert Rules

### GET /alerts

List all configured alert rules.

**Response:**
```json
[
  {
    "id": "rule_abc123",
    "name": "Night Person Alert",
    "description": "Alert when person detected after 10pm",
    "camera_name": "Front Door",
    "label": "person",
    "time_start": "22:00",
    "time_end": "06:00",
    "webhook_url": "https://example.com/hook",
    "enabled": true,
    "created_at": "2026-04-13T18:00:00"
  }
]
```

### POST /alerts

Create a new alert rule.

**Request body:**
```json
{
  "name": "Night Person Alert",
  "description": "Alert when person detected after 10pm",
  "camera_name": "Front Door",
  "label": "person",
  "time_start": "22:00",
  "time_end": "06:00",
  "webhook_url": "https://example.com/hook"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Human-readable rule name |
| `description` | string | ❌ | Longer description |
| `camera_name` | string | ❌ | Restrict to a specific camera (any camera if omitted) |
| `label` | string | ❌ | Restrict to a specific object label |
| `time_start` | string | ❌ | Active window start (`HH:MM`, 24h) |
| `time_end` | string | ❌ | Active window end (`HH:MM`, 24h) |
| `webhook_url` | string | ❌ | Fire a POST to this URL on match |

Returns `201 Created` with the created rule including its `id`.

### GET /alerts/{rule_id}

Get a specific alert rule.

Returns `404` if the rule does not exist.

### PATCH /alerts/{rule_id}

Update an alert rule (partial update — only send fields you want to change).

```bash
# Disable a rule
curl -X PATCH http://localhost:8000/alerts/rule_abc123 \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

### DELETE /alerts/{rule_id}

Delete an alert rule permanently.

---

## GET /metrics

Prometheus-compatible metrics endpoint for Grafana, alerting, and observability.

```bash
curl http://localhost:8000/metrics
```

**Exposed metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `cctvql_queries_total` | counter | Total NLP queries processed |
| `cctvql_active_sessions` | gauge | Number of active conversation sessions |
| `cctvql_adapter_status` | gauge | 1 = adapter healthy, 0 = degraded |
| `cctvql_llm_status` | gauge | 1 = LLM healthy, 0 = degraded |
| `cctvql_cameras_online` | gauge | Cameras currently reporting online |
| `cctvql_cameras_offline` | gauge | Cameras currently reporting offline |
| `cctvql_alert_rules_total` | gauge | Number of configured alert rules |

**Example output:**
```
# HELP cctvql_queries_total Total NLP queries processed
# TYPE cctvql_queries_total counter
cctvql_queries_total 47

# HELP cctvql_cameras_online Cameras currently online
# TYPE cctvql_cameras_online gauge
cctvql_cameras_online 3

# HELP cctvql_cameras_offline Cameras currently offline
# TYPE cctvql_cameras_offline gauge
cctvql_cameras_offline 1
```

---

## DELETE /sessions/{session_id}

Clear conversation history for a session. Also removes the session from the database if persistence is enabled.

```bash
curl -X DELETE http://localhost:8000/sessions/my-session
```

**Response:**
```json
{"status": "cleared", "session_id": "my-session"}
```

Returns `200` even if the session did not exist.

---

## WebSocket — GET /ws/events

Real-time event stream. Each message is a JSON object representing a new event from the adapter.

```
ws://localhost:8000/ws/events
```

**Example (wscat):**
```bash
wscat -c ws://localhost:8000/ws/events
```

**Sample message:**
```json
{
  "id": "evt_001",
  "camera": "Front Door",
  "type": "object_detected",
  "start_time": "2026-04-14T09:44:12",
  "objects": [{"label": "person", "confidence": 0.94}],
  "zones": ["porch"],
  "snapshot_url": "http://192.168.1.100:5000/api/events/evt_001/snapshot.jpg"
}
```

---

## Home Assistant Integration

Use the `/query` endpoint from Home Assistant automations or scripts:

```yaml
# configuration.yaml
rest_command:
  cctvql_query:
    url: "http://192.168.1.x:8000/query"
    method: POST
    headers:
      Content-Type: "application/json"
    payload: '{"query": "{{ query }}", "session_id": "homeassistant"}'
```

Then call it in an automation:
```yaml
action:
  - service: rest_command.cctvql_query
    data:
      query: "Any motion on the front door camera in the last 10 minutes?"
```
