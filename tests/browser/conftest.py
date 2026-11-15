"""
The page in a real browser, against the real server and a pretend model. Skipped
when Playwright or Chrome isn't there:

    uv run --with playwright pytest tests/browser
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

playwright = pytest.importorskip("playwright.sync_api")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """OpenSpeak running for real, with its own empty home."""
    port, home = free_port(), tmp_path_factory.mktemp("home")
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENSPEAK_")} | {"OPENSPEAK_HOME": str(home)}
    proc = subprocess.Popen([sys.executable, "-m", "openspeak", "--no-browser", "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/", timeout=2)
            break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("the server didn't start")
    body = json.dumps({"setup_done": True, "llm": {"chat_model": "m"}, "tts": {"engine": "off"}}).encode()
    urllib.request.urlopen(urllib.request.Request(
        base + "/api/config", body, {"Content-Type": "application/json", "Origin": base}), timeout=5)
    yield base
    proc.terminate()
    proc.wait(10)


@pytest.fixture(scope="session")
def browser():
    with playwright.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        except Exception as e:  # no Chrome installed
            pytest.skip(f"needs Chrome: {e}")
        yield b
        b.close()


class Fake:
    """The server's session endpoints, pretended: sessions come and go as the test says."""

    def __init__(self):
        self.sessions = {}  # id -> title shown in History
        self.gone = set()  # ids whose status now answers 404, as if put away
        self.n = 0
        self.rtl = False  # whether the language in play reads right to left

    def route(self, route, request):
        url, method = request.url, request.method
        path = url.split("//", 1)[1].split("/", 1)[1].split("?")[0]
        if path == "api/session" and method == "POST":
            self.n += 1
            sid = f"2026010{self.n}_120000"
            self.sessions[sid] = "Free conversation"
            return self.reply(route, {"id": sid, "text": f"Hello {sid}", "aid": "", "tts_lang": "en-US", "rtl": self.rtl})
        if path.endswith("/status"):
            sid = path.split("/")[2]
            if sid in self.gone:
                return self.reply(route, {"detail": "Session not found."}, 404)
            return self.reply(route, {"graded": {}, "pending": 0})
        if path == "api/history":
            return self.reply(route, {"sessions": [
                {"id": sid, "at": "2026-01-01T12:00:00", "scene": None, "target": "en", "turns": 2, "errors": 0, "ended": False,
                 "complete": True, "live": False, "working": False, "has_report": False, "ungraded": 0, "problem": ""}
                for sid in self.sessions]})
        if path.startswith("api/report/") and method == "DELETE":
            self.sessions.pop(path.split("/")[2], None)
            return self.reply(route, {"ok": True})
        if path.endswith("/leave"):
            return self.reply(route, {})
        return route.continue_()

    @staticmethod
    def reply(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


@pytest.fixture
def fake():
    return Fake()


@pytest.fixture
def page(browser, server, fake):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.grant_permissions(["microphone"], origin=server)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.route("**/api/**", fake.route)
    pg.goto(server + "/")
    pg.wait_for_selector("#catTabs button")
    yield pg
    assert pg.errors == []  # nothing the page threw, whatever the test was about
    ctx.close()
