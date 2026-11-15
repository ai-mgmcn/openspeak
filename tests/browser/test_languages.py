"""
Choosing languages in the settings, as a person does: what is saved, what the page
then shows, and that it is still so after a reload.
"""

import json
import urllib.request

import pytest

SAVED_DEFAULTS = {"languages": {"target": "en", "native": "zh-CN", "report": "zh-CN"}, "ui_language": "auto"}


@pytest.fixture(autouse=True)
def put_languages_back(server):
    """The server is shared by every test in the session; leave its languages as found."""
    yield
    urllib.request.urlopen(urllib.request.Request(
        server + "/api/config", json.dumps(SAVED_DEFAULTS).encode(), {"Content-Type": "application/json", "Origin": server}), timeout=5)


def open_settings(page):
    page.evaluate("openDrawer('settings', 'lang')")
    page.wait_for_selector("#settings.open #target")


def pick(page, selector, value):
    page.select_option(selector, value)
    page.wait_for_timeout(400)  # the page saves in the background


def saved(page):
    """What the server has, not just what the page believes."""
    return page.evaluate("fetch('/api/meta').then(r => r.json()).then(m => [m.config.languages, m.config.ui_language])")


class TestPracticeNativeAndFeedbackLanguages:
    @pytest.mark.parametrize("lang", ["ja", "es", "ar", "zh-TW", "pt-BR", "yue"])
    def test_choosing_what_to_practise(self, page, lang):
        open_settings(page)
        pick(page, "#target", lang)
        assert saved(page)[0]["target"] == lang
        assert page.evaluate("langName(cfg.languages.target)") in page.inner_text("#langPill")

    def test_the_other_three_are_independent(self, page):
        open_settings(page)
        pick(page, "#native", "fr")
        pick(page, "#reportLang", "de")
        languages = saved(page)[0]
        assert languages["native"] == "fr" and languages["report"] == "de" and languages["target"] == "en"

    def test_a_language_typed_in(self, page):
        open_settings(page)
        page.select_option("#target", "__other")
        assert page.is_visible("#targetOther")
        page.fill("#targetOther", "Swiss German")
        page.press("#targetOther", "Enter")
        page.wait_for_timeout(500)
        assert saved(page)[0]["target"] == "Swiss German"
        assert "Swiss German" in page.inner_text("#langPill")
        assert page.evaluate("$('#langNote').textContent").startswith("Custom language")  # and says what that means

    def test_the_choice_is_there_after_a_reload(self, page, server):
        open_settings(page)
        pick(page, "#target", "ko")
        page.reload()
        page.wait_for_selector("#catTabs button")
        open_settings(page)
        assert page.input_value("#target") == "ko" and "한국어" in page.inner_text("#langPill")

    def test_a_refused_choice_goes_back(self, page):
        open_settings(page)
        page.route("**/api/config", lambda route: route.fulfill(status=400, content_type="application/json", body='{"detail":"nope"}'))
        pick(page, "#target", "ja")
        assert page.input_value("#target") == "en" and page.evaluate("cfg.languages.target") == "en"
        assert "nope" in page.inner_text("#toast")

    def test_a_conversation_starts_in_the_chosen_language(self, page, fake):
        asked = []
        page.route("**/api/session", lambda route, request: (asked.append(1), fake.route(route, request))[1])
        open_settings(page)
        pick(page, "#target", "ar")
        page.evaluate("closeDrawers()")
        page.click(".card.feature")
        page.wait_for_function("S && V.active")
        assert asked and page.evaluate("S.tts") == "en-US"  # what the server said; the page uses it for the voice


class TestRightToLeft:
    def test_the_conversation_reads_right_to_left_when_the_language_does(self, page, fake):
        fake.rtl = True
        page.click(".card.feature")
        page.wait_for_function("S")
        assert page.evaluate("$('#chat').dir") == "rtl"

    def test_and_left_to_right_when_it_does_not(self, page, fake):
        page.click(".card.feature")
        page.wait_for_function("S")
        assert page.evaluate("$('#chat').dir") == "auto"


def choose_interface(page, code):
    """What a person does: the globe in the header, then the language."""
    page.click("#langBtn")
    page.click(f"#langMenu button:nth-child({['auto', 'zh', 'en', 'ja'].index(code) + 1})")
    page.wait_for_timeout(400)


class TestInterfaceLanguage:
    HERO = {"en": "What do you want to practise today?", "zh": "今天想练什么？", "ja": "今日は何を練習しますか"}

    def test_it_is_in_the_header_not_buried_in_the_settings(self, page):
        assert page.is_visible("#langBtn")
        open_settings(page)
        assert page.query_selector("#uiLang") is None

    def test_the_menu_names_each_language_in_itself(self, page):
        page.click("#langBtn")
        names = page.inner_text("#langMenu").split()
        assert names[-3:] == ["中文", "English", "日本語"] and page.evaluate("$('#langBtn').getAttribute('aria-expanded')") == "true"

    def test_the_current_one_is_marked(self, page):
        choose_interface(page, "ja")
        page.click("#langBtn")
        marked = page.evaluate("[...document.querySelectorAll('#langMenu button')].filter(b => b.getAttribute('aria-checked') === 'true').map(b => b.textContent)")
        assert marked == ["日本語"]

    def test_it_closes_on_escape_and_on_a_click_elsewhere(self, page):
        page.click("#langBtn")
        page.keyboard.press("Escape")
        assert not page.is_visible("#langMenu")
        page.click("#langBtn")
        page.click(".hero h1")
        assert not page.is_visible("#langMenu") and page.evaluate("$('#langBtn').getAttribute('aria-expanded')") == "false"

    def test_the_button_opens_and_closes_it(self, page):
        page.click("#langBtn")
        assert page.is_visible("#langMenu")
        page.click("#langBtn")
        assert not page.is_visible("#langMenu")

    def test_the_menu_stays_on_screen_on_a_phone(self, page):
        page.set_viewport_size({"width": 320, "height": 640})
        page.wait_for_timeout(500)
        page.click("#langBtn")
        box = page.evaluate("(() => { const r = $('#langMenu').getBoundingClientRect(); return [r.left, r.right, r.bottom] })()")
        assert box[0] >= 0 and box[1] <= 320 and box[2] <= 640

    @pytest.mark.parametrize("code", ["zh", "ja", "en"])
    def test_every_visible_word_follows(self, page, code):
        choose_interface(page, code)
        assert saved(page)[1] == code
        assert page.evaluate("document.documentElement.lang") == code
        hero = page.inner_text(".hero h1")
        assert hero == self.HERO[code] or hero.startswith(self.HERO[code][:6]), hero
        # nothing left in another language: no English in the chrome of a Chinese or Japanese page
        if code != "en":
            words = page.evaluate("""[...document.querySelectorAll('[data-i18n]')].map(e => e.textContent)
                .filter(t => /^[A-Za-z ]{4,}$/.test(t))""")
            assert [w for w in words if w != "Markdown"] == []  # a file format's name stays as it is

    def test_the_settings_are_in_it_too(self, page):
        choose_interface(page, "zh")
        open_settings(page)
        assert "设置" in page.inner_text("#settings .drawer-head") and "语言" in page.inner_text("#setTabs")

    def test_the_menu_itself_is_relabelled(self, page):
        choose_interface(page, "zh")
        assert page.evaluate("$('#langBtn').getAttribute('aria-label')") == "界面语言"
        page.click("#langBtn")
        assert page.inner_text("#langMenu").startswith("自动")

    def test_a_conversation_carries_on_when_it_changes(self, page):
        page.click(".card.feature")
        page.wait_for_function("S && V.active")
        before = page.evaluate("S.id")
        choose_interface(page, "ja")
        assert page.evaluate("S.id") == before and page.evaluate("V.active") and not page.evaluate("$('#talk').classList.contains('hidden')")
        title = page.inner_text("#sceneTitle")
        assert page.evaluate("T.freeTitle") in title and "Free conversation" not in title  # the title is in the new language

    def test_it_survives_a_reload(self, page):
        choose_interface(page, "ja")
        page.reload()
        page.wait_for_selector("#catTabs button")
        assert page.evaluate("document.documentElement.lang") == "ja"

    def test_a_refused_change_goes_back(self, page):
        page.route("**/api/config", lambda route: route.fulfill(status=400, content_type="application/json", body='{"detail":"nope"}'))
        choose_interface(page, "zh")
        assert page.evaluate("document.documentElement.lang") != "zh" and "nope" in page.inner_text("#toast")
