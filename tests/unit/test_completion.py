import anyio
import pytest

from openspeak.practice import completion
from openspeak.practice import sessionlog as log

pytestmark = pytest.mark.anyio

TALK = [("partner", 0, "Welcome"), ("heard", 1, "I want check in"), ("partner", 1, "Name?"),
        ("heard", 2, "My name is Li"), ("partner", 2, "Thanks")]


def kinds(path):
    return [r["kind"] for r in log.read(path)]


async def test_grades_whats_missing_then_summarises(cfg, llm, write_log):
    path = write_log(TALK)
    fixed, added = await completion.complete(cfg, path)
    assert fixed == 2 and sorted(added) == ["summary", "vocab"]
    assert kinds(path).count("turn") == 2


async def test_a_turn_is_graded_knowing_only_what_came_before_it(cfg, llm, write_log):
    seen = {}

    def grade(messages):
        said = messages[1]["content"].rsplit("utterance by the learner:\n", 1)[1]
        seen[said] = messages[1]["content"]
        return {"errors": []}

    llm.script["grade"] = grade
    path = write_log([("partner", 0, "Welcome"), ("heard", 1, "first thing said"), ("partner", 1, "Name please"),
                      ("heard", 2, "second thing said"), ("partner", 2, "Thanks")])
    await completion.grade_missing(cfg, path)
    assert "Welcome" in seen["first thing said"] and "Name please" not in seen["first thing said"]
    assert "first thing said" in seen["second thing said"] and "Name please" in seen["second thing said"]
    assert "Thanks" not in seen["second thing said"]


def watch_overlap(monkeypatch, llm):
    """How many grading calls were in the air at once, at most."""
    from openspeak.ai import client

    seen = {"now": 0, "most": 0}

    async def chat(*args, **kw):
        seen["now"] += 1
        seen["most"] = max(seen["most"], seen["now"])
        try:
            return await llm(*args, **kw)
        finally:
            seen["now"] -= 1

    monkeypatch.setattr(client, "chat", chat)
    llm.delay = 0.02
    return seen


MANY = [("partner", 0, "Welcome")] + [row for n in range(1, 7) for row in (("heard", n, f"I want check in {n}"), ("partner", n, "Ok"))]


async def test_a_cloud_model_grades_several_turns_at_once(cfg, llm, write_log, monkeypatch):
    seen = watch_overlap(monkeypatch, llm)
    path = write_log(MANY)
    assert await completion.grade_missing(cfg, path) == 6
    assert 1 < seen["most"] <= cfg["coach"]["max_concurrent"]
    assert sorted(r["turn"] for r in log.read(path) if r["kind"] == "turn") == [1, 2, 3, 4, 5, 6]


async def test_a_local_model_grades_one_at_a_time(local_cfg, llm, write_log, monkeypatch):
    seen = watch_overlap(monkeypatch, llm)
    path = write_log(MANY)
    assert await completion.grade_missing(local_cfg, path) == 6
    assert seen["most"] == 1


async def test_second_run_does_nothing(cfg, llm, write_log):
    path = write_log(TALK)
    await completion.complete(cfg, path)
    llm.calls.clear()
    assert await completion.complete(cfg, path) == (0, [])
    assert llm.calls == []


async def test_concurrent_runs_dont_grade_twice(cfg, llm, write_log):
    llm.delay = 0.05
    path = write_log(TALK)
    async with anyio.create_task_group() as tg:
        tg.start_soon(completion.complete, cfg, path)
        tg.start_soon(completion.complete, cfg, path)
    assert kinds(path).count("turn") == 2
    assert kinds(path).count("summary") == 1
    assert completion._completing == {}  # nothing left behind


async def test_ungraded_turns_need_no_summary(cfg, llm, write_log):
    path = write_log([("partner", 0, "Welcome"), ("heard", 1, "hello", False)])
    _, added = await completion.complete(cfg, path)
    assert added == ["vocab"]
    assert "summary" not in llm.calls


async def test_a_failure_is_recorded_with_its_reason(cfg, llm, write_log):
    llm.script["summary"] = RuntimeError("quota exceeded")
    path = write_log(TALK)
    _, added = await completion.complete(cfg, path)
    assert added == ["vocab"]
    errors = [r for r in log.read(path) if r["kind"] == "fill_error"]
    assert errors[0]["what"] == "summary" and "quota exceeded" in errors[0]["error"]


async def test_refused_while_live_in_another_process(cfg, llm, write_log, other_pid):
    path = write_log(TALK)
    open(path + ".live", "w").write(str(other_pid))
    with pytest.raises(log.InUse):
        await completion.complete(cfg, path)
    assert llm.calls == []


async def test_long_sessions_are_mined_in_batches(cfg, llm, write_log, monkeypatch):
    monkeypatch.setattr(completion, "TRANSCRIPT_BATCH_LINES", 2)
    path = write_log(TALK)
    await completion.fill_missing(cfg, path)
    assert llm.calls.count("vocab") == 3  # 5 lines, 2 per batch


async def test_a_turn_that_still_fails_is_recorded(cfg, llm, write_log):
    llm.script["grade"] = ValueError("not json")
    path = write_log(TALK)
    await completion.complete(cfg, path)
    errors = [r for r in log.read(path) if r["kind"] == "turn_error"]
    assert {r["turn"] for r in errors} == {1, 2} and "not json" in errors[0]["error"]
    assert "summary" not in kinds(path)  # nothing graded to summarise


async def test_examples_per_type_are_capped(cfg, llm, write_log):
    err = {"type": "grammar", "original": "x", "correction": "y", "severity": None}
    turn = {"kind": "turn", "turn": 1, "said": "s", "verdict": "errors", "errors": [err] * 10}
    seen = {}

    def summary(messages):
        seen["prompt"] = messages[1]["content"]
        return {"level": "B1"}

    llm.script["summary"] = summary
    path = write_log([("heard", 1, "s"), turn])
    out = await completion._summary(cfg, path, log.session_langs(log.read(path)))
    assert out["level"] == "B1" and seen["prompt"].count('"original": "x"') == completion.MAX_EXAMPLES_PER_TYPE


async def test_vocab_drops_items_without_a_term_and_bad_sources(cfg, llm, write_log):
    llm.script["vocab"] = {"items": [{"term": " "}, "junk", {"term": "late check-out", "source": "made-up"}]}
    path = write_log(TALK)
    items = await completion._vocab(cfg, path, log.session_langs(log.read(path)))
    assert [(i["term"], i["source"]) for i in items] == [("late check-out", "partner")]


async def test_vocab_needs_some_conversation(cfg, llm, write_log):
    path = write_log([("partner", 0, "Welcome")])
    assert await completion._vocab(cfg, path, log.session_langs(log.read(path))) == []
    assert await completion.fill_missing(cfg, path) == []


async def test_one_failed_vocab_batch_keeps_the_others(cfg, llm, write_log, monkeypatch):
    monkeypatch.setattr(completion, "TRANSCRIPT_BATCH_LINES", 2)
    answers = iter([RuntimeError("timeout"), None, None])
    llm.script["vocab"] = lambda m: next(answers)
    path = write_log(TALK)
    items = await completion._vocab(cfg, path, log.session_langs(log.read(path)))
    assert [i["term"] for i in items] == ["check in"]  # the same item from two batches, once


async def test_nothing_new_to_add_writes_nothing(cfg, llm, write_log):
    llm.script["vocab"] = {"items": []}
    path = write_log(TALK)
    await completion.complete(cfg, path)
    assert "vocab" not in kinds(path) and "summary" in kinds(path)


async def test_nothing_to_summarise_or_fill(cfg, llm, write_log):
    path = write_log([])
    assert await completion._summary(cfg, path, log.session_langs(log.read(path))) is None
    assert await completion.fill_missing(cfg, path) == [] and not llm.calls
