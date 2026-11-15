"""
The prompts are the product: a stray brace, a missing language or a dropped rule
changes what every learner gets. Nothing else reads them, so these tests do.
"""

import itertools
import re

import pytest

from openspeak.ai import prompts
from openspeak.languages import label, resolve
from openspeak.practice.session import split_aid

from ..conftest import FakeLLM

LANGS = {"target": resolve("es"), "native": resolve("zh-CN"), "report": resolve("ja")}
SCENE = {"id": 8, "title": {"en": "Hotel"}, "prompt": "You are a hotel clerk. SCENE-MARKER", "hard": "The guest is angry. HARD-MARKER"}


def unresolved(text):
    """A {name} left in a prompt that was meant to be filled in."""
    return re.findall(r"\{[A-Za-z_]+\}", text)


@pytest.mark.parametrize("mode, level, scene, hard", list(itertools.product(prompts.REPLY_MODES, prompts.LEVELS, [None, SCENE], [False, True])))
def test_the_partner_prompt_is_complete_in_every_combination(mode, level, scene, hard):
    text = prompts.partner_system(LANGS, level, mode, scene, hard)
    assert not unresolved(text) and "{" not in text and "}" not in text
    assert label(LANGS["target"]) in text
    assert prompts.LEVELS[level] in text
    assert "Do NOT correct their grammar" in text  # corrections belong to the grader, never to the conversation
    assert ("SCENE-MARKER" in text) == bool(scene)
    assert ("HARD-MARKER" in text) == bool(scene and hard)
    if mode != "immersive":
        assert label(LANGS["native"]) in text  # the hint or translation is written in the learner's language


def test_the_modes_differ_in_what_they_ask_for():
    texts = {m: prompts.partner_system(LANGS, "intermediate", m) for m in prompts.REPLY_MODES}
    assert "Reply only in" in texts["immersive"] and prompts.AID_MARK not in texts["immersive"].split("7.")[1]
    assert prompts.AID_MARK in texts["translate"] and "translation" in texts["translate"]
    assert "STUCK" in texts["rescue"]
    assert prompts.partner_system(LANGS, "intermediate", "no-such-mode") == texts["rescue"]  # unknown: the default
    assert prompts.LEVELS["intermediate"] in prompts.partner_system(LANGS, "no-such-level", "rescue")


def test_free_conversation_has_no_scene():
    text = prompts.partner_system(LANGS, "beginner", "rescue")
    assert "FREE CONVERSATION" in text and "ROLE-PLAY" not in text


@pytest.mark.parametrize("build, report_language", [
    (prompts.grader_system, True), (prompts.summary_system, True), (prompts.vocab_system, True), (prompts.help_system, False),
])
def test_the_other_prompts_are_filled_in(build, report_language):
    text = build(LANGS)
    assert not unresolved(text)
    assert label(LANGS["target"]) in text
    if report_language:
        assert label(LANGS["report"]) in text  # feedback comes out in the language chosen for it


def test_the_opening_asks_for_the_target_language():
    assert label(LANGS["target"]) in prompts.opening_request(LANGS)


class TestTheFakeModelKnowsTheRealPrompts:
    """FakeLLM tells requests apart by words in the system prompt: reword a prompt and this fails, not every test quietly."""

    @pytest.mark.parametrize("build, want_json, kind", [
        (prompts.grader_system, True, "grade"), (prompts.summary_system, True, "summary"),
        (prompts.vocab_system, True, "vocab"), (prompts.help_system, True, "help"),
    ])
    def test_kinds(self, build, want_json, kind):
        assert FakeLLM.kind([{"role": "system", "content": build(LANGS)}], want_json) == kind

    def test_a_conversation_turn_is_a_partner_call(self):
        system = prompts.partner_system(LANGS, "intermediate", "rescue")
        assert FakeLLM.kind([{"role": "system", "content": system}], False) == "partner"


class TestSplitAid:
    @pytest.mark.parametrize("raw, spoken, aid", [
        ("Hola.\n---\nHello.", "Hola.", "Hello."),
        ("Hola.\n  ----  \nHello.", "Hola.", "Hello."),
        ("Hola.", "Hola.", ""),
        ("Hola.\n---\nOne\n---\nTwo", "Hola.", "One\n---\nTwo"),  # only the first divider splits
        ("Well --- maybe", "Well --- maybe", ""),  # a dash run inside a sentence isn't one
    ])
    def test_the_format_the_prompts_ask_for(self, raw, spoken, aid):
        assert split_aid(raw) == (spoken, aid)
