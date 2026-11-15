"""
Completing a session from its log: works on any log, live or from last month.

Grades every turn that has no result yet, then writes the summary and the
vocabulary. Idempotent: each step re-reads the log and skips what's already there,
so running it twice (a double click, or `openspeak report` alongside the app) is
safe, and one completer per log runs at a time, across processes too.
"""

import asyncio
import json

from ..ai import client, prompts
from ..ai.grading import call, grade, models, timeout_for
from ..languages import label
from . import sessionlog as log

# A long session never loses content to these; they only bound prompt size:
#   TRANSCRIPT_BATCH_LINES - transcript lines per vocabulary call; longer sessions are
#       split into parallel calls and merged, so the end is mined as well as the start.
#   MAX_EXAMPLES_PER_TYPE - the summary gets exact counts of every error, plus this
#       many verbatim examples per type.
TRANSCRIPT_BATCH_LINES = 160
MAX_EXAMPLES_PER_TYPE = 6


def _spoken(records):
    return any(r.get("kind") in ("heard", "turn", "partner") for r in records)


async def grade_missing(cfg, path):
    """
    Grade every turn that should have been graded but has no result: grading timed
    out, errored, was cancelled at Stop, or the process died mid-call (which leaves
    no error record at all). Idempotent: turns already graded are skipped. They are
    all handed to grade(), whose gate lets through one at a time for a local model
    and a few for a cloud one, so a long session isn't graded line by line.
    """
    records = log.read(path)
    langs = log.session_langs(records)
    done = {r.get("turn") for r in records if r.get("kind") == "turn"}
    todo = {
        r["turn"]: r["said"] for r in records
        if r.get("kind") == "heard" and r.get("graded") and r.get("turn") not in done
    }
    if not todo:
        return 0
    spoken = log.ordered(records)

    async def one(turn, said):
        context = [
            {"role": "user" if r["kind"] == "heard" else "assistant", "content": r["said"]}
            for r in spoken if r["turn"] < turn
        ]
        try:
            analysis = await grade(cfg, langs, said, context)
        except Exception as e:
            print(f"grader: turn {turn} still failing ({type(e).__name__}: {e})")
            log.append(path, {"kind": "turn_error", "at": log.now(), "turn": turn, "said": said, "error": f"{type(e).__name__}: {e}"})
            return 0
        log.append(path, {"kind": "turn", "at": log.now(), "turn": turn, "said": said, **analysis})
        return 1

    return sum(await asyncio.gather(*(one(turn, said) for turn, said in sorted(todo.items()))))


async def _summary(cfg, path, langs):
    turns = [r for r in log.read(path) if r.get("kind") == "turn"]
    if not turns:
        return None
    counts, sev, examples = {}, {}, {}
    for t in turns:
        for e in t.get("errors", []):
            et = e.get("type") or "other"
            counts[et] = counts.get(et, 0) + 1
            s = e.get("severity") or "medium"
            sev[s] = sev.get(s, 0) + 1
            bucket = examples.setdefault(et, [])
            if len(bucket) < MAX_EXAMPLES_PER_TYPE:
                bucket.append({"original": e.get("original", ""), "correction": e.get("correction", "")})
    digest = {
        "turns_spoken": len(turns),
        "clean_turns": sum(1 for t in turns if t.get("verdict") == "clean"),
        "total_errors": sum(counts.values()),
        "errors_by_type": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "errors_by_severity": sev,
        "examples_by_type": examples,
    }
    raw = await call(
        cfg,
        [{"role": "system", "content": prompts.summary_system(langs)},
         {"role": "user", "content": "Session data:\n" + json.dumps(digest, ensure_ascii=False)
          + f"\n\nWrite the debrief in {label(langs['report'])}."}],
        timeout=timeout_for(cfg, "finish_timeout"), model=models(cfg)[0],
    )
    data = client.parse_json(raw)

    def as_list(v):
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    return {
        "level": client.text(data.get("level")),
        "patterns": as_list(data.get("patterns")),
        "priorities": as_list(data.get("priorities")),
        "encouragement": client.text(data.get("encouragement")),
    }


async def _vocab_batch(cfg, langs, batch, corrections, natives):
    lines = [f'{"Partner" if r["kind"] == "partner" else "Learner"}: {r["said"].strip()}' for r in batch]
    turns = sorted({r.get("turn", 0) for r in batch})
    corr = [c for t in turns for c in corrections.get(t, [])]
    nat = [n for t in turns for n in natives.get(t, [])]
    raw = await call(
        cfg,
        [{"role": "system", "content": prompts.vocab_system(langs)},
         {"role": "user", "content": "Transcript:\n" + "\n".join(lines)
          + "\n\nCorrections logged:\n" + ("\n".join(corr) or "(none)")
          + "\n\nNative-speaker rewrites:\n" + ("\n".join(nat) or "(none)")
          + f"\n\nGlosses and notes in {label(langs['report'])}."}],
        timeout=timeout_for(cfg, "finish_timeout"), model=models(cfg)[0],
    )
    items = []
    for it in client.parse_json(raw).get("items") or []:
        term = client.text(it.get("term")) if isinstance(it, dict) else ""
        if not term:
            continue
        src = (client.text(it.get("source")) or "partner").lower()
        items.append(
            {
                "term": term,
                "pos": client.text(it.get("pos")).lower(),
                "meaning": client.text(it.get("meaning")),
                "example": client.text(it.get("example")),
                "from_transcript": bool(it.get("from_transcript")),
                "source": src if src in ("partner", "correction", "learner") else "partner",
                "note": client.text(it.get("note")),
            }
        )
    return items


async def _vocab(cfg, path, langs):
    records = log.read(path)
    spoken = log.ordered(records)
    if len(spoken) < 2:
        return []
    corrections, natives = {}, {}
    for r in records:
        if r.get("kind") != "turn":
            continue
        for e in r.get("errors", []):
            corrections.setdefault(r["turn"], []).append(f'{e.get("original", "")} -> {e.get("correction", "")}')
        if (r.get("native_version") or "").strip():
            natives.setdefault(r["turn"], []).append(r["native_version"].strip())
    batches = [spoken[i : i + TRANSCRIPT_BATCH_LINES] for i in range(0, len(spoken), TRANSCRIPT_BATCH_LINES)]
    results = await asyncio.gather(
        *(_vocab_batch(cfg, langs, b, corrections, natives) for b in batches), return_exceptions=True
    )
    items, seen = [], set()
    for i, res in enumerate(results, 1):
        if isinstance(res, Exception):
            print(f"vocab: batch {i}/{len(batches)} failed ({type(res).__name__}); keeping the rest")
            continue
        for it in res:
            if it["term"].lower() not in seen:
                seen.add(it["term"].lower())
                items.append(it)
    return items


async def fill_missing(cfg, path):
    """Add summary/vocabulary if the log lacks them. Idempotent. Returns kinds added."""
    records = log.read(path)
    if not _spoken(records):
        return []
    langs = log.session_langs(records)
    todo = log.outdated(records)
    jobs = []
    if "summary" in todo and any(r["kind"] == "turn" for r in records):
        jobs.append(("summary", _summary(cfg, path, langs)))
    if "vocab" in todo:
        jobs.append(("vocab", _vocab(cfg, path, langs)))
    if not jobs:
        return []
    results = await asyncio.gather(*(c for _, c in jobs), return_exceptions=True)
    added = []
    for (kind, _), res in zip(jobs, results, strict=True):
        if isinstance(res, Exception):
            print(f"{kind}: failed ({type(res).__name__}: {res})")
            # Kept so the history can say why the report is still incomplete.
            log.append(path, {"kind": "fill_error", "at": log.now(), "what": kind, "error": f"{type(res).__name__}: {res}"})
        elif res:
            log.append(path, {"kind": "summary", **res} if kind == "summary" else {"kind": "vocab", "items": res})
            added.append(kind)
    return added


_completing = {}  # path -> [lock, users]; dropped when the last user is done


async def complete(cfg, path, on_stage=None):
    """
    Everything a finished session should have: grade what's missing, then summarise.

    Only one completer per log at a time, in this process (a double-clicked repair)
    and across processes (`openspeak report` while the app finishes the same
    session). Each step re-reads the log, so whoever goes second finds nothing to do.
    A log that another process has open as a live session raises log.InUse.
    """
    if log.in_use_elsewhere(path):
        raise log.InUse()
    entry = _completing.setdefault(path, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        return await _complete(cfg, path, entry[0], on_stage or (lambda stage: None))
    finally:
        entry[1] -= 1
        if not entry[1]:
            _completing.pop(path, None)


async def _complete(cfg, path, lock, on_stage):
    async with lock, log.exclusive(path, wait_s=timeout_for(cfg, "finish_timeout")):
        on_stage("grading")
        fixed = await grade_missing(cfg, path)
        on_stage("writing")
        added = await fill_missing(cfg, path)
    return fixed, added
