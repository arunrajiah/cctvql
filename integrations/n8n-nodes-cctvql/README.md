# n8n-nodes-cctvql

n8n community nodes for [cctvQL](https://github.com/arunrajiah/cctvql) — a natural-language query layer for CCTV systems.

Ask questions like *"Were there any people at the front door last night?"* directly inside n8n workflows, fetch live detection events, and send PTZ commands — across Frigate, Hikvision, Synology, Dahua, Milestone, ONVIF, and more.

---

## Installation

In your n8n instance: **Settings → Community Nodes → Install → search `n8n-nodes-cctvql`**

Or via CLI:
```bash
npm install n8n-nodes-cctvql
```

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

## Credentials

Create a **cctvQL API** credential with:
- **Host** — hostname or IP of your cctvQL server (default: `localhost`)
- **Port** — port (default: `8000`)
- **Protocol** — `http` or `https`
- **API Key** — optional, if you have auth enabled

---

## Nodes

### cctvQL Query
Ask cctvQL a natural language question. Supports n8n expressions so the query can come from upstream nodes.

| Property | Description |
|---|---|
| Query | Natural language question (required) |
| Session ID | For multi-turn conversations (default: `n8n`) |

**Output fields:** `answer`, `intent`, `session_id`, plus the full API response.

---

### cctvQL Events
Fetch recent detection events, optionally filtered by camera or label. Each event becomes a separate item when **Split Into Items** is on.

| Property | Description |
|---|---|
| Camera | Filter by camera name (blank = all) |
| Label | Filter by object label e.g. `person`, `car` |
| Limit | Max events to return (default 20) |
| Split Into Items | One item per event (default on) |

---

### cctvQL PTZ
Send a pan/tilt/zoom command to a camera.

| Property | Description |
|---|---|
| Camera ID | Camera to control (supports expressions) |
| Action | left / right / up / down / zoom_in / zoom_out / home / preset |
| Speed | 1–100 (default 50) |
| Preset ID | Required when action is **Go to Preset** |

---

## Example Workflow

```json
[
  {
    "nodes": [
      { "name": "Schedule Trigger", "type": "n8n-nodes-base.scheduleTrigger" },
      { "name": "cctvQL Query",     "type": "n8n-nodes-cctvql.cctvqlQuery",
        "parameters": { "query": "Any motion at the back door in the last hour?", "sessionId": "nightly-check" } },
      { "name": "Send Telegram",    "type": "n8n-nodes-base.telegram",
        "parameters": { "text": "={{ $json.answer }}" } }
    ]
  }
]
```

---

## License

MIT — [arunrajiah/cctvql](https://github.com/arunrajiah/cctvql)
