# Docker Deployment

cctvQL ships with a Dockerfile and a Docker Compose stack that bundles the application with a local Ollama instance.

---

## Quick Start

```bash
# 1. Copy and edit the config
cp config/example.yaml config/config.yaml

# 2. Start services
docker compose up -d
```

This brings up two containers:

| Service | Port | Description |
|---------|------|-------------|
| `cctvql` | `8000` | REST API server |
| `ollama` | `11434` | Local LLM backend |

---

## Configuration

Mount your config file as a read-only volume:

```yaml
volumes:
  - ./config/config.yaml:/app/config/config.yaml:ro
```

For cloud LLM backends, set API keys via environment variables in `docker-compose.yml`:

```yaml
environment:
  OPENAI_API_KEY: "sk-..."
  # or
  ANTHROPIC_API_KEY: "sk-ant-..."
```

---

## GPU Support (Ollama)

To enable GPU acceleration for Ollama, uncomment the deploy section in `docker-compose.yml`:

```yaml
ollama:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

---

## Building the Image

```bash
# Build only
docker build -t cctvql .

# Run standalone (without Ollama)
docker run -p 8000:8000 \
  -v ./config/config.yaml:/app/config/config.yaml:ro \
  cctvql
```

---

## Production Tips

- Pin the Ollama image tag instead of using `latest` for reproducible builds.
- Use Docker secrets or an external secret manager for API keys instead of plain-text environment variables.
- Add a reverse proxy (Nginx, Traefik) in front of cctvQL for TLS termination.
- Set resource limits on containers to prevent runaway memory usage.
