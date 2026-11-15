"""
Each route's own answers: settings, connection checks, errors from the model or
speech service, bad ids, and what history leaves out.
"""

import os
import time

import httpx
import pytest

from openspeak import config, report
from openspeak.ai import client, speech
from openspeak.ai.client import LLMError
from openspeak.practice import sessionlog as log
from openspeak.web import server

from ..conftest import CLOUD
from .test_lifecycle import A, history, start, wait_job

AUDIO = b"\x1aE\xdf\xa3" + b"\0" * 2000  # big enough to be speech, never decoded


@pytest.fixture
def heard(monkeypatch):
    """speech.transcribe answers with whatever the test puts in heard["text"]."""
    out = {"text": "I want check in please", "calls": []}

    async def fake(cfg, audio, content_type, language):
        out["calls"].append((content_type, language))
        if isinstance(out["text"], BaseException):
            raise out["text"]
        return out["text"]

    monkeypatch.setattr(speech, "transcribe", fake)
    return out


class TestSettings:
    def test_saved_key_comes_back_masked(self, api):
        r = api.post("/api/config", json={"llm": {"api_key": "sk-secret-1234"}}).json()
        assert r["config"]["llm"]["api_key"].endswith("1234") and "sk-secret" not in str(r)
        assert config.key_for(config.load(), CLOUD) == "sk-secret-1234"

    @pytest.mark.parametrize("path", ["/api/config", "/api/models"])
    def test_a_key_that_cant_be_sent_is_refused_without_quoting_it(self, api, path):
        body = {"llm": {"api_key": "sk-secret\x00"}} if path == "/api/config" else {"api_key": "sk-secret\x00"}
        r = api.post(path, json=body)
        assert r.status_code == 400 and "sk-secret" not in r.text and not config.load()["keys"]

    def test_meta_never_has_the_key(self, api):
        config.save({"llm": {"api_key": "sk-secret-1234"}})
        assert "sk-secret" not in api.get("/api/meta").text


class TestKeys:
    def test_clear(self, api):
        api.post("/api/config", json={"llm": {"api_key": "sk-secret-1234"}})
        r = api.request("DELETE", "/api/keys", json={"base_url": config.origin(CLOUD)})
        assert r.status_code == 200 and r.json()["config"]["keys"] == []
        assert not config.load()["keys"] and r.json()["config"]["llm"]["api_key"] == ""

    def test_what_goes_over_the_wire_after_a_url_change(self, api, http):
        # End to end: the request a changed URL gets carries no Authorization at all.
        config.save({"llm": {"api_key": "sk-saved"}})
        masked = config.public(config.load())["llm"]["api_key"]
        http.on("GET", "/models", httpx.Response(200, json={"data": [{"id": "m"}]}))
        api.post("/api/models", json={"base_url": "https://x.example.invalid/v1", "api_key": masked})
        api.post("/api/models", json={"base_url": CLOUD, "api_key": masked})
        to_other, to_ours = http.requests
        assert "authorization" not in to_other.headers
        assert to_ours.headers["authorization"] == "Bearer sk-saved"


class TestConnectionChecks:
    @pytest.fixture
    def seen(self, monkeypatch):
        seen = []

        async def list_models(base, key, timeout=5):
            seen.append((base, key))
            if "down" in base:
                raise LLMError("Can't reach it")
            return ["a", "b"]

        monkeypatch.setattr(client, "list_models", list_models)
        return seen

    def test_masked_key_means_the_one_saved_for_that_service(self, api, seen):
        config.save({"llm": {"api_key": "sk-saved"}})
        masked = config.public(config.load())["llm"]["api_key"]
        r = api.post("/api/models", json={"base_url": CLOUD + "/models", "api_key": masked})
        assert r.json() == {"models": ["a", "b"]}
        assert seen == [(CLOUD + "/models", "sk-saved")]  # as typed; the client finds its endpoint

    @pytest.mark.parametrize("key", ["", "masked"])
    def test_another_url_doesnt_get_the_saved_key(self, api, seen, key):
        config.save({"llm": {"api_key": "sk-saved"}})
        if key:
            key = config.public(config.load())["llm"]["api_key"]
        api.post("/api/models", json={"base_url": "https://x.example.invalid/v1", "api_key": key})
        assert seen == [("https://x.example.invalid/v1", "")]

    def test_a_typed_key_is_tried_but_not_saved(self, api, seen):
        api.post("/api/models", json={"base_url": "https://x.example.invalid/v1", "api_key": "sk-try"})
        assert seen == [("https://x.example.invalid/v1", "sk-try")]
        assert not config.load()["keys"]

    def test_a_new_key_is_used_as_typed(self, api, seen):
        api.post("/api/models", json={"api_key": "sk-new"})
        assert seen == [(CLOUD, "sk-new")]

    def test_models_error(self, api, seen):
        r = api.post("/api/models", json={"base_url": "https://down.example.invalid/v1"})
        assert r.status_code == 502 and "Can't reach" in r.json()["detail"]

    def test_test_button(self, api, llm):
        r = api.post("/api/test", json={"model": "m"})
        assert r.json() == {"ok": True, "reply": llm.REPLY}

    def test_test_button_error(self, api, llm):
        llm.script["partner"] = LLMError("HTTP 401: bad key")
        r = api.post("/api/test", json={"model": "m"})
        assert r.status_code == 502 and r.json()["detail"] == "HTTP 401: bad key"

    def test_detect(self, api, monkeypatch):
        async def detect_local():
            return [{"provider": "ollama", "base_url": "http://localhost:11434/v1", "models": ["q"]}]

        monkeypatch.setattr(client, "detect_local", detect_local)
        assert api.get("/api/detect").json()["found"][0]["provider"] == "ollama"


class TestStart:
    def test_unknown_scene(self, api):
        assert api.post("/api/session", json={"scene_id": 99999}, headers=A).status_code == 404

    def test_custom_scene(self, api):
        r = api.post("/api/session", json={"custom": "Returning a broken phone " * 5}, headers=A).json()
        s = server.live.get(r["id"])
        assert s.scene["id"] == "custom" and len(s.scene["title"]["en"]) == 60
        assert r["text"] and r["tts_lang"]

    def test_partner_cant_open(self, api, llm):
        llm.script["partner"] = LLMError("model is down")
        r = api.post("/api/session", json={"scene_id": 8}, headers=A)
        assert r.status_code == 502 and r.json()["detail"] == "model is down"

    def test_a_failed_start_leaves_nothing_behind(self, api, llm):
        # The page never got an id, so nothing else could ever clean it up.
        llm.script["partner"] = LLMError("model is down")
        for _ in range(3):
            api.post("/api/session", json={"scene_id": 8}, headers=A)
        assert not server.live._live
        assert api.get("/api/history").json()["sessions"] == [] and not os.listdir(config.SESSIONS_DIR)

    def test_cant_resume_while_the_report_is_being_written(self, api, llm):
        sid, _ = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        llm.delay = 0.3
        api.post(f"/api/session/{sid}/finish", headers=A)
        r = api.post(f"/api/session/{sid}/resume", json={}, headers=A)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "working"
        wait_job(api, sid)

    def test_resume_reply_fails(self, api, llm, write_log):
        write_log([("partner", 0, "Welcome"), ("heard", 1, "Is breakfast included?")])
        llm.script["partner"] = LLMError("model is down")
        r = api.post("/api/session/20260101_120000/resume", json={}, headers=A)
        assert r.status_code == 502


class TestBadInput:
    """JSON lets a client send anything for any field: a clear 400, never a 500 or a Python error message."""

    @pytest.mark.parametrize("body", [{"custom": 5}, {"custom": ["x"]}, {"scene_id": [1]}, {"scene_id": {"a": 1}}])
    def test_session_start(self, api, body):
        r = api.post("/api/session", json=body, headers=A)
        assert r.status_code == 400 and not server.live._live

    @pytest.mark.parametrize("text", [5, None, ["x"], {"a": 1}])
    def test_text_turn(self, api, text):
        sid, _ = start(api)
        r = api.post(f"/api/session/{sid}/text", json={"text": text}, headers=A)
        assert r.status_code == 400 and "must be text" in r.json()["detail"]

    @pytest.mark.parametrize("text", [None, 5])
    def test_tts(self, api, text):
        assert api.post("/api/tts", json={"text": text}, headers=A).status_code == 400


class TestProviderFailures:
    """What the page is told when the service times out or answers nonsense: always something to act on."""

    def test_a_timeout_is_explained(self, api, llm):
        llm.script["partner"] = httpx.ReadTimeout("")
        r = api.post("/api/session", json={"scene_id": 8}, headers=A)
        assert r.status_code == 502 and "didn't answer in time" in r.json()["detail"]

    def test_an_error_without_a_message_still_says_something(self, api, llm):
        llm.script["partner"] = RuntimeError()
        detail = api.post("/api/session", json={"scene_id": 8}, headers=A).json()["detail"]
        assert detail and "RuntimeError" in detail

    def test_a_page_that_isnt_json_is_explained(self, api, monkeypatch):
        async def models(base, key, timeout=5):
            import json as j
            j.loads("<html>")

        monkeypatch.setattr(client, "list_models", models)
        detail = api.post("/api/models", json={"base_url": CLOUD}, headers=A).json()["detail"]
        assert "isn't JSON" in detail and "/v1" in detail


class TestAudio:
    def test_too_short_to_be_speech(self, api, heard):
        sid, _ = start(api)
        r = api.post(f"/api/session/{sid}/audio", content=b"x" * 10, headers=A).json()
        assert r == {"heard": "", "text": ""} and not heard["calls"]

    def test_heard_and_answered(self, api, heard):
        sid, _ = start(api)
        r = api.post(f"/api/session/{sid}/audio", content=AUDIO, headers=A | {"content-type": "audio/webm"}).json()
        assert r["turn"] == 1 and r["text"]
        assert heard["calls"] == [("audio/webm", "en")]

    def test_nothing_recognised(self, api, heard):
        heard["text"] = ""
        sid, _ = start(api)
        assert api.post(f"/api/session/{sid}/audio", content=AUDIO, headers=A).json() == {"heard": "", "text": ""}

    def test_transcription_fails(self, api, heard):
        heard["text"] = RuntimeError("Transcription failed: HTTP 500")
        sid, _ = start(api)
        r = api.post(f"/api/session/{sid}/audio", content=AUDIO, headers=A)
        assert r.status_code == 502 and "Transcription failed" in r.json()["detail"]

    def test_partner_fails_but_what_was_heard_is_shown(self, api, heard, llm):
        sid, _ = start(api)
        llm.script["partner"] = LLMError("model is down")
        r = api.post(f"/api/session/{sid}/audio", content=AUDIO, headers=A)
        assert r.status_code == 502 and r.json()["detail"] == {"heard": heard["text"], "error": "model is down"}

    def test_ended(self, api, heard):
        sid, _ = start(api)
        server.live.get(sid).ending = True
        r = api.post(f"/api/session/{sid}/audio", content=AUDIO, headers=A)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "closed"

    def test_not_found(self, api, heard):
        assert api.post("/api/session/20990101_000000/audio", content=AUDIO, headers=A).status_code == 404

    def test_an_upload_past_the_limit_is_refused_unread(self, api, heard, monkeypatch):
        monkeypatch.setattr(server, "MAX_AUDIO_BYTES", 5000)
        sid, _ = start(api)
        r = api.post(f"/api/session/{sid}/audio", content=b"x" * 5001, headers=A)
        assert r.status_code == 413 and not heard["calls"]
        assert api.post(f"/api/session/{sid}/audio", content=b"x" * 5000, headers=A).status_code == 200

    def test_a_limit_holds_without_a_declared_length(self, api, heard, monkeypatch):
        monkeypatch.setattr(server, "MAX_AUDIO_BYTES", 5000)
        sid, _ = start(api)
        r = api.post(f"/api/session/{sid}/audio", content=(b"x" * 1000 for _ in range(6)), headers=A)  # streamed: no content-length
        assert r.status_code == 413 and not heard["calls"]

    def test_json_past_the_limit_is_refused(self, api, monkeypatch):
        monkeypatch.setattr(server, "MAX_JSON_BYTES", 100)
        r = api.post("/api/config", json={"llm": {"chat_model": "m" * 200}}, headers=A)
        assert r.status_code == 413 and config.load()["llm"]["chat_model"] == "test-model"


class TestTextAndHelp:
    def test_text_partner_fails(self, api, llm):
        sid, _ = start(api)
        llm.script["partner"] = LLMError("model is down")
        r = api.post(f"/api/session/{sid}/text", json={"text": "hello there friend"}, headers=A)
        assert r.status_code == 502

    def test_text_after_end(self, api):
        sid, _ = start(api)
        server.live.get(sid).ending = True
        r = api.post(f"/api/session/{sid}/text", json={"text": "hello"}, headers=A)
        assert r.json()["detail"]["code"] == "closed"

    def test_help(self, api):
        sid, _ = start(api)
        r = api.post(f"/api/session/{sid}/help", headers=A).json()
        assert r == {"hint": "Ask about breakfast", "say": ["Is breakfast included?"]}

    def test_help_fails(self, api, llm):
        sid, _ = start(api)
        llm.script["help"] = LLMError("model is down")
        assert api.post(f"/api/session/{sid}/help", headers=A).status_code == 502

    def test_help_after_end(self, api):
        sid, _ = start(api)
        server.live.get(sid).ending = True
        assert api.post(f"/api/session/{sid}/help", headers=A).json()["detail"]["code"] == "closed"


class TestTts:
    def test_audio_comes_back(self, api, monkeypatch):
        got = {}

        async def synthesize(cfg, text, instructions=None):
            got.update(text=text, instructions=instructions)
            return b"ID3"

        monkeypatch.setattr(speech, "synthesize", synthesize)
        r = api.post("/api/tts", json={"text": "x" * 2000, "instructions": "slowly"})
        assert r.content == b"ID3" and r.headers["content-type"] == "audio/mpeg"
        assert len(got["text"]) == 1000 and got["instructions"] == "slowly"

    def test_error(self, api, monkeypatch):
        async def synthesize(cfg, text, instructions=None):
            raise RuntimeError("Speech synthesis failed: HTTP 401")

        monkeypatch.setattr(speech, "synthesize", synthesize)
        assert api.post("/api/tts", json={"text": "hi"}).status_code == 502


class TestReports:
    @pytest.mark.parametrize("url", ["/report/abc", "/report/abc.md"])
    def test_a_bad_id_is_refused(self, api, url):
        assert api.get(url).status_code == 400

    def test_a_path_in_the_id_never_reaches_the_disk(self, api):
        assert api.get("/report/..%2Fconfig").status_code == 404  # no such route; the id check isn't even reached

    def test_deleting_a_bad_id_is_refused(self, api):
        assert api.delete("/api/report/abc").status_code == 400

    def test_missing(self, api):
        assert api.get("/report/20990101_000000").status_code == 404
        assert api.post("/api/report/20990101_000000/repair").status_code == 404

    def test_stale_markdown_is_rebuilt(self, api, write_log):
        path = write_log([("heard", 1, "I want check in"), ("turn", 1, "I want check in")])
        api.get("/report/20260101_120000.md")
        md = path[:-6] + ".md"
        os.utime(md, (time.time() - 100, time.time() - 100))
        with open(path, "a") as f:
            f.write('{"kind":"heard","turn":2,"said":"a brand new line","graded":false}\n')
        assert "a brand new line" in api.get("/report/20260101_120000.md").text

    def test_repair_of_a_session_open_here_finishes_it(self, api):
        sid, _ = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        job = api.post(f"/api/report/{sid}/repair").json()
        assert job["kind"] == "repair"
        assert wait_job(api, sid)["stage"] == "ready" and sid not in server.live


class TestHistory:
    def test_an_abandoned_empty_log_is_removed(self, api, write_log):
        path = write_log([("partner", 0, "Welcome")])
        assert api.get("/api/history").json()["sessions"] == []
        assert os.path.exists(path)  # recent: could still be starting
        old = time.time() - server.EMPTY_LOG_MAX_AGE_S - 10
        os.utime(path, (old, old))
        api.get("/api/history")
        assert not os.path.exists(path)

    def test_an_unreadable_log_is_skipped(self, api, write_log, monkeypatch):
        write_log([("heard", 1, "I want check in")], sid="20260101_120000")
        write_log([("heard", 1, "I want check in")], sid="20260102_120000")
        real = report.describe

        def describe(path):
            if "20260101" in path:
                raise OSError("disk says no")
            return real(path)

        monkeypatch.setattr(report, "describe", describe)
        assert [s["id"] for s in api.get("/api/history").json()["sessions"]] == ["20260102_120000"]

    def test_a_log_removed_while_listing_is_left_out(self, api, write_log, monkeypatch):
        path = write_log([("partner", 0, "Welcome")])
        real = os.path.getmtime

        def getmtime(p):
            if p == path:
                raise FileNotFoundError(p)  # another window deleted it a moment ago
            return real(p)

        monkeypatch.setattr(os.path, "getmtime", getmtime)
        assert api.get("/api/history").json()["sessions"] == []

    def test_a_live_session_is_marked(self, api):
        sid, _ = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        h = history(api, sid)
        assert h["live"] and not h["working"]


def test_ended_while_the_audio_was_being_transcribed(api, heard, monkeypatch):
    sid, _ = start(api)

    async def slow_ear(cfg, audio, content_type, language):
        server.live.get(sid).ending = True  # End pressed in the meantime
        return "I want check in please"

    monkeypatch.setattr(speech, "transcribe", slow_ear)
    s = server.live.get(sid)
    r = api.post(f"/api/session/{sid}/audio", content=AUDIO, headers=A)
    # Spoken before End: it's kept and reported, but there's no reply to it.
    assert r.status_code == 200 and r.json()["heard"] == "I want check in please" and r.json()["text"] == ""
    said = [x["kind"] for x in log.ordered(log.read(s.path))]
    assert said == ["partner", "heard"]


def test_audio_after_end_is_refused(api, heard):
    sid, _ = start(api)
    server.live.get(sid).ending = True
    r = api.post(f"/api/session/{sid}/audio", content=AUDIO, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "closed" and not heard["calls"]


def test_repair_waits_for_a_put_away_in_progress(api):
    sid, _ = start(api)
    api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
    server.live.get(sid).ending = True  # being put away: not "open here"
    job = api.post(f"/api/report/{sid}/repair").json()
    assert job["kind"] == "repair" and wait_job(api, sid)["stage"] == "ready"


def test_no_other_site_may_frame_the_page(api):
    for url in ("/", "/api/meta"):
        r = api.get(url)
        assert r.headers["x-frame-options"] == "SAMEORIGIN" and "frame-ancestors 'self'" in r.headers["content-security-policy"]


def test_the_page_is_checked_for_updates_on_every_load(api):
    # So a new version shows on a plain refresh, while unchanged files cost a 304.
    for url in ("/", "/static/app.js", "/static/app.css"):
        r = api.get(url)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", url
    assert api.get("/static/app.css", headers={"if-none-match": r.headers["etag"]}).status_code == 304
