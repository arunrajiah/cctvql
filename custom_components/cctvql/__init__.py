"""
cctvQL Home Assistant Integration.

Provides sensors, binary sensors, and services for cctvQL
(natural-language CCTV query layer).

Setup: Settings → Add Integration → search "cctvQL"
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PTZ_ACTIONS,
)
from .coordinator import CctvqlClient

logger = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up cctvQL from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    api_key = entry.data.get(CONF_API_KEY)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    client = CctvqlClient(host=host, port=port, api_key=api_key)

    # Verify connectivity
    try:
        await client.health()
    except Exception as exc:
        raise ConfigEntryNotReady(f"Cannot connect to cctvQL at {host}:{port}") from exc

    async def _async_update() -> dict:
        try:
            return await client.fetch_all()
        except Exception as exc:
            raise UpdateFailed(f"cctvQL update failed: {exc}") from exc

    coordinator = DataUpdateCoordinator(
        hass,
        logger,
        name=DOMAIN,
        update_method=_async_update,
        update_interval=timedelta(seconds=scan_interval),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, client)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def _register_services(hass: HomeAssistant, client: CctvqlClient) -> None:
    """Register cctvQL services (idempotent — skip if already registered)."""
    if hass.services.has_service(DOMAIN, "query"):
        return

    async def handle_query(call: ServiceCall) -> None:
        """cctvql.query — ask cctvQL a natural language question."""
        query_text: str = call.data["query"]
        session_id: str = call.data.get("session_id", "homeassistant")
        try:
            result = await client.query(query_text, session_id=session_id)
        except Exception as exc:
            logger.error("cctvql.query failed: %s", exc)
            hass.bus.async_fire(
                f"{DOMAIN}_service_error",
                {"service": "query", "error": str(exc)},
            )
            return
        hass.bus.async_fire(
            f"{DOMAIN}_query_result",
            {
                "query": query_text,
                "answer": result.get("answer", ""),
                "intent": result.get("intent", ""),
                "session_id": result.get("session_id", session_id),
            },
        )

    async def handle_ptz(call: ServiceCall) -> None:
        """cctvql.ptz — send a PTZ command to a camera."""
        camera_id: str = call.data["camera_id"]
        action: str = call.data["action"]
        if action not in PTZ_ACTIONS:
            logger.error("cctvql.ptz: invalid action '%s'", action)
            hass.bus.async_fire(
                f"{DOMAIN}_service_error",
                {"service": "ptz", "error": f"Invalid action: {action}"},
            )
            return
        speed: int = call.data.get("speed", 50)
        preset_id: int | None = call.data.get("preset_id")
        try:
            await client.ptz(camera_id, action=action, speed=speed, preset_id=preset_id)
        except Exception as exc:
            logger.error("cctvql.ptz failed for camera '%s': %s", camera_id, exc)
            hass.bus.async_fire(
                f"{DOMAIN}_service_error",
                {"service": "ptz", "camera_id": camera_id, "error": str(exc)},
            )

    async def handle_clear_session(call: ServiceCall) -> None:
        """cctvql.clear_session — reset conversation history."""
        session_id: str = call.data.get("session_id", "homeassistant")
        try:
            await client.clear_session(session_id)
        except Exception as exc:
            logger.error("cctvql.clear_session failed for session '%s': %s", session_id, exc)
            hass.bus.async_fire(
                f"{DOMAIN}_service_error",
                {"service": "clear_session", "session_id": session_id, "error": str(exc)},
            )

    hass.services.async_register(DOMAIN, "query", handle_query)
    hass.services.async_register(DOMAIN, "ptz", handle_ptz)
    hass.services.async_register(DOMAIN, "clear_session", handle_clear_session)
