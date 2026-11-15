import pytest

from openspeak import languages
from openspeak.languages import all_languages, label, resolve

ALL = all_languages()


def test_ids_are_unique():
    ids = [lang["id"] for lang in ALL]
    assert len(ids) == len(set(ids))


def test_exactly_these_scripts_run_right_to_left():
    assert {lang["id"] for lang in ALL if lang["rtl"]} == {"ar", "he", "fa", "ur"}


def test_exactly_these_are_counted_in_characters_not_words():
    # Written without spaces between words, so "enough to grade" can't be a word count.
    assert {lang["id"] for lang in ALL if lang["chars"]} == {"zh-CN", "zh-TW", "yue", "ja", "th"}


def test_every_built_in_has_what_speech_needs():
    for lang in ALL:
        assert lang["name"] and lang["native"] and lang["stt"] and lang["tts"], lang["id"]


def test_there_are_38():
    assert len(ALL) == 38  # the README says so


class TestResolve:
    def test_a_known_id(self):
        assert resolve("ja")["native"] == "日本語" and resolve("pt-BR")["stt"] == "pt"

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_nothing_means_english(self, blank):
        assert resolve(blank)["id"] == "en"

    def test_whitespace_around_an_id_is_ignored(self):
        assert resolve("  fr \n")["id"] == "fr"

    def test_a_language_typed_in_works_for_prompts_and_leaves_speech_to_detect(self):
        swiss = resolve("Swiss German")
        assert swiss["name"] == swiss["native"] == swiss["id"] == "Swiss German"
        assert swiss["stt"] is None and swiss["tts"] is None and not swiss["chars"] and not swiss["rtl"]

    def test_the_result_is_a_copy(self):
        resolve("en")["name"] = "changed"
        assert resolve("en")["name"] == "English"


def test_label_names_a_language_for_a_prompt():
    assert label(resolve("es")) == "Spanish (Español)"
    assert label(resolve("English")) == "English"  # the same name twice isn't repeated
    assert label(resolve("Swiss German")) == "Swiss German"


def test_the_list_handed_out_is_a_copy():
    all_languages()[0]["id"] = "changed"
    assert all_languages()[0]["id"] == "en"
    assert languages.resolve("en")["id"] == "en"
