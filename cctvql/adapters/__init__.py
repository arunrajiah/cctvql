from .base import AdapterRegistry, BaseAdapter
from .dahua import DahuaAdapter
from .demo import DemoAdapter
from .frigate import FrigateAdapter
from .hikvision import HikvisionAdapter
from .milestone import MilestoneAdapter
from .onvif import ONVIFAdapter
from .scrypted import ScryptedAdapter
from .synology import SynologyAdapter

__all__ = [
    "BaseAdapter",
    "AdapterRegistry",
    "FrigateAdapter",
    "ONVIFAdapter",
    "DemoAdapter",
    "HikvisionAdapter",
    "DahuaAdapter",
    "SynologyAdapter",
    "MilestoneAdapter",
    "ScryptedAdapter",
]
