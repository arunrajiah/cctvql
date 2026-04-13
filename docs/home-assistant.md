# Home Assistant Integration

cctvQL can be integrated with Home Assistant via its REST API, enabling natural-language CCTV queries from your smart-home dashboard.

---

## Prerequisites

- cctvQL running and accessible from your Home Assistant host (e.g. `http://192.168.1.50:8000`)
- Home Assistant 2024.1 or later

---

## Option 1 — REST Command

Add a REST command to `configuration.yaml` to send natural-language queries:

```yaml
rest_command:
  cctvql_query:
    url: "http://192.168.1.50:8000/query"
    method: POST
    content_type: "application/json"
    payload: '{"query": "{{ query }}"}'
```

Call it from an automation or script:

```yaml
service: rest_command.cctvql_query
data:
  query: "Were there any people in the driveway today?"
```

---

## Option 2 — RESTful Sensor

Create a sensor that polls cctvQL for recent events:

```yaml
sensor:
  - platform: rest
    name: "CCTV Recent Events"
    resource: "http://192.168.1.50:8000/events?minutes=30"
    method: GET
    value_template: "{{ value_json.events | length }}"
    json_attributes:
      - events
    scan_interval: 60
```

---

## Option 3 — Camera Health Sensor

Monitor camera status from your dashboard:

```yaml
sensor:
  - platform: rest
    name: "CCTV Cameras"
    resource: "http://192.168.1.50:8000/cameras"
    method: GET
    value_template: "{{ value_json.cameras | length }} cameras"
    json_attributes:
      - cameras
    scan_interval: 300
```

---

## Dashboard Card

Use a Markdown card to display the most recent events:

```yaml
type: markdown
title: CCTV Activity
content: >
  {% for event in state_attr('sensor.cctv_recent_events', 'events')[:5] %}
  - **{{ event.label }}** on {{ event.camera }} at {{ event.timestamp }}
  {% endfor %}
```

---

## Tips

- Run cctvQL on the same machine or local network as Home Assistant to minimize latency.
- Use the `/health` endpoint in a binary sensor to alert if cctvQL goes offline.
- Pair with Home Assistant automations to get notifications when specific objects are detected (e.g. "person at front door after 11 PM").
