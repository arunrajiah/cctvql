"""
Binary sensor platform for cctvQL.

Creates one binary sensor per camera:
  - ON  → at least one event detected on that camera in the most recent poll
  - OFF → no events in the poll window
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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

    cameras: list[dict] = coordinator.data.get("cameras", [])
    entities = [
        CctvqlMotionBinarySensor(coordinator, entry, cam)
        for cam in cameras
    ]
    async_add_entities(entities)


class CctvqlMotionBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """True when a recent event was detected on this camera."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_icon = "mdi:motion-sensor"

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        camera: dict,
    ) -> None:
        super().__init__(coordinator)
        self._camera_id: str = camera.get("id", "")
        self._camera_name: str = camera.get("name", self._camera_id)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_motion_{self._camera_id}"
        self._attr_name = f"{self._camera_name} Motion"

    @property
    def is_on(self) -> bool:
        """Return True if there are any recent events for this camera."""
        events: list[dict] = self.coordinator.data.get("events", [])
        cam_lower = self._camera_name.lower()
        return any(
            e.get("camera", "").lower() == cam_lower
            for e in events
        )

    @property
    def extra_state_attributes(self) -> dict:
        events: list[dict] = self.coordinator.data.get("events", [])
        cam_lower = self._camera_name.lower()
        cam_events = [e for e in events if e.get("camera", "").lower() == cam_lower]
        latest = cam_events[0] if cam_events else None
        return {
            "camera_id": self._camera_id,
            "event_count": len(cam_events),
            "latest_event_time": latest.get("start_time") if latest else None,
            "latest_label": (
                (latest.get("objects") or [{}])[0].get("label") if latest else None
            ),
            "snapshot_url": latest.get("snapshot_url") if latest else None,
        }

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "cctvQL",
            "manufacturer": "cctvQL",
            "model": "CCTV Query Layer",
        }
