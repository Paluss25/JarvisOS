"""Speech-to-Text — faster-whisper (local CPU) or OpenAI Whisper API."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Whisper models are downloaded from HuggingFace on first use and cached here.
# Mount /app/models/whisper as a volume to persist across container restarts.
_MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", "/app/models/whisper")

_model_cache: dict = {}


def _get_model(model_size: str):
    if model_size not in _model_cache:
        from faster_whisper import WhisperModel
        logger.info("stt: loading whisper '%s' (first use — may download ~%s)", model_size, {
            "tiny": "39 MB", "base": "74 MB", "small": "244 MB",
            "medium": "769 MB", "large-v3": "1.5 GB",
        }.get(model_size, "?"))
        _model_cache[model_size] = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=_MODEL_DIR,
        )
        logger.info("stt: whisper '%s' ready", model_size)
    return _model_cache[model_size]


def _transcribe_sync(audio_bytes: bytes, model_size: str, language: str | None) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.flush()
        tmp.close()
        model = _get_model(model_size)
        segments, info = model.transcribe(
            tmp.name,
            language=language,
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info(
            "stt: %d bytes → %d chars  lang=%s (%.0f%%)",
            len(audio_bytes), len(text), info.language, info.language_probability * 100,
        )
        return text
    finally:
        Path(tmp.name).unlink(missing_ok=True)


async def transcribe(
    audio_bytes: bytes,
    *,
    backend: str = "faster-whisper",
    model_size: str = "tiny",
    language: str | None = None,
) -> str:
    """Transcribe audio bytes to text.

    backend    — "faster-whisper" (local, no API key) | "openai" (requires OPENAI_API_KEY)
    model_size — faster-whisper model: "tiny" (39 MB), "base", "small", "medium"
    language   — ISO-639-1 hint ("en", "it") or None for auto-detect
    """
    if backend == "openai":
        return await _transcribe_openai(audio_bytes, language)
    return await asyncio.get_event_loop().run_in_executor(
        None, _transcribe_sync, audio_bytes, model_size, language
    )


async def _transcribe_openai(audio_bytes: bytes, language: str | None) -> str:
    import httpx
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set — cannot use openai STT backend")
    async with httpx.AsyncClient(timeout=30) as client:
        data: dict = {"model": "whisper-1"}
        if language:
            data["language"] = language
        resp = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("audio.ogg", audio_bytes, "audio/ogg")},
            data=data,
        )
        resp.raise_for_status()
        return resp.json().get("text", "")
