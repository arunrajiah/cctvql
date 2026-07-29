# cctvQL
Conversational query layer for CCTV systems: ask cameras anything in plain English via local or cloud LLMs.

## Stack
Python 3.10+ (setuptools, pyproject.toml), FastAPI + uvicorn, pydantic v2, httpx, aiosqlite, websockets. Optional extras: mqtt, onvif, voice (whisper/openai), face, push. pytest, ruff, mypy. Docker + Home Assistant integration (hacs.json).

## Layout
- `cctvql/` - package: `adapters/` (frigate, onvif, dahua...), `core/`, `llm/` (openai, ollama backends), `interfaces/` (cli, voice), `notifications/`
- `tests/` - pytest suite
- `docs/`, `deploy/`, `custom_components/`, `integrations/`, `mobile/` - docs, deployment, HA integration, mobile client
- `config/`, `blueprints/` - runtime config and HA blueprints

## Commands
- `make dev` - install with dev deps (side effect: pip install)
- `make test`, `make coverage` - pytest
- `make lint` (ruff), `make format` (auto-formats files), `make type-check` (mypy)
- `make docker`, `make docker-up|docker-down` - Docker (side effects: image build, running containers)
- `make demo` - interactive demo with mock adapter

## Conventions
- Typed package (`py.typed`); pre-commit hooks configured (`.pre-commit-config.yaml`).
- No em dashes in user-facing copy.

## Token efficiency
- Grep/Glob to the target file; read only the relevant section, never whole large files.
- Don't re-read files after editing. Verify once per batch of edits, not per edit.
- Keep progress narration and final summaries to 2-3 sentences.
