import time

import anyio
import pytest

from openspeak.practice import live as live_mod
from openspeak.practice import sessionlog as log
from openspeak.practice.live import Elsewhere, LiveSessions, NotFound
from openspeak.practice.session import Session

pytestmark = pytest.mark.anyio


@pytest.fixture
def live():
    return LiveSessions()


async def open_session(live, cfg, tab="A"):
    s = Session(cfg, tab=tab)
    await s.open()
    live.add(s)
    return s


class TestOwnership:
    async def test_only_the_owner_tab_gets_it(self, live, cfg, llm):
        s = await open_session(live, cfg)
        assert live.owned(s.id, "A") is s
        with pytest.raises(Elsewhere):
            live.owned(s.id, "B")
        with pytest.raises(NotFound):
            live.owned("nope", "A")

    async def test_resume_from_another_tab_needs_take(self, live, cfg, llm):
        s = await open_session(live, cfg)
        with pytest.raises(Elsewhere):
            await live.resume(cfg, s.path, s.id, None, "B")
        assert await live.resume(cfg, s.path, s.id, None, "B", take=True) is s
        assert s.tab == "B"

    async def test_a_quiet_owner_tab_is_taken_over_without_asking(self, live, cfg, llm):
        s = await open_session(live, cfg)
        s.seen -= live_mod.OWNER_FRESH_S + 1
        assert await live.resume(cfg, s.path, s.id, None, "B") is s

    async def test_resume_rebuilds_from_the_log_when_not_in_memory(self, live, cfg, llm, write_log):
        path = write_log([("partner", 0, "Welcome")], sid="20260101_120000")
        s = await live.resume(cfg, path, "20260101_120000", None, "A")
        assert s.id in live and log.owner(path) is not None

    async def test_resume_waits_for_a_put_away_in_progress(self, live, cfg, llm):
        s = await open_session(live, cfg)
        await s.say("I want check in please")
        llm.delay = 0.1  # grading still running when put_away starts
        async with anyio.create_task_group() as tg:
            tg.start_soon(s.put_away)
            await anyio.sleep(0)
            again = await live.resume(cfg, s.path, s.id, None, "A")
        assert again is not s and not again.closed


class TestReaping:
    async def test_idle_rules(self, live, cfg, llm):
        a = await open_session(live, cfg)
        b = await open_session(live, cfg)
        c = await open_session(live, cfg)
        now = time.monotonic()
        live.leave(a.id, "A")  # tab closed
        live.leave(b.id, "Z")  # not the owner: ignored
        c.calls = 1  # a turn in progress
        soon = now + live_mod.LEFT_GRACE_S + 1
        assert live.idle(soon) == [a]
        later = now + live_mod.IDLE_S + 1
        assert set(live.idle(later)) == {a, b}

    async def test_reap_puts_sessions_away_and_drops_them(self, live, cfg, llm, monkeypatch):
        s = await open_session(live, cfg)
        await s.say("I want check in please")
        monkeypatch.setattr(live_mod, "IDLE_S", -1)
        live.reap()
        with anyio.fail_after(2):
            while s.id in live:
                await anyio.sleep(0.01)
        assert s.done and log.owner(s.path) is None
        assert not live._closing

    async def test_shutdown_releases_every_claim(self, live, cfg, llm):
        s = await open_session(live, cfg)
        await live.shutdown()
        assert log.owner(s.path) is None and s.id not in live


async def test_the_reaper_outlives_an_error(live, monkeypatch, capsys):
    monkeypatch.setattr(live_mod, "REAP_EVERY_S", 0.01)
    calls = []

    def reap():
        calls.append(1)
        raise RuntimeError("one bad session")

    monkeypatch.setattr(live, "reap", reap)
    live.start_reaper()
    live.start_reaper()  # one reaper only
    with anyio.fail_after(2):
        while len(calls) < 2:
            await anyio.sleep(0.01)
    assert "reaper: RuntimeError" in capsys.readouterr().out
    await live.shutdown()
