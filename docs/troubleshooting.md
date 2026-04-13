# Troubleshooting

---

## cctvQL says "Could not connect to CCTV system"

1. Verify your Frigate/ONVIF host is reachable: `curl http://192.168.1.100:5000/api/version`
2. Check the `host` value in `config/config.yaml` — no trailing slash, correct port
3. If using Docker, make sure cctvQL can reach your NVR (same network, not `localhost`)
4. For ONVIF: confirm the device supports ONVIF and credentials are correct

---

## Ollama is not responding

1. Check Ollama is running: `curl http://localhost:11434/api/tags`
2. If using Docker, Ollama needs to be on the same Docker network as cctvQL
3. In Docker, use `http://ollama:11434` as the host (service name), not `localhost`
4. Make sure your model is pulled: `ollama pull llama3`

---

## LLM returns bad JSON / intent is always "unknown"

1. Try a more capable model — `phi3` or `gemma2` sometimes struggle with structured output
2. Switch to `llama3` or `mistral` for better instruction-following
3. Set `logging.level: DEBUG` in config to see the raw LLM output
4. If using OpenAI/Anthropic, verify your API key is correct

---

## MQTT events are not appearing

1. Confirm `mqtt_host` in config points to your MQTT broker (not Frigate)
2. Install the MQTT extra: `pip install cctvql[mqtt]`
3. Check broker is accessible: `mosquitto_sub -h 192.168.1.100 -t "frigate/#" -v`
4. Verify Frigate is publishing to MQTT in its own logs

---

## REST API returns 503

The adapter or LLM backend is not initialized. Check:
- `GET /health` for status details
- Docker logs: `docker logs cctvql`
- Verify config file is mounted correctly in Docker

---

## Docker: "config file not found"

Make sure you mount your config:
```yaml
volumes:
  - ./config/config.yaml:/app/config/config.yaml:ro
```
And that the file exists locally before starting.

---

## Events are returned but times look wrong

cctvQL uses the local system time for date parsing ("last night", "today"). Make sure:
- Your cctvQL container/host is in the correct timezone
- Set `TZ` env var in Docker: `TZ: America/New_York`

---

## Enable debug logging

```yaml
# config/config.yaml
logging:
  level: DEBUG
```

Or via environment variable:
```bash
CCTVQL_LOG_LEVEL=DEBUG cctvql chat
```

---

## Still stuck?

Open an issue: [github.com/arunrajiah/cctvql/issues](https://github.com/arunrajiah/cctvql/issues)

Please include:
- Your config (redact passwords/API keys)
- Debug logs
- cctvQL version (`cctvql --version`)
- Python version (`python --version`)
