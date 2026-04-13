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

Usage:
    cctvql serve --config config/config.yaml --port 8000
    uvicorn cctvql.interfaces.rest_api:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cctvql.adapters.base import AdapterRegistry
from cctvql.core.nlp_engine import NLPEngine
from cctvql.core.query_router import QueryRouter
from cctvql.llm.base import LLMRegistry

logger = logging.getLogger(__name__)

app = FastAPI(
    title="cctvQL",
    description="Conversational query layer for CCTV systems",
    version="0.1.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global singletons (initialized on startup)
_nlp: Optional[NLPEngine] = None
_router: Optional[QueryRouter] = None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = "default"


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
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    adapter = AdapterRegistry.get_active()
    connected = await adapter.connect()
    if not connected:
        logger.error("Failed to connect to CCTV adapter on startup")


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
    try:
        nlp = _get_nlp_for_session(req.session_id or "default")
        router = QueryRouter(AdapterRegistry.get_active(), LLMRegistry.get_active())

        ctx = await nlp.parse(req.query)
        answer = await router.route(ctx)

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
    camera: Optional[str] = Query(None, description="Camera name or ID"),
    label: Optional[str] = Query(None, description="Object label (person, car, etc.)"),
    zone: Optional[str] = Query(None, description="Zone name"),
    after: Optional[int] = Query(None, description="Unix timestamp — events after this time"),
    before: Optional[int] = Query(None, description="Unix timestamp — events before this time"),
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
