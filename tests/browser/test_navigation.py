"""
Moving between the conversation, the home screen and the sidebar: what a stray click
costs, and that "back" only ever means the conversation that was open.
"""


def start_free_talk(page):
    page.click(".card.feature")
    page.wait_for_function("S && !$('#talk').classList.contains('hidden') && V.active")


def sid(page):
    return page.evaluate("S && S.id")


def on(page, view):
    return not page.evaluate(f"$('#{view}').classList.contains('hidden')")


def sidebar_open(page):
    return page.evaluate("document.body.classList.contains('side-open')")


class TestTheIconOpensTheSidebar:
    def test_it_opens_a_hidden_sidebar(self, page):
        page.evaluate("setSide(false)")
        page.click("#brandBtn")
        assert sidebar_open(page)

    def test_it_never_closes_it(self, page):
        page.evaluate("setSide(true)")
        page.click("#brandBtn")  # one click on an open sidebar must leave it open
        assert sidebar_open(page)
        page.click("#brandBtn")
        assert sidebar_open(page)

    def test_the_sidebar_button_is_what_closes_it(self, page):
        page.evaluate("setSide(true)")
        page.click("#sideBtn")
        assert not sidebar_open(page)

    def test_a_click_in_a_conversation_leaves_it_running(self, page):
        start_free_talk(page)
        before = sid(page)
        page.click("#brandBtn")
        assert on(page, "talk") and sid(page) == before and page.evaluate("V.active")

    def test_it_is_a_button_for_the_keyboard_and_screen_readers(self, page):
        assert page.evaluate("[$('#brandBtn').tagName, $('#brandBtn').getAttribute('aria-label')]") == ["BUTTON", "History"]


class TestNewSessionFromTheHeader:
    def test_it_shows_only_while_the_sidebar_is_hidden(self, page):
        page.evaluate("setSide(false)")
        assert page.is_visible("#newTop")
        page.evaluate("setSide(true)")
        assert not page.is_visible("#newTop")

    def test_one_click_goes_home_from_a_conversation(self, page):
        page.evaluate("setSide(false)")
        start_free_talk(page)
        page.click("#newTop")
        assert on(page, "home") and not on(page, "talk")


class TestPausedConversation:
    def pause(self, page):
        page.evaluate("setSide(false)")
        page.click("#newTop")

    def test_going_home_pauses_it_and_says_so(self, page):
        start_free_talk(page)
        self.pause(page)
        assert page.is_visible("#pausedBar") and "Practice paused" in page.inner_text("#pausedBar")
        assert not page.evaluate("V.active") and page.evaluate("V.state") == "idle"  # the mic is off, not listening at the home screen

    def test_continue_comes_back_to_the_same_conversation_with_the_mic_as_it_was(self, page):
        start_free_talk(page)
        before = sid(page)
        self.pause(page)
        page.click("#pausedBar button")
        assert on(page, "talk") and sid(page) == before
        page.wait_for_function("V.active")
        assert not page.is_visible("#pausedBar")

    def test_a_mic_that_was_off_stays_off(self, page):
        start_free_talk(page)
        page.click("#micBtn")  # off
        assert not page.evaluate("V.active")
        self.pause(page)
        page.click("#pausedBar button")
        page.wait_for_timeout(300)
        assert on(page, "talk") and not page.evaluate("V.active")

    def test_nothing_is_shown_when_there_is_no_conversation(self, page):
        assert not page.is_visible("#pausedBar")

    def test_it_exists_only_while_paused(self, page):
        hidden = "$('#pausedBar').classList.contains('hidden')"
        start_free_talk(page)
        assert page.evaluate(hidden)  # in the conversation itself
        self.pause(page)
        assert not page.evaluate(hidden)
        page.evaluate("leaveSession()")  # the conversation goes away by any route, with no screen change
        assert page.evaluate(hidden) and page.evaluate("$('#pausedBar').children.length") == 0

    def test_starting_another_conversation_replaces_it(self, page, fake):
        start_free_talk(page)
        first = sid(page)
        self.pause(page)
        page.click(".card.feature")
        page.wait_for_function(f"S && S.id !== '{first}' && !$('#talk').classList.contains('hidden')")
        second = sid(page)
        self.pause(page)
        page.click("#pausedBar button")
        assert sid(page) == second != first  # back to the one now open, never the earlier one

    def test_a_stale_continue_does_nothing(self, page):
        start_free_talk(page)
        self.pause(page)
        page.evaluate("window.__old = $('#pausedBar button')")  # the button as it was, still wired to the old conversation
        page.evaluate("leaveSession(); show('home')")
        page.evaluate("window.__old.click()")  # a click that arrives late
        assert on(page, "home") and not page.is_visible("#pausedBar") and page.evaluate("S") is None

    def test_deleting_it_from_history_removes_the_way_back(self, page, fake):
        start_free_talk(page)
        self.pause(page)
        page.evaluate("setSide(true)")
        page.once("dialog", lambda d: d.accept())
        page.evaluate(f"deleteSession('{fake.n and list(fake.sessions)[0]}')")
        page.wait_for_function("S === null")
        assert on(page, "home") and not page.is_visible("#pausedBar")

    def test_a_conversation_the_server_dropped_removes_the_way_back(self, page, fake):
        start_free_talk(page)
        self.pause(page)
        fake.gone.add(sid(page))
        page.wait_for_function("S === null", timeout=8000)  # the page's own status poll finds out
        assert on(page, "home") and not page.is_visible("#pausedBar")

    def test_the_history_row_of_the_open_conversation_also_goes_back(self, page):
        start_free_talk(page)
        before = sid(page)
        self.pause(page)
        page.evaluate("setSide(true)")
        page.wait_for_selector("#historyList .hist .main")
        page.click("#historyList .hist .main")
        assert on(page, "talk") and sid(page) == before
        page.wait_for_function("V.active")  # the same way back as the Continue button: mic as it was

    def test_back_from_a_report_resumes_the_mic_too(self, page):
        start_free_talk(page)
        page.evaluate("showReport('20260101_000000')")
        assert on(page, "reportView") and not page.evaluate("V.active")
        page.click("#backHome")
        page.wait_for_function("V.active")
        assert on(page, "talk")

    def test_the_words_follow_the_interface_language(self, page):
        start_free_talk(page)
        self.pause(page)
        page.evaluate("cfg.ui_language = 'zh'; relabel()")
        assert "练习已暂停" in page.inner_text("#pausedBar")


class TestTheHeaderOnASmallScreen:
    def test_every_control_fits_in_320_px(self, page):
        page.set_viewport_size({"width": 320, "height": 640})
        page.evaluate("setSide(false)")
        page.wait_for_timeout(500)  # the sidebar's padding eases away
        boxes = page.evaluate("""[...document.querySelectorAll('.top > *')].filter(e => e.offsetParent).map(e => {
            const r = e.getBoundingClientRect(); return [e.id || e.className, Math.round(r.left), Math.round(r.right)] })""")
        assert {b[0] for b in boxes} >= {"sideBtn", "brandBtn", "newTop", "langPill", "langBtn", "settingsBtn"}
        assert all(0 <= left and right <= 320 for _, left, right in boxes), boxes
        assert page.evaluate("document.documentElement.scrollWidth") <= 320


def test_a_report_card_names_the_scene_that_was_practised(page):
    """The job's scene is just a title in each language, not the whole scene."""
    page.evaluate("""Jobs.track({id: "20260101_120000", kind: "finish", stage: "ready", complete: true, ungraded: 0, problem: "",
                                   scene: {en: "Check-in: overweight bag", zh: "值机"}})""")
    card = page.locator("#jobs .job b").first
    assert "Check-in: overweight bag" in card.inner_text()
    page.evaluate("""Jobs.track({id: "20260101_130000", kind: "finish", stage: "ready", complete: true, ungraded: 0, problem: "", scene: null})""")
    assert "Free conversation" in page.locator("#jobs .job b").nth(1).inner_text()


def test_the_mic_ring_at_its_largest_does_not_make_the_page_scroll(page):
    """It grows with your voice; if it overflowed, a scrollbar would flicker in and out as you speak."""
    page.click(".card.feature")
    page.wait_for_selector("#micBtn")
    for width, height in ((1100, 760), (390, 700), (1280, 800)):
        page.set_viewport_size({"width": width, "height": height})
        spare = page.evaluate("() => { const se = document.scrollingElement; return se.scrollHeight - se.clientHeight }")
        page.evaluate("() => { document.querySelector('#ring').style.transition = 'none'; document.querySelector('#ring').style.transform = `scale(${1 + RING_MAX})` }")
        assert page.evaluate("() => { const se = document.scrollingElement; return se.scrollHeight - se.clientHeight }") == spare, (width, height)
