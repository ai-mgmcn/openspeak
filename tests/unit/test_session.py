import os

import anyio
import pytest

from openspeak.practice import sessionlog as log
from openspeak.practice.session import Session, SessionClosed, split_aid

pytestmark = pytest.mark.anyio


def kinds(path):
    return [r["kind"] for r in log.read(path)]


async def started(cfg, **kw):
    s = Session(cfg, scene={"id": 8, "title": {"en": "Hotel"}, "prompt": "hotel desk"}, **kw)
    await s.open()
    return s


def test_split_aid():
    assert split_aid("Hello!\n---\n你好") == ("Hello!", "你好")
    assert split_aid("Hello!") == ("Hello!", "")


class TestNew:
    async def test_same_second_gets_a_new_id(self, cfg, llm, monkeypatch):
        from datetime import datetime

        from openspeak.practice import session as session_mod

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 1, 1, 12, 0, 0)

        monkeypatch.setattr(session_mod, "datetime", Frozen)  # a clock that never ticks over to the next second
        a, b = Session(cfg), Session(cfg)
        assert a.id != b.id and b.id.startswith(a.id)
        assert os.path.exists(a.path) and os.path.exists(b.path)

    async def test_claims_the_log(self, cfg, llm):
        s = await started(cfg)
        assert log.owner(s.path) == os.getpid()
        assert kinds(s.path) == ["session_start", "partner"]


class TestSay:
    async def test_writes_what_was_heard_before_replying(self, cfg, llm):
        s = await started(cfg)
        order = []
        llm.script["partner"] = lambda m: order.append(kinds(s.path)[-1]) or "Sure."
        r = await s.say("I want check in please")
        assert order == ["heard"]
        assert r["turn"] == 1 and r["text"] == "Sure." and r["graded"]

    async def test_grades_live_in_the_background(self, cfg, llm):
        s = await started(cfg)
        await s.say("I want check in please")
        await s._settle()
        assert s.graded == {1: "ok"}
        assert "turn" in kinds(s.path)

    async def test_local_model_grades_later(self, local_cfg, llm):
        s = await started(local_cfg)
        await s.say("I want check in please")
        assert s.graded == {1: "later"} and not s.pending
        assert "grade" not in llm.calls

    async def test_grading_failure_is_logged_not_raised(self, cfg, llm):
        llm.script["grade"] = RuntimeError("model down")
        s = await started(cfg)
        await s.say("I want check in please")
        await s._settle()
        assert s.graded == {1: "failed"}
        assert "turn_error" in kinds(s.path)

    async def test_grader_never_sees_the_opening_instruction(self, cfg, llm):
        seen = []
        llm.script["grade"] = lambda m: seen.append(m[1]["content"]) or '{"errors": []}'
        s = await started(cfg)
        await s.say("I want check in please")
        await s._settle()
        assert "Begin" not in seen[0] and "Sure, may I have your name?" in seen[0]

    async def test_refused_once_ending(self, cfg, llm):
        s = await started(cfg)
        s.ending = True
        with pytest.raises(SessionClosed):
            await s.say("hello there friend")
        with pytest.raises(SessionClosed):
            await s.help()


class TestConversationLimits:
    async def test_the_partner_sees_only_the_recent_conversation(self, cfg, llm, monkeypatch):
        from openspeak.practice import session as session_mod

        monkeypatch.setattr(session_mod, "CHAT_HISTORY_MESSAGES", 4)
        sizes = []
        llm.script["partner"] = lambda m: sizes.append(len(m)) or "Go on, please."
        s = await started(cfg)
        for n in range(6):
            await s.say(f"this is my sentence number {n}")
        assert max(sizes) == 1 + 4  # the instructions, then the last four messages
        assert sizes[0] < sizes[-1]  # and it grew until then
        assert [r["kind"] for r in log.read(s.path)].count("heard") == 6  # the log keeps everything

    async def test_nothing_is_graded_when_coaching_is_off(self, cfg, llm):
        cfg["coach"]["enabled"] = False
        s = await started(cfg)
        reply = await s.say("I want check in please")
        assert reply["graded"] is False and "grade" not in llm.calls and s.graded[1] == "skipped"

    async def test_short_filler_is_not_graded(self, cfg, llm):
        s = await started(cfg)
        await s.say("okay thanks")
        assert "grade" not in llm.calls and s.graded[1] == "skipped"


class TestEnding:
    async def test_finish_grades_and_writes_the_report(self, local_cfg, llm):
        s = await started(local_cfg)
        await s.say("I want check in please")
        stages = []
        report = await s.finish(stages.append)
        assert stages == ["grading", "writing"]
        assert os.path.exists(report["html"])
        assert {"turn", "summary", "vocab", "session_end"} <= set(kinds(s.path))
        assert s.done and log.owner(s.path) is None

    async def test_finish_with_nothing_said_removes_the_log(self, cfg, llm):
        s = await started(cfg)
        assert await s.finish() is None
        assert not os.path.exists(s.path)

    async def test_put_away_keeps_the_log_and_lets_go(self, cfg, llm):
        s = await started(cfg)
        await s.say("I want check in please")
        await s.put_away()
        assert s.done and log.owner(s.path) is None
        assert "session_end" not in kinds(s.path)

    async def test_finish_twice_is_one_finish(self, local_cfg, llm):
        s = await started(local_cfg)
        await s.say("I want check in please")
        async with anyio.create_task_group() as tg:
            tg.start_soon(s.finish)
            tg.start_soon(s.finish)
        assert kinds(s.path).count("session_end") == 1


class TestResume:
    async def test_rebuilds_the_conversation(self, cfg, llm, write_log):
        path = write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in"), ("turn", 1, "I want check in"),
                          ("partner", 1, "Name?"), ("heard", 2, "Li", False), ("partner", 2, "Thanks")])
        s = Session.resume(cfg, path)
        assert s.turn == 2
        assert s.graded == {1: "ok", 2: "skipped"}
        assert [m["role"] for m in s.history] == ["system", "user", "assistant", "user", "assistant", "user", "assistant"]
        assert s.scene["title"] == {"en": "Hotel"}
        assert [t["who"] for t in s.transcript()] == ["ai", "me", "ai", "me", "ai"]
        r = await s.say("Is breakfast included?")
        assert r["turn"] == 3

    async def test_ungraded_turn_is_graded_later(self, cfg, llm, write_log):
        s = Session.resume(cfg, write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in")]))
        assert s.graded == {1: "later"}

    async def test_catch_up_answers_an_unanswered_line(self, cfg, llm, write_log):
        s = Session.resume(cfg, write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in")]))
        assert (await s.catch_up())["text"] == llm.REPLY

    async def test_nothing_to_catch_up(self, cfg, llm, write_log):
        s = Session.resume(cfg, write_log([("partner", 0, "Welcome")]))
        assert await s.catch_up() is None

    async def test_refused_while_another_process_has_it(self, cfg, write_log, other_pid):
        path = write_log([("partner", 0, "Welcome")])
        open(path + ".live", "w").write(str(other_pid))
        with pytest.raises(log.InUse):
            Session.resume(cfg, path)

    async def test_releases_the_claim_if_the_log_is_unusable(self, cfg, write_log):
        path = write_log([])
        with open(path, "w") as f:
            f.write('{"kind":"heard","turn":1,"said":"no start record"}\n')
        with pytest.raises(ValueError):
            Session.resume(cfg, path)
        assert log.owner(path) is None


class TestEdges:
    async def test_blank_input_is_ignored(self, cfg, llm):
        s = await started(cfg)
        assert await s.say("   ") is None
        assert kinds(s.path) == ["session_start", "partner"] and s.status()["turns"] == 0

    async def test_too_short_to_grade_is_skipped(self, cfg, llm):
        s = await started(cfg)
        await s.say("ok thanks")
        assert s.status() == {"turns": 1, "graded": {1: "skipped"}, "pending": 0}
        assert "grade" not in llm.calls

    async def test_help_is_logged_not_graded(self, cfg, llm):
        s = await started(cfg)
        out = await s.help()
        assert out["say"] == ["Is breakfast included?"]
        assert kinds(s.path)[-1] == "help" and llm.calls == ["partner", "help"]

    async def test_put_away_cancels_grading_that_runs_too_long(self, cfg, llm, monkeypatch):
        from openspeak.practice import session as session_mod

        async def stuck(*a, **kw):
            await anyio.sleep(30)

        monkeypatch.setattr(session_mod, "grade", stuck)
        cfg["coach"]["finish_timeout"] = 0.05
        s = await started(cfg)
        await s.say("I want check in please")
        with anyio.fail_after(2):
            await s.put_away()
        assert s.done and not s.pending and "turn" not in kinds(s.path)  # regraded from the log later

    async def test_put_away_with_nothing_said_removes_the_log(self, cfg, llm):
        s = await started(cfg)
        await s.put_away()
        await s.put_away()  # second call: nothing left to do
        assert not os.path.exists(s.path) and log.owner(s.path) is None

    async def test_resume_releases_the_claim_if_rebuilding_fails(self, cfg, write_log, monkeypatch):
        path = write_log([("partner", 0, "Welcome")])

        def broken(*a, **kw):
            raise RuntimeError("bad scene")

        monkeypatch.setattr(Session, "_rebuild", classmethod(lambda cls, *a: broken()))
        with pytest.raises(RuntimeError):
            Session.resume(cfg, path)
        assert log.owner(path) is None

    async def test_resume_survives_a_bad_start_time(self, cfg, write_log):
        path = write_log([{"kind": "session_start", "at": "not a time", "level": "B1"}, ("partner", 0, "Welcome")])
        s = Session.resume(cfg, path)
        assert s.started and s.transcript()[0]["said"] == "Welcome"


class TestOverlap:
    """Things that happen at the same time land in the log as they would one after another."""

    async def test_overlapping_turns_each_get_their_own_reply(self, cfg, llm):
        llm.delay = 0.05
        s = await started(cfg)
        async with anyio.create_task_group() as tg:
            tg.start_soon(s.say, "I want check in please")
            await anyio.sleep(0.01)
            tg.start_soon(s.say, "Is breakfast included?")
        spoken = [(r["kind"], r["turn"]) for r in log.ordered(log.read(s.path))]
        assert spoken == [("partner", 0), ("heard", 1), ("partner", 1), ("heard", 2), ("partner", 2)]

    async def test_end_doesnt_wait_forever_for_a_call_that_hangs(self, cfg, llm):
        cfg["coach"]["finish_timeout"] = 0.2
        s = await started(cfg)
        stuck = anyio.Event()  # a transcription that never comes back

        async def never():
            await stuck.wait()

        async with anyio.create_task_group() as tg:
            tg.start_soon(s.say, never())
            await anyio.sleep(0.01)
            with anyio.fail_after(3):
                await s.finish()
            tg.cancel_scope.cancel()
        assert s.finished

    async def test_end_waits_for_a_turn_under_way_and_keeps_it(self, cfg, llm):
        s = await started(cfg)
        ear = anyio.Event()

        async def transcribing():
            await ear.wait()
            return "I want check in please"

        async with anyio.create_task_group() as tg:
            tg.start_soon(s.say, transcribing())
            await anyio.sleep(0.01)
            tg.start_soon(s.finish)
            await anyio.sleep(0.01)
            ear.set()
        assert s.finished and s.report
        assert kinds(s.path).count("heard") == 1 and llm.calls.count("partner") == 1  # no reply after End

    async def test_a_turn_refused_after_end_doesnt_leave_its_transcription_running(self, cfg, llm):
        s = await started(cfg)
        s.ending = True

        async def transcribing():
            raise AssertionError("ran")

        with pytest.raises(SessionClosed):
            await s.say(transcribing())

    async def test_end_while_being_put_away_still_writes_the_report(self, cfg, llm):
        s = await started(cfg)
        await s.say("I want check in please")
        async with anyio.create_task_group() as tg:
            tg.start_soon(s.put_away)
            await anyio.sleep(0)
            got = []
            tg.start_soon(lambda: _into(got, s.finish()))
        assert got[0] and kinds(s.path)[-1] == "session_end" and log.owner(s.path) is None

    async def test_catch_up_waits_for_a_reply_under_way_instead_of_answering_twice(self, cfg, llm):
        llm.delay = 0.05
        s = await started(cfg)
        got = []
        async with anyio.create_task_group() as tg:
            tg.start_soon(s.say, "I want check in please")
            await anyio.sleep(0.01)
            tg.start_soon(lambda: _into(got, s.catch_up()))
        assert got == [None] and llm.calls.count("partner") == 2  # the opening and one reply

    async def test_nothing_is_written_once_deleted(self, cfg, llm, monkeypatch):
        from openspeak.practice import session as session_mod

        graded = anyio.Event()

        async def slow_grade(*a, **kw):
            await graded.wait()
            raise RuntimeError("would log a turn_error")

        monkeypatch.setattr(session_mod, "grade", slow_grade)
        llm.delay = 0.05
        s = await started(cfg)
        async with anyio.create_task_group() as tg:
            tg.start_soon(s.say, "I want check in please")
            await anyio.sleep(0.01)
            s.drop()
            os.remove(s.path)
        graded.set()
        await s.discard()
        assert not os.path.exists(s.path)


async def _into(out, coro):
    out.append(await coro)
