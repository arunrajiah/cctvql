"""
cctvQL Session Store
---------------------
Persisted conversation memory backed by the Database class.
"""

from __future__ import annotations

import logging

from cctvql.core.database import Database

logger = logging.getLogger(__name__)


class SessionStore:
    """
    Persists conversation history for NLP sessions.

    Args:
        db: Connected Database instance.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_history(self, session_id: str) -> list[dict]:
        """
        Return message history for a session.

        Returns:
            list of {"role": "user"|"assistant", "content": str}
        """
        rows = await self._db.get_session_messages(session_id)
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Persist a new message to the session history."""
        await self._db.save_message(session_id, role, content)

    async def clear_session(self, session_id: str) -> None:
        """Delete all messages for a session."""
        await self._db.delete_session_messages(session_id)
        logger.info("SessionStore: cleared session %s", session_id)
