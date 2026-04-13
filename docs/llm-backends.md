# LLM Backend Setup

cctvQL supports multiple LLM backends. All backends implement the same interface — switching between them is a one-line config change.

---

## Ollama (Recommended — Local & Private)

Ollama runs LLMs locally. **No data leaves your network.**

### 1. Install Ollama

```bash
# Linux / macOS
curl -fsSL https://ollama.com/install.sh | sh

# Windows
# Download from https://ollama.com/download
```

### 2. Pull a model

```bash
ollama pull llama3          # best general quality (~4GB)
ollama pull mistral         # good balance of speed/quality (~4GB)
ollama pull phi3            # fast, runs on low-RAM devices (~2GB)
ollama pull gemma2          # Google's model, excellent quality
```

### 3. Configure cctvQL

```yaml
llm:
  active: ollama
  backends:
    ollama:
      provider: ollama
      host: http://localhost:11434
      model: llama3
```

### Docker with Ollama

```yaml
# docker-compose.yml — Ollama is included by default
services:
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
```

After starting, pull a model:
```bash
docker exec ollama ollama pull llama3
```

### GPU acceleration

Ollama automatically uses GPU if available. For Docker:
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

---

## OpenAI

```yaml
llm:
  active: openai
  backends:
    openai:
      provider: openai
      model: gpt-4o-mini    # fastest & cheapest — recommended
      # model: gpt-4o       # highest accuracy
      api_key: ""           # or set OPENAI_API_KEY env var
```

Typical cost for cctvQL queries: < $0.001 per query with `gpt-4o-mini`.

---

## Anthropic

```yaml
llm:
  active: anthropic
  backends:
    anthropic:
      provider: anthropic
      model: claude-haiku-4-5-20251001    # fastest & cheapest
      api_key: ""                          # or set ANTHROPIC_API_KEY env var
```

---

## Any OpenAI-Compatible API

LM Studio, Together AI, Groq, Fireworks, Perplexity, and many others expose an OpenAI-compatible API. Use the `openai` provider with a custom `base_url`:

```yaml
llm:
  active: lmstudio
  backends:
    lmstudio:
      provider: openai
      base_url: http://localhost:1234/v1
      model: meta-llama-3-8b-instruct
      api_key: lm-studio     # required but can be any string
```

---

## Which model should I use?

| Scenario | Recommendation |
|----------|---------------|
| Privacy is critical | Ollama + llama3 or mistral |
| Low-resource device (Raspberry Pi, etc.) | Ollama + phi3 |
| Best accuracy | OpenAI gpt-4o or Anthropic claude-sonnet |
| Fastest responses | OpenAI gpt-4o-mini or Anthropic claude-haiku |
| Offline / air-gapped | Ollama (any model) |

---

## Adding a Custom Backend

Implement `BaseLLM`:

```python
from cctvql.llm.base import BaseLLM, LLMMessage, LLMResponse

class MyCustomBackend(BaseLLM):
    @property
    def name(self) -> str:
        return "my_backend"

    async def complete(self, messages, temperature=0.2, max_tokens=1024) -> LLMResponse:
        # call your LLM API here
        return LLMResponse(content="...", model="my-model")
```

Register it in `_bootstrap.py` and configure via `config.yaml`.
