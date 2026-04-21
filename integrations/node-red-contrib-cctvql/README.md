# node-red-contrib-cctvql

Node-RED nodes for [cctvQL](https://github.com/arunrajiah/cctvql) — a natural-language query layer for CCTV systems.

Ask questions like *"Were there any people at the front door last night?"* directly inside Node-RED flows, fetch live events, and send PTZ commands — across Frigate, Hikvision, Synology, Dahua, Milestone, ONVIF, and more.

---

## Installation

```bash
npm install node-red-contrib-cctvql
```

Or in Node-RED: **Menu → Manage Palette → Install → search `cctvql`**

---

## Prerequisites

A running [cctvQL server](https://github.com/arunrajiah/cctvql):

```bash
docker run -p 8000:8000 \
  -e CCTVQL_ADAPTER=frigate \
  -e CCTVQL_FRIGATE_HOST=http://192.168.1.100:5000 \
  ghcr.io/arunrajiah/cctvql:latest
```

---

## Nodes

### cctvQL Query
Ask cctvQL a natural language question. The answer arrives on `msg.answer` ready for a notification, template, or debug node.

**Inputs:** `msg.query` (string) — overrides the configured default query  
**Outputs:** `msg.payload` (full response), `msg.answer` (plain text), `msg.intent`

### cctvQL Events
Fetch recent detection events, optionally filtered by camera or label. Can poll on an interval or trigger on an incoming message.

**Outputs:** `msg.payload` — array of event objects

### cctvQL PTZ
Send a pan/tilt/zoom command to a camera.

**Inputs:** `msg.cameraId`, `msg.action`, `msg.speed`, `msg.presetId`

---

## Example Flow

```json
[
  {
    "id": "inject1",
    "type": "inject",
    "name": "Ask cctvQL",
    "props": [{ "p": "query", "v": "Any people at the front door last night?", "vt": "str" }],
    "wires": [["query1"]]
  },
  {
    "id": "query1",
    "type": "cctvql-query",
    "name": "NLP Query",
    "server": "server1",
    "sessionId": "node-red",
    "wires": [["debug1"]]
  },
  {
    "id": "debug1",
    "type": "debug",
    "name": "Answer",
    "active": true,
    "tosidebar": true,
    "property": "answer"
  },
  {
    "id": "server1",
    "type": "cctvql-config",
    "name": "cctvQL Server",
    "host": "localhost",
    "port": 8000
  }
]
```

---

## License

MIT — [arunrajiah/cctvql](https://github.com/arunrajiah/cctvql)
