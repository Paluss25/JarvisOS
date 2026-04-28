"""Text-to-Speech — edge-tts (free, no API key) or OpenAI TTS API.

Output pipeline:
  edge-tts → MP3 bytes → ffmpeg → OGG/Opus → Telegram reply_voice()
"""

import asyncio
import io
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Strip Markdown formatting for cleaner spoken output.
# Handles: **bold**, *italic*, `code`, ~~strike~~, [text](url), headings, blockquotes.
_MD_RE = re.compile(
    r"```.*?```"                   # fenced code blocks
    r"|`[^`]+`"                    # inline code
    r"|\[([^\]]+)\]\([^)]+\)"      # [text](url) → keep text
    r"|[*_~#>]+"                   # formatting chars
    , re.DOTALL,
)


def _clean(text: str, max_chars: int) -> str:
    text = _MD_RE.sub(lambda m: m.group(1) or "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\n", " ", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars].rfind(". ")
        text = (text[:cut + 1] if cut > max_chars // 2 else text[:max_chars]) + "…"
    return text


async def synthesize(
    text: str,
    *,
    backend: str = "edge",
    voice: str = "it-IT-ElsaNeural",
    max_chars: int = 800,
) -> bytes:
    """Synthesize text to MP3 bytes.

    backend   — "edge" (edge-tts, free) | "openai" (requires OPENAI_API_KEY)
    voice     — edge-tts voice name (e.g. "it-IT-ElsaNeural", "en-US-JennyNeural")
                or OpenAI voice name (alloy, echo, fable, onyx, nova, shimmer)
    max_chars — truncate cleaned text to this many characters before synthesis
    """
    clean = _clean(text, max_chars)
    if not clean:
        return b""
    if backend == "openai":
        return await _synth_openai(clean, voice)
    return await _synth_edge(clean, voice)


async def _synth_edge(text: str, voice: str) -> bytes:
    import edge_tts
    buf = io.BytesIO()
    comm = edge_tts.Communicate(text, voice)
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    data = buf.getvalue()
    logger.info("tts: edge %d chars → %d bytes  voice=%s", len(text), len(data), voice)
    return data


async def _synth_openai(text: str, voice: str) -> bytes:
    import httpx
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    _oai_voices = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
    oai_voice = voice if voice in _oai_voices else "nova"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "tts-1", "input": text, "voice": oai_voice},
        )
        resp.raise_for_status()
        logger.info("tts: openai %d chars → %d bytes  voice=%s", len(text), len(resp.content), oai_voice)
        return resp.content


async def mp3_to_ogg_opus(mp3_bytes: bytes) -> bytes:
    """Convert MP3 to OGG/Opus so Telegram shows it as a voice message."""
    in_tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    out_path = in_tmp.name[:-4] + ".ogg"
    try:
        in_tmp.write(mp3_bytes)
        in_tmp.flush()
        in_tmp.close()
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", in_tmp.name,
            "-c:a", "libopus", "-b:a", "48k", "-vbr", "on",
            out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        p = Path(out_path)
        if p.exists() and p.stat().st_size > 0:
            data = p.read_bytes()
            logger.info("tts: mp3→ogg %d → %d bytes", len(mp3_bytes), len(data))
            return data
        logger.warning("tts: ffmpeg produced empty output")
        return b""
    finally:
        Path(in_tmp.name).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)
