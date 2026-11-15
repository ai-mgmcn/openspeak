import os
import time

import anyio
import pytest

from openspeak.practice import sessionlog as log


def vanish(monkeypatch, path):
    """The file goes away just as its age is looked up, as when another process lets go."""
    real = os.path.getmtime

    def getmtime(p):
        if p == path:
            if os.path.exists(p):
                os.remove(p)
            raise FileNotFoundError(p)
        return real(p)

    monkeypatch.setattr(os.path, "getmtime", getmtime)


class TestRead:
    def test_skips_garbage_and_malformed_records(self, home):
        path = str(home / "sessions" / "session_x.jsonl")
        with open(path, "wb") as f:
            f.write(b'{"kind":"session_start"}\n'
                    b'[1,2]\n"str"\nnot json\n'
                    b'{"kind":"heard","said":"no turn"}\n'
                    b'{"kind":"heard","turn":"1","said":"turn is a string"}\n'
                    b'{"kind":"heard","turn":1,"said":"ok"}\n'
                    b'{"kind":"heard","turn":2,"said":"caf\xc3')  # cut off mid-character by a crash
        records = log.read(path)
        assert [r["kind"] for r in records] == ["session_start", "heard"]
        assert records[1]["said"] == "ok"

    def test_coerces_turn_fields_to_strings(self, write_log):
        path = write_log([{"kind": "turn", "turn": 1, "said": "x", "corrected": 5, "native_version": None,
                           "errors": [], "good_note": ["a"]}])
        turn = log.read(path)[1]
        assert all(isinstance(turn[k], str) for k in ("corrected", "native_version", "good_note"))


class TestRules:
    def test_ordered_puts_each_reply_after_its_turn(self, write_log):
        path = write_log([("partner", 0, "Welcome"), ("partner", 1, "Sure"), ("heard", 1, "I want check in"),
                          ("heard", 2, "  ")])
        assert [(r["kind"], r["turn"]) for r in log.ordered(log.read(path))] == \
            [("partner", 0), ("heard", 1), ("partner", 1)]

    def test_summary_is_outdated_after_new_talk(self, write_log):
        assert log.outdated(log.read(write_log([("heard", 1, "a b c")]))) == {"summary", "vocab"}
        done = write_log([("heard", 1, "a b c"), "summary", "vocab"], sid="2")
        assert log.outdated(log.read(done)) == set()
        resumed = write_log([("heard", 1, "a b c"), "summary", "vocab", ("heard", 2, "more words here")], sid="3")
        assert log.outdated(log.read(resumed)) == {"summary", "vocab"}

    def test_ended_only_if_nothing_said_or_resumed_since(self, write_log):
        assert log.ended(log.read(write_log([("heard", 1, "x"), "session_end"])))
        assert not log.ended(log.read(write_log([("heard", 1, "x")], sid="2")))
        assert not log.ended(log.read(write_log([("heard", 1, "x"), "session_end", "session_resume"], sid="3")))

    def test_a_log_with_no_talk_is_neither_ended_nor_outdated(self, write_log):
        quiet = log.read(write_log([("partner", 0, "Welcome")]))
        assert not log.ended(quiet) and log.outdated(quiet) == set()

    def test_has_talk_ignores_the_partner_opening(self, write_log):
        assert not log.has_talk(log.read(write_log([("partner", 0, "Welcome")])))


class TestOwnership:
    def test_claim_and_release(self, write_log):
        path = write_log([])
        assert log.claim(path) and log.owner(path) == os.getpid()
        assert log.claim(path)  # claiming again is fine for the owner
        assert not log.in_use_elsewhere(path)
        log.release(path)
        assert log.owner(path) is None and not os.path.exists(path + ".live")

    def test_live_other_process_keeps_it(self, write_log, other_pid):
        path = write_log([])
        open(path + ".live", "w").write(str(other_pid))
        assert log.in_use_elsewhere(path)
        assert not log.claim(path)
        log.release(path)  # not ours: left alone
        assert os.path.exists(path + ".live")

    def test_dead_owner_is_cleared(self, write_log, dead_pid):
        path = write_log([])
        open(path + ".live", "w").write(str(dead_pid))
        assert not log.in_use_elsewhere(path)
        assert not os.path.exists(path + ".live")
        assert log.claim(path)

    def test_empty_file_is_being_claimed_until_old(self, write_log):
        path = write_log([])
        open(path + ".live", "w").close()
        assert log.owner(path) == -1
        old = time.time() - 60
        os.utime(path + ".live", (old, old))
        assert log.owner(path) is None

    def test_remove_log_takes_everything_with_it(self, write_log):
        path = write_log([])
        base = path[:-len(".jsonl")]
        for p in (base + ".html", base + ".md", path + ".lock", path + ".live"):
            open(p, "w").close()
        log.remove_log(path)
        assert not os.listdir(os.path.dirname(path))


@pytest.mark.anyio
class TestExclusive:
    async def test_second_holder_waits_for_the_first(self, write_log):
        path = write_log([])
        order = []

        async def hold(name, hold_s):
            async with log.exclusive(path, wait_s=10):
                order.append(f"{name} in")
                await anyio.sleep(hold_s)
                order.append(f"{name} out")

        async with anyio.create_task_group() as tg:
            tg.start_soon(hold, "a", 0.2)
            await anyio.sleep(0.05)
            tg.start_soon(hold, "b", 0)
        assert order == ["a in", "a out", "b in", "b out"]
        assert not os.path.exists(path + ".lock")

    async def test_stale_lock_is_taken_over(self, write_log):
        path = write_log([])
        open(path + ".lock", "w").close()
        old = time.time() - log.LOCK_STALE_S - 1
        os.utime(path + ".lock", (old, old))
        with anyio.fail_after(2):
            async with log.exclusive(path, wait_s=10):
                pass

    async def test_lock_released_while_being_checked(self, write_log, monkeypatch):
        path = write_log([])
        open(path + ".lock", "w").close()
        vanish(monkeypatch, path + ".lock")
        with anyio.fail_after(2):
            async with log.exclusive(path, wait_s=10):
                pass


class TestEdges:
    def test_missing_log_reads_as_empty(self, home):
        assert log.read(str(home / "sessions" / "session_nope.jsonl")) == []

    def test_blank_lines_and_bad_said_are_skipped(self, write_log):
        path = write_log([("heard", 1, "hello there")])
        with open(path, "a") as f:
            f.write('\n\n{"kind":"heard","turn":2,"said":42}\n')
        assert [r["kind"] for r in log.read(path)] == ["session_start", "heard"]

    def test_unreadable_owner_file_counts_as_being_claimed(self, write_log):
        path = write_log([])
        open(path + ".live", "w").write("not a pid")
        assert log.owner(path) == -1

    def test_owner_file_gone_while_being_checked(self, write_log, monkeypatch):
        path = write_log([])
        open(path + ".live", "w").close()
        vanish(monkeypatch, path + ".live")
        assert log.owner(path) is None

    def test_claim_takes_over_from_a_dead_owner(self, write_log, dead_pid):
        path = write_log([])
        open(path + ".live", "w").write(str(dead_pid))
        assert log.claim(path) and log.owner(path) == os.getpid()
        assert log.claim(path)  # already ours
        log.release(path)
        log.release(path)  # nothing left to release
        assert log.owner(path) is None


def test_a_line_cut_short_by_a_crash_doesnt_swallow_the_next(write_log):
    path = write_log([("partner", 0, "Welcome")])
    with open(path, "a") as f:
        f.write('{"kind": "heard", "tu')
    log.append(path, {"kind": "heard", "turn": 1, "said": "hello there"})
    assert [r["kind"] for r in log.read(path)][-1] == "heard"


@pytest.mark.anyio
class TestLockOwnership:
    async def test_a_live_holder_isnt_taken_over_after_waiting(self, write_log, other_pid):
        path = write_log([])
        with open(path + ".lock", "w") as f:
            f.write(f"{other_pid} theirs")
        with anyio.fail_after(5), pytest.raises(log.InUse):
            async with log.exclusive(path, wait_s=1):
                pass
        assert open(path + ".lock").read() == f"{other_pid} theirs" and log.locked_elsewhere(path)

    async def test_a_dead_holders_lock_is_taken_over(self, write_log):
        path = write_log([])
        with open(path + ".lock", "w") as f:
            f.write("999999999 gone")
        with anyio.fail_after(2):
            async with log.exclusive(path, wait_s=10):
                assert not log.locked_elsewhere(path)
        assert not os.path.exists(path + ".lock")

    async def test_a_holder_never_removes_a_lock_that_isnt_its_own(self, write_log):
        path = write_log([])
        async with log.exclusive(path, wait_s=10):
            with open(path + ".lock", "w") as f:
                f.write("1 someone-else")  # taken over meanwhile
        assert os.path.exists(path + ".lock")


@pytest.mark.anyio
class TestLeftByAnEarlierRun:
    async def test_a_lock_with_our_pid_that_we_dont_hold_is_taken_over(self, write_log):
        # In a container the app is always pid 1, so a crashed run's lock has the pid of this one.
        path = write_log([])
        with open(path + ".lock", "w") as f:
            f.write(f"{os.getpid()} left-by-the-run-that-crashed")
        assert not log.locked_elsewhere(path)
        with anyio.fail_after(2):
            async with log.exclusive(path, wait_s=0):
                pass

    async def test_a_lock_this_process_holds_still_keeps_others_out(self, write_log):
        path = write_log([])
        async with log.exclusive(path, wait_s=0):
            with pytest.raises(log.InUse):
                async with log.exclusive(path, wait_s=0):
                    pass
