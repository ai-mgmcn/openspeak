"""
The sessions open in this process, and how they come and go:

    start / resume ──► live ──End──► finishing (a background job) ──► gone, report on disk
                        │
                        └── tab gone or idle ──► put away ──► gone, log on disk (can resume)

A live session belongs to one browser tab. Another tab can take it over; the old
tab finds out on its next request (409, code "elsewhere"). Nothing stays in memory
for a tab that's gone: the reaper puts idle sessions away, and the log on disk is
all that's needed to continue or report them later.
"""

import asyncio
import time

from . import sessionlog as log
from .session import Session

IDLE_S = 30 * 60  # no request from the tab for this long: put away
LEFT_GRACE_S = 20  # the tab said it was closing; a reload is back well within this
OWNER_FRESH_S = 15  # the owner tab polls every few seconds; quieter than this, it's gone
REAP_EVERY_S = 10


class NotFound(Exception):
    pass


class Elsewhere(Exception):
    """The session is open in another tab (here) or another OpenSpeak process."""


class LiveSessions:
    def __init__(self):
        self._live = {}
        self._reaper = None
        self._closing = set()  # put_away tasks, kept referenced until done

    def __contains__(self, sid):
        return sid in self._live

    def get(self, sid):
        return self._live.get(sid)

    def add(self, session):
        self._live[session.id] = session

    def remove(self, session):
        if self._live.get(session.id) is session:
            del self._live[session.id]

    def owned(self, sid, tab):
        """The session, if this tab owns it."""
        s = self._live.get(sid)
        if not s or s.done:
            raise NotFound()
        if s.tab and tab != s.tab:
            raise Elsewhere()
        return s

    async def resume(self, cfg, path, sid, scene, tab, take=False):
        """
        Continue a session: attach to it if it's still in memory, otherwise rebuild
        it from its log. `take` moves it away from another tab that still has it open.
        """
        while True:
            s = self._live.get(sid)
            if not s:
                if log.in_use_elsewhere(path):
                    raise Elsewhere()
                # No await between the check and add(): two resumes can't both build one.
                s = Session.resume(cfg, path, scene=scene, tab=tab)
                self.add(s)
                return s
            if not s.closed:
                if s.tab != tab and s.fresh(OWNER_FRESH_S) and not take:
                    raise Elsewhere()
                s.tab = tab
                s.touch()
                return s
            # Being finished or put away: let that land in the log, then continue from it.
            await s.settled()
            self.remove(s)

    async def discard(self, s):
        """The session is being deleted: close it now. Its tab hears 404 next time it asks."""
        self.remove(s)
        await s.discard()

    def leave(self, sid, tab):
        s = self._live.get(sid)
        if s and s.tab == tab:
            s.left = True

    def idle(self, now=None):
        now = now or time.monotonic()
        return [
            s for s in self._live.values()
            if not s.closed and not s.calls
            and now - s.seen > (LEFT_GRACE_S if s.left else IDLE_S)
        ]

    async def _put_away(self, s):
        try:
            await s.put_away()
        finally:
            self.remove(s)

    def reap(self):
        for s in self.idle():
            task = asyncio.create_task(self._put_away(s))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

    async def _reap_forever(self):
        while True:
            await asyncio.sleep(REAP_EVERY_S)
            try:
                self.reap()
            except Exception as e:  # the reaper must outlive any one bad session
                print(f"reaper: {type(e).__name__}: {e}")

    def start_reaper(self):
        if not self._reaper:
            self._reaper = asyncio.create_task(self._reap_forever())

    async def shutdown(self):
        if self._reaper:
            self._reaper.cancel()
            self._reaper = None
        # Logs are complete on disk already; just stop claiming them.
        for s in list(self._live.values()):
            log.release(s.path)
        self._live.clear()
