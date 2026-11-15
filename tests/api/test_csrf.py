"""
Another web page open in the same browser must not be able to make this server do
anything: not change settings, not start or end sessions, and above all not send
the saved key to a server of its choosing.
"""

import json

import pytest

from openspeak import config
from openspeak.ai import client
from openspeak.web import server

from .test_lifecycle import A, start

OWN = {"origin": "http://127.0.0.1:8765", "sec-fetch-site": "same-origin"}
EVIL = {"origin": "https://evil.example", "sec-fetch-site": "cross-site"}
# What a page sends with fetch(url, {mode: "no-cors", body: JSON.stringify(...)}):
# text/plain needs no CORS preflight, so the browser sends it straight through.
SIMPLE = {"content-type": "text/plain;charset=UTF-8"}


def unsafe_routes():
    """Every route that changes something, with a session id filled in."""
    for r in server.app.routes:
        for method in sorted(getattr(r, "methods", None) or ()):
            if method in server.UNSAFE_METHODS:
                yield method, r.path.replace("{sid}", "20260101_120000")


def test_unsafe_methods_are_everything_but_reading():
    # Written out, not read from the server: that is what would be checking itself.
    assert server.UNSAFE_METHODS == {"POST", "PUT", "PATCH", "DELETE"}
    served = {m for r in server.app.routes for m in (getattr(r, "methods", None) or ())}
    assert served - {"GET", "HEAD", "OPTIONS"} <= server.UNSAFE_METHODS


@pytest.mark.parametrize("method, path", sorted(set(unsafe_routes())))
def test_every_unsafe_route_refuses_another_site(api, llm, write_log, method, path):
    write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in")])
    r = api.request(method, path, content=json.dumps({"base_url": "https://evil.example/v1"}),
                    headers=EVIL | SIMPLE)
    assert r.status_code == 403, (method, path)
    assert not llm.calls


def test_the_key_cant_be_sent_to_another_server(api, llm, monkeypatch):
    config.save({"llm": {"api_key": "sk-saved"}})
    asked = []

    async def list_models(base, key, timeout=5):
        asked.append((base, key))
        return []

    monkeypatch.setattr(client, "list_models", list_models)
    body = json.dumps({"base_url": "https://evil.example/v1", "model": "x"})
    for path in ("/api/test", "/api/models"):
        assert api.post(path, content=body, headers=EVIL | SIMPLE).status_code == 403
    assert not llm.calls and not asked


def test_settings_cant_be_changed_from_another_site(api):
    before = config.load()["llm"]["base_url"]
    body = json.dumps({"llm": {"base_url": "https://evil.example/v1"}})
    assert api.post("/api/config", content=body, headers=EVIL | SIMPLE).status_code == 403
    assert config.load()["llm"]["base_url"] == before


@pytest.mark.parametrize("headers", [
    {"origin": "https://evil.example"},  # an older browser: Origin only
    {"sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "same-site"},  # another app on another localhost port
    {"origin": "http://127.0.0.1:3000"},
    {"origin": "http://localhost:8765"},  # same machine, but not the origin it's served on
    {"origin": "null"},  # sandboxed iframe, file:// page
], ids=lambda h: ",".join(f"{k}={v}" for k, v in h.items()))
def test_any_sign_of_another_origin_is_refused(api, headers):
    assert api.post("/api/config", json={}, headers=headers).status_code == 403


def test_our_own_page_works(api):
    r = api.post("/api/config", json={"llm": {"chat_model": "m2"}}, headers=OWN)
    assert r.status_code == 200 and config.load()["llm"]["chat_model"] == "m2"
    sid = api.post("/api/session", json={"scene_id": 8}, headers=OWN | A).json()["id"]
    assert api.post(f"/api/session/{sid}/text", json={"text": "hello there friend"}, headers=OWN | A).status_code == 200


def test_the_tab_closing_beacon_still_gets_through(api):
    # navigator.sendBeacon(url, TAB) posts the tab id as text/plain from our own page.
    sid, _ = start(api)
    r = api.post(f"/api/session/{sid}/leave", content="A", headers=OWN | SIMPLE)
    assert r.status_code == 200 and server.live.get(sid).left


def test_reading_is_still_allowed(api):
    assert api.get("/api/history", headers=EVIL).status_code == 200


class TestJsonBodies:
    """Second layer, for clients that send neither header: JSON only if sent as JSON."""

    def test_text_plain_isnt_read_as_json(self, api):
        body = json.dumps({"llm": {"base_url": "https://evil.example/v1"}})
        assert api.post("/api/config", content=body, headers=SIMPLE).status_code == 415
        assert "evil" not in config.load()["llm"]["base_url"]

    def test_form_posts_are_refused(self, api):
        assert api.post("/api/config", data={"x": "1"}).status_code == 415

    @pytest.mark.parametrize("body", ["{not json", "[1, 2]", '"text"'])
    def test_not_an_object(self, api, body):
        r = api.post("/api/config", content=body, headers={"content-type": "application/json"})
        assert r.status_code == 400
