"""
Speech in and out.

Transcription:
    local - faster-whisper on this machine. Free, offline; the model downloads once
            (base ≈ 150 MB). Install with:  uv tool install ".[local]"  (in the project folder)
    api   - any OpenAI-compatible /audio/transcriptions endpoint.

Speech output is usually done by the browser's own voices (free, offline, nothing
to install). The api option here proxies an OpenAI-compatible /audio/speech
endpoint so the key stays on the server.
"""

from .. import privacy  # noqa: F401  must precede faster_whisper

import asyncio
import tempfile
import threading

import httpx

from .. import config, fsutil
from .client import post_endpoint

_models = {}
_models_lock = threading.Lock()


def local_available():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _whisper(size):
    with _models_lock:
        if size not in _models:
            from faster_whisper import WhisperModel

            print(f"speech: loading faster-whisper '{size}' (first use downloads it)")
            _models[size] = WhisperModel(size, device="auto", compute_type="int8")
        return _models[size]


LOCAL_TIMEOUT_S = 600  # a first use also downloads the model
# One recognition at a time: the model already uses every core, and a burst of
# uploads would otherwise run them all at once and make each one slower.
_local_turn = None


async def _local_slot(audio, suffix, size, language):
    global _local_turn
    if _local_turn is None:
        _local_turn = asyncio.Semaphore(1)
    async with _local_turn:
        try:
            return await asyncio.wait_for(asyncio.to_thread(_local_transcribe, audio, suffix, size, language), LOCAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise RuntimeError("Speech recognition took too long. Try a smaller model under Settings → Voice.") from None


def _local_transcribe(audio, suffix, size, language):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio)
        name = f.name
    try:
        segments, _ = _whisper(size).transcribe(
            name,
            language=language,
            vad_filter=True,
            # Faster, and a learner's pauses shouldn't make it "remember" earlier text.
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()
    finally:
        fsutil.remove(name)


def _suffix(content_type):
    ct = (content_type or "").lower()
    for key, ext in (("webm", ".webm"), ("ogg", ".ogg"), ("mp4", ".mp4"), ("m4a", ".m4a"),
                     ("mpeg", ".mp3"), ("wav", ".wav")):
        if key in ct:
            return ext
    return ".webm"


async def transcribe(cfg, audio, content_type, language):
    """
    `language` is the practice language's ISO code. Pinning it matters: accented
    speech in short clips is often mis-detected as the speaker's first language.
    """
    stt = cfg["stt"]
    suffix = _suffix(content_type)
    if stt["engine"] == "local":
        if not local_available():
            raise RuntimeError('Local speech recognition isn\'t installed. In the OpenSpeak folder run: uv tool install --reinstall ".[local]" '
                               '(or pip install faster-whisper, if you used pip), then restart. Or choose "Via API" under Voice.')
        return await _local_slot(audio, suffix, stt["local_model"], language)

    base, key = config.connection(cfg, "stt")
    data = {"model": stt["model"]}
    if language:
        data["language"] = language
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await post_endpoint(
            client, base, "/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            data=data,
            files={"file": (f"speech{suffix}", audio, content_type or "audio/webm")},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Transcription failed: HTTP {resp.status_code} {resp.text[:200]}")
    return (resp.json().get("text") or "").strip()


async def synthesize(cfg, text, instructions=None):
    tts = cfg["tts"]
    base, key = config.connection(cfg, "tts")
    payload = {
        "model": tts["model"],
        "voice": tts["voice"],
        "input": text,
        "speed": float(tts.get("rate") or 1.0),
        "response_format": "mp3",
    }
    if instructions:
        payload["instructions"] = instructions
    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(3):
            resp = await post_endpoint(
                client, base, "/audio/speech",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"} if key
                else {"Content-Type": "application/json"},
                json=payload,
            )
            # Older TTS models reject instructions/speed; drop and retry.
            if resp.status_code == 400:
                dropped = next((p for p in ("instructions", "speed") if p in payload and p in resp.text), None)
                if dropped:
                    payload.pop(dropped)
                    continue
            break
    if resp.status_code >= 400:
        raise RuntimeError(f"Speech synthesis failed: HTTP {resp.status_code} {resp.text[:200]}")
    return resp.content
