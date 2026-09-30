# MCP server: ask your cameras from Alexa+ and other assistants

cctvQL can run as a [Model Context Protocol](https://modelcontextprotocol.io) server over
Streamable HTTP (protocol 2025-11-25). Any MCP client, including Alexa+ integrations,
Claude, ChatGPT connectors and IDE agents, can then answer questions about your cameras:

- "Was anyone at the front door while I was out?"
- "Did a package arrive today?"
- "What happened on the driveway in the last hour?"
- "Are all my cameras online?"

It works with every system cctvQL supports: Frigate, Hikvision, Dahua, Synology Surveillance
Station, Milestone, Scrypted and ONVIF.

## Privacy by design

The server runs on your own network next to your NVR. It returns short text answers and
snapshot links, never video. Nothing is sent to a cctvQL cloud, because there is none.

## Quick start

```bash
pip install "cctvql[mcp]"

# Try it with the built-in demo cameras (no hardware needed)
cctvql mcp --adapter demo

# Or with your own system from config/config.yaml
export CCTVQL_MCP_TOKEN="$(openssl rand -hex 24)"
cctvql mcp --config config/config.yaml --host 0.0.0.0 --port 8765
```

The endpoint is `http://<host>:8765/mcp`. When `CCTVQL_MCP_TOKEN` (or `--token`) is set,
clients must send `Authorization: Bearer <token>`. Always set a token before exposing the
server outside your network, for example through Cloudflare Tunnel or Tailscale Funnel
so a cloud assistant can reach it.

## Tools

| Tool | What it answers |
| --- | --- |
| `list_cameras` | Which cameras exist and whether they are online |
| `recent_activity` | What was detected in the last N minutes, on one camera or all |
| `who_was_at` | Was there a person, car, dog, package... at a camera or zone |
| `latest_snapshot` | Link to the latest still image, for screen devices such as Echo Show |
| `camera_health` | Offline cameras, NVR reachability and storage use |
| `ask_cameras` | Any other free-form question, using cctvQL's own query engine (needs an LLM configured) |
| `point_camera` | Move a PTZ camera to a preset (only with `--allow-ptz`) |

Every tool returns an `answer` field written to be read aloud, plus structured data.
Spoken camera names are matched loosely, so "front door" finds `Front_Door`.

## Connecting a client

Claude Desktop, Cursor and other MCP clients that support Streamable HTTP can add the
server by URL:

```json
{
  "mcpServers": {
    "cctvql": {
      "url": "http://localhost:8765/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

For Alexa+, register the public HTTPS URL of your tunnel as a self-hosted MCP server
following Amazon's Alexa+ MCP documentation.
