# Contributing to cctvQL

Thank you for your interest in contributing! cctvQL grows through community adapters and improvements.

## Ways to Contribute

- **Add an adapter** for a new CCTV system (most impactful!)
- **Improve the NLP engine** — better intent parsing, time expressions, multi-language
- **Report bugs** via GitHub Issues
- **Improve docs** — especially setup guides for specific camera brands

---

## Writing a New Adapter

The fastest path to getting your CCTV system supported.

### 1. Create your adapter file

```
cctvql/adapters/your_system.py
```

### 2. Subclass BaseAdapter

```python
from cctvql.adapters.base import BaseAdapter
from cctvql.core.schema import Camera, CameraStatus, Event, EventType, Clip, SystemInfo

class YourSystemAdapter(BaseAdapter):

    def __init__(self, host: str, username: str = "admin", password: str = ""):
        self.host = host
        self.username = username
        self.password = password

    @property
    def name(self) -> str:
        return "your_system"   # used in config.yaml

    async def connect(self) -> bool:
        # Establish connection, return True if successful
        ...

    async def disconnect(self) -> None:
        ...

    async def list_cameras(self) -> list[Camera]:
        # Return all cameras normalized to Camera schema
        ...

    async def get_camera(self, camera_id=None, camera_name=None):
        ...

    async def get_events(self, camera_id=None, camera_name=None,
                         label=None, zone=None,
                         start_time=None, end_time=None, limit=20):
        # Return events normalized to Event schema
        ...

    async def get_event(self, event_id: str):
        ...

    async def get_clips(self, ...):
        ...

    async def get_snapshot_url(self, camera_id=None, camera_name=None):
        ...

    async def get_system_info(self):
        ...
```

### 3. Register in `_bootstrap.py`

Add your system to the `_create_adapter()` function in `cctvql/_bootstrap.py`:

```python
elif adapter_type == "your_system":
    from cctvql.adapters.your_system import YourSystemAdapter
    return YourSystemAdapter(
        host=cfg.get("host"),
        username=cfg.get("username", "admin"),
        password=cfg.get("password", ""),
    )
```

### 4. Add to README compatibility table

Update the table in `README.md`.

### 5. Write a test

Add `tests/test_your_system_adapter.py` with at least basic mock tests.

---

## Development Setup

```bash
git clone https://github.com/arunrajiah/cctvql
cd cctvql
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mqtt,onvif]"
```

Run tests:
```bash
pytest tests/
```

Lint:
```bash
ruff check cctvql/
```

---

## Pull Request Guidelines

- Keep PRs focused — one adapter or feature per PR
- Include tests for new code
- Update `README.md` compatibility table for new adapters
- Use descriptive commit messages
- Don't add external dependencies without discussion

---

## Code of Conduct

Be respectful, helpful, and constructive. This project is for the community.
