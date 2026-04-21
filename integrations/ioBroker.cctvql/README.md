# ioBroker.cctvql

ioBroker adapter for [cctvQL](https://github.com/arunrajiah/cctvql) — a natural-language query layer for CCTV systems.

Ask questions like *"Were there any people at the front door last night?"* directly from ioBroker scripts and Blockly flows, fetch live detection events, and send PTZ commands — across Frigate, Hikvision, Synology, Dahua, Milestone, ONVIF, and more.

---

## Installation

In ioBroker Admin: **Adapter → + → search `cctvql`**

Or via CLI:
```bash
cd /opt/iobroker && npm install iobroker.cctvql
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

## Configuration

| Field | Default | Description |
|---|---|---|
| Host | `localhost` | cctvQL server hostname or IP |
| Port | `8000` | cctvQL server port |
| Protocol | `http` | `http` or `https` |
| API Key | *(empty)* | Optional; leave blank if auth is off |
| Polling Interval | `30` s | How often to fetch detection events |

---

## Data Points

### Query

| ID | Type | Description |
|---|---|---|
| `cctvql.0.query.send` | string (writable) | Write a natural-language question here to trigger a query |
| `cctvql.0.query.answer` | string | Plain-text answer from cctvQL |
| `cctvql.0.query.intent` | string | Detected intent (e.g. `query_events`) |

### Events

| ID | Type | Description |
|---|---|---|
| `cctvql.0.events.latest` | JSON string | Array of recent detection events |
| `cctvql.0.events.count` | number | Count of recent events |
| `cctvql.0.cameras.<id>.lastEvent` | JSON string | Last event per camera (auto-created) |

### Status

| ID | Type | Description |
|---|---|---|
| `cctvql.0.info.connection` | boolean | `true` when cctvQL is reachable |

---

## Example: Query in a Script

```javascript
// In an ioBroker JavaScript adapter script:
setState('cctvql.0.query.send', 'Any cars in the driveway today?');

on({ id: 'cctvql.0.query.answer', change: 'any' }, (obj) => {
    log('cctvQL says: ' + obj.state.val);
    // → "Yes, a white SUV was detected at 14:32 and 17:10."
});
```

---

## License

MIT — [arunrajiah/cctvql](https://github.com/arunrajiah/cctvql)
