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

## Environment Variables

Sensitive values can be passed as environment variables instead of hardcoding them in the config file:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |

---

## Docker Environment Variables

When using Docker, pass variables via `docker-compose.yml` or `.env`:

```env
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

```yaml
# docker-compose.yml
services:
  cctvql:
    env_file: .env
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
