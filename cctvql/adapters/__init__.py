from .base import AdapterRegistry, BaseAdapter
from .dahua import DahuaAdapter
from .demo import DemoAdapter
from .frigate import FrigateAdapter
from .hikvision import HikvisionAdapter
from .onvif import ONVIFAdapter

__all__ = [
    "BaseAdapter",
    "AdapterRegistry",
    "FrigateAdapter",
    "ONVIFAdapter",
    "DemoAdapter",
    "HikvisionAdapter",
    "DahuaAdapter",
]
