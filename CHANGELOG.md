# Changelog

All notable changes to cctvQL will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- App Store / Play Store submission (requires Apple/Google developer credentials)
- InsightFace backend option (alternative to DeepFace)

---

## [0.9.0] — 2026-06-23

### Added
- **Pluggable face recognition backend system** (`cctvql/core/face_backends/`)
  - `BaseFaceBackend` — abstract interface: `embed_single`, `detect_and_embed`, `compare`
  - `DlibBackend` — wraps existing `face_recognition` library (128-d Euclidean); default backend
  - `DeepFaceBackend` — wraps `deepface` library (ArcFace 512-d cosine); GPU support via
    TensorFlow/PyTorch; configurable model (`ArcFace`, `Facenet512`, `VGG-Face`, …) and
    detector backend (`retinaface`, `mtcnn`, `opencv`, …)
  - `get_backend(name)` factory in `cctvql/core/face_backends/__init__.py`
  - `FaceRegistry` now accepts a `backend=` kwarg; all embedding/comparison calls go through
    the abstraction; per-backend tolerance defaults
  - Select backend via `CCTVQL_FACE_BACKEND=deepface` env var (default: `dlib`)
  - `[deepface]` optional dependency group: `pip install cctvql[deepface]`
- **EAS mobile build pipeline** (`mobile/`)
  - `mobile/eas.json` — development, preview, production profiles for iOS + Android
  - `mobile/app.json` — OTA update config (EAS Update), runtime version policy
  - `.github/workflows/mobile-build.yml` — EAS build on `mobile/v*` tag push; manual
    dispatch with platform (ios/android/all) and profile selection; optional store submission
  - `.github/workflows/mobile-ota.yml` — publishes OTA JS bundle update on every `main`
    push that touches `mobile/`; no App Store review required for JS-only changes

---

## [0.8.0] — 2026-06-14

### Added
- **Face recognition NLP integration** — natural language queries now route face searches
  - New `search_faces` intent in the NLP engine system prompt
  - Example queries: "Was Alice home last night?", "Did Bob visit today?",
    "When was Sarah last seen on the front door camera?"
  - The query router fetches events for the time window, runs `FaceRegistry.recognise_url()`
    on each snapshot, and returns a timeline of matches with camera, timestamp, and confidence
  - `person_name` field added to the NLP JSON schema so names are reliably extracted
  - `FaceRegistry` is now passed to `QueryRouter` from both `/query` and `/voice/query`
  - Graceful degradation: clear error messages when `face_recognition` library is absent or no
    face registry is configured

---

## [0.7.0] — 2026-06-14

### Added
- **AI event summary endpoint** (`GET /events/{id}/summary`)
  - Combines VisionAnalyzer LLM visual description with face recognition in one structured response
  - Returns `summary` text, `objects`, `zones`, `faces`, `snapshot_url`, `clip_url`
  - Optional `?include_faces=false` to skip recognition when speed matters
  - Respects multi-tenant camera-group scoping
- **Face enrollment + recognition** (`/faces/*`)
  - `GET /faces` — list all enrolled faces
  - `POST /faces/enroll` — enroll from a photo upload; admin-only in multi-tenant mode
  - `GET /faces/{face_id}` — fetch a single enrollment
  - `DELETE /faces/{face_id}` — remove enrollment (admin-only)
  - `POST /faces/recognize` — run recognition on an uploaded image
  - `GET /faces/search/{event_id}` — run recognition on an event's snapshot URL
  - `FaceRegistry` backed by SQLite with in-memory embedding cache
  - Graceful degradation when `face_recognition` library is not installed
- **Mobile push notification management** (`/push/*`)
  - `POST /push/register` — register iOS/Android FCM device token (idempotent upsert)
  - `DELETE /push/register/{token}` — unregister
  - `GET /push/tokens` — list tokens (admins see all; users see own)
  - `PushNotifier` fans out FCM HTTP v1 alerts and auto-removes stale tokens on 400/404
- **React Native mobile app** (`mobile/`) — Expo SDK 51, TypeScript, iOS + Android
  - `LoginScreen` — connects to any cctvQL server with API key or JWT credentials
  - `HomeScreen` — adapter/LLM health, cameras online/offline, recent 5 events
  - `EventsScreen` — filterable event feed with camera and label chips, pull-to-refresh
  - `EventDetailScreen` — snapshot viewer, detected objects with confidence bars, face recognition results
  - `ChatScreen` — multi-turn NLP chat with session management
  - `CameraListScreen` + `CameraDetailScreen` — live status, PTZ D-pad joystick, preset recall
  - `FaceListScreen` + `FaceEnrollScreen` — grid of enrolled faces, camera/library enrolment
  - `SettingsScreen` — server URL, API key, disconnect
  - Push notification registration via `usePushNotifications` hook + `POST /push/register`
  - Zustand auth store with Expo SecureStore persistence
  - TanStack Query v5 for data fetching + pull-to-refresh
- New SQLite tables: `face_enrollments`, `push_tokens` (auto-created on `Database.connect()`)
- `[face]` and `[push]` optional dependency groups in `pyproject.toml`

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
