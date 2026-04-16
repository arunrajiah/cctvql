"""
cctvQL User Store
------------------
SQLite-backed persistence for user accounts (multi-tenant mode).

Adds a ``users`` table to the existing cctvQL database.  The store is
only instantiated when ``CCTVQL_MULTI_TENANT=1`` is set.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from cctvql.core.auth import ROLE_ADMIN, AuthManager, User

logger = logging.getLogger(__name__)

_CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'viewer',
    camera_groups TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);
"""


class UserStore:
    """
    Async user persistence backed by the cctvQL SQLite database.

    Args:
        db_conn:     An open ``aiosqlite.Connection``.
        auth:        The shared ``AuthManager`` instance.
    """

    def __init__(self, db_conn: Any, auth: AuthManager) -> None:
        self._conn = db_conn
        self._auth = auth

    async def setup(self) -> None:
        """Create the users table if it does not exist."""
        await self._conn.executescript(_CREATE_USERS_TABLE)
        await self._conn.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_user(
        self,
        username: str,
        password: str,
        role: str = "viewer",
        camera_groups: list[str] | None = None,
    ) -> User:
        """
        Create and persist a new user.

        Raises ``ValueError`` if the username is already taken.
        """
        existing = await self.get_by_username(username)
        if existing:
            raise ValueError(f"Username '{username}' is already taken.")

        user = self._auth.make_user(
            username=username,
            password=password,
            role=role,
            camera_groups=camera_groups,
        )
        await self._conn.execute(
            """
            INSERT INTO users (id, username, password_hash, role, camera_groups, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.username,
                user.password_hash,
                user.role,
                json.dumps(user.camera_groups),
                user.created_at.isoformat(),
                int(user.active),
            ),
        )
        await self._conn.commit()
        logger.info("Created user '%s' (role=%s)", username, role)
        return user

    async def get_by_id(self, user_id: str) -> User | None:
        """Fetch a user by their UUID."""
        async with self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return _row_to_user(row) if row else None

    async def get_by_username(self, username: str) -> User | None:
        """Fetch a user by username (case-insensitive)."""
        async with self._conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_user(row) if row else None

    async def list_users(self) -> list[User]:
        """Return all users."""
        async with self._conn.execute("SELECT * FROM users ORDER BY created_at ASC") as cursor:
            rows = await cursor.fetchall()
        return [_row_to_user(r) for r in rows]

    async def count_users(self) -> int:
        """Return total user count."""
        async with self._conn.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def update_user(self, user_id: str, **kwargs: Any) -> User | None:
        """
        Update one or more user fields.

        Accepted kwargs: ``role``, ``camera_groups``, ``active``, ``password``.
        Returns the updated User, or None if not found.
        """
        user = await self.get_by_id(user_id)
        if not user:
            return None

        updates: list[str] = []
        params: list[Any] = []

        if "role" in kwargs:
            updates.append("role = ?")
            params.append(kwargs["role"])
        if "camera_groups" in kwargs:
            updates.append("camera_groups = ?")
            params.append(json.dumps(kwargs["camera_groups"]))
        if "active" in kwargs:
            updates.append("active = ?")
            params.append(int(kwargs["active"]))
        if "password" in kwargs:
            updates.append("password_hash = ?")
            params.append(self._auth.hash_password(kwargs["password"]))

        if not updates:
            return user

        params.append(user_id)
        await self._conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            params,  # noqa: S608
        )
        await self._conn.commit()
        return await self.get_by_id(user_id)

    async def delete_user(self, user_id: str) -> bool:
        """Delete a user.  Returns True if deleted, False if not found."""
        cursor = await self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def count_admins(self) -> int:
        """Count active admin users."""
        async with self._conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = ? AND active = 1", (ROLE_ADMIN,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row_to_user(row: Any) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        role=row["role"],
        camera_groups=json.loads(row["camera_groups"] or "[]"),
        created_at=datetime.fromisoformat(row["created_at"]),
        active=bool(row["active"]),
    )
