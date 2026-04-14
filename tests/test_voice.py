"""
Tests for VoiceInterface (cctvql.interfaces.voice).
"""

from __future__ import annotations

import platform
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cctvql.interfaces.voice import VoiceInterface, _normalise_audio_ext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def whisper_voice():
    """VoiceInterface configured for Whisper API STT."""
    return VoiceInterface(
        stt_backend="whisper_api",
        tts_backend="system",
        whisper_api_key="test-api-key",
        openai_tts_api_key="test-tts-key",
    )


@pytest.fixture
def openai_tts_voice():
    """VoiceInterface configured for OpenAI TTS."""
    return VoiceInterface(
        stt_backend="whisper_api",
        tts_backend="openai_tts",
        whisper_api_key="test-api-key",
        openai_tts_api_key="test-tts-key",
    )


# ---------------------------------------------------------------------------
# available property
# ---------------------------------------------------------------------------


def test_available_property_with_stt():
    voice = VoiceInterface(stt_backend="whisper_api")
    assert voice.available is True


def test_available_property_with_faster_whisper():
    voice = VoiceInterface(stt_backend="faster_whisper")
    assert voice.available is True


def test_available_property_without_stt():
    voice = VoiceInterface(stt_backend="none")
    assert voice.available is False


# ---------------------------------------------------------------------------
# transcribe — whisper_api
# ---------------------------------------------------------------------------


async def test_transcribe_whisper_api_success(whisper_voice):
    """POST to Whisper API returns transcribed text."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"text": "show me cameras"})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await whisper_voice.transcribe(b"fake_audio_bytes", audio_format="wav")

    assert result == "show me cameras"
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "transcriptions" in call_args[0][0]
    assert "Bearer test-api-key" in call_args[1]["headers"]["Authorization"]


async def test_transcribe_whisper_api_strips_whitespace(whisper_voice):
    """Transcribed text is stripped of leading/trailing whitespace."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"text": "  list all events  "})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await whisper_voice.transcribe(b"audio", audio_format="wav")

    assert result == "list all events"


async def test_transcribe_raises_on_missing_key():
    """Missing API key raises RuntimeError before any HTTP call."""
    voice = VoiceInterface(
        stt_backend="whisper_api",
        whisper_api_key=None,
    )
    # Ensure no env var is set
    with patch.dict("os.environ", {}, clear=True):
        voice.whisper_api_key = None
        with pytest.raises(RuntimeError, match="No API key for Whisper"):
            await voice.transcribe(b"audio")


async def test_transcribe_none_backend_returns_empty():
    """stt_backend='none' returns empty string immediately."""
    voice = VoiceInterface(stt_backend="none")
    result = await voice.transcribe(b"audio")
    assert result == ""


async def test_transcribe_unknown_backend_raises():
    voice = VoiceInterface(stt_backend="unsupported_engine")
    voice.whisper_api_key = "key"
    with pytest.raises(ValueError, match="Unknown STT backend"):
        await voice.transcribe(b"audio")


# ---------------------------------------------------------------------------
# synthesize — openai_tts
# ---------------------------------------------------------------------------


async def test_synthesize_openai_success(openai_tts_voice):
    """POST to OpenAI TTS returns MP3 bytes."""
    fake_mp3 = b"ID3\x03\x00\x00\x00\x00\x00fake_mp3_data"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = fake_mp3

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await openai_tts_voice.synthesize("Hello, this is a test")

    assert result == fake_mp3
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "speech" in call_args[0][0]
    payload = call_args[1]["json"]
    assert payload["input"] == "Hello, this is a test"
    assert payload["model"] == openai_tts_voice.tts_model
    assert payload["voice"] == openai_tts_voice.tts_voice


async def test_synthesize_openai_raises_on_missing_key():
    voice = VoiceInterface(
        stt_backend="none",
        tts_backend="openai_tts",
        openai_tts_api_key=None,
    )
    with patch.dict("os.environ", {}, clear=True):
        voice.openai_tts_api_key = None
        with pytest.raises(RuntimeError, match="No API key for OpenAI TTS"):
            await voice.synthesize("test")


async def test_synthesize_none_backend_returns_empty_bytes():
    voice = VoiceInterface(stt_backend="none", tts_backend="none")
    result = await voice.synthesize("hello")
    assert result == b""


async def test_synthesize_unknown_backend_raises():
    voice = VoiceInterface(stt_backend="none", tts_backend="bad_backend")
    with pytest.raises(ValueError, match="Unknown TTS backend"):
        await voice.synthesize("hello")


# ---------------------------------------------------------------------------
# synthesize — system TTS (macOS `say`)
# ---------------------------------------------------------------------------


async def test_synthesize_system_macos():
    """On macOS, system TTS calls subprocess `say` command."""
    if platform.system() != "Darwin":
        pytest.skip("macOS-only test")

    voice = VoiceInterface(stt_backend="none", tts_backend="system")
    fake_audio = b"fake_aiff_bytes"

    with (
        patch("subprocess.run") as mock_run,
        patch("pathlib.Path.read_bytes", return_value=fake_audio),
        patch("pathlib.Path.unlink"),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = await voice.synthesize("Hello world")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "say"
    assert "-o" in cmd
    assert "Hello world" in cmd
    assert result == fake_audio


async def test_synthesize_system_macos_any_platform():
    """
    Patch platform.system to 'Darwin' so the `say` branch is exercised
    regardless of the real OS the test runner is on.
    """
    voice = VoiceInterface(stt_backend="none", tts_backend="system")
    fake_audio = b"aiff_content"

    with (
        patch("cctvql.interfaces.voice.platform.system", return_value="Darwin"),
        patch("subprocess.run") as mock_run,
        patch("pathlib.Path.read_bytes", return_value=fake_audio),
        patch("pathlib.Path.unlink"),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = await voice.synthesize("Test speech")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "say"
    assert result == fake_audio


async def test_synthesize_system_linux():
    """On Linux, system TTS calls `espeak`."""
    voice = VoiceInterface(stt_backend="none", tts_backend="system")
    fake_audio = b"wav_content"

    with (
        patch("cctvql.interfaces.voice.platform.system", return_value="Linux"),
        patch("subprocess.run") as mock_run,
        patch("pathlib.Path.read_bytes", return_value=fake_audio),
        patch("pathlib.Path.unlink"),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = await voice.synthesize("Test speech")

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "espeak"
    assert result == fake_audio


async def test_synthesize_system_unsupported_os():
    """Unsupported OS raises RuntimeError."""
    voice = VoiceInterface(stt_backend="none", tts_backend="system")

    with patch("cctvql.interfaces.voice.platform.system", return_value="Windows"):
        with pytest.raises(RuntimeError, match="System TTS is not supported"):
            await voice.synthesize("test")


# ---------------------------------------------------------------------------
# _normalise_audio_ext helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_fmt,expected",
    [
        ("wav", "wav"),
        ("audio/wav", "wav"),
        ("audio/webm;codecs=opus", "webm"),
        ("audio/webm", "webm"),
        ("mp3", "mp3"),
        ("audio/mpeg", "mp3"),
        ("audio/x-wav", "wav"),
        ("audio/x-m4a", "m4a"),
        ("audio/ogg", "ogg"),
    ],
)
def test_normalise_audio_ext(input_fmt, expected):
    assert _normalise_audio_ext(input_fmt) == expected


# ---------------------------------------------------------------------------
# Whisper API passes correct file format hint
# ---------------------------------------------------------------------------


async def test_transcribe_whisper_api_correct_file_extension(whisper_voice):
    """The filename extension in the multipart form matches the audio format."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"text": "ok"})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        await whisper_voice.transcribe(b"audio", audio_format="audio/webm;codecs=opus")

    call_kwargs = mock_client.post.call_args[1]
    file_tuple = call_kwargs["files"]["file"]
    # file_tuple = (filename, file_obj, content_type)
    assert file_tuple[0].endswith(".webm")
