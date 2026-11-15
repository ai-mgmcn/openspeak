"""
Background work the browser shouldn't wait on: finishing a session, completing an
old report. Jobs run in the server, so closing the tab doesn't stop them. The page
polls /api/jobs for progress and is told when each report is ready.

One job per session at a time; asking again while one runs returns the same job.
Finished jobs are kept a few minutes so a reloaded page still hears about them,
then dropped.
"""

import asyncio
import time

from . import sessionlog as log

KEEP_DONE_S = 10 * 60
PROGRESS_CACHE_S = 1

# Stages, in order. completion.complete() also reports "writing" (a plain string, which the page keys on).
QUEUED, GRADING, READY, FAILED = "queued", "grading", "ready", "failed"


class Job:
    def __init__(self, sid, kind, path, scene):
        self.sid = sid
        self.kind = kind  # "finish" | "repair"
        self.path = path
        self.scene = scene  # title dict, for the progress card
        self.stage = QUEUED
        self.result = {}
        self.error = ""
        self.ended_at = None
        self.task = None
        self._progress = None

    @property
    def running(self):
        return self.ended_at is None

    def set_stage(self, stage):
        self.stage = stage

    def progress(self):
        """Turns graded so far, counted from the log (grading writes there directly). Re-read at most once a second."""
        now = time.monotonic()
        if not self._progress or now - self._progress[0] > PROGRESS_CACHE_S:
            records = log.read(self.path)
            want = {r["turn"] for r in records if r["kind"] == "heard" and r.get("graded")}
            got = {r["turn"] for r in records if r["kind"] == "turn"}
            self._progress = (now, {"done": len(want & got), "total": len(want)})
        return self._progress[1]

    def view(self):
        out = {"id": self.sid, "kind": self.kind, "stage": self.stage, "scene": self.scene,
               "error": self.error, **self.result}
        if self.stage == GRADING:
            out["progress"] = self.progress()
        return out


class Jobs:
    def __init__(self):
        self._jobs = {}

    def start(self, sid, kind, path, scene, work):
        """
        Run `work(on_stage)` in the background. It returns a dict that's merged into
        the job's view when it's done (e.g. {"empty": True}).
        """
        self.prune()
        job = self._jobs.get(sid)
        if job and job.running:
            return job
        job = self._jobs[sid] = Job(sid, kind, path, scene)
        job.task = asyncio.create_task(self._run(job, work))
        return job

    async def _run(self, job, work):
        try:
            job.result = await work(job.set_stage) or {}
            job.stage = READY
        except log.InUse:
            job.stage, job.error = FAILED, "This session is open in another OpenSpeak window."
        except Exception as e:
            job.stage, job.error = FAILED, f"{type(e).__name__}: {e}"
            print(f"job {job.kind} {job.sid}: failed ({job.error})")
        finally:
            job.ended_at = time.monotonic()

    def running(self, sid):
        job = self._jobs.get(sid)
        return bool(job and job.running)

    async def cancel(self, sid):
        """Stop a session's job and forget it: the session is being deleted."""
        job = self._jobs.pop(sid, None)
        if job and job.running:
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)

    def views(self):
        self.prune()
        return [j.view() for j in self._jobs.values()]

    def prune(self):
        now = time.monotonic()
        for sid, job in list(self._jobs.items()):
            if not job.running and now - job.ended_at > KEEP_DONE_S:
                del self._jobs[sid]

    async def wait_all(self, timeout):
        """At shutdown: give running jobs a moment; what's cut off is completed next time."""
        tasks = [j.task for j in self._jobs.values() if j.running]
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)

    async def cancel_all(self):
        """Stop whatever is still running, so nothing writes to a log after its claim is let go."""
        tasks = [j.task for j in self._jobs.values() if j.running]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
