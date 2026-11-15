"""
Shared fixtures. Every test runs:
  - in its own OPENSPEAK_HOME under tmp_path, never ~/.openspeak;
  - with OPENSPEAK_API_KEY / OPENSPEAK_BASE_URL removed, so a key in the shell
    can't reach a test;
  - with real network calls blocked: anything that tries fails the test. The model
    is a FakeLLM; ask for the `llm` fixture to script it, or `http` to script the
    HTTP answers underneath the real client.
"""

import json
import os
import subprocess
import sys

import httpx
import pytest

from openspeak import config
from openspeak.ai import client

CLOUD = "https://api.example.invalid/v1"  # not local: grading runs live, no ×3 timeouts
LOCAL = "http://127.0.0.1:11434/v1"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    for prefix in ("OPENSPEAK_", config.OLD_ENV_PREFIX):
        for name in ("API_KEY", "BASE_URL", "HOME"):
            monkeypatch.delenv(prefix + name, raising=False)
    monkeypatch.setattr(config, "OLD_HOME", str(tmp_path / "old-home"))  # never the real one
    monkeypatch.setattr(config, "HOME", str(tmp_path))
    monkeypatch.setattr(config, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "config.json"))
    (tmp_path / "sessions").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def forget_what_servers_rejected(monkeypatch):
    """The client remembers which options a server refused; that must not carry from one test to the next."""
    monkeypatch.setattr(client, "_rejected", {})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(self, request, *a, **kw):
        raise AssertionError(f"test tried to reach the network: {request.url}")

    async def refuse_async(self, request, *a, **kw):
        refuse(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)


class FakeHTTP:
    """
    Answers httpx requests in place of the network. `on(method, url_part, *answers)`
    registers answers for requests whose URL contains url_part: each an
    httpx.Response, an exception to raise, or a callable(request) -> Response. They
    are used in order and the last one repeats. `requests` records what was sent.
    """

    def __init__(self):
        self.routes = []
        self.requests = []

    def on(self, method, url_part, *answers):
        self.routes.append([method.upper(), url_part, list(answers)])
        return self

    async def handle(self, request):
        self.requests.append(request)
        await request.aread()
        for method, part, answers in self.routes:
            if method == request.method and part in str(request.url):
                answer = answers.pop(0) if len(answers) > 1 else answers[0]
                if callable(answer) and not isinstance(answer, httpx.Response):
                    answer = answer(request)
                if isinstance(answer, BaseException):
                    raise answer
                return answer
        raise AssertionError(f"unexpected request: {request.method} {request.url}")


@pytest.fixture
def http(monkeypatch, no_network):
    """Opt in to scripted HTTP answers (see FakeHTTP); anything unscripted still fails."""
    fake = FakeHTTP()

    async def handle(transport, request):
        return await fake.handle(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    return fake


GRADE_CLEAN = {"verdict": "clean", "corrected": "", "native_version": "", "errors": [], "good_note": ""}
GRADE_ONE_ERROR = {
    "verdict": "errors", "corrected": "I want to check in", "native_version": "I'd like to check in",
    "errors": [{"type": "grammar", "original": "want check", "correction": "want to check",
                "explain": "want + to", "severity": "medium"}],
    "good_note": "",
}
SUMMARY = {"level": "B1", "patterns": ["infinitives"], "priorities": ["want to"], "encouragement": "Good."}
VOCAB = {"items": [{"term": "check in", "pos": "phrasal verb", "meaning": "register", "example": "",
                    "from_transcript": True, "source": "partner", "note": ""}]}


class FakeLLM:
    """
    Stands in for ai.client.chat. Answers by what's being asked (read from the
    system prompt); `script` overrides one kind with a value, an exception, or a
    callable. `calls` records each request's kind.
    """

    REPLY = "Sure, may I have your name?"

    def __init__(self):
        self.calls = []
        self.script = {}
        self.delay = 0

    @staticmethod
    def kind(messages, want_json):
        if not want_json:
            return "partner"
        system = messages[0]["content"]
        for kind, marker in (("summary", "debrief"), ("vocab", "vocabulary"), ("help", "hint"), ("grade", "")):
            if marker.lower() in system.lower():
                return kind
        return "grade"

    async def __call__(self, base_url, key, model, messages, want_json=False, timeout=60):
        import anyio

        kind = self.kind(messages, want_json)
        self.calls.append(kind)
        if self.delay:
            await anyio.sleep(self.delay)
        answer = self.script.get(kind)
        if callable(answer):
            answer = answer(messages)
        if isinstance(answer, BaseException):
            raise answer
        if answer is None:
            answer = {"partner": self.REPLY, "grade": GRADE_ONE_ERROR, "summary": SUMMARY,
                      "vocab": VOCAB, "help": {"hint": "Ask about breakfast", "say": ["Is breakfast included?"]}}[kind]
        return answer if isinstance(answer, str) else json.dumps(answer)


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(client, "chat", fake)
    return fake


@pytest.fixture
def cfg():
    """A config for a cloud provider (grading live) with a model chosen."""
    c = config.load()
    c["llm"]["base_url"] = CLOUD
    c["llm"]["chat_model"] = "test-model"
    c["coach"]["retries"] = 0
    return c


@pytest.fixture
def local_cfg(cfg):
    cfg["llm"]["base_url"] = LOCAL
    return cfg


@pytest.fixture
def write_log(home):
    """
    write_log(records, sid=...) -> path. Records are dicts; a session_start is
    added first unless given. Shorthands: ("heard", turn, said[, graded]),
    ("partner", turn, said), ("turn", turn, said), or a bare kind like "session_end".
    """
    from openspeak.practice import sessionlog as log

    def write(records, sid="20260101_120000"):
        path = str(home / "sessions" / f"session_{sid}.jsonl")
        out = []
        for r in records:
            if isinstance(r, str):
                r = {"kind": r}
            elif isinstance(r, tuple):
                kind, turn, said, *rest = r
                r = {"kind": kind, "turn": turn, "said": said}
                if kind == "heard":
                    r["graded"] = rest[0] if rest else True
                if kind == "turn":
                    r |= GRADE_CLEAN
            out.append({"at": log.now(), **r})
        if not out or out[0]["kind"] != "session_start":
            out.insert(0, {"kind": "session_start", "at": log.now(), "level": "B1", "reply_mode": "immersive",
                           "languages": {"target": {"id": "en"}, "native": {"id": "zh-CN"}, "report": {"id": "zh-CN"}},
                           "scene": {"id": 8, "title": {"en": "Hotel"}, "prompt": "hotel desk", "hard": False}})
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out)
        return path

    return write


@pytest.fixture
def other_pid():
    """A pid that's alive but isn't us (our parent): an 'other OpenSpeak process'."""
    return os.getppid()


@pytest.fixture
def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid
