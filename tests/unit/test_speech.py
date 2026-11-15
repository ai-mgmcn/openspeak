import json
import os
import sys
import types

import anyio
import httpx
import pytest

from openspeak import config
from openspeak.ai import speech
from openspeak.ai.client import LLMError

from ..conftest import CLOUD

pytestmark = pytest.mark.anyio


@pytest.fixture
def api_cfg(cfg):
    cfg["stt"]["engine"] = "api"
    cfg["keys"][config.origin(CLOUD)] = {"key": "sk-test", "base_url": CLOUD}
    return cfg


@pytest.fixture
def fake_whisper(monkeypatch):
    """A stand-in faster_whisper module; records what it was asked to transcribe."""
    seen = {"loaded": [], "files": []}

    class WhisperModel:
        def __init__(self, size, **kw):
            seen["loaded"].append(size)

        def transcribe(self, name, **kw):
            seen["files"].append(name)
            assert os.path.exists(name) and kw["language"] == "en"
            Seg = types.SimpleNamespace
            return [Seg(text=" hello "), Seg(text="there ")], None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel))
    monkeypatch.setattr(speech, "_models", {})
    return seen


@pytest.mark.parametrize("ct, ext", [
    ("audio/webm;codecs=opus", ".webm"), ("audio/ogg", ".ogg"), ("audio/mp4", ".mp4"), ("audio/x-m4a", ".m4a"),
    ("audio/mpeg", ".mp3"), ("audio/wav", ".wav"), ("", ".webm"), (None, ".webm"),
])
def test_suffix(ct, ext):
    assert speech._suffix(ct) == ext


class TestTranscribeApi:
    async def test_a_request_that_cant_be_sent_doesnt_quote_the_key(self, http, api_cfg):
        http.on("POST", "/audio/transcriptions", httpx.LocalProtocolError("Illegal header value b'Bearer sk-secret\\n'"))
        with pytest.raises(LLMError) as e:
            await speech.transcribe(api_cfg, b"RIFF", "audio/wav", "en")
        assert "sk-secret" not in str(e.value) and CLOUD in str(e.value)

    async def test_sends_audio_model_and_language(self, http, api_cfg):
        http.on("POST", "/audio/transcriptions", httpx.Response(200, json={"text": "  I want check in "}))
        assert await speech.transcribe(api_cfg, b"RIFF", "audio/wav", "en") == "I want check in"
        req = http.requests[0]
        assert str(req.url) == f"{CLOUD}/audio/transcriptions"
        assert req.headers["authorization"] == "Bearer sk-test"
        body = req.content
        assert b'name="model"' in body and b'name="language"\r\n\r\nen' in body and b"speech.wav" in body

    async def test_no_language_no_key(self, http, api_cfg):
        api_cfg["keys"].clear()
        http.on("POST", "/audio/transcriptions", httpx.Response(200, json={}))
        assert await speech.transcribe(api_cfg, b"x", None, None) == ""
        req = http.requests[0]
        assert "authorization" not in req.headers and b'name="language"' not in req.content

    async def test_error(self, http, api_cfg):
        http.on("POST", "/audio/transcriptions", httpx.Response(500, text="whoops"))
        with pytest.raises(RuntimeError, match="Transcription failed: HTTP 500 whoops"):
            await speech.transcribe(api_cfg, b"x", "audio/webm", "en")


class TestTranscribeLocal:
    async def test_not_installed(self, cfg, monkeypatch):
        monkeypatch.setattr(speech, "local_available", lambda: False)
        with pytest.raises(RuntimeError, match="isn't installed"):
            await speech.transcribe(cfg, b"x", "audio/webm", "en")

    async def test_transcribes_on_this_machine(self, cfg, fake_whisper):
        cfg["stt"]["local_model"] = "tiny"
        assert speech.local_available()
        assert await speech.transcribe(cfg, b"audio", "audio/ogg", "en") == "hello there"
        assert await speech.transcribe(cfg, b"audio", "audio/ogg", "en") == "hello there"
        assert fake_whisper["loaded"] == ["tiny"]  # loaded once, then reused
        assert all(f.endswith(".ogg") and not os.path.exists(f) for f in fake_whisper["files"])


    async def test_one_recognition_at_a_time(self, cfg, fake_whisper, monkeypatch):
        import threading
        import time

        running = {"now": 0, "most": 0}
        lock = threading.Lock()

        def slow(audio, suffix, size, language):
            with lock:
                running["now"] += 1
                running["most"] = max(running["most"], running["now"])
            time.sleep(0.05)
            with lock:
                running["now"] -= 1
            return "ok"

        monkeypatch.setattr(speech, "_local_transcribe", slow)
        monkeypatch.setattr(speech, "_local_turn", None)
        async with anyio.create_task_group() as tg:
            for _ in range(4):
                tg.start_soon(speech.transcribe, cfg, b"audio", "audio/ogg", "en")
        assert running["most"] == 1

    async def test_a_recognition_that_hangs_gives_up(self, cfg, fake_whisper, monkeypatch):
        import time

        monkeypatch.setattr(speech, "_local_transcribe", lambda *a: time.sleep(0.3))
        monkeypatch.setattr(speech, "_local_turn", None)
        monkeypatch.setattr(speech, "LOCAL_TIMEOUT_S", 0.05)
        with pytest.raises(RuntimeError, match="took too long"):
            await speech.transcribe(cfg, b"audio", "audio/ogg", "en")


def test_local_not_available(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import raises ImportError
    assert not speech.local_available()


class TestSynthesize:
    async def test_a_request_that_cant_be_sent_doesnt_quote_the_key(self, http, cfg):
        cfg["keys"][config.origin(CLOUD)] = {"key": "sk-test", "base_url": CLOUD}
        http.on("POST", "/audio/speech", httpx.LocalProtocolError("Illegal header value b'Bearer sk-secret\\n'"))
        with pytest.raises(LLMError) as e:
            await speech.synthesize(cfg, "Hello")
        assert "sk-secret" not in str(e.value) and CLOUD in str(e.value)

    async def test_drops_what_an_older_model_rejects(self, http, cfg):
        cfg["keys"][config.origin(CLOUD)] = {"key": "sk-test", "base_url": CLOUD}
        cfg["tts"]["rate"] = 1.2
        http.on("POST", "/audio/speech",
                httpx.Response(400, text="unknown parameter: instructions"),
                httpx.Response(400, text="speed is not supported"),
                httpx.Response(200, content=b"ID3mp3"))
        assert await speech.synthesize(cfg, "Hello", instructions="warm") == b"ID3mp3"
        first, second, third = (json.loads(r.content) for r in http.requests)
        assert first["instructions"] == "warm" and first["speed"] == 1.2 and first["input"] == "Hello"
        assert "instructions" not in second and "speed" in second
        assert "speed" not in third
        assert http.requests[0].headers["authorization"] == "Bearer sk-test"

    async def test_error(self, http, cfg):
        http.on("POST", "/audio/speech", httpx.Response(400, text="bad voice"))
        with pytest.raises(RuntimeError, match="Speech synthesis failed: HTTP 400 bad voice"):
            await speech.synthesize(cfg, "Hello")
        assert len(http.requests) == 1 and "authorization" not in http.requests[0].headers


def test_the_installed_speech_libraries_can_decode_audio(tmp_path):
    """The real faster-whisper decoder, with whatever `av` was installed: a new `av` once broke it for everyone."""
    import wave

    pytest.importorskip("faster_whisper")
    from faster_whisper.audio import decode_audio

    path = tmp_path / "tone.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x10" * 16000)  # one second
    assert len(decode_audio(str(path))) == 16000
