"""Config flow for the cctvQL Home Assistant integration."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

logger = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_API_KEY, default=""): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            int, vol.Range(min=10, max=3600)
        ),
    }
)


async def _validate_connection(host: str, port: int, api_key: str) -> dict[str, str]:
    """Try GET /health and return errors dict (empty = success)."""
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"http://{host}:{port}/health", headers=headers
            )
            if resp.status_code == 401:
                return {"base": "invalid_auth"}
            if resp.status_code != 200:
                return {"base": "cannot_connect"}
    except (httpx.ConnectError, httpx.TimeoutException):
        return {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        return {"base": "unknown"}
    return {}


class CctvqlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup UI flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host: str = user_input[CONF_HOST].strip()
            port: int = user_input[CONF_PORT]
            api_key: str = user_input.get(CONF_API_KEY, "").strip()

            errors = await _validate_connection(host, port, api_key)
            if not errors:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"cctvQL ({host}:{port})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_API_KEY: api_key or None,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CctvqlOptionsFlow:
        return CctvqlOptionsFlow(config_entry)


class CctvqlOptionsFlow(OptionsFlow):
    """Handle options updates (scan interval) without re-authentication."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): vol.All(int, vol.Range(min=10, max=3600))
                }
            ),
        )
