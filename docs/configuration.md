# Configuration Reference

cctvQL is configured via a single YAML file: `config/config.yaml`.

Copy the example file to get started:
```bash
cp config/example.yaml config/config.yaml
```

---

## Full Reference

```yaml
# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging:
  level: INFO   # DEBUG | INFO | WARNING | ERROR

# ─────────────────────────────────────────────
# LLM Backends
# ─────────────────────────────────────────────
llm:
  active: ollama    # Which backend is used for NLP

  backends:

    # Ollama — fully local, no API key needed
    ollama:
      provider: ollama
      host: http://localhost:11434
      model: llama3          # any model pulled via `ollama pull <model>`

    # OpenAI
    openai:
      provider: openai
      model: gpt-4o-mini     # gpt-4o for best accuracy
      api_key: ""            # or use OPENAI_API_KEY env var

    # Anthropic
    anthropic:
      provider: anthropic
      model: claude-haiku-4-5-20251001
      api_key: ""            # or use ANTHROPIC_API_KEY env var

    # Any OpenAI-compatible endpoint (LM Studio, Together AI, Groq, etc.)
    lmstudio:
      provider: openai
      base_url: http://localhost:1234/v1
      model: local-model
      api_key: not-needed

# ─────────────────────────────────────────────
# CCTV Adapters
# ─────────────────────────────────────────────
adapters:
  active: frigate   # Which adapter is used

  systems:

    # Frigate NVR
    frigate:
      type: frigate
      host: http://192.168.1.100:5000   # Frigate base URL
      mqtt_host: 192.168.1.100          # MQTT broker (optional)
      mqtt_port: 1883                   # default: 1883

    # ONVIF device
    onvif:
      type: onvif
      host: 192.168.1.200
      port: 80
      username: admin
      password: ""
```

---

## Database

cctvQL persists conversation history and events to SQLite. Configure the database path via environment variable:

```bash
export CCTVQL_DB_PATH=/data/cctvql.db
```

If not set, data is written to `cctvql.db` in the working directory. See [persistence.md](persistence.md) for full details.

---

## Notifications

Send alerts to any combination of channels when an alert rule fires:

```yaml
notifications:
  # HTTP webhook (works with Home Assistant, Zapier, etc.)
  webhooks:
    - url: https://example.com/hook

  # Telegram bot
  telegram:
    bot_token: "123456:ABC-DEF..."
    chat_id: "-1001234567890"

  # Slack incoming webhook
  slack:
    webhook_url: "https://hooks.slack.com/services/..."

  # ntfy push notifications
  ntfy:
    topic: my-cctvql-alerts
    server: https://ntfy.sh        # defaults to ntfy.sh

  # Email via SMTP
  email:
    smtp_host: smtp.gmail.com
    smtp_port: 587
    username: you@gmail.com
    password: ""                   # use CCTVQL_SMTP_PASSWORD env var
    from_addr: you@gmail.com
    to_addrs:
      - recipient@example.com
    use_tls: true
```

See [notifications.md](notifications.md) for full setup instructions for each channel.

---

## Environment Variables

Sensitive values can be passed as environment variables instead of hardcoding them in the config file:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `CCTVQL_API_KEY` | Require `X-API-Key` header on all REST requests |
| `CCTVQL_DB_PATH` | SQLite database file path (default: `cctvql.db`) |
| `CCTVQL_HEALTH_POLL_INTERVAL` | Camera health poll interval in seconds (default: `60`) |
| `CCTVQL_SMTP_PASSWORD` | SMTP password for email notifications |

---

## Docker Environment Variables

When using Docker, pass variables via `docker-compose.yml` or `.env`:

```env
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
CCTVQL_DB_PATH=/data/cctvql.db
CCTVQL_HEALTH_POLL_INTERVAL=60
```

```yaml
# docker-compose.yml
services:
  cctvql:
    env_file: .env
    volumes:
      - cctvql_data:/data
```

---

## Multiple Systems

You can define multiple adapters and switch between them:

```yaml
adapters:
  active: frigate   # change to "onvif" to switch

  systems:
    frigate:
      type: frigate
      host: http://192.168.1.100:5000

    onvif_lobby:
      type: onvif
      host: 192.168.1.201
      username: admin
      password: secret123
```

Multi-system simultaneous querying is on the [roadmap](../README.md#roadmap).
