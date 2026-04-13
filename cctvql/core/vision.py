"""
cctvQL Vision Analysis
-----------------------
Sends camera snapshots to multimodal LLMs (GPT-4o, Claude claude-sonnet-4-6,
Ollama with llava/bakllava) for rich natural-language descriptions.

Supports:
  - Describe what is happening in a snapshot
  - Compare two snapshots for changes
  - Identify specific objects/people in a frame
  - Generate detailed incident reports from event clips
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

import httpx

from cctvql.llm.base import BaseLLM, LLMMessage

if TYPE_CHECKING:
    from cctvql.adapters.base import BaseAdapter
    from cctvql.core.schema import Event

logger = logging.getLogger(__name__)

DEFAULT_DESCRIBE_PROMPT = (
    "Describe what you see in this security camera image in detail. "
    "Include the scene, any people or objects visible, lighting conditions, "
    "and anything that might be relevant for security purposes."
)

DEFAULT_COMPARE_PROMPT = "What changed between these two security camera images?"


class VisionAnalyzer:
    """
    Sends camera snapshots to multimodal LLMs for rich natural-language analysis.

    Works with any LLM backend that implements ``supports_vision`` and
    ``complete_with_image``. Falls back gracefully to URL-only text descriptions
    when image fetching fails or the backend does not support vision.

    Args:
        llm: Any BaseLLM backend. Vision features are only active when
             ``llm.supports_vision`` is True.
    """

    def __init__(self, llm: BaseLLM) -> None:
        self.llm = llm
        self._http = httpx.AsyncClient(timeout=30.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def describe_snapshot(
        self,
        image_url: str,
        prompt: str = DEFAULT_DESCRIBE_PROMPT,
    ) -> str:
        """
        Fetch an image by URL and ask the LLM to describe it.

        Args:
            image_url: Publicly reachable URL (or local network URL) of the image.
            prompt:    Instruction sent to the LLM alongside the image.

        Returns:
            Natural-language description string.
        """
        if not self.llm.supports_vision:
            return (
                f"Vision analysis is not available with the current LLM backend "
                f"({self.llm.name}). Snapshot URL: {image_url}"
            )

        image_bytes, content_type = await self._fetch_image(image_url)
        if image_bytes is None:
            # Graceful fallback — describe by URL only via text LLM
            logger.warning("Image fetch failed for %s; falling back to text.", image_url)
            fallback_msg = LLMMessage(
                role="user",
                content=(
                    f"{prompt}\n\n"
                    f"Note: The image could not be fetched from {image_url}. "
                    "Please provide a general description of what a security camera at "
                    "this location might show."
                ),
            )
            response = await self.llm.complete([fallback_msg], temperature=0.3, max_tokens=1024)
            return response.content

        image_b64 = self._image_to_base64(image_bytes, content_type)
        messages = [LLMMessage(role="user", content=prompt)]

        response = await self.llm.complete_with_image(
            messages,
            image_b64=image_b64,
            image_media_type=content_type,
            temperature=0.3,
            max_tokens=1024,
        )
        return response.content

    async def analyze_event(self, event: Event, adapter: BaseAdapter) -> str:
        """
        Describe a CCTV event in the context of its metadata.

        Fetches the event's snapshot (if available) and generates a rich
        incident description combining visual analysis with structured metadata
        (camera name, timestamp, detected objects, zones).

        Args:
            event:   The Event object to analyse.
            adapter: Active adapter (used to resolve snapshot URLs if missing).

        Returns:
            Natural-language incident description.
        """
        # Build context string from event metadata
        object_str = ", ".join(str(o) for o in event.objects) if event.objects else "none detected"
        zone_str = ", ".join(event.zones) if event.zones else "unspecified"
        time_str = event.start_time.strftime("%Y-%m-%d %H:%M:%S")
        duration = (
            f"{event.duration_seconds:.0f}s" if event.duration_seconds else "unknown duration"
        )

        event_context = (
            f"Camera: {event.camera_name}\n"
            f"Time: {time_str}\n"
            f"Event type: {event.event_type.value}\n"
            f"Duration: {duration}\n"
            f"Detected objects: {object_str}\n"
            f"Zones: {zone_str}\n"
        )

        prompt = (
            "You are analysing a security camera event. Here is the structured metadata:\n\n"
            f"{event_context}\n"
            "Please provide a detailed natural-language incident report based on the image "
            "and the metadata above. Describe what is happening, any potential security "
            "concerns, and relevant details."
        )

        # Resolve snapshot URL — prefer event's own, then ask adapter
        snapshot_url = event.snapshot_url or event.thumbnail_url
        if not snapshot_url:
            try:
                snapshot_url = await adapter.get_snapshot_url(
                    camera_id=event.camera_id,
                    camera_name=event.camera_name,
                )
            except Exception as exc:
                logger.warning("Could not fetch snapshot URL from adapter: %s", exc)

        if snapshot_url:
            return await self.describe_snapshot(snapshot_url, prompt=prompt)

        # No image available — text-only summary
        if not self.llm.supports_vision:
            return (
                f"Event on {event.camera_name} at {time_str}: "
                f"{event.event_type.value} — {object_str} in {zone_str}. "
                "No snapshot available for visual analysis."
            )

        # Has vision but no URL — ask LLM to summarise from metadata alone
        fallback_msg = LLMMessage(role="user", content=prompt + "\n\nNo image is available.")
        response = await self.llm.complete([fallback_msg], temperature=0.3, max_tokens=1024)
        return response.content

    async def compare_snapshots(
        self,
        url1: str,
        url2: str,
        prompt: str = DEFAULT_COMPARE_PROMPT,
    ) -> str:
        """
        Fetch two images and ask the LLM to identify changes between them.

        If the LLM backend does not natively support multi-image messages,
        the images are sent in two sequential requests and the results are
        combined into a comparative summary.

        Args:
            url1:   URL of the earlier/reference image.
            url2:   URL of the later/comparison image.
            prompt: Instruction for the comparison.

        Returns:
            Natural-language change description.
        """
        if not self.llm.supports_vision:
            return (
                f"Vision analysis is not available with the current LLM backend "
                f"({self.llm.name}). Cannot compare {url1} and {url2}."
            )

        bytes1, ct1 = await self._fetch_image(url1)
        bytes2, ct2 = await self._fetch_image(url2)

        if bytes1 is None and bytes2 is None:
            return f"Could not fetch either image for comparison ({url1}, {url2})."

        if bytes1 is None:
            return await self.describe_snapshot(url2, prompt=f"This is image 2 only. {prompt}")

        if bytes2 is None:
            return await self.describe_snapshot(url1, prompt=f"This is image 1 only. {prompt}")

        # Describe each frame individually then compare via LLM
        b64_1 = self._image_to_base64(bytes1, ct1)
        b64_2 = self._image_to_base64(bytes2, ct2)

        desc1_resp = await self.llm.complete_with_image(
            [LLMMessage(role="user", content="Describe this security camera image in detail.")],
            image_b64=b64_1,
            image_media_type=ct1,
            temperature=0.2,
            max_tokens=512,
        )
        desc2_resp = await self.llm.complete_with_image(
            [LLMMessage(role="user", content="Describe this security camera image in detail.")],
            image_b64=b64_2,
            image_media_type=ct2,
            temperature=0.2,
            max_tokens=512,
        )

        comparison_prompt = (
            f"Image 1 description:\n{desc1_resp.content}\n\n"
            f"Image 2 description:\n{desc2_resp.content}\n\n"
            f"{prompt} Summarise the key differences."
        )
        comparison_resp = await self.llm.complete(
            [LLMMessage(role="user", content=comparison_prompt)],
            temperature=0.3,
            max_tokens=512,
        )
        return comparison_resp.content

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _image_to_base64(self, image_bytes: bytes, content_type: str = "image/jpeg") -> str:
        """Base64-encode image bytes for inclusion in LLM API payloads."""
        return base64.b64encode(image_bytes).decode("utf-8")

    async def _fetch_image(self, url: str) -> tuple[bytes | None, str]:
        """
        Download image bytes from a URL.

        Returns:
            (bytes, content_type) on success, (None, "image/jpeg") on failure.
        """
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            return response.content, content_type
        except Exception as exc:
            logger.warning("Failed to fetch image from %s: %s", url, exc)
            return None, "image/jpeg"
