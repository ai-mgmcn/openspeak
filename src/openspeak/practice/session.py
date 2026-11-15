"""
A live practice session: the conversation with the partner, and its log.

Two model calls per learner turn, on purpose:
  - the PARTNER replies, and that reply is what you hear;
  - the GRADER (ai.grading) judges what you said, in the background, and its result
    goes only into the log. It never reaches the conversation.

What you said is written to the log the moment it's transcribed, before grading or
replying, so a crash or a closed tab can cost a correction but never the transcript.
A session can be picked back up from its log (resume), and whatever grading is
missing at the end is redone from the log by practice.completion.
"""

import asyncio
import contextlib
import inspect
import os
import re
import time
from datetime import datetime

from .. import config, fsutil, report
from ..ai import client, grading, prompts
from ..ai.grading import grade, grade_live, models, should_grade, timeout_for
from ..languages import resolve
from . import sessionlog as log
from .completion import complete

# How much conversation the partner sees. The log keeps all of it.
CHAT_HISTORY_MESSAGES = 40

_AID_SPLIT = re.compile(r"\n\s*-{3,}\s*(?:\n|$)")


def split_aid(text):
    """Spoken reply, on-screen aid (translation or hint)."""
    parts = _AID_SPLIT.split(text.strip(), maxsplit=1)
    spoken = parts[0].strip()
    aid = parts[1].strip() if len(parts) > 1 else ""
    return spoken, aid


class SessionClosed(Exception):
    """A turn arrived after End was pressed."""


class Session:
    def __init__(self, cfg, scene=None, hard=False, tab=None):
        self.cfg = cfg
        fsutil.private_dir(config.SESSIONS_DIR)
        self.started = datetime.now()
        # Two sessions started in the same second (a double click, two tabs) must
        # not share a log. O_EXCL claims the name atomically.
        stamp = self.started.strftime("%Y%m%d_%H%M%S")
        for n in range(1, 100):
            self.id = stamp if n == 1 else f"{stamp}_{n}"
            self.path = os.path.join(config.SESSIONS_DIR, f"session_{self.id}.jsonl")
            try:
                os.close(os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                break
            except FileExistsError:
                continue
        log.claim(self.path)
        langs = {k: resolve(v) for k, v in cfg["languages"].items()}
        self._setup(langs, cfg["level"], cfg["reply_mode"], scene, hard, tab)
        chat_model, grader_model = models(cfg)
        self._log(
            {
                "kind": "session_start",
                "at": log.now(),
                "languages": self.langs,
                "level": cfg["level"],
                "reply_mode": cfg["reply_mode"],
                "scene": {"id": scene["id"], "title": scene["title"], "prompt": scene["prompt"], "hard": hard}
                if scene else None,
                "chat_model": chat_model,
                "grader_model": grader_model,
            },
        )

    def _setup(self, langs, level, reply_mode, scene, hard, tab):
        self.langs = langs
        self.scene = scene
        self.turn = 0
        self.pending = set()
        self.graded = {}  # turn -> "ok" | "failed" | "skipped" | "later"
        self.done = False  # finished or put away; no more turns
        self.ending = False  # End pressed (or idle) and on its way to done
        self.finished = False  # ended with End: the report is written
        self.gone = False  # deleted: nothing more is written
        self.report = None
        self._finishing = asyncio.Lock()
        self._turns = asyncio.Lock()  # one turn at a time, so each reply is logged under its turn
        self.calls = 0  # turns and hints in progress
        self._quiet = asyncio.Event()  # no calls in progress
        self._quiet.set()
        self.tab = tab  # the browser tab that owns this session
        self.seen = time.monotonic()
        self.left = False  # the tab said it was closing
        self.history = [{"role": "system", "content": prompts.partner_system(langs, level, reply_mode, scene=scene, hard=hard)}]

    @classmethod
    def resume(cls, cfg, path, scene=None, tab=None):
        """
        Pick a log back up, ended or not. The partner sees the conversation so far
        (as much as it would have seen anyway), turn numbers carry on, and the next
        End regrades what's missing and rewrites the report to cover everything.
        """
        records = log.read(path)
        start = next((r for r in records if r["kind"] == "session_start"), None)
        if not start:
            raise ValueError("This log has no session start record.")
        if not log.claim(path):
            raise log.InUse()
        try:
            return cls._rebuild(cfg, path, records, start, scene, tab)
        except Exception:
            log.release(path)
            raise

    @classmethod
    def _rebuild(cls, cfg, path, records, start, scene, tab):
        s = cls.__new__(cls)
        s.cfg, s.path = cfg, path
        s.id = os.path.basename(path)[len("session_"):-len(".jsonl")]
        try:
            s.started = datetime.fromisoformat(start.get("at"))
        except (TypeError, ValueError):
            s.started = datetime.now()
        stored = start.get("scene")
        if stored and not scene:
            scene = {"id": stored.get("id"), "title": stored.get("title"), "prompt": stored.get("prompt") or "", "hard": None}
        langs = log.session_langs(records)
        s._setup(langs, start.get("level") or cfg["level"], start.get("reply_mode") or cfg["reply_mode"],
                 scene, bool(stored and stored.get("hard")), tab)
        s.history.append({"role": "user", "content": prompts.opening_request(langs)})
        for r in log.ordered(records):
            if r["kind"] == "heard":
                s.history.append({"role": "user", "content": r["said"]})
            else:
                aid = (r.get("aid") or "").strip()
                s.history.append({"role": "assistant", "content": r["said"] + (f"\n{prompts.AID_MARK}\n{aid}" if aid else "")})
        got = {r["turn"] for r in records if r["kind"] == "turn"}
        for r in records:
            if r["kind"] == "heard":
                s.turn = max(s.turn, r["turn"])
                s.graded[r["turn"]] = "ok" if r["turn"] in got else "later" if r.get("graded") else "skipped"
        s._log({"kind": "session_resume", "at": log.now()})
        return s

    def _log(self, record):
        """Every record goes through here, so a deleted session can't write its log back."""
        if not self.gone:
            log.append(self.path, record)

    def transcript(self):
        """The conversation so far, for redrawing it in the browser."""
        records = log.read(self.path)
        return [
            {"who": "me" if r["kind"] == "heard" else "ai", "turn": r["turn"], "said": r["said"],
             "aid": r.get("aid") or "", "state": self.graded.get(r["turn"]) if r["kind"] == "heard" else None}
            for r in log.ordered(records)
        ]

    async def catch_up(self):
        """
        Resumed after the learner spoke but before the partner answered: answer now.
        A turn still under way (the tab was reloaded mid-reply) answers it instead.
        """
        if self.closed:
            return None
        async with self._call(), self._turns:
            if self.history[-1]["role"] == "user" and len(self.history) > 2:
                return await self._partner(self.turn)
        return None

    def _window(self):
        # System prompt plus the recent exchange; old turns stay in the log.
        return [self.history[0]] + self.history[1:][-CHAT_HISTORY_MESSAGES:]

    async def _partner(self, turn):
        with grading.gate().partner_replying():
            raw = await grading.call(self.cfg, self._window(), want_json=False, model=models(self.cfg)[0])
        self.history.append({"role": "assistant", "content": raw})
        spoken, aid = split_aid(raw)
        self._log({"kind": "partner", "at": log.now(), "turn": turn, "said": spoken, "aid": aid})
        return {"text": spoken, "aid": aid}

    async def open(self):
        """The partner speaks first, so the learner never faces a blank screen."""
        self.history.append({"role": "user", "content": prompts.opening_request(self.langs)})
        return await self._partner(0)

    @property
    def closed(self):
        return self.done or self.ending

    def touch(self):
        self.seen = time.monotonic()
        self.left = False

    def fresh(self, within_s):
        return time.monotonic() - self.seen < within_s

    async def settled(self):
        """Return once a finish or put-away in progress is done."""
        async with self._finishing:
            pass

    @contextlib.asynccontextmanager
    async def _call(self):
        """A turn or a hint. Refused once End is pressed; End waits for those under way."""
        if self.closed:
            raise SessionClosed()
        self.calls += 1
        self._quiet.clear()
        try:
            yield
        finally:
            self.calls -= 1
            if not self.calls:
                self._quiet.set()
            self.touch()

    async def say(self, text):
        """
        A learner turn. `text` may still be on its way (an awaitable: the audio
        being transcribed). A turn begun before End counts; it just gets no reply.
        """
        try:
            async with self._call():
                return await self._say(await text if inspect.isawaitable(text) else text)
        finally:
            if inspect.iscoroutine(text):
                text.close()  # refused before it ran

    async def _say(self, text):
        text = (text or "").strip()
        if not text:
            return None
        async with self._turns:
            return await self._turn(text)

    async def _turn(self, text):
        self.turn += 1
        turn = self.turn
        will_grade = self.cfg["coach"]["enabled"] and should_grade(text, self.langs["target"])
        # Written before grading or replying: this line is the transcript.
        self._log({"kind": "heard", "at": log.now(), "turn": turn, "said": text, "graded": will_grade})

        # history[1] is the "begin the conversation" instruction, not the learner.
        snapshot = [m for m in self.history[2:] if m["role"] in ("user", "assistant")]
        if will_grade and not grade_live(self.cfg):
            self.graded[turn] = "later"  # finish() grades it from the log
        elif will_grade:
            task = asyncio.create_task(self._grade_and_log(turn, text, snapshot))
            self.pending.add(task)
            task.add_done_callback(self.pending.discard)
        else:
            self.graded[turn] = "skipped"

        self.history.append({"role": "user", "content": text})
        reply = {"text": "", "aid": ""} if self.ending else await self._partner(turn)
        return {"turn": turn, "heard": text, "graded": will_grade, **reply}

    async def _grade_and_log(self, turn, text, history):
        started = time.monotonic()
        try:
            analysis = await grade(self.cfg, self.langs, text, history)
        except Exception as e:
            print(f"grader: turn {turn} failed ({type(e).__name__}: {e})")
            self._log({"kind": "turn_error", "at": log.now(), "turn": turn, "said": text, "error": f"{type(e).__name__}: {e}"})
            self.graded[turn] = "failed"
            return
        self._log({"kind": "turn", "at": log.now(), "turn": turn, "said": text,
                   "latency_ms": int((time.monotonic() - started) * 1000), **analysis})
        self.graded[turn] = "ok"

    async def help(self):
        """The 💡 button: what could I say now? Logged, never graded."""
        async with self._call():
            return await self._help()

    async def _help(self):
        convo = "\n".join(
            f"{'Learner' if m['role'] == 'user' else 'Partner'}: {m['content']}"
            for m in self.history[2:][-8:]
        )
        raw = await grading.call(
            self.cfg,
            [{"role": "system", "content": prompts.help_system(self.langs)},
             {"role": "user", "content": convo or "(the partner has just opened the conversation)"}],
            model=models(self.cfg)[0],
        )
        data = client.parse_json(raw)
        say = data.get("say") if isinstance(data.get("say"), list) else []
        out = {"hint": client.text(data.get("hint")), "say": [s for s in say if isinstance(s, str)]}
        self._log({"kind": "help", "at": log.now(), "turn": self.turn, **out})
        return out

    def status(self):
        return {"turns": self.turn, "graded": self.graded, "pending": len(self.pending)}

    async def _settle(self):
        """
        Let turns under way land in the log, and wait for grading in flight; cancel
        what's still running (it's regraded from the log).
        """
        # A call that hangs (a stuck transcription) mustn't hold End forever.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._quiet.wait(), timeout_for(self.cfg, "finish_timeout"))
        if self.pending:
            _, still = await asyncio.wait(list(self.pending), timeout=timeout_for(self.cfg, "finish_timeout"))
            for task in still:
                task.cancel()
            if still:
                await asyncio.gather(*still, return_exceptions=True)

    async def finish(self, on_stage=None):
        """End: grade everything, summarise, write the report. None if nothing was said."""
        self.ending = True
        async with self._finishing:
            if self.finished or self.gone:
                return self.report
            # Put away while End was on its way: finish it from its log all the same.
            if self.done and not log.claim(self.path):
                raise log.InUse()
            try:
                await self._settle()
                if not log.has_talk(log.read(self.path)):
                    log.remove_log(self.path)  # only the partner's opening: nothing to keep
                    return None
                await complete(self.cfg, self.path, on_stage)
                self._log({"kind": "session_end", "at": log.now()})
                self.report = report.build(self.path)
                return self.report
            finally:
                self.done = self.finished = True
                log.release(self.path)

    def drop(self):
        """Being deleted: from now on nothing reaches the disk, and grading in flight stops."""
        self.gone = self.ending = True
        for task in self.pending:
            task.cancel()

    async def discard(self):
        """Being deleted: stop everything and let go."""
        self.drop()
        async with self._finishing:
            await asyncio.gather(*self.pending, return_exceptions=True)
            self.done = True
            log.release(self.path)

    async def put_away(self):
        """
        The tab is gone without End. Let grading in flight land in the log, then let
        go of the session: it can be continued or reported later, from the log.
        """
        self.ending = True
        async with self._finishing:
            if self.done:
                return
            try:
                await self._settle()
                if not log.has_talk(log.read(self.path)):
                    log.remove_log(self.path)
            finally:
                self.done = True
                log.release(self.path)

