import json

import anyio
import httpx
import pytest

from openspeak.ai import grading
from openspeak.languages import resolve

EN_ZH = {"target": resolve("en"), "native": resolve("zh-CN"), "report": resolve("zh-CN")}


class TestShouldGrade:
    @pytest.mark.parametrize("text", ["", "   ", "hello", "yes I see", "Okay, thank you!", "uh um okay"])
    def test_skips_short_and_filler(self, text):
        assert not grading.should_grade(text, resolve("en"))

    def test_grades_a_real_sentence(self):
        assert grading.should_grade("I want check in please", resolve("en"))

    def test_counts_characters_for_languages_without_spaces(self):
        ja = resolve("ja")
        assert not grading.should_grade("はい", ja)
        assert grading.should_grade("チェックインしたいです", ja)

    def test_the_word_threshold_is_three(self):
        assert not grading.should_grade("very good", resolve("en")) and grading.should_grade("very good idea", resolve("en"))
        assert not grading.should_grade("muy bien", resolve("es")) and grading.should_grade("muy buena idea", resolve("es"))

    def test_the_character_threshold_is_four(self):
        assert not grading.should_grade("お願い", resolve("ja")) and grading.should_grade("お願いし", resolve("ja"))
        assert not grading.should_grade("！？。、……", resolve("ja"))  # punctuation isn't speech


class TestNormalize:
    def error(self, **kw):
        return {"type": "grammar", "original": "want check", "correction": "want to check", **kw}

    def test_drops_written_only_and_case_only_fixes(self):
        out = grading.normalize({"errors": [
            self.error(type="punctuation"),
            self.error(original="i want", correction="I want."),
            self.error(),
        ]})
        assert [e["original"] for e in out["errors"]] == ["want check"]
        assert out["verdict"] == "errors"

    def test_own_language_words_are_not_mistakes(self):
        out = grading.normalize({"verdict": "errors", "errors": [self.error(original="I want 退房")]}, EN_ZH)
        assert out["errors"] == [] and out["verdict"] == "clean"

    def test_repairs_bad_fields(self):
        out = grading.normalize({"verdict": "great", "errors": [self.error(severity="HUGE"), "junk", {}]})
        assert out["errors"][0]["severity"] == "medium"
        assert out["verdict"] == "errors"
        assert set(out) == {"verdict", "corrected", "native_version", "errors", "good_note"}

    def test_fields_of_the_wrong_type_read_as_empty(self):
        out = grading.normalize({"verdict": 3, "corrected": ["x"], "good_note": None,
                                 "errors": [self.error(severity=2, type=None, explain={"a": 1})]})
        assert out["errors"][0] | {"original": ""} == {"type": "other", "original": "", "correction": "want to check",
                                                      "explain": "", "severity": "medium"}
        assert out["corrected"] == "" and out["good_note"] == ""


class TestGate:
    def test_a_size_keeps_its_own_limiter(self):
        # Sessions started under different settings take turns at the gate; a swap would
        # drop the waiting calls of one from the other's count.
        gate = grading.Gate()
        one, three = gate.slots(1), gate.slots(3)
        assert gate.slots(1) is one and gate.slots(3) is three and one is not three


class TestSettings:
    def test_local_server_grades_later_one_at_a_time(self, local_cfg):
        assert not grading.grade_live(local_cfg)
        assert grading.max_concurrent(local_cfg) == 1
        assert grading.timeout_for(local_cfg) == 3 * float(local_cfg["coach"]["timeout"])

    def test_cloud_grades_live(self, cfg):
        assert grading.grade_live(cfg)
        cfg["coach"]["when"] = "end"
        assert not grading.grade_live(cfg)

    def test_grader_model_defaults_to_partner(self, cfg):
        assert grading.models(cfg) == ("test-model", "test-model")
        cfg["llm"]["grader_model"] = "big"
        assert grading.models(cfg) == ("test-model", "big")


@pytest.mark.anyio
class TestGrade:
    async def test_returns_normalized_result(self, cfg, llm):
        out = await grading.grade(cfg, EN_ZH, "I want check in", [])
        assert out["errors"][0]["correction"] == "want to check"
        assert llm.calls == ["grade"]

    async def test_retries_bad_json_then_gives_up(self, cfg, llm):
        cfg["coach"]["retries"] = 1
        llm.script["grade"] = "not json at all"
        with pytest.raises(ValueError):
            await grading.grade(cfg, EN_ZH, "I want check in", [])
        assert llm.calls == ["grade", "grade"]

    async def test_json_that_isnt_an_object_is_retried(self, cfg, llm):
        cfg["coach"]["retries"] = 1
        llm.script["grade"] = "[1, 2]"
        with pytest.raises(ValueError):
            await grading.grade(cfg, EN_ZH, "I want check in", [])
        assert llm.calls == ["grade", "grade"]

    @pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectError("reset"), json.JSONDecodeError("bad", "", 0)])
    async def test_a_timeout_or_dropped_connection_is_retried(self, cfg, llm, error):
        cfg["coach"]["retries"] = 1
        calls = []

        def flaky(messages):
            calls.append(1)
            if len(calls) == 1:
                raise error
            return json.dumps({"errors": []})

        llm.script["grade"] = flaky
        assert (await grading.grade(cfg, EN_ZH, "I want check in", []))["errors"] == []
        assert len(calls) == 2

    async def test_other_failures_are_not_retried(self, cfg, llm):
        cfg["coach"]["retries"] = 3
        llm.script["grade"] = RuntimeError("401")
        with pytest.raises(RuntimeError):
            await grading.grade(cfg, EN_ZH, "I want check in", [])
        assert llm.calls == ["grade"]

    async def test_the_grader_sees_the_last_six_messages_only(self, cfg, llm):
        seen = []
        llm.script["grade"] = lambda m: seen.append(m[1]["content"]) or json.dumps({"errors": []})
        history = [{"role": "user" if i % 2 else "assistant", "content": f"line-{i}"} for i in range(1, 11)]
        await grading.grade(cfg, EN_ZH, "I want check in", history)
        assert all(f"line-{i}" in seen[0] for i in range(5, 11))  # the last six
        assert "line-4" not in seen[0] and "line-3" not in seen[0]

    async def test_waits_while_the_partner_is_replying(self, cfg, llm):
        started = []
        llm.script["grade"] = lambda m: started.append(1) or json.dumps({"errors": []})
        reply_done = anyio.Event()

        async def partner():
            with grading.gate().partner_replying():
                await reply_done.wait()

        async with anyio.create_task_group() as tg:
            tg.start_soon(partner)
            await anyio.sleep(0.01)
            tg.start_soon(grading.grade, cfg, EN_ZH, "I want check in", [])
            await anyio.sleep(0.1)
            assert started == []  # held back while the partner talks
            reply_done.set()
        assert started == [1]

    async def test_one_grading_call_at_a_time_on_a_local_server(self, local_cfg, llm):
        running, peak = 0, 0

        llm.delay = 0.05
        original = llm.__call__

        async def counting(*a, **kw):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            try:
                return await original(*a, **kw)
            finally:
                running -= 1

        from openspeak.ai import client
        client.chat = counting  # restored by the llm fixture's monkeypatch
        async with anyio.create_task_group() as tg:
            for _ in range(3):
                tg.start_soon(grading.grade, local_cfg, EN_ZH, "I want check in", [])
        assert peak == 1 and llm.calls == ["grade"] * 3


def test_each_event_loop_gets_its_own_gate():
    async def get():
        return grading.gate()

    a, b = anyio.run(get), anyio.run(get)
    assert a is not b


def test_a_language_typed_in_still_works():
    lang = resolve("Hokkien")
    assert lang["id"] == lang["name"] == "Hokkien" and lang["stt"] is None
    assert resolve("")["id"] == "en"


def test_hard_scenes_add_their_complication():
    from openspeak.ai import prompts

    scene = {"id": 8, "title": {"en": "Hotel"}, "prompt": "hotel desk", "hard": "The room is overbooked"}
    assert "overbooked" in prompts.partner_system(EN_ZH, "B1", "immersive", scene, hard=True)
    assert "overbooked" not in prompts.partner_system(EN_ZH, "B1", "immersive", scene, hard=False)
