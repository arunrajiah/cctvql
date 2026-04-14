"""
cctvQL Multi-System Query
--------------------------
Fan-out queries across all registered adapters simultaneously,
then merge and deduplicate results.

Usage:
    router = MultiSystemRouter(llm)
    result = await router.route(ctx)   # queries ALL registered adapters
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from cctvql.adapters.base import AdapterRegistry
from cctvql.core.schema import (
    QueryContext,
    QueryResult,
)
from cctvql.llm.base import BaseLLM

logger = logging.getLogger(__name__)

# Intents that operate on a single system snapshot — fan-out doesn't add value.
_SINGLE_SYSTEM_INTENTS = {"get_snapshot", "get_system_info", "describe_event"}


class MultiSystemRouter:
    """
    Routes a QueryContext to ALL registered adapters concurrently,
    then merges and deduplicates the results into a single response.

    For intents that don't aggregate well (get_snapshot, get_system_info,
    describe_event) the active adapter is queried only, with a note
    directing the user to query each system individually for full coverage.

    Args:
        llm: LLM backend — forwarded to per-adapter QueryRouters for
             response formatting on fallback paths.
    """

    def __init__(self, llm: BaseLLM) -> None:
        self.llm = llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route(self, ctx: QueryContext) -> str:
        """
        Execute ctx against all registered adapters concurrently and return
        a merged, human-readable response.
        """
        adapters = AdapterRegistry.available()

        if not adapters:
            return "No adapters are registered. Please configure at least one CCTV system."

        # For non-aggregatable intents, fall back to the active adapter only.
        if ctx.intent in _SINGLE_SYSTEM_INTENTS:
            from cctvql.core.query_router import QueryRouter  # local import avoids circular dep

            active = AdapterRegistry.get_active()
            router = QueryRouter(active, self.llm)
            response = await router.route(ctx)
            return f"{response}\n\n_Note: for multi-system info, query each system individually._"

        # Fan-out to every registered adapter.
        tasks = [self._query_adapter(name, ctx) for name in adapters]
        results: list[QueryResult] = await asyncio.gather(*tasks)

        return self._merge_results(ctx, results, adapters)

    # ------------------------------------------------------------------
    # Per-adapter query
    # ------------------------------------------------------------------

    async def _query_adapter(self, adapter_name: str, ctx: QueryContext) -> QueryResult:
        """
        Run a single adapter query, catching all exceptions so one failing
        system never blocks the rest.
        """
        try:
            adapter = AdapterRegistry._adapters.get(adapter_name)
            if adapter is None:
                return QueryResult(
                    success=False,
                    intent=ctx.intent,
                    error=f"Adapter '{adapter_name}' not found in registry.",
                )

            data: Any = None
            if ctx.intent == "list_cameras":
                data = await adapter.list_cameras()
            elif ctx.intent == "get_camera":
                data = await adapter.get_camera(
                    camera_id=ctx.camera_id,
                    camera_name=ctx.camera_name,
                )
            elif ctx.intent == "get_events":
                data = await adapter.get_events(
                    camera_id=ctx.camera_id,
                    camera_name=ctx.camera_name,
                    label=ctx.label,
                    zone=ctx.zone,
                    start_time=ctx.start_time,
                    end_time=ctx.end_time,
                    limit=ctx.limit,
                )
            elif ctx.intent == "get_clips":
                data = await adapter.get_clips(
                    camera_id=ctx.camera_id,
                    camera_name=ctx.camera_name,
                    start_time=ctx.start_time,
                    end_time=ctx.end_time,
                    limit=ctx.limit,
                )
            else:
                # Unknown intent — return empty success; caller will handle.
                return QueryResult(success=True, intent=ctx.intent, data=None)

            return QueryResult(
                success=True,
                intent=ctx.intent,
                data=data,
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Multi-query: adapter '%s' failed for intent '%s': %s",
                adapter_name,
                ctx.intent,
                exc,
            )
            return QueryResult(
                success=False,
                intent=ctx.intent,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Merge helpers
    # ------------------------------------------------------------------

    def _merge_results(
        self,
        ctx: QueryContext,
        results: list[QueryResult],
        adapter_names: list[str],
    ) -> str:
        """Dispatch to the appropriate merge strategy based on intent."""
        errors = [
            f"  • **{name}**: {r.error}" for name, r in zip(adapter_names, results) if not r.success
        ]
        successes = [
            (name, r) for name, r in zip(adapter_names, results) if r.success and r.data is not None
        ]

        error_section = ""
        if errors:
            error_section = "\n\n**Systems with errors:**\n" + "\n".join(errors)

        if not successes:
            return f"No data returned from any system.{error_section}"

        if ctx.intent in ("get_events",):
            body = self._merge_events(successes)
        elif ctx.intent in ("list_cameras", "get_camera"):
            body = self._merge_cameras(successes)
        elif ctx.intent == "get_clips":
            body = self._merge_clips(successes)
        else:
            # Generic fallback: list results per system.
            lines = []
            for name, r in successes:
                lines.append(f"**{name}:** {r.data}")
            body = "\n".join(lines)

        return f"{body}{error_section}"

    def _merge_events(self, successes: list[tuple[str, QueryResult]]) -> str:
        """
        Combine events from multiple systems, sorted by start_time (newest first),
        deduplicated by (camera_name, start_time) composite key.
        """
        from cctvql.core.schema import Event  # local import — avoid circular

        seen: set[tuple[str, datetime]] = set()
        merged: list[tuple[str, Event]] = []  # (source_system, event)

        for system_name, result in successes:
            events: list[Event] = result.data or []
            for event in events:
                dedup_key = (event.camera_name, event.start_time)
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    merged.append((system_name, event))

        if not merged:
            return "No events found across any connected system."

        # Sort newest-first.
        merged.sort(key=lambda pair: pair[1].start_time, reverse=True)

        lines = [f"Found **{len(merged)}** event(s) across all systems:\n"]
        for system_name, event in merged:
            lines.append(f"• [{system_name}] {event.to_summary()}")

        return "\n".join(lines)

    def _merge_cameras(self, successes: list[tuple[str, QueryResult]]) -> str:
        """
        Combine camera lists from multiple systems, annotating each camera
        with its source system name.
        """
        from cctvql.core.schema import Camera  # local import — avoid circular

        lines: list[str] = []
        total = 0

        for system_name, result in successes:
            cameras: list[Camera] = (
                result.data
                if isinstance(result.data, list)
                else ([result.data] if result.data else [])
            )
            for cam in cameras:
                status = cam.status.value if hasattr(cam.status, "value") else str(cam.status)
                loc = f" ({cam.location})" if cam.location else ""
                lines.append(f"• **{cam.name}** [{system_name}] — {status}{loc}")
                total += 1

        if not lines:
            return "No cameras found across any connected system."

        header = f"Found **{total}** camera(s) across all systems:\n"
        return header + "\n".join(lines)

    def _merge_clips(self, successes: list[tuple[str, QueryResult]]) -> str:
        """
        Combine clips from multiple systems, sorted by start_time (newest first).
        """
        from cctvql.core.schema import Clip  # local import — avoid circular

        merged: list[tuple[str, Clip]] = []
        for system_name, result in successes:
            clips: list[Clip] = result.data or []
            for clip in clips:
                merged.append((system_name, clip))

        if not merged:
            return "No clips found across any connected system."

        merged.sort(key=lambda pair: pair[1].start_time, reverse=True)

        lines = [f"Found **{len(merged)}** clip(s) across all systems:\n"]
        for system_name, clip in merged:
            dl = f" [Download]({clip.download_url})" if clip.download_url else ""
            lines.append(
                f"• [{system_name}] {clip.camera_name} — "
                f"{clip.start_time.strftime('%Y-%m-%d %H:%M')} "
                f"({int(clip.duration_seconds)}s){dl}"
            )

        return "\n".join(lines)
