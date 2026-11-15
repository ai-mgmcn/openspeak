import anyio
import pytest

from openspeak.practice import jobs as jobs_mod
from openspeak.practice import sessionlog as log
from openspeak.practice.jobs import Jobs

pytestmark = pytest.mark.anyio


async def settle(job):
    with anyio.fail_after(2):
        await job.task


async def test_reports_stages_then_the_result(write_log):
    jobs = Jobs()
    gate = anyio.Event()

    async def work(on_stage):
        on_stage("grading")
        await gate.wait()
        on_stage("writing")
        return {"regraded": 1}

    job = jobs.start("s1", "repair", write_log([]), {"en": "Hotel"}, work)
    await anyio.sleep(0)
    assert job.view()["stage"] == "grading" and "progress" in job.view()
    assert jobs.running("s1")
    gate.set()
    await settle(job)
    view = jobs.views()[0]
    assert view["stage"] == "ready" and view["regraded"] == 1 and not jobs.running("s1")


async def test_progress_is_not_reread_on_every_poll(write_log, monkeypatch):
    path = write_log([("heard", 1, "hi there my friend"), ("heard", 2, "how are you")])
    job = Jobs().start("s1", "finish", path, None, lambda on_stage: anyio.sleep(10))
    reads = []
    real = log.read
    monkeypatch.setattr(log, "read", lambda p: reads.append(p) or real(p))
    first = [job.progress() for _ in range(5)]
    assert len(reads) == 1 and first[0] == first[-1]
    monkeypatch.setattr(jobs_mod, "PROGRESS_CACHE_S", 0)
    job.progress()
    assert len(reads) == 2
    job.task.cancel()


async def test_cancelling_stops_the_work_itself(write_log):
    jobs = Jobs()
    ran_on = []

    async def work(on_stage):
        await anyio.sleep(0.2)
        ran_on.append("finished")  # must never be reached

    job = jobs.start("s1", "finish", write_log([]), None, work)
    await anyio.sleep(0.01)
    await jobs.cancel("s1")
    await anyio.sleep(0.3)  # long enough for the work to have finished had it been left running
    assert ran_on == [] and job.task.cancelled() and not jobs.running("s1")


async def test_shutdown_stops_what_is_still_running(write_log):
    jobs = Jobs()
    job = jobs.start("s1", "finish", write_log([]), None, lambda on_stage: anyio.sleep(10))
    await anyio.sleep(0)
    await jobs.cancel_all()
    assert job.task.cancelled() or job.task.done()
    assert not jobs.running("s1")


async def test_one_job_per_session(write_log):
    jobs = Jobs()
    gate = anyio.Event()

    async def work(on_stage):
        await gate.wait()

    a = jobs.start("s1", "finish", write_log([]), None, work)
    b = jobs.start("s1", "repair", write_log([]), None, work)
    assert a is b
    gate.set()
    await settle(a)


async def test_failures_are_reported_not_raised(write_log):
    jobs = Jobs()

    async def busy(on_stage):
        raise log.InUse()

    async def broken(on_stage):
        raise RuntimeError("disk full")

    a = jobs.start("a", "repair", write_log([]), None, busy)
    b = jobs.start("b", "repair", write_log([]), None, broken)
    await settle(a)
    await settle(b)
    assert a.stage == b.stage == "failed"
    assert "another OpenSpeak window" in a.error and "disk full" in b.error


async def test_finished_jobs_are_forgotten_after_a_while(write_log, monkeypatch):
    jobs = Jobs()

    async def work(on_stage):
        return {}

    job = jobs.start("s1", "repair", write_log([]), None, work)
    await settle(job)
    assert len(jobs.views()) == 1
    monkeypatch.setattr(jobs_mod, "KEEP_DONE_S", -1)
    assert jobs.views() == []


async def test_progress_counts_graded_turns(write_log):
    path = write_log([("heard", 1, "a b c"), ("heard", 2, "d e f"), ("heard", 3, "hi", False), ("turn", 1, "a b c")])
    job = jobs_mod.Job("s", "finish", path, None)
    assert job.progress() == {"done": 1, "total": 2}


async def test_shutdown_waits_a_moment_for_running_jobs(write_log):
    jobs = Jobs()
    done = []

    async def quick(on_stage):
        await anyio.sleep(0.01)
        done.append(1)
        return {}

    async def slow(on_stage):
        await anyio.sleep(30)

    jobs.start("a", "finish", write_log([], sid="20260101_120000"), None, quick)
    jobs.start("b", "finish", write_log([], sid="20260101_120001"), None, slow)
    with anyio.fail_after(2):
        await jobs.wait_all(timeout=0.2)
    assert done == [1] and jobs.running("b")
    jobs._jobs["b"].task.cancel()
    await Jobs().wait_all(timeout=1)  # nothing running: returns at once
