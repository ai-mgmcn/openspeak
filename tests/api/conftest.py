import pytest
from fastapi.testclient import TestClient

from openspeak import config
from openspeak.practice import live as live_mod
from openspeak.practice.jobs import Jobs
from openspeak.practice.live import LiveSessions
from openspeak.web import server

from ..conftest import CLOUD


@pytest.fixture
def api(monkeypatch, llm):
    """The app as the page sees it, with fresh registries and quick idle timers."""
    monkeypatch.setattr(server, "live", LiveSessions())
    monkeypatch.setattr(server, "jobs", Jobs())
    monkeypatch.setattr(live_mod, "REAP_EVERY_S", 0.05)
    monkeypatch.setattr(live_mod, "LEFT_GRACE_S", 0.2)
    config.save({"llm": {"base_url": CLOUD, "chat_model": "test-model"}, "stt": {"engine": "api"}})
    with TestClient(server.app, base_url="http://127.0.0.1:8765") as c:
        yield c
