"""
cctvQL NLP Engine
-----------------
Translates natural language queries into structured QueryContext objects
using an LLM backend. Maintains conversation history for multi-turn dialogue.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from cctvql.core.schema import QueryContext
from cctvql.llm.base import BaseLLM, LLMMessage

if TYPE_CHECKING:
    from cctvql.core.session_store import SessionStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — instructs the LLM how to parse CCTV queries
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are cctvQL, an intelligent assistant for CCTV and surveillance systems.
Your job is to understand natural language queries and convert them into structured JSON commands.

You have access to these intents:
- list_cameras          → List all cameras
- get_camera            → Info about a specific camera (needs: camera_name or camera_id)
- get_events            → Fetch events (optional: camera_name, label, start/end_time, zone, limit)
- get_clips             → Fetch recorded clips (optional: camera_name, start_time, end_time)
- get_snapshot          → Get a live snapshot (needs: camera_name)
- get_system_info       → Get system health/storage info
- describe_event        → AI vision analysis of a specific event (needs: event_id or camera_name)
- analyze_snapshot      → Describe what is currently visible on a camera (needs: camera_name)
- set_alert             → Create an alert rule (needs: label, camera_name or zone, schedule)
- list_alerts           → Show configured alert rules
- delete_alert          → Remove an alert rule (needs: alert_id or description)
- detect_anomalies      → Find unusual activity patterns (optional: camera_name, hours window)
- ptz_move              → Pan/tilt/zoom a camera (needs: camera_name,
                          action: left|right|up|down|zoom_in|zoom_out|stop, speed: 1-100)
- ptz_preset            → Go to a PTZ preset position (needs: camera_name, preset_id)
- unknown               → Query cannot be mapped to any intent

Always respond with ONLY valid JSON in this format:
{{
  "intent": "<intent_name>",
  "camera_name": "<name or null>",
  "event_id": "<event_id or null>",
  "label": "<person|car|dog|etc or null>",
  "zone": "<zone_name or null>",
  "start_time": "<ISO 8601 datetime or null>",
  "end_time": "<ISO 8601 datetime or null>",
  "limit": <integer, default 20>,
  "explanation": "<one sentence explaining what you understood>"
}}

Time interpretation rules:
- "last night" = yesterday 20:00 to today 06:00
- "today"      = today 00:00 to now
- "yesterday"  = yesterday 00:00 to yesterday 23:59
- "last hour"  = now minus 60 minutes
- "this morning" = today 06:00 to 12:00
- Always use the current datetime as reference.
- For detect_anomalies: use start_time/end_time for the observe window. Default to last 24h.

Current datetime: {current_datetime}
"""


class NLPEngine:
    """
    Stateful NLP engine that maintains conversation history
    and parses user queries into QueryContext.

    Args:
        llm:           The LLM backend to use for parsing.
        session_store: Optional persistent session store for conversation memory.
    """

    def __init__(self, llm: BaseLLM, session_store: SessionStore | None = None) -> None:
        self.llm = llm
        self._session_store = session_store
        self._history: list[LLMMessage] = []

    def reset(self) -> None:
        """Clear in-memory conversation history."""
        self._history = []

    async def process(self, user_query: str, session_id: str = "default") -> QueryContext:
        """
        Parse a natural language query into a QueryContext, optionally persisting
        conversation history via the session store.

        Args:
            user_query: Raw user input string.
            session_id: Session identifier for history persistence.

        Returns:
            QueryContext with extracted intent and parameters.
        """
        now = datetime.now()
        system_msg = LLMMessage(
            role="system",
            content=SYSTEM_PROMPT.format(current_datetime=now.isoformat()),
        )

        # Load persistent history if session_store is configured
        prefix_messages: list[LLMMessage] = []
        if self._session_store:
            history = await self._session_store.get_history(session_id)
            for msg in history[-10:]:
                prefix_messages.append(LLMMessage(role=msg["role"], content=msg["content"]))

        user_msg = LLMMessage(role="user", content=user_query)
        self._history.append(user_msg)

        messages = [system_msg] + prefix_messages + [user_msg]

        try:
            response = await self.llm.complete(messages, temperature=0.1, max_tokens=512)
            raw = response.content.strip()
            logger.debug("LLM raw response: %s", raw)

            parsed = self._extract_json(raw)
            ctx = self._build_context(parsed, user_query, now, session_id=session_id)

            self._history.append(LLMMessage(role="assistant", content=raw))

            # Persist to session store
            if self._session_store:
                await self._session_store.add_message(session_id, "user", user_query)
                await self._session_store.add_message(session_id, "assistant", raw)

            return ctx

        except Exception as exc:
            logger.error("NLP parsing failed: %s", exc)
            if self._history and self._history[-1].role == "user":
                self._history.pop()  # remove failed user turn
            return QueryContext(intent="unknown", raw_query=user_query, session_id=session_id)

    async def parse(self, user_query: str, session_id: str = "default") -> QueryContext:
        """
        Parse a natural language query into a QueryContext.

        Delegates to process() for full session support.
        """
        return await self.process(user_query, session_id=session_id)

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM output, even if wrapped in markdown."""
        # Strip ```json ... ``` blocks if present
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            text = match.group(1)
        return json.loads(text)

    def _build_context(
        self,
        data: dict,
        raw_query: str,
        now: datetime,
        session_id: str = "default",
    ) -> QueryContext:
        """Convert parsed JSON dict into a QueryContext."""
        event_id = data.get("event_id")
        return QueryContext(
            intent=data.get("intent", "unknown"),
            camera_name=data.get("camera_name"),
            event_id=event_id,
            label=data.get("label"),
            zone=data.get("zone"),
            start_time=self._parse_dt(data.get("start_time"), now),
            end_time=self._parse_dt(data.get("end_time"), now),
            limit=int(data.get("limit", 20)),
            raw_query=raw_query,
            session_id=session_id,
            extra={
                "explanation": data.get("explanation", ""),
                "event_id": event_id,
                "action": data.get("action"),
                "speed": data.get("speed", 50),
                "preset_id": data.get("preset_id"),
            },
        )

    @staticmethod
    def _parse_dt(value: str | None, now: datetime) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Could not parse datetime: %s", value)
            return None

    @property
    def history(self) -> list[LLMMessage]:
        return list(self._history)
