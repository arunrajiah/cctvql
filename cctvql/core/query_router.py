"""
cctvQL Query Router
--------------------
Routes a parsed QueryContext to the correct adapter method,
then formats the result into a human-readable response.
"""

from __future__ import annotations

import logging

from cctvql.adapters.base import BaseAdapter
from cctvql.core.schema import (
    QueryContext,
    QueryResult,
)
from cctvql.llm.base import BaseLLM, LLMMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response formatter prompt
# ---------------------------------------------------------------------------

FORMAT_PROMPT = """You are cctvQL. Format the following CCTV data into a
concise, natural conversational response for the user.
Be brief and direct. Use bullet points only for lists of 3+.
Never mention raw JSON or internal field names.
Data: {data}
User's original question: {query}"""


class QueryRouter:
    """
    Routes QueryContext → adapter call → formatted response.

    Args:
        adapter: The active CCTV system adapter.
        llm:     LLM backend used to format responses.
    """

    def __init__(self, adapter: BaseAdapter, llm: BaseLLM) -> None:
        self.adapter = adapter
        self.llm = llm
        self._intent_map = {
            "list_cameras": self._handle_list_cameras,
            "get_camera": self._handle_get_camera,
            "get_events": self._handle_get_events,
            "get_clips": self._handle_get_clips,
            "get_snapshot": self._handle_get_snapshot,
            "get_system_info": self._handle_get_system_info,
            "describe_event": self._handle_describe_event,
        }

    async def route(self, ctx: QueryContext) -> str:
        """Execute the intent from ctx and return a formatted string response."""
        handler = self._intent_map.get(ctx.intent)

        if not handler:
            return (
                "I didn't understand that query. You can ask me things like:\n"
                '- "Show me all cameras"\n'
                '- "Any motion on the driveway camera in the last hour?"\n'
                '- "Did a person appear on Camera 1 last night?"'
            )

        result: QueryResult = await handler(ctx)

        if not result.success:
            return f"Sorry, I encountered an error: {result.error}"

        if result.summary:
            return result.summary

        return await self._format_with_llm(result, ctx.raw_query)

    # ------------------------------------------------------------------
    # Intent handlers
    # ------------------------------------------------------------------

    async def _handle_list_cameras(self, ctx: QueryContext) -> QueryResult:
        cameras = await self.adapter.list_cameras()
        if not cameras:
            return QueryResult(
                success=True,
                intent="list_cameras",
                summary="No cameras found in the system.",
            )
        lines = [
            f"• **{c.name}** — {c.status.value}" + (f" ({c.location})" if c.location else "")
            for c in cameras
        ]
        summary = f"Found {len(cameras)} camera(s):\n" + "\n".join(lines)
        return QueryResult(success=True, intent="list_cameras", data=cameras, summary=summary)

    async def _handle_get_camera(self, ctx: QueryContext) -> QueryResult:
        camera = await self.adapter.get_camera(
            camera_id=ctx.camera_id,
            camera_name=ctx.camera_name,
        )
        if not camera:
            return QueryResult(
                success=True,
                intent="get_camera",
                summary=f"Camera '{ctx.camera_name or ctx.camera_id}' not found.",
            )
        summary = (
            f"**{camera.name}**\n"
            f"Status: {camera.status.value}\n"
            + (f"Location: {camera.location}\n" if camera.location else "")
            + (f"Zones: {', '.join(camera.zones)}\n" if camera.zones else "")
        )
        return QueryResult(success=True, intent="get_camera", data=camera, summary=summary)

    async def _handle_get_events(self, ctx: QueryContext) -> QueryResult:
        events = await self.adapter.get_events(
            camera_id=ctx.camera_id,
            camera_name=ctx.camera_name,
            label=ctx.label,
            zone=ctx.zone,
            start_time=ctx.start_time,
            end_time=ctx.end_time,
            limit=ctx.limit,
        )
        if not events:
            return QueryResult(
                success=True,
                intent="get_events",
                summary="No events found matching your query.",
            )
        lines = [f"• {e.to_summary()}" for e in events[: ctx.limit]]
        summary = f"Found {len(events)} event(s):\n" + "\n".join(lines)
        return QueryResult(success=True, intent="get_events", data=events, summary=summary)

    async def _handle_get_clips(self, ctx: QueryContext) -> QueryResult:
        clips = await self.adapter.get_clips(
            camera_id=ctx.camera_id,
            camera_name=ctx.camera_name,
            start_time=ctx.start_time,
            end_time=ctx.end_time,
            limit=ctx.limit,
        )
        if not clips:
            return QueryResult(
                success=True,
                intent="get_clips",
                summary="No clips found for your query.",
            )
        lines = [
            f"• {c.camera_name} — {c.start_time.strftime('%Y-%m-%d %H:%M')} "
            f"({int(c.duration_seconds)}s)"
            + (f" [Download]({c.download_url})" if c.download_url else "")
            for c in clips
        ]
        summary = f"Found {len(clips)} clip(s):\n" + "\n".join(lines)
        return QueryResult(success=True, intent="get_clips", data=clips, summary=summary)

    async def _handle_get_snapshot(self, ctx: QueryContext) -> QueryResult:
        url = await self.adapter.get_snapshot_url(
            camera_id=ctx.camera_id,
            camera_name=ctx.camera_name,
        )
        if not url:
            return QueryResult(
                success=True,
                intent="get_snapshot",
                summary=f"Could not get snapshot for '{ctx.camera_name}'.",
            )
        summary = f"Live snapshot from **{ctx.camera_name}**: {url}"
        return QueryResult(success=True, intent="get_snapshot", data=url, summary=summary)

    async def _handle_get_system_info(self, ctx: QueryContext) -> QueryResult:
        info = await self.adapter.get_system_info()
        if not info:
            return QueryResult(
                success=False,
                intent="get_system_info",
                error="Could not retrieve system info.",
            )
        used_gb = round(info.storage_used_bytes / 1e9, 1) if info.storage_used_bytes else "?"
        total_gb = round(info.storage_total_bytes / 1e9, 1) if info.storage_total_bytes else "?"
        summary = (
            f"**{info.system_name}** v{info.version or 'unknown'}\n"
            f"Cameras: {info.camera_count}\n"
            f"Storage: {used_gb} GB / {total_gb} GB used\n"
        )
        if info.uptime_seconds:
            hours = info.uptime_seconds // 3600
            summary += f"Uptime: {hours}h\n"
        return QueryResult(success=True, intent="get_system_info", data=info, summary=summary)

    async def _handle_describe_event(self, ctx: QueryContext) -> QueryResult:
        event_id = ctx.extra.get("event_id") or ctx.camera_id
        if not event_id:
            return QueryResult(
                success=False,
                intent="describe_event",
                error="Please specify which event to describe.",
            )
        event = await self.adapter.get_event(event_id)
        if not event:
            return QueryResult(
                success=True,
                intent="describe_event",
                summary=f"Event '{event_id}' not found.",
            )
        return QueryResult(success=True, intent="describe_event", data=event)

    # ------------------------------------------------------------------
    # LLM formatter (fallback for complex data)
    # ------------------------------------------------------------------

    async def _format_with_llm(self, result: QueryResult, query: str) -> str:
        data_str = str(result.data)[:2000]
        prompt = FORMAT_PROMPT.format(data=data_str, query=query)
        response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)],
            temperature=0.3,
            max_tokens=512,
        )
        return response.content
