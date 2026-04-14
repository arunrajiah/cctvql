"""
Sensor platform for cctvQL.

Entities created:
  - Cameras Online        (count)
  - Cameras Offline       (count)
  - Adapter Status        ("ok" / "degraded")
  - LLM Status            ("ok" / "degraded")
  - Recent Events         (count over the last poll window)
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            CctvqlCamerasOnlineSensor(coordinator, entry),
            CctvqlCamerasOfflineSensor(coordinator, entry),
            CctvqlAdapterStatusSensor(coordinator, entry),
            CctvqlLlmStatusSensor(coordinator, entry),
            CctvqlRecentEventsSensor(coordinator, entry),
        ]
    )


class _CctvqlSensorBase(CoordinatorEntity, SensorEntity):
    """Shared base for all cctvQL sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_name = name
        self._entry = entry

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "cctvQL",
            "manufacturer": "cctvQL",
            "model": "CCTV Query Layer",
            "configuration_url": (
                f"http://{self._entry.data['host']}:{self._entry.data['port']}/docs"
            ),
        }


class CctvqlCamerasOnlineSensor(_CctvqlSensorBase):
    _attr_icon = "mdi:camera"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "cameras"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "cameras_online", "Cameras Online")

    @property
    def native_value(self) -> int:
        cam_health: list = self.coordinator.data.get("camera_health", [])
        return sum(1 for c in cam_health if c.get("status") == "online")

    @property
    def extra_state_attributes(self) -> dict:
        cam_health: list = self.coordinator.data.get("camera_health", [])
        return {"cameras": [c["camera_name"] for c in cam_health if c.get("status") == "online"]}


class CctvqlCamerasOfflineSensor(_CctvqlSensorBase):
    _attr_icon = "mdi:camera-off"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "cameras"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "cameras_offline", "Cameras Offline")

    @property
    def native_value(self) -> int:
        cam_health: list = self.coordinator.data.get("camera_health", [])
        return sum(1 for c in cam_health if c.get("status") != "online")

    @property
    def extra_state_attributes(self) -> dict:
        cam_health: list = self.coordinator.data.get("camera_health", [])
        return {"cameras": [c["camera_name"] for c in cam_health if c.get("status") != "online"]}


class CctvqlAdapterStatusSensor(_CctvqlSensorBase):
    _attr_icon = "mdi:server"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "adapter_status", "Adapter Status")

    @property
    def native_value(self) -> str:
        health = self.coordinator.data.get("health", {})
        return health.get("adapter", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        health = self.coordinator.data.get("health", {})
        return {
            "ok": health.get("adapter_ok", False),
            "status": health.get("status", "unknown"),
        }


class CctvqlLlmStatusSensor(_CctvqlSensorBase):
    _attr_icon = "mdi:brain"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "llm_status", "LLM Status")

    @property
    def native_value(self) -> str:
        health = self.coordinator.data.get("health", {})
        return health.get("llm", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        health = self.coordinator.data.get("health", {})
        return {
            "ok": health.get("llm_ok", False),
            "status": health.get("status", "unknown"),
        }


class CctvqlRecentEventsSensor(_CctvqlSensorBase):
    _attr_icon = "mdi:motion-sensor"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "events"

    def __init__(self, coordinator: DataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "recent_events", "Recent Events")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("events", []))

    @property
    def extra_state_attributes(self) -> dict:
        events: list = self.coordinator.data.get("events", [])
        # Return the 5 most recent as attributes for dashboard cards
        recent = events[:5]
        return {
            "recent": [
                {
                    "camera": e.get("camera", ""),
                    "type": e.get("type", ""),
                    "start_time": e.get("start_time", ""),
                    "label": (e.get("objects") or [{}])[0].get("label", ""),
                }
                for e in recent
            ]
        }
