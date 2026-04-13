"""
cctvQL REST API Interface
--------------------------
FastAPI-based HTTP server exposing cctvQL as a REST API.
Useful for integrating with Home Assistant, custom dashboards, or mobile apps.

Endpoints:
  POST /query          — Natural language query
  GET  /cameras        — List cameras
  GET  /events         — Get events (with filters)
  GET  /health         — System health check
  GET  /metrics        — Prometheus-compatible metrics
  WS   /ws/events      — Real-time event streaming via WebSocket

Usage:
    cctvql serve --config config/config.yaml --port 8000
    uvicorn cctvql.interfaces.rest_api:app --host 0.0.0.0 --port 8000
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
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cctvql.adapters.base import AdapterRegistry
from cctvql.core.alerts import AlertEngine, make_rule_from_context
from cctvql.core.multi_query import MultiSystemRouter
from cctvql.core.nlp_engine import NLPEngine
from cctvql.core.query_router import QueryRouter
from cctvql.core.schema import Event
from cctvql.llm.base import LLMRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metrics counters (module-level)
# ---------------------------------------------------------------------------

_query_count: int = 0

# ---------------------------------------------------------------------------
# API Key Authentication Middleware
# ---------------------------------------------------------------------------

_AUTH_SKIP_PATHS = {"/docs", "/openapi.json", "/redoc", "/health"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Optional API key authentication middleware.

    When the ``CCTVQL_API_KEY`` environment variable is set, every request
    (except health, docs, and WebSocket upgrades) must include a matching
    ``X-API-Key`` header.  If the env var is *not* set, all requests pass
    through without authentication.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        api_key = os.environ.get("CCTVQL_API_KEY")

        # No key configured — allow everything
        if not api_key:
            return await call_next(request)

        # Skip auth for docs / health / WebSocket upgrade
        if request.url.path in _AUTH_SKIP_PATHS:
            return await call_next(request)

        # WebSocket upgrade requests skip auth
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Validate key
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _alert_engine
    adapter = AdapterRegistry.get_active()
    connected = await adapter.connect()
    if not connected:
        logger.error("Failed to connect to CCTV adapter on startup")
    _alert_engine = AlertEngine(AdapterRegistry)
    await _alert_engine.start()
    yield
    await _alert_engine.stop()


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

# Global singletons (initialized on startup)
_nlp: NLPEngine | None = None
_router: QueryRouter | None = None
_alert_engine: AlertEngine | None = None


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


class AlertRuleUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    camera_name: str | None = None
    label: str | None = None
    zone: str | None = None
    time_start: str | None = None
    time_end: str | None = None
    webhook_url: str | None = None


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
    enabled: bool
    created_at: str
    last_triggered: str | None
    trigger_count: int


# ---------------------------------------------------------------------------
# Session store (in-memory, keyed by session_id)
# ---------------------------------------------------------------------------

_sessions: dict[str, NLPEngine] = {}


def _get_nlp_for_session(session_id: str) -> NLPEngine:
    if session_id not in _sessions:
        llm = LLMRegistry.get_active()
        _sessions[session_id] = NLPEngine(llm)
    return _sessions[session_id]


# ---------------------------------------------------------------------------
# WebSocket: real-time event streaming
# ---------------------------------------------------------------------------

_ws_clients: set[WebSocket] = set()


async def _broadcast_event(event: Event) -> None:
    """Serialize an Event to a JSON dict and broadcast to all connected
    WebSocket clients."""
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
            # Keep the connection alive; we don't expect client messages
            # but we must await to detect disconnection.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def root() -> HTMLResponse:
    """Serve the cctvQL Web UI."""
    index = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=index.read_text())


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """
    Submit a natural language query about your CCTV system.

    Set ``multi=true`` to fan-out the query across all registered adapters
    simultaneously and receive a merged response.

    Example:
        {"query": "Was there any motion on the driveway camera last night?"}
        {"query": "Show me all cameras", "multi": true}
    """
    global _query_count
    try:
        nlp = _get_nlp_for_session(req.session_id or "default")
        llm = LLMRegistry.get_active()

        ctx = await nlp.parse(req.query)

        if req.multi:
            multi_router = MultiSystemRouter(llm)
            answer = await multi_router.route(ctx)
        else:
            router = QueryRouter(
                AdapterRegistry.get_active(),
                llm,
                alert_engine=_alert_engine,
            )
            answer = await router.route(ctx)

        _query_count += 1

        return QueryResponse(
            answer=answer,
            intent=ctx.intent,
            session_id=req.session_id or "default",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("Query error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error processing query")


@app.get("/cameras")
async def list_cameras() -> list[dict[str, Any]]:
    """List all cameras in the connected CCTV system."""
    adapter = AdapterRegistry.get_active()
    cameras = await adapter.list_cameras()
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


@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str) -> dict[str, str]:
    """Clear conversation history for a session."""
    if session_id in _sessions:
        del _sessions[session_id]
    return {"status": "cleared", "session_id": session_id}


# ---------------------------------------------------------------------------
# Alert Rules CRUD
# ---------------------------------------------------------------------------


def _rule_to_response(rule) -> AlertRuleResponse:
    """Convert an AlertRule dataclass to the Pydantic response model."""
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
    """
    Create a new alert rule.

    The engine will start evaluating it on the next poll cycle.
    """
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

    Commonly used to enable or disable a rule:
        PATCH /alerts/{id}  {"enabled": false}
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
    Accept audio file, transcribe with Whisper, run NLP query, return text answer.
    Optionally returns audio if Accept: audio/* header is set.
    """
    import os

    from cctvql.interfaces.voice import VoiceInterface

    voice = VoiceInterface(
        stt_backend=os.environ.get("CCTVQL_STT_BACKEND", "whisper_api"),
        tts_backend=os.environ.get("CCTVQL_TTS_BACKEND", "none"),
        whisper_api_key=os.environ.get("OPENAI_API_KEY"),
    )
    audio_bytes = await audio.read()
    text = await voice.transcribe(audio_bytes, audio_format=audio.content_type or "wav")

    # reuse existing query logic
    sid = session_id or "default"
    nlp = _get_nlp_for_session(sid)
    router = QueryRouter(
        AdapterRegistry.get_active(), LLMRegistry.get_active(), alert_engine=_alert_engine
    )
    ctx = await nlp.parse(text)
    answer = await router.route(ctx)

    return QueryResponse(answer=answer, intent=ctx.intent, session_id=sid)


@app.post("/voice/synthesize")
async def voice_synthesize(body: dict) -> Response:
    """
    Convert text to speech audio.
    Body: {"text": "...", "voice": "alloy"}
    Returns audio/mpeg bytes.
    """
    import os

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


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    """Return Prometheus-compatible metrics in plain text exposition format."""
    adapter = AdapterRegistry.get_active()
    llm = LLMRegistry.get_active()

    adapter_ok = await adapter.health_check()
    llm_ok = await llm.health_check()

    lines = [
        "# HELP cctvql_queries_total Total number of queries processed.",
        "# TYPE cctvql_queries_total counter",
        f"cctvql_queries_total {_query_count}",
        "",
        "# HELP cctvql_active_sessions Number of active sessions.",
        "# TYPE cctvql_active_sessions gauge",
        f"cctvql_active_sessions {len(_sessions)}",
        "",
        "# HELP cctvql_adapter_status Adapter health (1=healthy, 0=unhealthy).",
        "# TYPE cctvql_adapter_status gauge",
        f"cctvql_adapter_status {1 if adapter_ok else 0}",
        "",
        "# HELP cctvql_llm_status LLM health (1=healthy, 0=unhealthy).",
        "# TYPE cctvql_llm_status gauge",
        f"cctvql_llm_status {1 if llm_ok else 0}",
        "",
    ]

    return PlainTextResponse(
        content="\n".join(lines),
        media_type="text/plain; version=0.0.4",
    )
