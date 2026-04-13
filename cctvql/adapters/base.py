"""
cctvQL Adapter Base
--------------------
Abstract interface that every CCTV system adapter must implement.
This is the contract between cctvQL's core and any vendor-specific system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

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
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
    ) -> Optional[Camera]:
        """Retrieve a single camera by id or name."""
        ...

    @abstractmethod
    async def get_events(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
        label: Optional[str] = None,
        zone: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[Event]:
        """
        Fetch detection/motion events with optional filters.

        All parameters are optional — omitting them returns all recent events.
        """
        ...

    @abstractmethod
    async def get_event(self, event_id: str) -> Optional[Event]:
        """Retrieve a single event by its ID."""
        ...

    @abstractmethod
    async def get_clips(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[Clip]:
        """Fetch recorded video clips."""
        ...

    @abstractmethod
    async def get_snapshot_url(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
    ) -> Optional[str]:
        """Return a URL to the latest snapshot for the given camera."""
        ...

    @abstractmethod
    async def get_system_info(self) -> Optional[SystemInfo]:
        """Return high-level system health and storage info."""
        ...

    # Optional — adapters can override for richer functionality

    async def list_zones(self, camera_id: Optional[str] = None) -> list[Zone]:
        """List configured zones/regions. Override for full support."""
        return []

    async def health_check(self) -> bool:
        """Return True if the system is reachable."""
        return True


class AdapterRegistry:
    """Maps adapter names to instances for multi-system setups."""

    _adapters: dict[str, BaseAdapter] = {}
    _active: Optional[str] = None

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
