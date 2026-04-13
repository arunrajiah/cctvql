# Changelog

All notable changes to cctvQL will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- Vision-based event description (multimodal LLM support)
- Home Assistant custom integration
- Hikvision adapter
- Dahua adapter
- Web UI (lightweight chat interface)
- Multi-system queries
- Voice interface (Whisper STT)

---

## [0.1.0] — 2026-04-13

### Added
- Initial release
- Vendor-agnostic core schema (`Camera`, `Event`, `Clip`, `Zone`, `QueryContext`)
- NLP engine with multi-turn conversation support
- Query router with intent-to-adapter mapping
- **Frigate NVR adapter** — full REST API + real-time MQTT event streaming
- **ONVIF adapter** — generic support for any ONVIF-compliant camera or NVR
- Pluggable LLM backends: Ollama (local), OpenAI, Anthropic
- Support for any OpenAI-compatible API (LM Studio, Together AI, etc.)
- Interactive CLI (`cctvql chat`)
- FastAPI REST server (`cctvql serve`) with Swagger docs
- Multi-turn session management via `session_id`
- Docker + Docker Compose deployment
- Full configuration via `config/config.yaml`
- GitHub Actions CI for Python 3.10, 3.11, 3.12
- MIT license

[Unreleased]: https://github.com/arunrajiah/cctvql/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/arunrajiah/cctvql/releases/tag/v0.1.0
