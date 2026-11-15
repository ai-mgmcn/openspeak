"""
Every built-in language, and one typed in by hand, taken through what depends on the
language: the prompts, a conversation, the report, and the codes speech engines need.
What a model *can* speak well isn't something a test can know; that the app asks for it correctly is.
"""

import json
import re

import pytest

from openspeak import report
from openspeak.ai import prompts
from openspeak.languages import all_languages, label, resolve
from openspeak.practice.session import Session

pytestmark = pytest.mark.anyio

IDS = [lang["id"] for lang in all_languages()]
CUSTOM = "Swiss German"
EVERYTHING = IDS + [CUSTOM]


def langs(target="en", native="zh-CN", report="zh-CN"):
    return {"target": resolve(target), "native": resolve(native), "report": resolve(report)}


@pytest.mark.parametrize("lang", EVERYTHING)
class TestAsTheLanguageBeingPracticed:
    def test_the_prompts_name_it(self, lang):
        both = langs(target=lang, native="en")
        for mode in prompts.REPLY_MODES:
            text = prompts.partner_system(both, "intermediate", mode)
            assert label(both["target"]) in text and "{" not in text
        for build in (prompts.grader_system, prompts.summary_system, prompts.vocab_system, prompts.help_system):
            assert label(both["target"]) in build(both)

    async def test_a_conversation_opens_and_goes_on(self, lang, cfg, llm):
        cfg["languages"] = {"target": lang, "native": "en", "report": "en"}
        sent = []
        llm.script["partner"] = lambda m: sent.append(m[0]["content"]) or "Reply."
        s = Session(cfg)
        await s.open()
        await s.say("one two three four five")
        assert all(label(resolve(lang)) in system for system in sent) and len(sent) == 2

    def test_the_report_shows_its_text(self, lang, write_log):
        text = f"sample in {lang}"
        records = [{"kind": "session_start", "at": "2026-01-01T12:00:00",
                    "languages": {"target": {"id": lang}, "native": {"id": "en"}, "report": {"id": "en"}}},
                   {"kind": "partner", "turn": 0, "said": text, "aid": ""},
                   {"kind": "heard", "turn": 1, "said": text, "graded": False}]
        path = write_log(records)
        page = open(report.build(path)["html"], encoding="utf-8").read()
        assert text in page and f'data-tts="{resolve(lang)["tts"] or ""}"' in page
        assert report.describe(path)["target"] == lang


@pytest.mark.parametrize("lang", EVERYTHING)
class TestAsTheLanguageOfFeedback:
    def test_the_report_is_laid_out_for_it(self, lang, write_log):
        records = [{"kind": "session_start", "at": "2026-01-01T12:00:00",
                    "languages": {"target": {"id": "en"}, "native": {"id": "en"}, "report": {"id": lang}}},
                   {"kind": "heard", "turn": 1, "said": "I want check in", "graded": False}]
        path = write_log(records)
        page = open(report.build(path)["html"], encoding="utf-8").read()
        assert f'lang="{lang}"' in page
        assert f'dir="{"rtl" if resolve(lang)["rtl"] else "ltr"}"' in page
        assert report.L.get(lang.split("-")[0], report.L["en"])["title"] in page  # its own wording, or English

    def test_the_prompts_ask_for_feedback_in_it(self, lang):
        both = langs(report=lang)
        for build in (prompts.grader_system, prompts.summary_system, prompts.vocab_system):
            assert label(both["report"]) in build(both)


@pytest.mark.parametrize("lang", IDS)
def test_what_speech_engines_are_given(lang):
    entry = resolve(lang)
    assert re.fullmatch(r"[a-z]{2,3}", entry["stt"]) and re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}", entry["tts"])
    assert entry["tts"].split("-")[0] == entry["stt"] or lang in {"no", "tl", "yue"}  # a voice speaks the language it transcribes


def test_whisper_understands_every_code_we_send():
    tokenizer = pytest.importorskip("faster_whisper.tokenizer")
    unknown = [lang["id"] for lang in all_languages() if lang["stt"] not in tokenizer._LANGUAGE_CODES]
    assert unknown == []


@pytest.mark.parametrize("lang", EVERYTHING)
def test_whether_a_turn_is_worth_grading_follows_the_script(lang):
    from openspeak.ai.grading import should_grade

    entry = resolve(lang)
    assert not should_grade("", entry) and not should_grade("  ", entry)
    long_enough = "一二三四五六七八九十" if entry["chars"] else "one two three four five six"
    assert should_grade(long_enough, entry)


def test_the_speech_recognition_language_is_left_to_detect_for_a_typed_one():
    entry = resolve(CUSTOM)
    assert entry["stt"] is None and entry["tts"] is None


def test_json_of_a_custom_language_survives_a_round_trip_through_the_log(write_log):
    path = write_log([{"kind": "session_start", "at": "2026-01-01T12:00:00",
                       "languages": {"target": {"id": CUSTOM}, "native": {"id": "en"}, "report": {"id": "en"}}}])
    assert json.loads(open(path, encoding="utf-8").readline())["languages"]["target"]["id"] == CUSTOM
    from openspeak.practice import sessionlog

    assert sessionlog.session_langs(sessionlog.read(path))["target"]["id"] == CUSTOM
