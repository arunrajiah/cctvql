"""
cctvQL data coordinator.

Pure asyncio HTTP client — no Home Assistant imports here so it can be
unit-tested independently.  HA-specific DataUpdateCoordinator subclass lives
in __init__.py.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)


class CctvqlClient:
    """Thin async HTTP client for the cctvQL REST API."""

    def __init__(
        self,
        host: str,
        port: int,
        api_key: str | None = None,
    ) -> None:
        self.base_url = f"http://{host}:{port}"
        self._headers: dict[str, str] = {}
        if api_key:
            self._headers["X-API-Key"] = api_key

    # ------------------------------------------------------------------
    # Core fetchers
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """GET /health — overall system health."""
        return await self._get("/health")

    async def cameras(self) -> list[dict[str, Any]]:
        """GET /cameras — list of cameras."""
        return await self._get("/cameras")

    async def camera_health(self) -> list[dict[str, Any]]:
        """GET /health/cameras — per-camera health status."""
        return await self._get("/health/cameras")

    async def events(self, limit: int = 50) -> list[dict[str, Any]]:
        """GET /events — recent events."""
        return await self._get("/events", params={"limit": limit})

    async def fetch_all(self) -> dict[str, Any]:
        """Fetch health, cameras, camera_health and events in one call.

        Each endpoint is fetched independently so a single failure only nullifies
        that key rather than aborting the entire update.
        """
        async with httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT) as client:
            health = await self._safe_get(client, "/health", default={})
            cameras = await self._safe_get(client, "/cameras", default=[])
            camera_health = await self._safe_get(client, "/health/cameras", default=[])
            events = await self._safe_get(client, "/events", params={"limit": 50}, default=[])

        return {
            "health": health,
            "cameras": cameras,
            "camera_health": camera_health,
            "events": events,
        }

    async def _safe_get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict | None = None,
        default: Any,
    ) -> Any:
        """GET a path, returning *default* on any error instead of raising."""
        try:
            resp = await client.get(f"{self.base_url}{path}", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.warning("cctvQL: failed to fetch %s — returning default", path)
            return default

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def query(self, query_text: str, session_id: str = "homeassistant") -> dict[str, Any]:
        """POST /query — natural language query."""
        return await self._post("/query", json={"query": query_text, "session_id": session_id})

    async def ptz(
        self,
        camera_id: str,
        action: str,
        speed: int = 50,
        preset_id: int | None = None,
    ) -> dict[str, Any]:
        """POST /cameras/{camera_id}/ptz — PTZ command."""
        body: dict[str, Any] = {"action": action, "speed": speed}
        if preset_id is not None:
            body["preset_id"] = preset_id
        return await self._post(f"/cameras/{camera_id}/ptz", json=body)

    async def clear_session(self, session_id: str = "homeassistant") -> dict[str, Any]:
        """DELETE /sessions/{session_id} — clear conversation history."""
        async with httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT) as client:
            resp = await client.delete(f"{self.base_url}/sessions/{session_id}")
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT) as client:
            resp = await client.get(f"{self.base_url}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, json: dict) -> Any:
        async with httpx.AsyncClient(headers=self._headers, timeout=_TIMEOUT) as client:
            resp = await client.post(f"{self.base_url}{path}", json=json)
            resp.raise_for_status()
            return resp.json()
