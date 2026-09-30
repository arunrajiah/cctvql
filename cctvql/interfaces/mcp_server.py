"""
cctvQL MCP Server
------------------
Exposes any cctvQL-connected CCTV/NVR system (Frigate, Hikvision, Dahua,
Synology, Milestone, Scrypted, ONVIF, demo) as a Model Context Protocol server
over Streamable HTTP, so voice and chat assistants such as Alexa+ can answer
questions like "Was anyone at the front door while I was out?".

Design notes
- Tools return short, speakable sentences first and structured data second,
  because a voice assistant reads the answer aloud.
- Everything stays local: the server talks to the NVR on your network and only
  returns text summaries and snapshot links. No video leaves the house.
- An optional bearer token protects the endpoint when it is exposed through a
  tunnel for a cloud assistant.

Run:
    cctvql mcp --adapter demo --port 8765
    cctvql mcp --config config/config.yaml --token "$CCTVQL_MCP_TOKEN"
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from cctvql.adapters.base import AdapterRegistry, BaseAdapter
from cctvql.core.schema import Camera, Event

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = (
    "cctvQL answers questions about the user's home or business security cameras. "
    "Use list_cameras to learn camera names, recent_activity for 'what happened' "
    "questions, who_was_at for questions about people, vehicles or animals at a "
    "place, and camera_health when a camera may be offline. Answers are written "
    "to be read aloud; keep them short when speaking to the user."
)

MAX_LIMIT = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ago(dt: datetime, now: datetime | None = None) -> str:
    """Human, speakable relative time: 'just now', '12 minutes ago', '3 hours ago'."""
    now = now or _now()
    secs = int((now - _aware(dt)).total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _normalise_label(label: str | None) -> str | None:
    if not label:
        return None
    label = label.strip().lower()
    aliases = {
        "people": "person",
        "someone": "person",
        "anyone": "person",
        "persons": "person",
        "cars": "car",
        "vehicle": "car",
        "vehicles": "car",
        "dogs": "dog",
        "cats": "cat",
        "packages": "package",
        "parcel": "package",
        "delivery": "package",
    }
    return aliases.get(label, label)


def _label_of(e: Event) -> str:
    """Primary label as plain lowercase text (adapters may return enums)."""
    lbl = e.primary_label
    if lbl is None:
        return e.event_type.value
    return str(getattr(lbl, "value", lbl)).lower()


def _article(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def _plural(label: str, n: int) -> str:
    if n == 1:
        return label
    return "people" if label == "person" else f"{label}s"


async def _resolve_camera(adapter: BaseAdapter, name: str | None) -> Camera | None:
    """Match a spoken camera name loosely ('front door' -> 'Front_Door')."""
    if not name:
        return None
    cam = await adapter.get_camera(camera_name=name)
    if cam:
        return cam
    wanted = name.lower().replace("_", " ").replace("-", " ").strip()
    for c in await adapter.list_cameras():
        candidate = c.name.lower().replace("_", " ").replace("-", " ")
        if wanted == candidate or wanted in candidate or candidate in wanted:
            return c
    return None


def _event_dict(e: Event) -> dict[str, Any]:
    return {
        "id": e.id,
        "camera": e.camera_name,
        "type": e.event_type.value,
        "label": _label_of(e),
        "zones": e.zones,
        "start": _aware(e.start_time).isoformat(),
        "end": _aware(e.end_time).isoformat() if e.end_time else None,
        "snapshot_url": e.snapshot_url,
        "clip_url": e.clip_url,
    }


def _summarise(events: list[Event], place: str, window: str) -> str:
    if not events:
        return f"Nothing was detected {place} {window}."
    counts = Counter(_label_of(e) for e in events)
    parts = [f"{n} {_plural(lbl, n)}" for lbl, n in counts.most_common(4)]
    latest = max(events, key=lambda e: _aware(e.start_time))
    what = _label_of(latest)
    return (
        f"{len(events)} event{'s' if len(events) != 1 else ''} {place} {window}: "
        f"{', '.join(parts)}. The most recent was {_article(what)} {what} on the "
        f"{latest.camera_name.replace('_', ' ')} camera, {_ago(latest.start_time)}."
    )


def _window_text(minutes: int) -> str:
    if minutes % 1440 == 0:
        d = minutes // 1440
        return "in the last day" if d == 1 else f"in the last {d} days"
    if minutes % 60 == 0:
        h = minutes // 60
        return "in the last hour" if h == 1 else f"in the last {h} hours"
    return f"in the last {minutes} minutes"


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def build_server(
    adapter: BaseAdapter | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    allow_ptz: bool = False,
) -> FastMCP:
    """
    Build the FastMCP server. If ``adapter`` is None the active adapter from the
    AdapterRegistry is used at call time, so config reloads are picked up.
    """
    mcp = FastMCP(
        "cctvQL",
        instructions=SERVER_INSTRUCTIONS,
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )

    def _adapter() -> BaseAdapter:
        return adapter or AdapterRegistry.get_active()

    @mcp.tool()
    async def list_cameras() -> dict[str, Any]:
        """List every camera with its name, status and location."""
        cams = await _adapter().list_cameras()
        online = [c for c in cams if c.status.value == "online"]
        names = ", ".join(c.name.replace("_", " ") for c in cams) or "none"
        return {
            "answer": f"You have {len(cams)} cameras, {len(online)} online: {names}.",
            "cameras": [
                {"id": c.id, "name": c.name, "status": c.status.value, "location": c.location}
                for c in cams
            ],
        }

    @mcp.tool()
    async def recent_activity(
        camera: str | None = None,
        minutes: int = 60,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Summarise what the cameras detected recently.

        Args:
            camera: Optional camera name, e.g. "front door". Omit for all cameras.
            minutes: How far back to look (default 60, max 7 days).
            limit: Maximum events to return (max 50).
        """
        ad = _adapter()
        minutes = max(1, min(int(minutes), 7 * 1440))
        cam = await _resolve_camera(ad, camera)
        if camera and not cam:
            return {"answer": f"I couldn't find a camera called {camera}.", "events": []}
        start = _now() - timedelta(minutes=minutes)
        events = await ad.get_events(
            camera_id=cam.id if cam else None,
            start_time=start,
            limit=max(1, min(int(limit), MAX_LIMIT)),
        )
        events = [e for e in events if _aware(e.start_time) >= start]
        place = f"on the {cam.name.replace('_', ' ')} camera" if cam else "across your cameras"
        return {
            "answer": _summarise(events, place, _window_text(minutes)),
            "events": [_event_dict(e) for e in events],
        }

    @mcp.tool()
    async def who_was_at(
        label: str = "person",
        camera: str | None = None,
        zone: str | None = None,
        minutes: int = 1440,
    ) -> dict[str, Any]:
        """
        Answer "was anyone / was there a car / did a package arrive" questions.

        Args:
            label: What to look for: person, car, dog, cat, package, bicycle...
            camera: Optional camera name, e.g. "driveway".
            zone: Optional zone name configured on the NVR, e.g. "porch".
            minutes: How far back to look (default 24 hours).
        """
        ad = _adapter()
        lbl = _normalise_label(label) or "person"
        minutes = max(1, min(int(minutes), 7 * 1440))
        cam = await _resolve_camera(ad, camera)
        if camera and not cam:
            return {"answer": f"I couldn't find a camera called {camera}.", "events": []}
        start = _now() - timedelta(minutes=minutes)
        events = await ad.get_events(
            camera_id=cam.id if cam else None,
            label=lbl,
            zone=zone,
            start_time=start,
            limit=MAX_LIMIT,
        )
        events = [e for e in events if _aware(e.start_time) >= start]
        where = f"at the {cam.name.replace('_', ' ')}" if cam else "across your cameras"
        if zone:
            where += f" in the {zone} zone"
        window = _window_text(minutes)
        if not events:
            answer = f"No, I didn't see any {_plural(lbl, 2)} {where} {window}."
        else:
            latest = max(events, key=lambda e: _aware(e.start_time))
            on = "" if cam else f" on the {latest.camera_name.replace('_', ' ')} camera"
            answer = (
                f"Yes. {len(events)} {_plural(lbl, len(events))} detected {where} {window}. "
                f"The latest was{on} {_ago(latest.start_time)}."
            )
        return {"answer": answer, "events": [_event_dict(e) for e in events]}

    @mcp.tool()
    async def latest_snapshot(camera: str) -> dict[str, Any]:
        """
        Get a link to the latest still image from a camera, for display on a
        screen device such as an Echo Show.

        Args:
            camera: Camera name, e.g. "back yard".
        """
        ad = _adapter()
        cam = await _resolve_camera(ad, camera)
        if not cam:
            return {"answer": f"I couldn't find a camera called {camera}.", "url": None}
        url = await ad.get_snapshot_url(camera_id=cam.id)
        if not url:
            return {"answer": f"{cam.name} has no snapshot available right now.", "url": None}
        name = cam.name.replace("_", " ")
        return {"answer": f"Here is the latest image from the {name} camera.", "url": url}

    @mcp.tool()
    async def camera_health() -> dict[str, Any]:
        """Report which cameras are offline and overall NVR health and storage."""
        ad = _adapter()
        cams = await ad.list_cameras()
        offline = [c.name for c in cams if c.status.value != "online"]
        info = await ad.get_system_info()
        healthy = await ad.health_check()
        parts = []
        if not healthy:
            parts.append(f"I can't reach the {ad.name} system right now.")
        if offline:
            parts.append(f"{len(offline)} camera(s) not online: {', '.join(offline)}.")
        else:
            parts.append(f"All {len(cams)} cameras are online.")
        if info and info.storage_total_bytes and info.storage_used_bytes is not None:
            pct = 100 * info.storage_used_bytes / info.storage_total_bytes
            parts.append(f"Recording storage is {pct:.0f}% full.")
        return {
            "answer": " ".join(parts),
            "system": info.system_name if info else ad.name,
            "offline": offline,
            "reachable": healthy,
        }

    @mcp.tool()
    async def ask_cameras(question: str) -> dict[str, Any]:
        """
        Ask any free-form question about the cameras in plain English, for
        anything the other tools do not cover. Uses cctvQL's own query engine.

        Args:
            question: The user's question, e.g. "how long was the gate open?".
        """
        from cctvql.core.nlp_engine import NLPEngine
        from cctvql.core.query_router import QueryRouter
        from cctvql.llm.base import LLMRegistry

        try:
            llm = LLMRegistry.get_active()
        except Exception:
            return {
                "answer": (
                    "Free-form questions need an LLM configured in cctvQL. "
                    "Try asking about recent activity or who was at a camera instead."
                )
            }
        ad = _adapter()
        engine = NLPEngine(llm)
        ctx = await engine.parse(question, session_id="mcp")
        answer = await QueryRouter(ad, llm).route(ctx)
        return {"answer": answer}

    if allow_ptz:

        @mcp.tool()
        async def point_camera(camera: str, preset: int) -> dict[str, Any]:
            """
            Move a pan-tilt-zoom camera to a saved preset position.

            Args:
                camera: PTZ camera name.
                preset: Preset number saved on the camera.
            """
            ad = _adapter()
            cam = await _resolve_camera(ad, camera)
            if not cam:
                return {"answer": f"I couldn't find a camera called {camera}."}
            ok = await ad.ptz_preset(cam.name, int(preset))
            return {
                "answer": (
                    f"Moved {cam.name} to preset {preset}."
                    if ok
                    else f"{cam.name} did not accept that move."
                )
            }

    return mcp


# ---------------------------------------------------------------------------
# ASGI app with optional bearer-token auth
# ---------------------------------------------------------------------------


class BearerAuthMiddleware:
    """Minimal ASGI middleware: require ``Authorization: Bearer <token>``."""

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and scope.get("path", "") != "/healthz":
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode()
            if auth != f"Bearer {self.token}":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def build_app(
    adapter: BaseAdapter | None = None,
    token: str | None = None,
    allow_ptz: bool = False,
) -> Any:
    """Return the Streamable HTTP ASGI app (served at /mcp)."""
    server = build_server(adapter=adapter, allow_ptz=allow_ptz)
    app = server.streamable_http_app()
    token = token or os.environ.get("CCTVQL_MCP_TOKEN")
    return BearerAuthMiddleware(app, token) if token else app


def run(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    allow_ptz: bool = False,
) -> None:
    import uvicorn

    token = token or os.environ.get("CCTVQL_MCP_TOKEN")
    if host not in ("127.0.0.1", "localhost") and not token:
        logger.warning(
            "cctvQL MCP is listening on %s without a token. Set CCTVQL_MCP_TOKEN "
            "before exposing it beyond your network.",
            host,
        )
    uvicorn.run(build_app(token=token, allow_ptz=allow_ptz), host=host, port=port)
