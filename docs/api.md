# REST API Reference

cctvQL exposes a REST API when running in `serve` mode. All endpoints return JSON.

**Base URL:** `http://localhost:8000` (default)  
**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

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
| `session_id` | string | ❌ | Session ID for multi-turn conversation (default: `"default"`) |

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

## GET /events

Fetch events with optional filters.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `camera` | string | Camera name or ID |
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

## DELETE /sessions/{session_id}

Clear conversation history for a session.

```bash
curl -X DELETE http://localhost:8000/sessions/my-session
```

**Response:**
```json
{"status": "cleared", "session_id": "my-session"}
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
