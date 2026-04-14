# Home Assistant Integration

cctvQL ships as a native Home Assistant custom integration. Once installed, it appears in the **Integrations** UI exactly like any official integration — no YAML editing required.

---

## Installation

### Option A — HACS (recommended)

1. Open Home Assistant → **HACS** → **Integrations**
2. Click **⋮ → Custom repositories**
3. Add `https://github.com/arunrajiah/cctvql`, category **Integration**
4. Search for **cctvQL** and click **Install**
5. Restart Home Assistant

### Option B — Manual

1. Copy the `custom_components/cctvql/` folder into your HA `config/custom_components/`:
   ```bash
   cp -r custom_components/cctvql/ /config/custom_components/cctvql/
   ```
2. Restart Home Assistant

---

## Setup

After installing:

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **cctvQL**
3. Enter your cctvQL server details:

   | Field | Description |
   |-------|-------------|
   | **Host** | IP or hostname where cctvQL is running (e.g. `192.168.1.50`) |
   | **Port** | cctvQL port (default: `8000`) |
   | **API Key** | Optional — only needed if `CCTVQL_API_KEY` is set on the server |

4. Click **Submit** — HA will verify connectivity before saving

---

## Entities Created

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.cctvql_cameras_online` | Number of cameras currently online |
| `sensor.cctvql_cameras_offline` | Number of cameras currently offline |
| `sensor.cctvql_adapter_status` | Active adapter name (`frigate`, `demo`, etc.) |
| `sensor.cctvql_llm_status` | Active LLM backend name (`ollama`, `openai`, etc.) |
| `sensor.cctvql_recent_events` | Count of events from the last poll; `recent` attribute holds the 5 latest |

### Binary Sensors

One binary sensor per camera (auto-discovered):

| Entity | State | Description |
|--------|-------|-------------|
| `binary_sensor.cctvql_{camera}_motion` | `ON` / `OFF` | `ON` if an event was detected in the last poll window |

**Attributes on each motion sensor:**
- `camera_id` — camera ID
- `event_count` — number of recent events
- `latest_event_time` — ISO timestamp of the last event
- `latest_label` — detected object label (`person`, `car`, etc.)
- `snapshot_url` — link to the event snapshot image

---

## Services

### `cctvql.query`

Ask cctvQL a natural language question. The answer is fired as a
`cctvql_query_result` HA event so automations and scripts can react.

```yaml
action:
  - service: cctvql.query
    data:
      query: "Were there any people at the front door last night?"
      session_id: "homeassistant"   # optional, for multi-turn conversations
```

**Reacting to the answer in an automation:**

```yaml
trigger:
  - platform: event
    event_type: cctvql_query_result
action:
  - service: notify.mobile_app
    data:
      message: "{{ trigger.event.data.answer }}"
```

---

### `cctvql.ptz`

Send a PTZ (pan/tilt/zoom) command to a camera.

```yaml
action:
  - service: cctvql.ptz
    data:
      camera_id: "cam_front_door"
      action: "left"       # left | right | up | down | zoom_in | zoom_out | home | preset
      speed: 50            # optional, 1-100
      preset_id: 2         # required when action is "preset"
```

---

### `cctvql.clear_session`

Reset the conversation history for a session.

```yaml
action:
  - service: cctvql.clear_session
    data:
      session_id: "homeassistant"
```

---

## Dashboard Examples

### Camera status card

```yaml
type: entities
title: CCTV Status
entities:
  - entity: sensor.cctvql_cameras_online
    name: Cameras Online
  - entity: sensor.cctvql_cameras_offline
    name: Cameras Offline
  - entity: sensor.cctvql_adapter_status
    name: Adapter
  - entity: sensor.cctvql_llm_status
    name: LLM Backend
```

### Recent events Markdown card

```yaml
type: markdown
title: Recent CCTV Events
content: >
  {% set events = state_attr('sensor.cctvql_recent_events', 'recent') %}
  {% if events %}
  {% for e in events %}
  - **{{ e.label or 'motion' }}** on **{{ e.camera }}** at {{ e.start_time[:16] | replace('T', ' ') }}
  {% endfor %}
  {% else %}
  No recent events.
  {% endif %}
```

### Motion alert automation

Notify your phone when a person is detected on any camera:

```yaml
alias: CCTV Person Detected
trigger:
  - platform: state
    entity_id:
      - binary_sensor.cctvql_front_door_motion
      - binary_sensor.cctvql_backyard_motion
    to: "on"
condition:
  - condition: template
    value_template: >
      {{ state_attr(trigger.entity_id, 'latest_label') == 'person' }}
action:
  - service: notify.mobile_app
    data:
      title: "Person detected"
      message: >
        {{ state_attr(trigger.entity_id, 'latest_label') | title }}
        on {{ state_attr(trigger.entity_id, 'camera_id') }}
      data:
        url: "{{ state_attr(trigger.entity_id, 'snapshot_url') }}"
```

### Ask cctvQL from a dashboard button

```yaml
# scripts.yaml
cctvql_ask:
  sequence:
    - service: cctvql.query
      data:
        query: "{{ states('input_text.cctvql_query') }}"
        session_id: "dashboard"
```

```yaml
# Lovelace card (requires input_text.cctvql_query helper)
type: vertical-stack
cards:
  - type: entities
    entities:
      - entity: input_text.cctvql_query
        name: Ask cctvQL
  - type: button
    name: Ask
    tap_action:
      action: call-service
      service: script.cctvql_ask
```

---

## Polling Interval

Default: **30 seconds**. To change it:

1. Go to **Settings → Devices & Services → cctvQL → Configure**
2. Set the desired interval (10–3600 seconds)

---

## Troubleshooting

**"Cannot connect to cctvQL"**
Check that cctvQL is reachable from the HA host:
```bash
curl http://192.168.1.50:8000/health
```

**Entities show "unavailable"**
Check HA logs (**Settings → System → Logs**) for `homeassistant.helpers.update_coordinator`.

**Motion sensors all show OFF**
The demo adapter generates events on demand. Reduce the poll interval
or check `/events` directly to verify events are being produced.

**PTZ service has no effect**
The demo adapter does not support PTZ. Use an adapter for a PTZ-capable
camera (ONVIF, Hikvision, Dahua).

---

## Architecture

```
Home Assistant
    │
    ├── DataUpdateCoordinator (default: every 30 s)
    │       ├── GET /health
    │       ├── GET /cameras
    │       ├── GET /health/cameras
    │       └── GET /events?limit=50
    │
    ├── Sensors (5 entities) — read from coordinator data
    ├── Binary Sensors (1 per camera) — motion state + snapshot URL
    │
    └── Services
            ├── cctvql.query        → POST /query → fires cctvql_query_result HA event
            ├── cctvql.ptz          → POST /cameras/{id}/ptz
            └── cctvql.clear_session → DELETE /sessions/{id}
```
