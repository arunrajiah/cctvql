"""
cctvQL REST API Interface
--------------------------
FastAPI-based HTTP server exposing cctvQL as a REST API.

Endpoints:
  POST /query                  — Natural language query
  GET  /cameras                — List cameras
  POST /cameras/{id}/ptz       — PTZ camera control
  GET  /events                 — Get events (with filters)
  GET  /events/export          — Export events as CSV
  GET  /events/timeline        — Events grouped by camera and time bucket
  GET  /events/{id}/summary    — AI-powered natural-language event summary
  GET  /anomalies              — Detect statistically unusual activity
  GET  /faces                  — List enrolled faces
  POST /faces/enroll           — Enroll a new face (admin-only)
  GET  /faces/{face_id}        — Get a face enrollment
  DELETE /faces/{face_id}      — Delete a face enrollment (admin-only)
  POST /faces/recognize        — Recognize faces in an uploaded image
  GET  /faces/search/{event_id} — Recognize faces in an event snapshot
  POST /push/register          — Register a mobile push token
  DELETE /push/register/{token} — Unregister a push token
  GET  /push/tokens            — List registered push tokens
  GET  /health                 — System health check
  GET  /health/cameras         — Per-camera health status
  GET  /metrics                — Prometheus-compatible metrics
  GET  /alerts                 — List alert rules
  POST /alerts                 — Create alert rule
  GET  /alerts/{id}            — Get alert rule
  PATCH /alerts/{id}           — Update alert rule
  DELETE /alerts/{id}          — Delete alert rule
  DELETE /sessions/{id}        — Clear conversation session
  GET  /discover/onvif         — Discover ONVIF cameras on the local network
  POST /voice/query            — Voice query (audio → text answer)
  POST /voice/synthesize       — Text-to-speech
  WS   /ws/events              — Real-time event streaming via WebSocket
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cctvql.adapters.base import AdapterRegistry
from cctvql.core.alerts import AlertEngine, make_rule_from_context
from cctvql.core.auth import ROLE_ADMIN, AuthManager, User
from cctvql.core.database import Database
from cctvql.core.face_registry import FaceRegistry
from cctvql.core.health_monitor import HealthMonitor
from cctvql.core.multi_query import MultiSystemRouter
from cctvql.core.nlp_engine import NLPEngine
from cctvql.core.query_router import QueryRouter
from cctvql.core.schema import Event
from cctvql.core.session_store import SessionStore
from cctvql.core.user_store import UserStore
from cctvql.core.vision import VisionAnalyzer
from cctvql.llm.base import LLMRegistry
from cctvql.notifications.registry import NotifierRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metrics counters (module-level)
# ---------------------------------------------------------------------------

_query_count: int = 0

# ---------------------------------------------------------------------------
# API Key Authentication Middleware
# ---------------------------------------------------------------------------

_AUTH_SKIP_PATHS = {"/docs", "/openapi.json", "/redoc", "/health", "/health/cameras"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Optional API key authentication middleware.

    When the ``CCTVQL_API_KEY`` environment variable is set, every request
    (except health, docs, and WebSocket upgrades) must include a matching
    ``X-API-Key`` header.  If the env var is *not* set, all requests pass
    through without authentication.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        api_key = os.environ.get("CCTVQL_API_KEY")

        if not api_key:
            return await call_next(request)

        if request.url.path in _AUTH_SKIP_PATHS:
            return await call_next(request)

        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        provided = request.headers.get("X-API-Key")
        if not provided or provided != api_key:
            return Response(
                content='{"detail":"Invalid or missing API key"}',
                status_code=401,
                media_type="application/json",
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Multi-tenant feature flag
# ---------------------------------------------------------------------------

_MULTI_TENANT: bool = os.environ.get("CCTVQL_MULTI_TENANT", "0").strip() in {"1", "true", "yes"}

# Global singletons — set in lifespan, used in route handlers
_db: Database | None = None
_session_store: SessionStore | None = None
_alert_engine: AlertEngine | None = None
_health_monitor: HealthMonitor | None = None
_auth_manager: AuthManager | None = None
_user_store: UserStore | None = None
_face_registry: FaceRegistry | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db, _session_store, _alert_engine, _health_monitor, _auth_manager, _user_store, _face_registry

    # ── 1. Adapter connection ────────────────────────────────────────────────
    try:
        adapter = AdapterRegistry.get_active()
        connected = await adapter.connect()
        if not connected:
            logger.error("Failed to connect to CCTV adapter on startup")
    except RuntimeError:
        logger.warning("No active adapter configured — running in limited mode")

    # ── 2. Database + session store ──────────────────────────────────────────
    db_path = os.environ.get("CCTVQL_DB_PATH", "cctvql.db")
    try:
        _db = Database(db_path=db_path)
        await _db.connect()
        _session_store = SessionStore(_db)
        logger.info("Database connected: %s", db_path)
    except Exception as exc:
        logger.warning("Database unavailable (%s) — sessions will be in-memory only", exc)
        _db = None
        _session_store = None

    # ── 3. Face registry ─────────────────────────────────────────────────────
    if _db is not None:
        _face_registry = FaceRegistry(_db)
        await _face_registry.load_cache()

    # ── 4. Multi-tenant user store (opt-in) ──────────────────────────────────
    if _MULTI_TENANT:
        if _db is None:
            logger.error("Multi-tenant mode requires a database. Set CCTVQL_DB_PATH.")
        else:
            _auth_manager = AuthManager()
            _user_store = UserStore(_db._conn, _auth_manager)
            await _user_store.setup()
            logger.info("Multi-tenant mode enabled")

    # ── 5. Alert engine ──────────────────────────────────────────────────────
    _alert_engine = AlertEngine(AdapterRegistry)
    await _alert_engine.start()

    # ── 6. Health monitor ────────────────────────────────────────────────────
    poll_interval = int(os.environ.get("CCTVQL_HEALTH_POLL_INTERVAL", "60"))
    _health_monitor = HealthMonitor(
        adapter_registry=AdapterRegistry,
        notifier_registry=NotifierRegistry,
        poll_interval=poll_interval,
    )
    await _health_monitor.start()

    logger.info("cctvQL API started")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    await _health_monitor.stop()
    await _alert_engine.stop()
    if _db:
        await _db.disconnect()
    logger.info("cctvQL API stopped")


app = FastAPI(
    title="cctvQL",
    description="Conversational query layer for CCTV systems",
    version="0.1.0",
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(APIKeyMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (Web UI)
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = "default"
    multi: bool = False  # if True, fan-out to all registered adapters


class QueryResponse(BaseModel):
    answer: str
    intent: str
    session_id: str


class HealthResponse(BaseModel):
    status: str
    adapter: str
    llm: str
    adapter_ok: bool
    llm_ok: bool


class AlertRuleCreate(BaseModel):
    name: str
    description: str
    camera_name: str | None = None
    label: str | None = None
    zone: str | None = None
    time_start: str | None = None  # "22:00" HH:MM
    time_end: str | None = None  # "06:00" HH:MM
    webhook_url: str | None = None
    cooldown_seconds: int = 300  # min seconds between firings (0 = no cooldown)


class AlertRuleUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    camera_name: str | None = None
    label: str | None = None
    zone: str | None = None
    time_start: str | None = None
    time_end: str | None = None
    webhook_url: str | None = None
    cooldown_seconds: int | None = None


class AlertRuleResponse(BaseModel):
    id: str
    name: str
    description: str
    camera_name: str | None
    label: str | None
    zone: str | None
    time_start: str | None
    time_end: str | None
    webhook_url: str | None
    cooldown_seconds: int
    enabled: bool
    created_at: str
    last_triggered: str | None
    trigger_count: int


class PTZRequest(BaseModel):
    action: str  # left | right | up | down | zoom_in | zoom_out | stop
    speed: int = 50  # 1–100
    preset_id: int | None = None  # for preset moves


class FaceEnrollResponse(BaseModel):
    face_id: str
    name: str
    label: str
    created_at: str
    image_b64: str


class FaceMatchResponse(BaseModel):
    face_id: str
    name: str
    label: str
    confidence: float


class RecognizeResponse(BaseModel):
    matches: list[FaceMatchResponse]
    face_count: int
    recognition_available: bool


class PushRegisterRequest(BaseModel):
    token: str
    platform: str  # "ios" | "android"
    device_name: str = ""


class PushTokenResponse(BaseModel):
    token: str
    platform: str
    device_name: str
    user_id: str | None
    created_at: str


class EventSummaryResponse(BaseModel):
    event_id: str
    camera_name: str
    timestamp: str
    summary: str
    objects: list[dict]
    zones: list[str]
    snapshot_url: str | None
    clip_url: str | None
    faces: list[FaceMatchResponse]


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user_id: str
    username: str
    role: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    camera_groups: list[str] = []


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    camera_groups: list[str]
    created_at: str
    active: bool


class UserUpdate(BaseModel):
    role: str | None = None
    camera_groups: list[str] | None = None
    active: bool | None = None
    password: str | None = None


# ---------------------------------------------------------------------------
# Multi-tenant auth dependency
# ---------------------------------------------------------------------------


def _require_multi_tenant() -> None:
    """Raise 501 if multi-tenant mode is not enabled."""
    if not _MULTI_TENANT or _user_store is None or _auth_manager is None:
        raise HTTPException(
            status_code=501,
            detail="Multi-tenant mode is not enabled. Set CCTVQL_MULTI_TENANT=1.",
        )


async def _get_current_user(
    request: Request,
) -> User | None:
    """
    Extract and validate the Bearer JWT from the Authorization header.

    Returns the ``User`` object, or ``None`` if multi-tenant is disabled
    (so single-tenant routes can still work without a token).
    """
    if not _MULTI_TENANT:
        return None
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = auth_header[len("Bearer ") :]
    assert _auth_manager is not None
    payload = _auth_manager.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    assert _user_store is not None
    user = await _user_store.get_by_id(payload["sub"])
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")
    return user


def _require_admin(user: User | None) -> User:
    """Raise 403 if *user* is not an admin."""
    if user is None or user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# ---------------------------------------------------------------------------
# Session management (DB-backed when available, in-memory fallback)
# ---------------------------------------------------------------------------

_in_memory_sessions: dict[str, NLPEngine] = {}


def _get_nlp_for_session(session_id: str) -> NLPEngine:
    """
    Return (or create) an NLPEngine for the given session.

    When a SessionStore is available the engine persists conversation history
    to SQLite so it survives restarts.  Without a DB the engine falls back to
    the in-memory dict.
    """
    if session_id not in _in_memory_sessions:
        llm = LLMRegistry.get_active()
        _in_memory_sessions[session_id] = NLPEngine(llm, session_store=_session_store)
    return _in_memory_sessions[session_id]


# ---------------------------------------------------------------------------
# WebSocket: real-time event streaming
# ---------------------------------------------------------------------------

_ws_clients: set[WebSocket] = set()


async def _broadcast_event(event: Event) -> None:
    """Serialize an Event and broadcast to all connected WebSocket clients."""
    data = {
        "id": event.id,
        "camera": event.camera_name,
        "type": event.event_type.value,
        "start_time": event.start_time.isoformat(),
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "objects": [{"label": o.label, "confidence": o.confidence} for o in event.objects],
        "zones": event.zones,
        "snapshot_url": event.snapshot_url,
        "clip_url": event.clip_url,
    }
    message = json.dumps(data)
    disconnected: set[WebSocket] = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _ws_clients.difference_update(disconnected)


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Accept a WebSocket connection and stream real-time CCTV events."""
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Authentication & user management (multi-tenant only)
# ---------------------------------------------------------------------------


@app.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """
    Obtain a JWT access token.

    Only available when ``CCTVQL_MULTI_TENANT=1`` is set.
    """
    _require_multi_tenant()
    assert _user_store is not None and _auth_manager is not None
    user = await _user_store.get_by_username(body.username)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if not _auth_manager.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    import os as _os

    expire_hours = int(_os.environ.get("CCTVQL_TOKEN_EXPIRE_HOURS", "24"))
    return TokenResponse(
        access_token=_auth_manager.create_token(user),
        expires_in=expire_hours * 3600,
        user_id=user.id,
        username=user.username,
        role=user.role,
    )


@app.post("/auth/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, request: Request) -> UserResponse:
    """
    Register a new user.

    - The **first** user to register becomes an admin automatically (bootstrap).
    - All subsequent registrations require an existing admin's Bearer token.

    Only available when ``CCTVQL_MULTI_TENANT=1`` is set.
    """
    _require_multi_tenant()
    assert _user_store is not None

    total = await _user_store.count_users()
    if total == 0:
        # Bootstrap: first user becomes admin regardless of requested role
        role = ROLE_ADMIN
    else:
        # Must be authenticated as admin
        caller = await _get_current_user(request)
        _require_admin(caller)
        role = body.role if body.role in {"admin", "viewer"} else "viewer"

    try:
        user = await _user_store.create_user(
            username=body.username,
            password=body.password,
            role=role,
            camera_groups=body.camera_groups,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return UserResponse(**user.to_dict())


@app.get("/users", response_model=list[UserResponse])
async def list_users(request: Request) -> list[UserResponse]:
    """List all user accounts (admin only)."""
    _require_multi_tenant()
    caller = await _get_current_user(request)
    _require_admin(caller)
    assert _user_store is not None
    users = await _user_store.list_users()
    return [UserResponse(**u.to_dict()) for u in users]


@app.get("/users/me", response_model=UserResponse)
async def get_me(request: Request) -> UserResponse:
    """Return the currently authenticated user's profile."""
    _require_multi_tenant()
    user = await _get_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return UserResponse(**user.to_dict())


@app.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, body: UserUpdate, request: Request) -> UserResponse:
    """
    Update a user account (admin only).

    Allowed fields: ``role``, ``camera_groups``, ``active``, ``password``.
    """
    _require_multi_tenant()
    caller = await _get_current_user(request)
    _require_admin(caller)
    assert _user_store is not None

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields provided.")

    # Guard: cannot demote the last admin
    if updates.get("role") == "viewer" or updates.get("active") is False:
        target = await _user_store.get_by_id(user_id)
        if target and target.role == ROLE_ADMIN:
            admin_count = await _user_store.count_admins()
            if admin_count <= 1:
                raise HTTPException(
                    status_code=409, detail="Cannot demote or deactivate the last admin."
                )

    user = await _user_store.update_user(user_id, **updates)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    return UserResponse(**user.to_dict())


@app.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> dict[str, str]:
    """Delete a user account (admin only)."""
    _require_multi_tenant()
    caller = await _get_current_user(request)
    _require_admin(caller)
    assert _user_store is not None

    # Guard: cannot delete the last admin
    target = await _user_store.get_by_id(user_id)
    if target and target.role == ROLE_ADMIN:
        admin_count = await _user_store.count_admins()
        if admin_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot delete the last admin.")

    deleted = await _user_store.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")
    return {"status": "deleted", "id": user_id}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """Serve the cctvQL Web UI."""
    index = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=index.read_text())


@app.get("/timeline", response_class=HTMLResponse)
async def timeline_ui() -> HTMLResponse:
    """Serve the cctvQL Event Timeline UI."""
    page = Path(__file__).parent / "static" / "timeline.html"
    return HTMLResponse(content=page.read_text())


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """
    Submit a natural language query about your CCTV system.

    Set ``multi=true`` to fan-out the query across all registered adapters
    simultaneously and receive a merged response.
    """
    global _query_count
    try:
        sid = req.session_id or "default"
        nlp = _get_nlp_for_session(sid)
        llm = LLMRegistry.get_active()

        ctx = await nlp.parse(req.query, session_id=sid)

        if req.multi:
            multi_router = MultiSystemRouter(llm)
            answer = await multi_router.route(ctx)
        else:
            router = QueryRouter(
                AdapterRegistry.get_active(),
                llm,
                alert_engine=_alert_engine,
                face_registry=_face_registry,
            )
            answer = await router.route(ctx)

        # Log event to DB if available
        _query_count += 1

        return QueryResponse(answer=answer, intent=ctx.intent, session_id=sid)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Query error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing query")


@app.get("/cameras")
async def list_cameras(request: Request) -> list[dict[str, Any]]:
    """List all cameras in the connected CCTV system."""
    adapter = AdapterRegistry.get_active()
    cameras = await adapter.list_cameras()
    user = await _get_current_user(request)
    if user is not None:
        cameras = [c for c in cameras if user.can_see_camera(c.name)]
    return [
        {
            "id": c.id,
            "name": c.name,
            "status": c.status.value,
            "location": c.location,
            "zones": c.zones,
            "snapshot_url": c.snapshot_url,
            "stream_url": c.stream_url,
        }
        for c in cameras
    ]


@app.post("/cameras/{camera_id}/ptz")
async def ptz_control(camera_id: str, body: PTZRequest) -> dict[str, Any]:
    """
    Send a PTZ (pan/tilt/zoom) command to a camera.

    Actions: ``left`` | ``right`` | ``up`` | ``down`` |
             ``zoom_in`` | ``zoom_out`` | ``stop`` | ``preset``

    For preset moves supply ``preset_id`` in the request body.
    """
    adapter = AdapterRegistry.get_active()

    # Resolve camera name from ID or name match
    cameras = await adapter.list_cameras()
    camera = next(
        (c for c in cameras if c.id == camera_id or c.name.lower() == camera_id.lower()),
        None,
    )
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")

    if body.action == "preset":
        if body.preset_id is None:
            raise HTTPException(status_code=422, detail="preset_id required for preset action.")
        supported = await adapter.ptz_preset(camera.name, body.preset_id)
    else:
        valid_actions = {"left", "right", "up", "down", "zoom_in", "zoom_out", "stop"}
        if body.action not in valid_actions:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid action '{body.action}'. Valid: {', '.join(sorted(valid_actions))}",
            )
        supported = await adapter.ptz_move(camera.name, body.action, body.speed)

    if not supported:
        raise HTTPException(
            status_code=501,
            detail=f"PTZ is not supported by the '{adapter.name}' adapter.",
        )

    return {
        "camera_id": camera_id,
        "camera_name": camera.name,
        "action": body.action,
        "speed": body.speed,
        "preset_id": body.preset_id,
        "status": "sent",
    }


@app.get("/cameras/{camera_id}/ptz/presets")
async def list_ptz_presets(camera_id: str) -> list[dict[str, Any]]:
    """List available PTZ presets for a camera."""
    adapter = AdapterRegistry.get_active()
    cameras = await adapter.list_cameras()
    camera = next(
        (c for c in cameras if c.id == camera_id or c.name.lower() == camera_id.lower()),
        None,
    )
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_id}' not found.")

    presets = await adapter.get_ptz_presets(camera.name)
    return presets


@app.get("/events")
async def get_events(
    camera: str | None = Query(None, description="Camera name or ID"),
    label: str | None = Query(None, description="Object label (person, car, etc.)"),
    zone: str | None = Query(None, description="Zone name"),
    after: int | None = Query(None, description="Unix timestamp — events after this time"),
    before: int | None = Query(None, description="Unix timestamp — events before this time"),
    limit: int = Query(20, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Fetch events with optional filters."""
    adapter = AdapterRegistry.get_active()
    events = await adapter.get_events(
        camera_name=camera,
        label=label,
        zone=zone,
        start_time=datetime.fromtimestamp(after) if after else None,
        end_time=datetime.fromtimestamp(before) if before else None,
        limit=limit,
    )
    return [
        {
            "id": e.id,
            "camera": e.camera_name,
            "type": e.event_type.value,
            "start_time": e.start_time.isoformat(),
            "end_time": e.end_time.isoformat() if e.end_time else None,
            "objects": [{"label": o.label, "confidence": o.confidence} for o in e.objects],
            "zones": e.zones,
            "snapshot_url": e.snapshot_url,
            "clip_url": e.clip_url,
        }
        for e in events
    ]


@app.get("/events/export")
async def export_events(
    camera: str | None = Query(None),
    label: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    fmt: str = Query("csv", description="Export format: csv | json"),
) -> Response:
    """
    Export events as CSV or JSON.

    Exports from the live adapter (not the database) so it reflects the
    current state of your NVR.  Use ``fmt=json`` for machine-readable output.

    Example:
        GET /events/export?camera=Front+Door&label=person&limit=500
        GET /events/export?fmt=json
    """
    adapter = AdapterRegistry.get_active()
    events = await adapter.get_events(camera_name=camera, label=label, limit=limit)

    if fmt == "json":
        rows = [
            {
                "id": e.id,
                "camera": e.camera_name,
                "type": e.event_type.value,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "objects": [{"label": o.label, "confidence": o.confidence} for o in e.objects],
                "zones": e.zones,
                "snapshot_url": e.snapshot_url,
                "clip_url": e.clip_url,
            }
            for e in events
        ]
        return Response(
            content=json.dumps(rows, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=events.json"},
        )

    # CSV
    import csv
    import io

    buf = io.StringIO()
    fieldnames = [
        "id",
        "camera",
        "type",
        "start_time",
        "end_time",
        "labels",
        "zones",
        "snapshot_url",
        "clip_url",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for e in events:
        writer.writerow(
            {
                "id": e.id,
                "camera": e.camera_name,
                "type": e.event_type.value,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat() if e.end_time else "",
                "labels": ";".join(o.label for o in e.objects),
                "zones": ";".join(e.zones),
                "snapshot_url": e.snapshot_url or "",
                "clip_url": e.clip_url or "",
            }
        )

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events.csv"},
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Check health of connected adapter and LLM backend."""
    adapter = AdapterRegistry.get_active()
    llm = LLMRegistry.get_active()

    adapter_ok = await adapter.health_check()
    llm_ok = await llm.health_check()

    return HealthResponse(
        status="ok" if (adapter_ok and llm_ok) else "degraded",
        adapter=adapter.name,
        llm=llm.name,
        adapter_ok=adapter_ok,
        llm_ok=llm_ok,
    )


@app.get("/health/cameras")
async def camera_health() -> list[dict[str, Any]]:
    """
    Return per-camera health status from the background health monitor.

    Each entry includes the camera name, current status (online/offline/degraded),
    last check timestamp, consecutive failure count, and round-trip latency.
    """
    if _health_monitor is None:
        raise HTTPException(status_code=503, detail="Health monitor is not running.")
    return _health_monitor.get_status_dict()


@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str) -> dict[str, str]:
    """Clear conversation history for a session (in-memory and persistent)."""
    _in_memory_sessions.pop(session_id, None)
    if _session_store:
        await _session_store.clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}


# ---------------------------------------------------------------------------
# Alert Rules CRUD
# ---------------------------------------------------------------------------


def _rule_to_response(rule) -> AlertRuleResponse:
    return AlertRuleResponse(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        camera_name=rule.camera_name,
        label=rule.label,
        zone=rule.zone,
        time_start=rule.time_start,
        time_end=rule.time_end,
        webhook_url=rule.webhook_url,
        cooldown_seconds=rule.cooldown_seconds,
        enabled=rule.enabled,
        created_at=rule.created_at.isoformat(),
        last_triggered=rule.last_triggered.isoformat() if rule.last_triggered else None,
        trigger_count=rule.trigger_count,
    )


def _require_alert_engine() -> AlertEngine:
    if _alert_engine is None:
        raise HTTPException(status_code=503, detail="Alert engine is not running.")
    return _alert_engine


@app.get("/alerts", response_model=list[AlertRuleResponse])
async def list_alert_rules() -> list[AlertRuleResponse]:
    """List all configured alert rules."""
    engine = _require_alert_engine()
    return [_rule_to_response(r) for r in engine.get_rules()]


@app.post("/alerts", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(body: AlertRuleCreate) -> AlertRuleResponse:
    """Create a new alert rule. The engine evaluates it on the next poll cycle."""
    engine = _require_alert_engine()
    rule = make_rule_from_context(
        name=body.name,
        description=body.description,
        camera_name=body.camera_name,
        label=body.label,
        zone=body.zone,
        time_start=body.time_start,
        time_end=body.time_end,
        webhook_url=body.webhook_url,
        cooldown_seconds=body.cooldown_seconds,
    )
    engine.add_rule(rule)
    return _rule_to_response(rule)


@app.get("/alerts/{rule_id}", response_model=AlertRuleResponse)
async def get_alert_rule(rule_id: str) -> AlertRuleResponse:
    """Retrieve a specific alert rule by ID."""
    engine = _require_alert_engine()
    rule = engine.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Alert rule '{rule_id}' not found.")
    return _rule_to_response(rule)


@app.delete("/alerts/{rule_id}")
async def delete_alert_rule(rule_id: str) -> dict[str, str]:
    """Delete an alert rule by ID."""
    engine = _require_alert_engine()
    deleted = engine.remove_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Alert rule '{rule_id}' not found.")
    return {"status": "deleted", "id": rule_id}


@app.patch("/alerts/{rule_id}", response_model=AlertRuleResponse)
async def update_alert_rule(rule_id: str, body: AlertRuleUpdate) -> AlertRuleResponse:
    """
    Update one or more fields of an alert rule.

    To enable/disable: ``PATCH /alerts/{id}  {"enabled": false}``
    """
    engine = _require_alert_engine()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields provided to update.")
    rule = engine.update_rule(rule_id, **updates)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Alert rule '{rule_id}' not found.")
    return _rule_to_response(rule)


# ---------------------------------------------------------------------------
# Voice endpoints
# ---------------------------------------------------------------------------


@app.post("/voice/query", response_model=QueryResponse)
async def voice_query(
    audio: UploadFile = File(...),
    session_id: str | None = Form(None),
) -> QueryResponse:
    """
    Accept an audio file, transcribe with Whisper, run an NLP query, return text answer.
    """
    from cctvql.interfaces.voice import VoiceInterface

    voice = VoiceInterface(
        stt_backend=os.environ.get("CCTVQL_STT_BACKEND", "whisper_api"),
        tts_backend=os.environ.get("CCTVQL_TTS_BACKEND", "none"),
        whisper_api_key=os.environ.get("OPENAI_API_KEY"),
    )
    audio_bytes = await audio.read()
    text = await voice.transcribe(audio_bytes, audio_format=audio.content_type or "wav")

    sid = session_id or "default"
    nlp = _get_nlp_for_session(sid)
    router = QueryRouter(
        AdapterRegistry.get_active(),
        LLMRegistry.get_active(),
        alert_engine=_alert_engine,
        face_registry=_face_registry,
    )
    ctx = await nlp.parse(text, session_id=sid)
    answer = await router.route(ctx)

    return QueryResponse(answer=answer, intent=ctx.intent, session_id=sid)


@app.post("/voice/synthesize")
async def voice_synthesize(body: dict) -> Response:
    """
    Convert text to speech audio.
    Body: ``{"text": "...", "voice": "alloy"}``
    Returns ``audio/mpeg`` bytes.
    """
    from cctvql.interfaces.voice import VoiceInterface

    voice = VoiceInterface(
        tts_backend=os.environ.get("CCTVQL_TTS_BACKEND", "openai_tts"),
        openai_tts_api_key=os.environ.get("OPENAI_API_KEY"),
        tts_voice=body.get("voice", "alloy"),
    )
    audio_bytes = await voice.synthesize(body.get("text", ""))
    return Response(content=audio_bytes, media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Prometheus-compatible metrics
# ---------------------------------------------------------------------------


@app.get("/events/timeline")
async def events_timeline(
    hours: int = Query(default=24, ge=1, le=168, description="Time window in hours (1–168)"),
    bucket_minutes: int = Query(
        default=0,
        ge=0,
        le=120,
        description="Bucket size in minutes (0 = auto: 15 for ≤6h, 60 for >6h)",
    ),
    camera: str | None = Query(default=None, description="Filter to a specific camera name"),
) -> dict:
    """
    Return events grouped into time buckets for timeline visualisation.

    The response includes:
    - cameras: ordered list of camera names present in the window
    - buckets: ordered list of ISO-format bucket timestamps
    - bucket_minutes: the resolved bucket size used
    - range_start / range_end: the time window boundaries (ISO)
    - data: dict[camera_name, dict[bucket_ts, {count, labels, top_label}]]
    """
    from datetime import timedelta, timezone

    # Resolve bucket size
    if bucket_minutes == 0:
        bucket_minutes = 15 if hours <= 6 else 60

    adapter = AdapterRegistry.get_active()
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)

    raw_events = await adapter.get_events(
        camera_name=camera,
        start_time=start,
        end_time=now,
        limit=2000,
    )

    # Build bucket grid
    delta = timedelta(minutes=bucket_minutes)
    buckets: list[str] = []
    t = start
    while t <= now:
        buckets.append(t.strftime("%Y-%m-%dT%H:%M"))
        t += delta

    # Collect camera names in encounter order
    cameras_seen: list[str] = []
    cameras_set: set[str] = set()

    # data[camera][bucket] = {"count": int, "labels": list[str]}
    data: dict[str, dict[str, dict]] = {}

    for evt in raw_events:
        cam = evt.camera_name
        if cam not in cameras_set:
            if camera and cam.lower() != camera.lower():
                continue
            cameras_seen.append(cam)
            cameras_set.add(cam)
            data[cam] = {}

        # Find the bucket this event falls into
        evt_ts = evt.start_time
        if evt_ts.tzinfo is None:
            evt_ts = evt_ts.replace(tzinfo=timezone.utc)
        # Floor to bucket boundary
        offset = int((evt_ts - start).total_seconds() // (bucket_minutes * 60))
        if offset < 0 or offset >= len(buckets):
            continue
        bucket_key = buckets[offset]

        if bucket_key not in data[cam]:
            data[cam][bucket_key] = {"count": 0, "labels": []}
        data[cam][bucket_key]["count"] += 1
        for obj in evt.objects or []:
            data[cam][bucket_key]["labels"].append(obj.label)

    # Add top_label to each bucket cell
    for cam_data in data.values():
        for cell in cam_data.values():
            labels = cell["labels"]
            if labels:
                cell["top_label"] = max(set(labels), key=labels.count)
            else:
                cell["top_label"] = None

    return {
        "range_start": start.strftime("%Y-%m-%dT%H:%M"),
        "range_end": now.strftime("%Y-%m-%dT%H:%M"),
        "hours": hours,
        "bucket_minutes": bucket_minutes,
        "cameras": cameras_seen,
        "buckets": buckets,
        "data": data,
    }


@app.get("/anomalies")
async def get_anomalies(
    hours: int = Query(
        default=24,
        ge=1,
        le=168,
        description="Observe window size in hours (1–168, default 24)",
    ),
    baseline_days: int = Query(
        default=7,
        ge=1,
        le=30,
        description="Days of history used to build the normal baseline (default 7)",
    ),
    camera: str | None = Query(default=None, description="Restrict to a specific camera name"),
    threshold: float = Query(
        default=2.0,
        ge=0.5,
        le=10.0,
        description="Z-score threshold above which activity is considered anomalous (default 2.0)",
    ),
) -> dict:
    """
    Detect statistically unusual activity across cameras.

    Compares the observe window against a historical baseline of the same
    hour-of-day across the last ``baseline_days`` days.  Returns both spikes
    (more events than normal) and silences (unusually quiet periods).

    **Example:**
    ```
    GET /anomalies?hours=24&baseline_days=7&threshold=2.0
    GET /anomalies?camera=Front+Door&hours=6
    ```
    """
    from datetime import timedelta, timezone

    from cctvql.core.anomaly import AnomalyDetector

    adapter = AdapterRegistry.get_active()
    now = datetime.now(timezone.utc)

    observe_end = now
    observe_start = now - timedelta(hours=hours)
    baseline_start = observe_start - timedelta(days=baseline_days)

    observe_events = await adapter.get_events(
        camera_name=camera,
        start_time=observe_start,
        end_time=observe_end,
        limit=2000,
    )
    baseline_events = await adapter.get_events(
        camera_name=camera,
        start_time=baseline_start,
        end_time=observe_start,
        limit=5000,
    )

    detector = AnomalyDetector(threshold=threshold)
    anomalies = detector.detect(
        observe_events=observe_events,
        baseline_events=baseline_events,
        observe_start=observe_start,
        observe_end=observe_end,
    )

    return {
        "observe_start": observe_start.strftime("%Y-%m-%dT%H:%M"),
        "observe_end": observe_end.strftime("%Y-%m-%dT%H:%M"),
        "baseline_days": baseline_days,
        "threshold": threshold,
        "total": len(anomalies),
        "high": sum(1 for a in anomalies if a.severity == "high"),
        "medium": sum(1 for a in anomalies if a.severity == "medium"),
        "low": sum(1 for a in anomalies if a.severity == "low"),
        "anomalies": [a.to_dict() for a in anomalies],
    }


@app.get("/events/{event_id}/summary", response_model=EventSummaryResponse)
async def get_event_summary(
    event_id: str,
    request: Request,
    include_faces: bool = Query(default=True, description="Run face recognition on the snapshot"),
) -> EventSummaryResponse:
    """
    Generate an AI-powered natural-language summary for a single event.

    Fetches the event from the adapter, sends the snapshot to the configured
    LLM for visual analysis, and optionally runs face recognition on the image.

    **Example:**
    ```
    GET /events/1234abcd/summary
    GET /events/1234abcd/summary?include_faces=false
    ```
    """
    user = await _get_current_user(request)

    adapter = AdapterRegistry.get_active()
    event = await adapter.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")

    # Multi-tenant camera-group scoping
    if user is not None and not user.can_see_camera(event.camera_name):
        raise HTTPException(status_code=403, detail="Access denied to this camera.")

    # AI visual summary
    llm = LLMRegistry.get_active()
    analyzer = VisionAnalyzer(llm)
    summary_text = await analyzer.analyze_event(event, adapter)

    # Optional face recognition
    face_matches: list[FaceMatchResponse] = []
    if include_faces and _face_registry is not None:
        snapshot_url = event.snapshot_url or event.thumbnail_url
        if snapshot_url:
            result = await _face_registry.recognise_url(snapshot_url)
            face_matches = [
                FaceMatchResponse(
                    face_id=m.face_id,
                    name=m.name,
                    label=m.label,
                    confidence=m.confidence,
                )
                for m in result.matches
            ]

    return EventSummaryResponse(
        event_id=event.id,
        camera_name=event.camera_name,
        timestamp=event.start_time.isoformat(),
        summary=summary_text,
        objects=[
            {"label": o.label, "confidence": round(o.confidence, 3)}
            for o in event.objects
        ],
        zones=event.zones,
        snapshot_url=event.snapshot_url,
        clip_url=event.clip_url,
        faces=face_matches,
    )


# ---------------------------------------------------------------------------
# Face enrollment + recognition
# ---------------------------------------------------------------------------


@app.get("/faces", response_model=list[FaceEnrollResponse])
async def list_faces(request: Request) -> list[FaceEnrollResponse]:
    """List all enrolled faces."""
    if _face_registry is None:
        raise HTTPException(status_code=503, detail="Face registry not available (no database).")
    enrollments = await _face_registry.list_enrollments()
    return [
        FaceEnrollResponse(
            face_id=e.face_id,
            name=e.name,
            label=e.label,
            created_at=e.created_at,
            image_b64=e.image_b64,
        )
        for e in enrollments
    ]


@app.post("/faces/enroll", response_model=FaceEnrollResponse, status_code=201)
async def enroll_face(
    request: Request,
    name: str = Form(..., description="Person's name"),
    label: str = Form(default="", description="Optional role / label"),
    image: UploadFile = File(..., description="Photo containing exactly one face"),
) -> FaceEnrollResponse:
    """
    Enroll a new face.  Admin-only in multi-tenant mode.

    The uploaded image must contain exactly one clearly-visible face.
    When the ``face_recognition`` library is installed the 128-d embedding
    is computed and stored; otherwise only the image is stored.
    """
    user = await _get_current_user(request)
    if _MULTI_TENANT:
        _require_admin(user)

    if _face_registry is None:
        raise HTTPException(status_code=503, detail="Face registry not available (no database).")

    image_bytes = await image.read()
    content_type = image.content_type or "image/jpeg"

    try:
        enrollment = await _face_registry.enroll(
            name=name,
            image_bytes=image_bytes,
            label=label,
            content_type=content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return FaceEnrollResponse(
        face_id=enrollment.face_id,
        name=enrollment.name,
        label=enrollment.label,
        created_at=enrollment.created_at,
        image_b64=enrollment.image_b64,
    )


@app.get("/faces/{face_id}", response_model=FaceEnrollResponse)
async def get_face(face_id: str) -> FaceEnrollResponse:
    """Get a single face enrollment by ID."""
    if _face_registry is None:
        raise HTTPException(status_code=503, detail="Face registry not available (no database).")
    enrollment = await _face_registry.get_enrollment(face_id)
    if enrollment is None:
        raise HTTPException(status_code=404, detail=f"Face '{face_id}' not found.")
    return FaceEnrollResponse(
        face_id=enrollment.face_id,
        name=enrollment.name,
        label=enrollment.label,
        created_at=enrollment.created_at,
        image_b64=enrollment.image_b64,
    )


@app.delete("/faces/{face_id}", status_code=204)
async def delete_face(face_id: str, request: Request) -> None:
    """Delete a face enrollment.  Admin-only in multi-tenant mode."""
    user = await _get_current_user(request)
    if _MULTI_TENANT:
        _require_admin(user)

    if _face_registry is None:
        raise HTTPException(status_code=503, detail="Face registry not available (no database).")
    deleted = await _face_registry.delete_enrollment(face_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Face '{face_id}' not found.")


@app.post("/faces/recognize", response_model=RecognizeResponse)
async def recognize_faces(
    image: UploadFile = File(..., description="Image to search for enrolled faces"),
) -> RecognizeResponse:
    """
    Find enrolled faces in an uploaded image.

    Returns matches sorted by confidence (highest first).
    Requires ``pip install cctvql[face]`` for recognition to return results.
    """
    if _face_registry is None:
        raise HTTPException(status_code=503, detail="Face registry not available (no database).")
    image_bytes = await image.read()
    result = await _face_registry.recognise_image(image_bytes)
    return RecognizeResponse(
        matches=[
            FaceMatchResponse(
                face_id=m.face_id,
                name=m.name,
                label=m.label,
                confidence=m.confidence,
            )
            for m in result.matches
        ],
        face_count=result.face_count,
        recognition_available=result.recognition_available,
    )


@app.get("/faces/search/{event_id}", response_model=RecognizeResponse)
async def search_faces_in_event(event_id: str, request: Request) -> RecognizeResponse:
    """
    Run face recognition on the snapshot of a specific event.

    Fetches the event's snapshot URL and searches it for enrolled faces.
    """
    user = await _get_current_user(request)

    if _face_registry is None:
        raise HTTPException(status_code=503, detail="Face registry not available (no database).")

    adapter = AdapterRegistry.get_active()
    event = await adapter.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")

    if user is not None and not user.can_see_camera(event.camera_name):
        raise HTTPException(status_code=403, detail="Access denied to this camera.")

    snapshot_url = event.snapshot_url or event.thumbnail_url
    if not snapshot_url:
        return RecognizeResponse(
            matches=[],
            face_count=0,
            recognition_available=True,
        )

    result = await _face_registry.recognise_url(snapshot_url)
    return RecognizeResponse(
        matches=[
            FaceMatchResponse(
                face_id=m.face_id,
                name=m.name,
                label=m.label,
                confidence=m.confidence,
            )
            for m in result.matches
        ],
        face_count=result.face_count,
        recognition_available=result.recognition_available,
    )


# ---------------------------------------------------------------------------
# Push notification token management
# ---------------------------------------------------------------------------


@app.post("/push/register", response_model=PushTokenResponse, status_code=201)
async def register_push_token(
    body: PushRegisterRequest,
    request: Request,
) -> PushTokenResponse:
    """Register a mobile device push token (idempotent — upserts on conflict)."""
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not available.")

    user = await _get_current_user(request)
    user_id = user.id if user else None

    await _db.save_push_token(
        token=body.token,
        platform=body.platform,
        device_name=body.device_name,
        user_id=user_id,
    )

    from datetime import timezone

    return PushTokenResponse(
        token=body.token,
        platform=body.platform,
        device_name=body.device_name,
        user_id=user_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@app.delete("/push/register/{token}", status_code=204)
async def unregister_push_token(token: str) -> None:
    """Remove a registered push token."""
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not available.")
    await _db.delete_push_token(token)


@app.get("/push/tokens", response_model=list[PushTokenResponse])
async def list_push_tokens(request: Request) -> list[PushTokenResponse]:
    """
    List registered push tokens.

    Admins see all tokens; non-admin users see only their own tokens.
    """
    if _db is None:
        raise HTTPException(status_code=503, detail="Database not available.")

    user = await _get_current_user(request)
    if _MULTI_TENANT and user is not None and user.role != ROLE_ADMIN:
        rows = await _db.list_push_tokens(user_id=user.id)
    else:
        rows = await _db.list_push_tokens()

    return [
        PushTokenResponse(
            token=row["token"],
            platform=row["platform"],
            device_name=row["device_name"],
            user_id=row.get("user_id"),
            created_at=row["created_at"],
        )
        for row in rows
    ]


@app.get("/discover/onvif")
async def discover_onvif(
    timeout: float = Query(default=3.0, ge=0.5, le=10.0, description="Probe timeout in seconds"),
    interface: str = Query(default="", description="Local interface IP to bind to (default: all)"),
) -> list[dict]:
    """
    Discover ONVIF cameras on the local network using WS-Discovery (UDP multicast).

    Sends a WS-Discovery Probe to 239.255.255.250:3702 and collects responses.
    Returns a list of discovered devices with their ONVIF endpoint URLs and names.

    This endpoint is useful for bootstrapping — copy the discovered `host` and `port`
    values into your `config.yaml` to add ONVIF adapters.
    """
    from cctvql.adapters.onvif_discovery import discover_and_format

    devices = await discover_and_format(timeout=timeout, interface=interface)
    return devices


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    """Return Prometheus-compatible metrics in plain text exposition format."""
    adapter = AdapterRegistry.get_active()
    llm = LLMRegistry.get_active()

    adapter_ok = await adapter.health_check()
    llm_ok = await llm.health_check()

    camera_health = _health_monitor.get_status_dict() if _health_monitor else []
    cameras_online = sum(1 for c in camera_health if c.get("status") == "online")
    cameras_offline = sum(1 for c in camera_health if c.get("status") == "offline")

    lines = [
        "# HELP cctvql_queries_total Total number of queries processed.",
        "# TYPE cctvql_queries_total counter",
        f"cctvql_queries_total {_query_count}",
        "",
        "# HELP cctvql_active_sessions Number of active in-memory sessions.",
        "# TYPE cctvql_active_sessions gauge",
        f"cctvql_active_sessions {len(_in_memory_sessions)}",
        "",
        "# HELP cctvql_adapter_status Adapter health (1=healthy, 0=unhealthy).",
        "# TYPE cctvql_adapter_status gauge",
        f"cctvql_adapter_status {1 if adapter_ok else 0}",
        "",
        "# HELP cctvql_llm_status LLM health (1=healthy, 0=unhealthy).",
        "# TYPE cctvql_llm_status gauge",
        f"cctvql_llm_status {1 if llm_ok else 0}",
        "",
        "# HELP cctvql_cameras_online Number of cameras currently online.",
        "# TYPE cctvql_cameras_online gauge",
        f"cctvql_cameras_online {cameras_online}",
        "",
        "# HELP cctvql_cameras_offline Number of cameras currently offline.",
        "# TYPE cctvql_cameras_offline gauge",
        f"cctvql_cameras_offline {cameras_offline}",
        "",
        "# HELP cctvql_alert_rules_total Total number of configured alert rules.",
        "# TYPE cctvql_alert_rules_total gauge",
        f"cctvql_alert_rules_total {len(_alert_engine.get_rules()) if _alert_engine else 0}",
        "",
    ]

    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/plain; version=0.0.4",
    )
