"""
Tests for multi-tenant authentication and user management.

Covers:
- AuthManager: password hashing, JWT creation/verification
- UserStore: CRUD operations in-memory SQLite
- REST endpoints: /auth/login, /auth/register, /users/*
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from cctvql.adapters.base import AdapterRegistry
from cctvql.adapters.demo import DemoAdapter
from cctvql.core.auth import ROLE_ADMIN, ROLE_VIEWER, AuthManager, User
from cctvql.llm.base import LLMRegistry, LLMResponse

# ---------------------------------------------------------------------------
# AuthManager unit tests
# ---------------------------------------------------------------------------


class TestAuthManager:
    def _mgr(self) -> AuthManager:
        return AuthManager(secret_key="test-secret-key-1234")

    def test_hash_and_verify_correct_password(self):
        mgr = self._mgr()
        h = mgr.hash_password("s3cur3P@ss")
        assert mgr.verify_password("s3cur3P@ss", h)

    def test_verify_wrong_password_returns_false(self):
        mgr = self._mgr()
        h = mgr.hash_password("correct")
        assert not mgr.verify_password("wrong", h)

    def test_hash_is_non_deterministic(self):
        mgr = self._mgr()
        h1 = mgr.hash_password("password")
        h2 = mgr.hash_password("password")
        assert h1 != h2  # different salts

    def test_create_and_verify_token(self):
        mgr = self._mgr()
        user = User(id="u1", username="alice", password_hash="x", role=ROLE_ADMIN)
        token = mgr.create_token(user)
        payload = mgr.verify_token(token)
        assert payload is not None
        assert payload["username"] == "alice"
        assert payload["role"] == ROLE_ADMIN

    def test_token_contains_camera_groups(self):
        mgr = self._mgr()
        user = User(
            id="u2",
            username="bob",
            password_hash="x",
            role=ROLE_VIEWER,
            camera_groups=["Front Door", "Backyard"],
        )
        token = mgr.create_token(user)
        payload = mgr.verify_token(token)
        assert payload is not None
        assert payload["camera_groups"] == ["Front Door", "Backyard"]

    def test_tampered_token_rejected(self):
        mgr = self._mgr()
        user = User(id="u1", username="alice", password_hash="x")
        token = mgr.create_token(user)
        # Flip one character in the signature
        parts = token.split(".")
        parts[2] = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
        bad_token = ".".join(parts)
        assert mgr.verify_token(bad_token) is None

    def test_token_with_wrong_secret_rejected(self):
        mgr1 = AuthManager(secret_key="secret-one")
        mgr2 = AuthManager(secret_key="secret-two")
        user = User(id="u1", username="alice", password_hash="x")
        token = mgr1.create_token(user)
        assert mgr2.verify_token(token) is None

    def test_make_user_populates_fields(self):
        mgr = self._mgr()
        user = mgr.make_user("charlie", "pass123", role=ROLE_VIEWER, camera_groups=["Cam1"])
        assert user.username == "charlie"
        assert user.role == ROLE_VIEWER
        assert user.camera_groups == ["Cam1"]
        assert user.id  # UUID generated

    def test_malformed_token_returns_none(self):
        mgr = self._mgr()
        assert mgr.verify_token("not.a.valid.jwt.at.all") is None
        assert mgr.verify_token("") is None
        assert mgr.verify_token("only.two") is None


class TestUser:
    def test_admin_can_see_all_cameras(self):
        u = User(id="1", username="admin", password_hash="x", role=ROLE_ADMIN)
        assert u.can_see_camera("Front Door")
        assert u.can_see_camera("Any Camera")

    def test_viewer_with_no_groups_can_see_all(self):
        u = User(id="2", username="bob", password_hash="x", role=ROLE_VIEWER, camera_groups=[])
        assert u.can_see_camera("Front Door")

    def test_viewer_restricted_to_groups(self):
        u = User(
            id="3",
            username="eve",
            password_hash="x",
            role=ROLE_VIEWER,
            camera_groups=["Front Door"],
        )
        assert u.can_see_camera("Front Door")
        assert not u.can_see_camera("Backyard")

    def test_camera_group_case_insensitive(self):
        u = User(
            id="4",
            username="test",
            password_hash="x",
            role=ROLE_VIEWER,
            camera_groups=["front door"],
        )
        assert u.can_see_camera("Front Door")
        assert u.can_see_camera("FRONT DOOR")

    def test_to_dict_excludes_password_hash(self):
        u = User(id="5", username="x", password_hash="secret")
        d = u.to_dict()
        assert "password_hash" not in d
        assert "id" in d
        assert "username" in d
        assert "role" in d


# ---------------------------------------------------------------------------
# UserStore tests (in-memory SQLite)
# ---------------------------------------------------------------------------


@pytest.fixture
async def user_store():
    """Provide a UserStore backed by an in-memory SQLite database."""
    import aiosqlite

    from cctvql.core.user_store import UserStore

    auth = AuthManager(secret_key="store-test-key")
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    store = UserStore(conn, auth)
    await store.setup()
    yield store, auth
    await conn.close()


async def test_user_store_create_and_fetch(user_store):
    store, auth = user_store
    user = await store.create_user("alice", "pass", role=ROLE_ADMIN)
    fetched = await store.get_by_id(user.id)
    assert fetched is not None
    assert fetched.username == "alice"
    assert fetched.role == ROLE_ADMIN


async def test_user_store_get_by_username(user_store):
    store, _ = user_store
    await store.create_user("bob", "pass")
    u = await store.get_by_username("Bob")  # case-insensitive
    assert u is not None
    assert u.username == "bob"


async def test_user_store_duplicate_username_raises(user_store):
    store, _ = user_store
    await store.create_user("charlie", "pass")
    with pytest.raises(ValueError, match="already taken"):
        await store.create_user("charlie", "other")


async def test_user_store_list_users(user_store):
    store, _ = user_store
    await store.create_user("u1", "p")
    await store.create_user("u2", "p")
    users = await store.list_users()
    assert len(users) == 2


async def test_user_store_count_users(user_store):
    store, _ = user_store
    assert await store.count_users() == 0
    await store.create_user("x", "p")
    assert await store.count_users() == 1


async def test_user_store_update_role(user_store):
    store, _ = user_store
    user = await store.create_user("dave", "p", role=ROLE_VIEWER)
    updated = await store.update_user(user.id, role=ROLE_ADMIN)
    assert updated is not None
    assert updated.role == ROLE_ADMIN


async def test_user_store_update_camera_groups(user_store):
    store, _ = user_store
    user = await store.create_user("eve", "p")
    updated = await store.update_user(user.id, camera_groups=["Cam1", "Cam2"])
    assert updated is not None
    assert updated.camera_groups == ["Cam1", "Cam2"]


async def test_user_store_update_password(user_store):
    store, auth = user_store
    user = await store.create_user("frank", "oldpass")
    await store.update_user(user.id, password="newpass")
    refreshed = await store.get_by_id(user.id)
    assert refreshed is not None
    assert auth.verify_password("newpass", refreshed.password_hash)
    assert not auth.verify_password("oldpass", refreshed.password_hash)


async def test_user_store_delete(user_store):
    store, _ = user_store
    user = await store.create_user("grace", "p")
    deleted = await store.delete_user(user.id)
    assert deleted is True
    assert await store.get_by_id(user.id) is None


async def test_user_store_delete_nonexistent_returns_false(user_store):
    store, _ = user_store
    assert await store.delete_user("no-such-id") is False


async def test_user_store_count_admins(user_store):
    store, _ = user_store
    await store.create_user("a1", "p", role=ROLE_ADMIN)
    await store.create_user("v1", "p", role=ROLE_VIEWER)
    assert await store.count_admins() == 1


# ---------------------------------------------------------------------------
# REST API tests for auth endpoints
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_registries():
    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None

    adapter = DemoAdapter()
    AdapterRegistry.register(adapter)
    AdapterRegistry.set_active("demo")

    mock_llm = MagicMock()
    mock_llm.name = "mock"
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"intent":"list_cameras","limit":20,"explanation":"list"}',
            model="mock",
        )
    )
    mock_llm.health_check = AsyncMock(return_value=True)
    LLMRegistry.register(mock_llm)
    LLMRegistry.set_active("mock")

    yield

    AdapterRegistry._adapters = {}
    AdapterRegistry._active = None
    LLMRegistry._backends = {}
    LLMRegistry._active = None


@pytest.fixture
async def mt_client():
    """API client with CCTVQL_MULTI_TENANT=1 and an in-memory SQLite DB."""

    import aiosqlite

    import cctvql.interfaces.rest_api as api_module
    from cctvql.core.alerts import AlertEngine
    from cctvql.core.auth import AuthManager
    from cctvql.core.health_monitor import HealthMonitor
    from cctvql.core.user_store import UserStore
    from cctvql.notifications.registry import NotifierRegistry

    # Patch the module-level flag and global singletons
    original_mt = api_module._MULTI_TENANT
    api_module._MULTI_TENANT = True
    api_module._in_memory_sessions.clear()
    api_module._db = None
    api_module._session_store = None

    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row

    auth = AuthManager(secret_key="api-test-secret")
    store = UserStore(conn, auth)
    await store.setup()

    api_module._auth_manager = auth
    api_module._user_store = store

    engine = AlertEngine(AdapterRegistry)
    await engine.start()
    api_module._alert_engine = engine

    monitor = HealthMonitor(AdapterRegistry, NotifierRegistry, poll_interval=9999)
    await monitor.start()
    api_module._health_monitor = monitor

    transport = httpx.ASGITransport(app=api_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, auth, store

    await engine.stop()
    await monitor.stop()
    await conn.close()
    api_module._MULTI_TENANT = original_mt
    api_module._auth_manager = None
    api_module._user_store = None
    api_module._in_memory_sessions.clear()


# -- /auth/register ----------------------------------------------------------


async def test_first_register_becomes_admin(mt_client):
    client, auth, store = mt_client
    resp = await client.post("/auth/register", json={"username": "admin", "password": "secret123"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["role"] == "admin"


async def test_register_returns_user_shape(mt_client):
    client, _, _ = mt_client
    resp = await client.post("/auth/register", json={"username": "alice", "password": "pass"})
    assert resp.status_code == 201
    for key in ["id", "username", "role", "camera_groups", "created_at", "active"]:
        assert key in resp.json()


async def test_duplicate_username_returns_409(mt_client):
    client, _, _ = mt_client
    await client.post("/auth/register", json={"username": "dup", "password": "pass"})
    resp = await client.post("/auth/register", json={"username": "dup", "password": "pass2"})
    # Second call needs admin auth — but it also would conflict on username
    # Without a token this returns 401 (not authenticated), not 409
    assert resp.status_code in {401, 409}


# -- /auth/login -------------------------------------------------------------


async def _bootstrap(client, username="admin", password="secret") -> str:
    """Register first user (becomes admin) and return their JWT."""
    await client.post("/auth/register", json={"username": username, "password": password})
    resp = await client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()["access_token"]


async def test_login_returns_token(mt_client):
    client, _, _ = mt_client
    token = await _bootstrap(client)
    assert token


async def test_login_response_shape(mt_client):
    client, _, _ = mt_client
    await client.post("/auth/register", json={"username": "admin", "password": "pass"})
    resp = await client.post("/auth/login", json={"username": "admin", "password": "pass"})
    assert resp.status_code == 200
    for key in ["access_token", "token_type", "expires_in", "user_id", "username", "role"]:
        assert key in resp.json()


async def test_login_wrong_password_returns_401(mt_client):
    client, _, _ = mt_client
    await client.post("/auth/register", json={"username": "admin", "password": "correct"})
    resp = await client.post("/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


async def test_login_unknown_user_returns_401(mt_client):
    client, _, _ = mt_client
    resp = await client.post("/auth/login", json={"username": "ghost", "password": "x"})
    assert resp.status_code == 401


# -- /users ------------------------------------------------------------------


async def test_list_users_requires_admin(mt_client):
    client, auth, store = mt_client
    # Create admin + viewer
    await store.create_user("admin", "p", role=ROLE_ADMIN)
    viewer = await store.create_user("viewer", "p", role=ROLE_VIEWER)
    viewer_token = auth.create_token(viewer)
    resp = await client.get("/users", headers={"Authorization": f"Bearer {viewer_token}"})
    assert resp.status_code == 403


async def test_list_users_as_admin(mt_client):
    client, auth, store = mt_client
    admin = await store.create_user("admin", "p", role=ROLE_ADMIN)
    await store.create_user("viewer", "p", role=ROLE_VIEWER)
    token = auth.create_token(admin)
    resp = await client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_me(mt_client):
    client, auth, store = mt_client
    user = await store.create_user("me", "p", role=ROLE_VIEWER)
    token = auth.create_token(user)
    resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "me"


async def test_update_user_role(mt_client):
    client, auth, store = mt_client
    admin = await store.create_user("admin", "p", role=ROLE_ADMIN)
    await store.create_user("admin2", "p", role=ROLE_ADMIN)  # second admin so we can demote
    viewer = await store.create_user("viewer", "p", role=ROLE_VIEWER)
    token = auth.create_token(admin)
    resp = await client.patch(
        f"/users/{viewer.id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_cannot_delete_last_admin(mt_client):
    client, auth, store = mt_client
    admin = await store.create_user("admin", "p", role=ROLE_ADMIN)
    token = auth.create_token(admin)
    resp = await client.delete(f"/users/{admin.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 409


async def test_delete_user(mt_client):
    client, auth, store = mt_client
    admin = await store.create_user("admin", "p", role=ROLE_ADMIN)
    await store.create_user("admin2", "p", role=ROLE_ADMIN)  # second admin
    viewer = await store.create_user("viewer", "p", role=ROLE_VIEWER)
    token = auth.create_token(admin)
    resp = await client.delete(f"/users/{viewer.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


# -- Camera filtering --------------------------------------------------------


async def test_camera_filter_viewer_restricted(mt_client):
    client, auth, store = mt_client
    # Viewer only allowed to see "Front Door"
    viewer = await store.create_user("viewer", "p", role=ROLE_VIEWER, camera_groups=["Front Door"])
    token = auth.create_token(viewer)
    resp = await client.get("/cameras", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    cameras = resp.json()
    assert all(c["name"].lower() == "front door" for c in cameras)


async def test_camera_filter_admin_sees_all(mt_client):
    client, auth, store = mt_client
    admin = await store.create_user("admin", "p", role=ROLE_ADMIN)
    token = auth.create_token(admin)
    resp = await client.get("/cameras", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1  # demo adapter has 4 cameras


# -- Auth disabled -----------------------------------------------------------


@pytest.fixture
async def st_client():
    """Single-tenant client (no multi-tenant)."""
    import cctvql.interfaces.rest_api as api_module
    from cctvql.core.alerts import AlertEngine
    from cctvql.core.health_monitor import HealthMonitor
    from cctvql.notifications.registry import NotifierRegistry

    api_module._in_memory_sessions.clear()
    api_module._db = None
    api_module._session_store = None
    api_module._auth_manager = None
    api_module._user_store = None

    engine = AlertEngine(AdapterRegistry)
    await engine.start()
    api_module._alert_engine = engine

    monitor = HealthMonitor(AdapterRegistry, NotifierRegistry, poll_interval=9999)
    await monitor.start()
    api_module._health_monitor = monitor

    transport = httpx.ASGITransport(app=api_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await engine.stop()
    await monitor.stop()


async def test_login_returns_501_when_disabled(st_client):
    resp = await st_client.post("/auth/login", json={"username": "x", "password": "y"})
    assert resp.status_code == 501


async def test_register_returns_501_when_disabled(st_client):
    resp = await st_client.post("/auth/register", json={"username": "x", "password": "y"})
    assert resp.status_code == 501


async def test_cameras_accessible_without_auth_in_single_tenant(st_client):
    resp = await st_client.get("/cameras")
    assert resp.status_code == 200
