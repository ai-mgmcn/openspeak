"""
The session log: one JSONL file per session, and the small files beside it.

    session_<id>.jsonl   the log. Append-only; the one source of truth.
    session_<id>.html/md reports, rebuilt from the log whenever it's newer
    session_<id>.jsonl.live   present while a process has the session open (holds its pid)
    session_<id>.jsonl.lock   present while a process is completing the report

The rules for these files (what a valid record is, who may touch a log) live here.
"""

import asyncio
import contextlib
import json
import os
import time
import uuid
from datetime import datetime

from .. import fsutil
from ..languages import resolve

def now():
    return datetime.now().isoformat(timespec="seconds")


def append(path, record):
    """One record per line; opened and closed each call so it's on disk on return."""
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    with open(path, "a+b") as f:
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                line = b"\n" + line  # a line cut short by a crash stays apart from this one
        f.write(line)


class InUse(Exception):
    """The log belongs to a session that's live in another OpenSpeak process."""


# A log in use by a live session has "<log>.live" next to it, holding the owner's
# pid. Another OpenSpeak process (or `openspeak report`) then leaves the log alone
# instead of grading turns the owner is about to grade. A file left by a process
# that died is noticed (its pid is gone) and removed.
def owner(path):
    """pid of the live process using this log, or None. -1: being claimed right now."""
    lp = path + ".live"
    try:
        with open(lp, encoding="utf-8") as f:
            pid = int(f.read().strip() or 0)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        pid = 0
    if pid == os.getpid() or (pid and fsutil.pid_alive(pid)):
        return pid
    if not pid:
        try:
            if time.time() - os.path.getmtime(lp) < 10:
                return -1  # created, pid not written yet
        except OSError:
            return None
    with contextlib.suppress(OSError):
        fsutil.remove(lp)
    return None


def in_use_elsewhere(path):
    return owner(path) not in (None, os.getpid())


def claim(path):
    """Mark the log as this process's live session. False if another process has it."""
    while True:
        try:
            fd = os.open(path + ".live", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            who = owner(path)  # removes it if its owner is dead
            if who == os.getpid():
                return True
            if who is not None:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True


def release(path):
    if owner(path) == os.getpid():
        with contextlib.suppress(OSError):
            fsutil.remove(path + ".live")


def remove_log(path):
    """Delete a log and everything generated from it."""
    base = os.path.splitext(path)[0]
    for p in (path, base + ".html", base + ".md", path + ".lock", path + ".live"):
        fsutil.remove(p)


_NEEDS_TURN = ("heard", "partner", "turn", "turn_error", "help")
_NEEDS_SAID = ("heard", "partner", "turn")


def _valid(r):
    """
    Everything downstream indexes records directly, so anything malformed (a line
    cut short by a crash, or a log edited by hand) is dropped here, once.
    """
    if not isinstance(r, dict) or not isinstance(r.get("kind"), str):
        return False
    if r["kind"] in _NEEDS_TURN and not isinstance(r.get("turn"), int):
        return False
    if r["kind"] in _NEEDS_SAID and not isinstance(r.get("said"), str):
        return False
    if r["kind"] == "turn":
        for k in ("corrected", "native_version", "good_note"):
            r[k] = str(r.get(k) or "")
        r["errors"] = [
            {k: str(e.get(k) or "") for k in ("type", "original", "correction", "explain", "severity")}
            for e in (r.get("errors") if isinstance(r.get("errors"), list) else [])
            if isinstance(e, dict)
        ]
    elif r["kind"] in _SHAPES:
        _SHAPES[r["kind"]](r)
    return True


def _text(value):
    return value if isinstance(value, str) else "" if value is None else str(value)


def _texts(value):
    """A list of strings, from whatever was written there."""
    if isinstance(value, str):
        value = [value]
    return [_text(x) for x in value if x is not None] if isinstance(value, list) else []


def _session_start(r):
    r["at"] = _text(r.get("at"))
    scene = r.get("scene")
    if isinstance(scene, dict):
        title = scene.get("title")
        scene["title"] = title if isinstance(title, dict) else {"en": title} if isinstance(title, str) else {}
    else:
        r["scene"] = None
    langs = r.get("languages") if isinstance(r.get("languages"), dict) else {}
    r["languages"] = {k: v if isinstance(v, dict) else {"id": _text(v)} for k, v in langs.items()}


def _vocab(r):
    items = r.get("items") if isinstance(r.get("items"), list) else []
    r["items"] = [{**it, "term": _text(it["term"]), "meaning": _text(it.get("meaning")), "example": _text(it.get("example"))}
                  for it in items if isinstance(it, dict) and _text(it.get("term")).strip()]


def _summary(r):
    r["level"], r["encouragement"] = _text(r.get("level")), _text(r.get("encouragement"))
    r["patterns"], r["priorities"] = _texts(r.get("patterns")), _texts(r.get("priorities"))


def _help(r):
    r["hint"], r["say"] = _text(r.get("hint")), _texts(r.get("say"))


# What each kind of record may be trusted to hold once it has been read.
_SHAPES = {
    "session_start": _session_start, "vocab": _vocab, "summary": _summary, "help": _help,
    "partner": lambda r: r.__setitem__("aid", _text(r.get("aid"))),
    "session_end": lambda r: r.__setitem__("at", _text(r.get("at"))),
}


def read(path):
    """Read a log, skipping any line cut short by a crash."""
    records = []
    if not os.path.exists(path):
        return records
    # errors="replace": a crash mid-write can cut a multi-byte character in half.
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _valid(r):
                records.append(r)
    return records


def ordered(records):
    """What was said, in spoken order: each learner turn, then the partner's reply."""
    return sorted(
        [r for r in records if r["kind"] in ("heard", "partner") and r["said"].strip()],
        key=lambda r: (r["turn"], 1 if r["kind"] == "partner" else 0),
    )


def has_talk(records):
    return any(r["kind"] == "heard" for r in records)


def _last(records):
    """Where in the log each kind of record last appears."""
    return {r["kind"]: i for i, r in enumerate(records)}


def outdated(records):
    """
    Which of summary/vocab are missing, or older than something they should cover.
    A session continued after it ended, or a turn regraded later, makes them stale.
    """
    last = _last(records)
    newest_talk = max(last.get("heard", -1), last.get("turn", -1))
    return {k for k in ("summary", "vocab") if last.get(k, -1) < newest_talk}


def ended(records):
    """Ended with End (or a repair), and nothing said since."""
    last = _last(records)
    return last.get("session_end", -1) > max(last.get("heard", -1), last.get("session_resume", -1))


def session_langs(records):
    start = next((r for r in records if r.get("kind") == "session_start"), {})
    langs = start.get("languages") or {}
    return {k: resolve((langs.get(k) or {}).get("id") or "en") for k in ("target", "native", "report")}


LOCK_STALE_S = 30 * 60
_held = set()  # tokens of the locks this process holds right now


def _holder(lockfile):
    """What a lock file holds ("<pid> <token>"), or None if there's none."""
    try:
        with open(lockfile, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return ""


def _abandoned(lockfile, holder):
    """Its process is gone, or it's older than any completion takes."""
    pid, _, token = holder.partition(" ")
    if pid.isdigit():
        if int(pid) == os.getpid():
            # Ours by number, but not one we hold: left by an earlier run that had the same
            # pid (the first process in a container always does), so nobody holds it.
            if token and token not in _held:
                return True
        elif not fsutil.pid_alive(int(pid)):
            return True
    try:
        return time.time() - os.path.getmtime(lockfile) > LOCK_STALE_S
    except OSError:
        return False  # let go of just now


def locked_elsewhere(path):
    """Another process is completing this log's report right now."""
    holder = _holder(path + ".lock")
    if holder is None or _abandoned(path + ".lock", holder):
        return False
    return holder.split()[:1] != [str(os.getpid())]


@contextlib.asynccontextmanager
async def exclusive(path, wait_s):
    """
    Hold "<log>.lock" across processes. Waits up to wait_s for another holder, then
    InUse. A lock whose process died, or older than LOCK_STALE_S, is taken over; a
    holder only ever removes its own.
    """
    lockfile = path + ".lock"
    token = uuid.uuid4().hex
    mine = f"{os.getpid()} {token}"
    _held.add(token)
    try:
        async with _locked(lockfile, mine, wait_s):
            yield
    finally:
        _held.discard(token)


@contextlib.asynccontextmanager
async def _locked(lockfile, mine, wait_s):
    waited = 0
    while True:
        try:
            fd = os.open(lockfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            theirs = _holder(lockfile)
            if theirs is None:
                continue  # released between the two calls
            if _abandoned(lockfile, theirs):
                if _holder(lockfile) == theirs:  # not taken over by someone else meanwhile
                    with contextlib.suppress(OSError):
                        fsutil.remove(lockfile)
                continue
            if waited >= wait_s:
                raise InUse() from None
            await asyncio.sleep(1)
            waited += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(mine)
        break
    try:
        yield
    finally:
        if _holder(lockfile) == mine:
            with contextlib.suppress(OSError):
                fsutil.remove(lockfile)
