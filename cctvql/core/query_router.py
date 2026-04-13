"""
cctvQL Query Router
--------------------
Routes a parsed QueryContext to the correct adapter method,
then formats the result into a human-readable response.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cctvql.adapters.base import BaseAdapter
from cctvql.core.schema import (
    QueryContext,
    QueryResult,
)
from cctvql.core.vision import VisionAnalyzer
from cctvql.llm.base import BaseLLM, LLMMessage

if TYPE_CHECKING:
    from cctvql.core.alerts import AlertEngine

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

    def __init__(
        self,
        adapter: BaseAdapter,
        llm: BaseLLM,
        alert_engine: AlertEngine | None = None,
    ) -> None:
        self.adapter = adapter
        self.llm = llm
        self.alert_engine = alert_engine
        self._vision = VisionAnalyzer(llm)
        self._intent_map = {
            "list_cameras": self._handle_list_cameras,
            "get_camera": self._handle_get_camera,
            "get_events": self._handle_get_events,
            "get_clips": self._handle_get_clips,
            "get_snapshot": self._handle_get_snapshot,
            "get_system_info": self._handle_get_system_info,
            "describe_event": self._handle_describe_event,
            "analyze_snapshot": self._handle_analyze_snapshot,
            "set_alert": self._handle_set_alert,
            "list_alerts": self._handle_list_alerts,
            "delete_alert": self._handle_delete_alert,
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
        event_id = ctx.event_id or ctx.extra.get("event_id") or ctx.camera_id
        if not event_id:
            return QueryResult(
                success=False,
                intent="describe_event",
                error="Please specify which event to describe (e.g. 'describe event abc123').",
            )
        event = await self.adapter.get_event(event_id)
        if not event:
            return QueryResult(
                success=True,
                intent="describe_event",
                summary=f"Event '{event_id}' not found.",
            )

        if self.llm.supports_vision:
            try:
                description = await self._vision.analyze_event(event, self.adapter)
                return QueryResult(
                    success=True,
                    intent="describe_event",
                    data=event,
                    summary=description,
                )
            except Exception as exc:
                logger.warning("Vision analysis failed, falling back to text: %s", exc)

        # Fallback: text-only summary
        snap = f"Snapshot: {event.snapshot_url}" if event.snapshot_url else "No snapshot available."
        summary = f"**Event {event_id}** on **{event.camera_name}**\n{event.to_summary()}\n" + snap
        return QueryResult(success=True, intent="describe_event", data=event, summary=summary)

    async def _handle_analyze_snapshot(self, ctx: QueryContext) -> QueryResult:
        """Fetch the live snapshot for a camera and describe it with vision AI."""
        if not ctx.camera_name and not ctx.camera_id:
            return QueryResult(
                success=False,
                intent="analyze_snapshot",
                error="Please specify a camera name to analyze.",
            )

        snapshot_url = await self.adapter.get_snapshot_url(
            camera_id=ctx.camera_id,
            camera_name=ctx.camera_name,
        )
        if not snapshot_url:
            return QueryResult(
                success=True,
                intent="analyze_snapshot",
                summary=f"Could not retrieve a snapshot for '{ctx.camera_name or ctx.camera_id}'.",
            )

        if self.llm.supports_vision:
            try:
                description = await self._vision.describe_snapshot(snapshot_url)
                return QueryResult(
                    success=True,
                    intent="analyze_snapshot",
                    data=snapshot_url,
                    summary=f"**{ctx.camera_name or ctx.camera_id} — Live View**\n\n{description}",
                )
            except Exception as exc:
                logger.warning("Vision analysis failed for snapshot: %s", exc)

        # Fallback: just return the URL
        summary = (
            f"Live snapshot from **{ctx.camera_name or ctx.camera_id}**: {snapshot_url}\n"
            f"(Vision analysis requires a vision-capable LLM backend.)"
        )
        return QueryResult(
            success=True, intent="analyze_snapshot", data=snapshot_url, summary=summary
        )

    async def _handle_set_alert(self, ctx: QueryContext) -> QueryResult:
        """Create an alert rule from NLP-extracted context."""
        if self.alert_engine is None:
            return QueryResult(
                success=False,
                intent="set_alert",
                error=(
                    "Alert engine is not available. "
                    "Use the POST /alerts REST endpoint to create alert rules."
                ),
            )

        from cctvql.core.alerts import make_rule_from_context

        name = ctx.extra.get("alert_name") or (
            f"Alert on {ctx.camera_name or 'all cameras'}"
            + (f" — {ctx.label}" if ctx.label else "")
        )
        rule = make_rule_from_context(
            name=name,
            description=ctx.raw_query,
            camera_name=ctx.camera_name,
            label=ctx.label,
            zone=ctx.zone,
            time_start=ctx.extra.get("time_start"),
            time_end=ctx.extra.get("time_end"),
            webhook_url=ctx.extra.get("webhook_url"),
        )
        self.alert_engine.add_rule(rule)

        conditions: list[str] = []
        if rule.camera_name:
            conditions.append(f"camera: {rule.camera_name}")
        if rule.label:
            conditions.append(f"label: {rule.label}")
        if rule.zone:
            conditions.append(f"zone: {rule.zone}")
        if rule.time_start or rule.time_end:
            conditions.append(f"between {rule.time_start or 'any'} and {rule.time_end or 'any'}")
        condition_str = ", ".join(conditions) if conditions else "any event"

        summary = (
            f"Alert rule **'{rule.name}'** created (ID: `{rule.id}`).\n"
            f"Triggers on: {condition_str}.\n"
            + (f"Webhook: {rule.webhook_url}" if rule.webhook_url else "No webhook configured.")
        )
        return QueryResult(success=True, intent="set_alert", data=rule, summary=summary)

    async def _handle_list_alerts(self, ctx: QueryContext) -> QueryResult:
        """List all current alert rules."""
        if self.alert_engine is None:
            return QueryResult(
                success=False,
                intent="list_alerts",
                error=(
                    "Alert engine is not available. "
                    "Use the GET /alerts REST endpoint to list alert rules."
                ),
            )

        rules = self.alert_engine.get_rules()
        if not rules:
            return QueryResult(
                success=True,
                intent="list_alerts",
                summary="No alert rules configured. Use 'notify me when...' to create one.",
            )

        lines = []
        for r in rules:
            status = "enabled" if r.enabled else "disabled"
            triggered = f", triggered {r.trigger_count}x" if r.trigger_count else ""
            lines.append(f"• **{r.name}** [{status}{triggered}] — `{r.id}`")

        summary = f"**{len(rules)} alert rule(s):**\n" + "\n".join(lines)
        return QueryResult(success=True, intent="list_alerts", data=rules, summary=summary)

    async def _handle_delete_alert(self, ctx: QueryContext) -> QueryResult:
        """Delete an alert rule by ID or name."""
        if self.alert_engine is None:
            return QueryResult(
                success=False,
                intent="delete_alert",
                error=(
                    "Alert engine is not available. "
                    "Use the DELETE /alerts/{id} REST endpoint to remove alert rules."
                ),
            )

        # Try to find by explicit ID in extra, or match by name against raw_query.
        rule_id: str | None = ctx.extra.get("alert_id") or ctx.extra.get("event_id")
        rule_name: str | None = ctx.extra.get("alert_name")

        if not rule_id and rule_name:
            # Search by name (case-insensitive substring match).
            for r in self.alert_engine.get_rules():
                if rule_name.lower() in r.name.lower():
                    rule_id = r.id
                    break

        if not rule_id:
            return QueryResult(
                success=False,
                intent="delete_alert",
                error=(
                    "Please specify which alert to delete, e.g. "
                    "'delete alert <rule-id>' or 'remove the front door alert'."
                ),
            )

        deleted = self.alert_engine.remove_rule(rule_id)
        if deleted:
            return QueryResult(
                success=True,
                intent="delete_alert",
                summary=f"Alert rule `{rule_id}` has been deleted.",
            )
        return QueryResult(
            success=True,
            intent="delete_alert",
            summary=f"No alert rule found with ID `{rule_id}`.",
        )

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
