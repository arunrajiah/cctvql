# Writing a cctvQL Adapter

An **adapter** is a Python class that connects cctvQL's NLP engine to a specific CCTV system. All adapters normalize vendor-specific data into cctvQL's common schema, so the NLP layer never needs to know which system it's talking to.

Writing a new adapter typically takes **50–150 lines** of Python.

---

## Step 1 — Create your adapter file

```
cctvql/adapters/your_system.py
```

---

## Step 2 — Subclass `BaseAdapter`

```python
from cctvql.adapters.base import BaseAdapter
from cctvql.core.schema import (
    Camera, CameraStatus, Clip, Event, EventType,
    DetectedObject, SystemInfo
)
from datetime import datetime
from typing import Optional


class YourSystemAdapter(BaseAdapter):

    def __init__(self, host: str, username: str = "admin", password: str = ""):
        self.host = host.rstrip("/")
        self.username = username
        self.password = password
        # initialize your HTTP client here, e.g. httpx.AsyncClient()

    @property
    def name(self) -> str:
        return "your_system"   # used as the key in config.yaml

    # ── Connection ────────────────────────────────────────
    async def connect(self) -> bool:
        """Test connectivity. Return True if successful."""
        try:
            # e.g. call a health/version endpoint
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        """Release resources (close HTTP clients, MQTT connections, etc.)"""
        pass

    # ── Cameras ──────────────────────────────────────────
    async def list_cameras(self) -> list[Camera]:
        """Return all cameras, normalized to Camera objects."""
        # Call your system's API, convert to Camera objects
        return [
            Camera(
                id="cam1",
                name="Front Door",
                status=CameraStatus.ONLINE,
                snapshot_url="http://...",
                stream_url="rtsp://...",
            )
        ]

    async def get_camera(
        self,
        camera_id: Optional[str] = None,
        camera_name: Optional[str] = None,
    ) -> Optional[Camera]:
        cameras = await self.list_cameras()
        for cam in cameras:
            if camera_id and cam.id == camera_id:
                return cam
            if camera_name and cam.name.lower() == camera_name.lower():
                return cam
        return None

    # ── Events ──────────────────────────────────────────
    async def get_events(
        self,
        camera_id=None, camera_name=None,
        label=None, zone=None,
        start_time=None, end_time=None,
        limit=20,
    ) -> list[Event]:
        """Fetch detection/motion events with optional filters."""
        # Call your system's event API, convert to Event objects
        return []

    async def get_event(self, event_id: str) -> Optional[Event]:
        return None

    # ── Clips ────────────────────────────────────────────
    async def get_clips(
        self,
        camera_id=None, camera_name=None,
        start_time=None, end_time=None,
        limit=20,
    ) -> list[Clip]:
        return []

    # ── Snapshots ────────────────────────────────────────
    async def get_snapshot_url(
        self,
        camera_id=None,
        camera_name=None,
    ) -> Optional[str]:
        return f"{self.host}/snapshot/{camera_name or camera_id}"

    # ── System Info ──────────────────────────────────────
    async def get_system_info(self) -> Optional[SystemInfo]:
        return SystemInfo(
            system_name="Your System",
            version="1.0",
            camera_count=1,
        )
```

---

## Step 3 — Register in `_bootstrap.py`

Open `cctvql/_bootstrap.py` and add your system to `_create_adapter()`:

```python
elif adapter_type == "your_system":
    from cctvql.adapters.your_system import YourSystemAdapter
    return YourSystemAdapter(
        host=cfg.get("host"),
        username=cfg.get("username", "admin"),
        password=cfg.get("password", ""),
    )
```

---

## Step 4 — Add to `adapters/__init__.py`

```python
from .your_system import YourSystemAdapter
```

---

## Step 5 — Write tests

Create `tests/test_your_system_adapter.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from cctvql.adapters.your_system import YourSystemAdapter

@pytest.mark.asyncio
async def test_connect():
    adapter = YourSystemAdapter(host="http://fake-host")
    # Mock your HTTP calls and assert connect() returns True

@pytest.mark.asyncio
async def test_list_cameras():
    adapter = YourSystemAdapter(host="http://fake-host")
    cameras = await adapter.list_cameras()
    assert isinstance(cameras, list)
```

---

## Step 6 — Update the README

Add your system to the [compatibility table](../README.md#supported-systems).

---

## Step 7 — Open a Pull Request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for PR guidelines.

---

## Tips

- Use `httpx.AsyncClient` for async HTTP requests
- Normalize all timestamps to `datetime` objects (not Unix timestamps)
- Always return empty lists `[]` rather than `None` from list methods
- Add `metadata={"source": "your_system"}` to all objects for debugging
- If your system uses RTSP, store the RTSP URL in `Camera.stream_url`
- Test with `pytest -v` before opening a PR

---

## Reference Implementations

Each bundled adapter illustrates a different authentication pattern — pick the closest match when starting yours:

| Adapter | Auth pattern | Transport | File |
|---------|--------------|-----------|------|
| `frigate` | No auth (LAN) | REST + MQTT | [`cctvql/adapters/frigate.py`](../cctvql/adapters/frigate.py) |
| `onvif` | WS-Security | SOAP (onvif-zeep) | [`cctvql/adapters/onvif.py`](../cctvql/adapters/onvif.py) |
| `hikvision` | HTTP Digest | XML / ISAPI | [`cctvql/adapters/hikvision.py`](../cctvql/adapters/hikvision.py) |
| `dahua` | HTTP Digest | CGI key=value | [`cctvql/adapters/dahua.py`](../cctvql/adapters/dahua.py) |
| `synology` | Session ID (SID) | JSON Web API | [`cctvql/adapters/synology.py`](../cctvql/adapters/synology.py) |
| `milestone` | OAuth 2.0 Bearer | REST / OData | [`cctvql/adapters/milestone.py`](../cctvql/adapters/milestone.py) |
| `scrypted` | Long-lived Bearer token | REST (plugin endpoints) | [`cctvql/adapters/scrypted.py`](../cctvql/adapters/scrypted.py) |

### Config snippets

```yaml
# Synology Surveillance Station — session-based auth
synology:
  type: synology
  host: http://192.168.1.10:5000
  username: admin
  password: "${SYNOLOGY_PASSWORD}"

# Milestone XProtect — OAuth2 password grant against IDP
milestone:
  type: milestone
  host: https://vms.example.com
  username: admin
  password: "${MILESTONE_PASSWORD}"
  client_id: GrantValidatorClient

# Scrypted — Bearer token generated in Settings → Users
scrypted:
  type: scrypted
  host: https://scrypted.local:10443
  api_token: "${SCRYPTED_API_TOKEN}"
```
