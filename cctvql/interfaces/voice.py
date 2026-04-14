"""
cctvQL Voice Interface
-----------------------
Speech-to-text (STT) via OpenAI Whisper API or local faster-whisper,
and text-to-speech (TTS) via system voices or ElevenLabs.

Usage:
    voice = VoiceInterface()
    text = await voice.transcribe(audio_bytes)   # STT
    audio = await voice.synthesize(text)          # TTS

Supports:
  - STT: OpenAI Whisper API (cloud) or faster-whisper (local)
  - TTS: OpenAI TTS API, system `say` (macOS), `espeak` (Linux), or pyttsx3
"""

from __future__ import annotations

import io
import platform
import subprocess
import tempfile
from pathlib import Path


class VoiceInterface:
    """Voice interface providing speech-to-text and text-to-speech capabilities.

    Parameters
    ----------
    stt_backend:
        STT engine to use. One of ``"whisper_api"``, ``"faster_whisper"``, or
        ``"none"`` (disables transcription).
    tts_backend:
        TTS engine to use. One of ``"openai_tts"``, ``"system"``, or ``"none"``
        (disables synthesis).
    whisper_api_key:
        API key for the OpenAI Whisper API. Falls back to the ``OPENAI_API_KEY``
        environment variable when *None*.
    openai_tts_api_key:
        API key for the OpenAI TTS API. Falls back to the ``OPENAI_API_KEY``
        environment variable when *None*.
    whisper_model:
        Whisper model identifier (cloud: ``"whisper-1"``; local: e.g.
        ``"base"``, ``"small"``, ``"medium"``, ``"large-v3"``).
    tts_voice:
        OpenAI TTS voice name (e.g. ``"alloy"``, ``"echo"``, ``"fable"``,
        ``"onyx"``, ``"nova"``, ``"shimmer"``).
    tts_model:
        OpenAI TTS model (``"tts-1"`` or ``"tts-1-hd"``).
    language:
        BCP-47 language code used as a hint for Whisper (e.g. ``"en"``).
    """

    def __init__(
        self,
        stt_backend: str = "whisper_api",  # "whisper_api" | "faster_whisper" | "none"
        tts_backend: str = "system",  # "openai_tts" | "system" | "none"
        whisper_api_key: str | None = None,
        openai_tts_api_key: str | None = None,
        whisper_model: str = "whisper-1",
        tts_voice: str = "alloy",  # OpenAI TTS voices
        tts_model: str = "tts-1",
        language: str = "en",
    ) -> None:
        import os

        self.stt_backend = stt_backend
        self.tts_backend = tts_backend
        self.whisper_api_key = whisper_api_key or os.environ.get("OPENAI_API_KEY")
        self.openai_tts_api_key = openai_tts_api_key or os.environ.get("OPENAI_API_KEY")
        self.whisper_model = whisper_model
        self.tts_voice = tts_voice
        self.tts_model = tts_model
        self.language = language

        # Cached faster-whisper model instance (loaded lazily)
        self._fw_model = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transcribe(self, audio_bytes: bytes, audio_format: str = "wav") -> str:
        """Convert audio bytes to text using the configured STT backend.

        Parameters
        ----------
        audio_bytes:
            Raw audio data.
        audio_format:
            MIME type or simple extension string (e.g. ``"wav"``, ``"audio/wav"``,
            ``"audio/webm"``). Used as the filename hint for the Whisper API.

        Returns
        -------
        str
            The transcribed text, or an empty string if STT is disabled.
        """
        if self.stt_backend == "whisper_api":
            return await self._transcribe_whisper_api(audio_bytes, audio_format)
        if self.stt_backend == "faster_whisper":
            return await self._transcribe_faster_whisper(audio_bytes)
        if self.stt_backend == "none":
            return ""
        raise ValueError(f"Unknown STT backend: {self.stt_backend!r}")

    async def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes using the configured TTS backend.

        Parameters
        ----------
        text:
            The input text to synthesize.

        Returns
        -------
        bytes
            Raw audio data (MP3 for OpenAI TTS; WAV/AIFF for system TTS).
        """
        if self.tts_backend == "openai_tts":
            return await self._synthesize_openai(text)
        if self.tts_backend == "system":
            return await self._synthesize_system(text)
        if self.tts_backend == "none":
            return b""
        raise ValueError(f"Unknown TTS backend: {self.tts_backend!r}")

    # ------------------------------------------------------------------
    # STT backends
    # ------------------------------------------------------------------

    async def _transcribe_whisper_api(self, audio_bytes: bytes, audio_format: str) -> str:
        """Transcribe via OpenAI Whisper API (/v1/audio/transcriptions).

        Sends a multipart form POST containing the audio file and model name.
        The ``language`` hint is included to improve accuracy and latency.
        """
        import httpx

        if not self.whisper_api_key:
            raise RuntimeError(
                "No API key for Whisper. Set OPENAI_API_KEY or pass whisper_api_key."
            )

        # Derive a sensible filename extension from the format hint
        ext = _normalise_audio_ext(audio_format)

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.whisper_api_key}"},
                files={"file": (f"audio.{ext}", io.BytesIO(audio_bytes), f"audio/{ext}")},
                data={"model": self.whisper_model, "language": self.language},
            )
            response.raise_for_status()
            payload = response.json()
            return payload.get("text", "").strip()

    async def _transcribe_faster_whisper(self, audio_bytes: bytes) -> str:
        """Transcribe using local faster-whisper (optional dependency).

        The model is loaded once and cached on the instance for subsequent
        calls. Requires ``pip install faster-whisper``.
        """
        try:
            from faster_whisper import WhisperModel  # type: ignore[import]
        except ImportError:
            raise RuntimeError("faster-whisper is not installed. Run: pip install faster-whisper")

        import asyncio

        # Lazy-load the model on first use
        if self._fw_model is None:
            self._fw_model = WhisperModel(self.whisper_model)

        # Write audio bytes to a temporary file because faster-whisper
        # expects a file path or file-like object.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        loop = asyncio.get_event_loop()
        fw_model = self._fw_model  # capture for closure — mypy can't narrow self attrs

        def _run() -> str:
            assert fw_model is not None
            segments, _info = fw_model.transcribe(tmp_path, language=self.language)
            return " ".join(seg.text for seg in segments).strip()

        try:
            text = await loop.run_in_executor(None, _run)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return text

    # ------------------------------------------------------------------
    # TTS backends
    # ------------------------------------------------------------------

    async def _synthesize_openai(self, text: str) -> bytes:
        """Synthesize via OpenAI TTS API (/v1/audio/speech).

        Returns MP3-encoded audio bytes.
        """
        import httpx

        if not self.openai_tts_api_key:
            raise RuntimeError(
                "No API key for OpenAI TTS. Set OPENAI_API_KEY or pass openai_tts_api_key."
            )

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {self.openai_tts_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.tts_model,
                    "input": text,
                    "voice": self.tts_voice,
                },
            )
            response.raise_for_status()
            return response.content

    async def _synthesize_system(self, text: str) -> bytes:
        """Synthesize using system TTS (macOS ``say`` / Linux ``espeak``).

        Returns the raw bytes of the generated audio file. On macOS the output
        is AIFF; on Linux it is WAV.
        """
        import asyncio

        os_name = platform.system()

        with tempfile.NamedTemporaryFile(
            suffix=".aiff" if os_name == "Darwin" else ".wav",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name

        loop = asyncio.get_event_loop()

        def _run() -> bytes:
            if os_name == "Darwin":
                subprocess.run(
                    ["say", "-o", tmp_path, text],
                    check=True,
                    capture_output=True,
                )
            elif os_name == "Linux":
                subprocess.run(
                    ["espeak", "-w", tmp_path, text],
                    check=True,
                    capture_output=True,
                )
            else:
                raise RuntimeError(
                    f"System TTS is not supported on {os_name}. "
                    "Use tts_backend='openai_tts' instead."
                )
            return Path(tmp_path).read_bytes()

        try:
            audio_bytes = await loop.run_in_executor(None, _run)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        return audio_bytes

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return ``True`` if at least STT is configured (backend != ``"none"``)."""
        return self.stt_backend != "none"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_audio_ext(audio_format: str) -> str:
    """Derive a simple file extension from a MIME type or extension string.

    Examples
    --------
    >>> _normalise_audio_ext("audio/wav")
    'wav'
    >>> _normalise_audio_ext("audio/webm;codecs=opus")
    'webm'
    >>> _normalise_audio_ext("mp3")
    'mp3'
    """
    # Strip MIME prefix and codec parameters
    fmt = audio_format.split(";")[0].strip()
    if "/" in fmt:
        fmt = fmt.split("/")[-1]
    # Normalise common aliases
    _aliases = {"x-wav": "wav", "mpeg": "mp3", "x-m4a": "m4a"}
    return _aliases.get(fmt, fmt) or "wav"
