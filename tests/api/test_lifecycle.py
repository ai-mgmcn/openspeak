"""
The HTTP API end to end, the way the page uses it: start, talk, leave, resume,
take over from another tab, end with a background report, and the guards that
keep two processes off one log.
"""

import os
import time

import anyio
from fastapi.testclient import TestClient

from openspeak.practice import sessionlog as log
from openspeak.web import server

A, B, C = ({"x-tab": t} for t in "ABC")


def start(api, tab=A):
    sid = api.post("/api/session", json={"scene_id": 8}, headers=tab).json()["id"]
    return sid, server.live.get(sid).path


def history(api, sid):
    return next(s for s in api.get("/api/history").json()["sessions"] if s["id"] == sid)


def wait_job(api, sid, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = next((j for j in api.get("/api/jobs").json()["jobs"] if j["id"] == sid), None)
        if job and job["stage"] in ("ready", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job for {sid} didn't finish")


def wait_until(cond, timeout=3):
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


class TestTabs:
    def test_another_tab_is_told_elsewhere(self, api):
        sid, _ = start(api)
        r = api.get(f"/api/session/{sid}/status", headers=B)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "elsewhere"

    def test_take_over(self, api):
        sid, _ = start(api)
        assert api.post(f"/api/session/{sid}/resume", json={}, headers=B).status_code == 409
        assert api.post(f"/api/session/{sid}/resume", json={"take": True}, headers=B).status_code == 200
        assert api.get(f"/api/session/{sid}/status", headers=A).status_code == 409
        assert api.get(f"/api/session/{sid}/status", headers=B).status_code == 200


class TestLeaveAndResume:
    def test_closed_tab_releases_the_session_and_it_can_continue(self, api):
        sid, path = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        api.post(f"/api/session/{sid}/leave", content="A")
        wait_until(lambda: sid not in server.live)
        assert log.owner(path) is None
        h = history(api, sid)
        assert not h["ended"] and not h["live"]

        r = api.post(f"/api/session/{sid}/resume", json={}, headers=B).json()
        assert [t["who"] for t in r["transcript"]] == ["ai", "me", "ai"]
        assert r["transcript"][1]["state"] == "ok"
        t = api.post(f"/api/session/{sid}/text", json={"text": "My name is Li"}, headers=B).json()
        assert t["turn"] == 2

    def test_leave_from_a_tab_that_doesnt_own_it_is_ignored(self, api):
        sid, _ = start(api)
        api.post(f"/api/session/{sid}/leave", content="B")
        time.sleep(0.4)
        assert sid in server.live


class TestEnd:
    def test_report_is_written_in_the_background(self, api):
        sid, path = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        job = api.post(f"/api/session/{sid}/finish", headers=A).json()
        assert job["kind"] == "finish" and job["stage"] in ("queued", "grading", "writing")
        assert api.post(f"/api/session/{sid}/text", json={"text": "one more"}, headers=A).status_code in (404, 409)
        job = wait_job(api, sid)
        assert job["stage"] == "ready" and job["complete"]
        assert os.path.exists(path[:-6] + ".html") and log.owner(path) is None
        assert history(api, sid)["ended"]

    def test_nothing_said_leaves_nothing_behind(self, api):
        sid, path = start(api)
        api.post(f"/api/session/{sid}/finish", headers=A)
        assert wait_job(api, sid)["empty"]
        assert not os.path.exists(path)


class TestDelete:
    """Every session can be deleted, whatever it's doing; nothing of it is left behind."""

    def gone(self, api, sid, path):
        base = path[:-6]
        return (not any(os.path.exists(p) for p in (path, base + ".html", base + ".md", path + ".live"))
                and sid not in server.live and all(s["id"] != sid for s in api.get("/api/history").json()["sessions"]))

    def test_while_the_report_is_being_written(self, api, llm):
        sid, path = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        llm.delay = 0.3
        api.post(f"/api/session/{sid}/finish", headers=A)
        assert history(api, sid)["working"]
        assert api.delete(f"/api/report/{sid}").status_code == 200
        time.sleep(0.5)  # the cancelled job writes nothing afterwards
        assert self.gone(api, sid, path) and all(j["id"] != sid for j in api.get("/api/jobs").json()["jobs"])

    def test_while_open_with_grading_in_flight(self, api, llm):
        sid, path = start(api)
        llm.delay = 0.3
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        assert api.delete(f"/api/report/{sid}").status_code == 200
        time.sleep(0.5)
        assert self.gone(api, sid, path)
        assert api.get(f"/api/session/{sid}/status", headers=A).status_code == 404  # the tab finds out

    def test_while_the_report_waits_for_grading(self, api, monkeypatch):
        from openspeak.practice import session as session_mod

        async def slow_grade(*a, **kw):
            await anyio.sleep(0.4)
            raise RuntimeError("would log a turn_error")

        monkeypatch.setattr(session_mod, "grade", slow_grade)
        sid, path = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        api.post(f"/api/session/{sid}/finish", headers=A)  # waits for that grading
        assert api.delete(f"/api/report/{sid}").status_code == 200
        time.sleep(0.6)  # past when the grading would have ended
        assert self.gone(api, sid, path)

    def test_can_not_be_continued_while_being_deleted(self, api, monkeypatch):
        sid, path = start(api)
        monkeypatch.setattr(server, "_deleting", {sid})
        assert api.post(f"/api/session/{sid}/resume", json={}, headers=A).status_code == 404

    def test_not_while_another_process_writes_its_report(self, api, write_log, other_pid):
        path = write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in")], sid="20260101_120000")
        open(path + ".lock", "w").write(f"{other_pid} theirs")
        assert api.delete("/api/report/20260101_120000").status_code == 409 and os.path.exists(path)

    def test_one_that_was_put_away(self, api):
        sid, path = start(api)
        api.post(f"/api/session/{sid}/text", json={"text": "I want check in please"}, headers=A)
        api.post(f"/api/session/{sid}/leave", content="A")
        wait_until(lambda: sid not in server.live)
        assert api.delete(f"/api/report/{sid}").status_code == 200 and self.gone(api, sid, path)


class TestOldLogs:
    def test_repair_completes_a_session_that_was_never_ended(self, api, write_log):
        path = write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in")], sid="20260101_120000")
        api.post("/api/report/20260101_120000/repair")
        job = wait_job(api, "20260101_120000")
        assert job["stage"] == "ready" and job["regraded"] == 1 and job["complete"]
        assert os.path.exists(path[:-6] + ".html")

    def test_resume_answers_a_line_left_unanswered(self, api, write_log):
        write_log([("partner", 0, "Welcome"), ("heard", 1, "Is breakfast included?")], sid="20260101_120000")
        r = api.post("/api/session/20260101_120000/resume", json={}, headers=A).json()
        assert r["reply"]["text"]

    def test_another_process_owns_it(self, api, write_log, other_pid):
        path = write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in")], sid="20260101_120000")
        open(path + ".live", "w").write(str(other_pid))
        assert api.post("/api/session/20260101_120000/resume", json={}, headers=A).status_code == 409
        assert api.post("/api/report/20260101_120000/repair").status_code == 409
        assert api.delete("/api/report/20260101_120000").status_code == 409
        assert history(api, "20260101_120000")["live"]

    def test_corrupt_log_doesnt_break_history(self, api, home):
        with open(home / "sessions" / "session_20200101_000000.jsonl", "wb") as f:
            f.write(b'{"kind":"session_start"}\n[1,2]\n{"kind":"heard","turn":1,"said":"caf\xc3')
        assert api.get("/api/history").status_code == 200
        assert api.get("/report/20200101_000000").status_code == 200

    def test_markdown_download(self, api, write_log):
        write_log([("heard", 1, "I want check in"), ("turn", 1, "I want check in")], sid="20260101_120000")
        r = api.get("/report/20260101_120000.md")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")


def test_only_this_machine(llm):
    with TestClient(server.app, base_url="http://evil.example") as c:
        assert c.get("/api/history").status_code == 403


def test_page_and_assets_are_served(api):
    for url in ("/", "/static/app.js", "/static/app.css"):
        assert api.get(url).status_code == 200, url
    assert len(api.get("/api/meta").json()["scenes"]) > 0
