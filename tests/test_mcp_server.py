"""End-to-end tests for the cctvQL MCP server over Streamable HTTP."""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

pytest.importorskip("mcp")

import uvicorn  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402

from cctvql.adapters.demo import LiveDemoAdapter  # noqa: E402
from cctvql.interfaces.mcp_server import _ago, _normalise_label, build_app  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    port = _free_port()
    app = build_app(adapter=LiveDemoAdapter(), token="t0ken")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


async def _call(url: str, tool: str, args: dict | None = None, token: str = "t0ken") -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args or {})
            return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_lists_tools(server_url):
    headers = {"Authorization": "Bearer t0ken"}
    async with streamablehttp_client(server_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "cctvQL"
            names = {t.name for t in (await session.list_tools()).tools}
    assert {
        "list_cameras",
        "recent_activity",
        "who_was_at",
        "latest_snapshot",
        "camera_health",
        "ask_cameras",
    } <= names
    assert "point_camera" not in names


@pytest.mark.asyncio
async def test_list_cameras(server_url):
    out = await _call(server_url, "list_cameras")
    assert out["answer"].startswith("You have")
    assert out["cameras"]


@pytest.mark.asyncio
async def test_who_was_at_person_today(server_url):
    out = await _call(server_url, "who_was_at", {"label": "someone", "minutes": 1440})
    assert out["answer"].startswith("Yes.")
    assert all(e["label"] == "person" for e in out["events"])


@pytest.mark.asyncio
async def test_unknown_camera(server_url):
    out = await _call(server_url, "who_was_at", {"camera": "moon base"})
    assert "couldn't find" in out["answer"]


@pytest.mark.asyncio
async def test_recent_activity_window(server_url):
    out = await _call(server_url, "recent_activity", {"minutes": 1440})
    assert "events" in out and out["events"]
    assert "in the last day" in out["answer"]


@pytest.mark.asyncio
async def test_camera_health(server_url):
    out = await _call(server_url, "camera_health")
    assert "reachable" in out


@pytest.mark.asyncio
async def test_rejects_missing_token(server_url):
    import httpx

    r = httpx.post(server_url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401


def test_helpers():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert _ago(now - timedelta(seconds=10), now) == "just now"
    assert _ago(now - timedelta(minutes=1), now) == "1 minute ago"
    assert _ago(now - timedelta(hours=3), now) == "3 hours ago"
    assert _normalise_label("People") == "person"
    assert _normalise_label("parcel") == "package"
