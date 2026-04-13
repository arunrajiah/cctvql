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
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from cctvql.adapters.base import AdapterRegistry
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
    adapter = AdapterRegistry.get_active()
    connected = await adapter.connect()
    if not connected:
        logger.error("Failed to connect to CCTV adapter on startup")
    yield


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

# Global singletons (initialized on startup)
_nlp: NLPEngine | None = None
_router: QueryRouter | None = None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = "default"


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


@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """
    Submit a natural language query about your CCTV system.

    Example:
        {"query": "Was there any motion on the driveway camera last night?"}
    """
    global _query_count
    try:
        nlp = _get_nlp_for_session(req.session_id or "default")
        router = QueryRouter(AdapterRegistry.get_active(), LLMRegistry.get_active())

        ctx = await nlp.parse(req.query)
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
