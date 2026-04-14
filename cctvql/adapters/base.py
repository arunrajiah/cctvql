"""
cctvQL Adapter Base
--------------------
Abstract interface that every CCTV system adapter must implement.
This is the contract between cctvQL's core and any vendor-specific system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from cctvql.core.schema import Camera, Clip, Event, SystemInfo, Zone


class BaseAdapter(ABC):
    """
    Abstract base class for CCTV system adapters.

    To add support for a new system:
        1. Subclass BaseAdapter
        2. Implement all abstract methods
        3. Register via AdapterRegistry or in config.yaml

    Each method should return normalized cctvQL schema objects —
    never vendor-specific raw data.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable adapter name (e.g. 'frigate', 'onvif')."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to the CCTV system.
        Returns True if successful.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the CCTV system."""
        ...

    @abstractmethod
    async def list_cameras(self) -> list[Camera]:
        """Return all cameras in the system."""
        ...

    @abstractmethod
    async def get_camera(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> Camera | None:
        """Retrieve a single camera by id or name."""
        ...

    @abstractmethod
    async def get_events(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        label: str | None = None,
        zone: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Event]:
        """
        Fetch detection/motion events with optional filters.

        All parameters are optional — omitting them returns all recent events.
        """
        ...

    @abstractmethod
    async def get_event(self, event_id: str) -> Event | None:
        """Retrieve a single event by its ID."""
        ...

    @abstractmethod
    async def get_clips(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 20,
    ) -> list[Clip]:
        """Fetch recorded video clips."""
        ...

    @abstractmethod
    async def get_snapshot_url(
        self,
        camera_id: str | None = None,
        camera_name: str | None = None,
    ) -> str | None:
        """Return a URL to the latest snapshot for the given camera."""
        ...

    @abstractmethod
    async def get_system_info(self) -> SystemInfo | None:
        """Return high-level system health and storage info."""
        ...

    # Optional — adapters can override for richer functionality

    async def list_zones(self, camera_id: str | None = None) -> list[Zone]:
        """List configured zones/regions. Override for full support."""
        return []

    async def health_check(self) -> bool:
        """Return True if the system is reachable."""
        return True

    async def ptz_move(self, camera_name: str, action: str, speed: int = 50) -> bool:
        """
        Pan/tilt/zoom a camera.

        Args:
            camera_name: Camera to control.
            action:      One of left|right|up|down|zoom_in|zoom_out|stop.
            speed:       Movement speed 1–100 (default: 50).

        Returns:
            True if the command was accepted, False if PTZ is not supported.
        """
        return False

    async def ptz_preset(self, camera_name: str, preset_id: int) -> bool:
        """
        Move camera to a named PTZ preset.

        Args:
            camera_name: Camera to control.
            preset_id:   Numeric preset identifier.

        Returns:
            True if the command was accepted, False if PTZ is not supported.
        """
        return False

    async def get_ptz_presets(self, camera_name: str) -> list[dict]:
        """
        Return available PTZ presets for a camera.

        Returns:
            list of {"id": int, "name": str} dicts.
        """
        return []


class AdapterRegistry:
    """Maps adapter names to instances for multi-system setups."""

    _adapters: dict[str, BaseAdapter] = {}
    _active: str | None = None

    @classmethod
    def register(cls, adapter: BaseAdapter) -> None:
        cls._adapters[adapter.name] = adapter

    @classmethod
    def set_active(cls, name: str) -> None:
        if name not in cls._adapters:
            raise ValueError(f"Adapter '{name}' not registered.")
        cls._active = name

    @classmethod
    def get_active(cls) -> BaseAdapter:
        if not cls._active or cls._active not in cls._adapters:
            raise RuntimeError("No active adapter configured.")
        return cls._adapters[cls._active]

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._adapters.keys())
