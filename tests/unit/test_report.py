import os

import pytest

from openspeak import report


def summary():
    return {"kind": "summary", "level": "B1", "patterns": [], "priorities": [], "encouragement": ""}


class TestDescribe:
    def test_hello_only_is_complete_without_a_summary(self, write_log):
        d = report.describe(write_log([("heard", 1, "hello", False), "vocab", "session_end"]))
        assert d["complete"] and d["ended"] and d["turns"] == 1

    def test_ungraded_turn_is_incomplete(self, write_log):
        d = report.describe(write_log([("heard", 1, "I want check in"), "session_end"]))
        assert not d["complete"] and d["ungraded"] == 1

    def test_stale_summary_is_incomplete(self, write_log):
        d = report.describe(write_log([("heard", 1, "I want check in"), ("turn", 1, "I want check in"), summary(),
                                       "vocab", ("heard", 2, "and one more thing")]))
        assert not d["complete"] and not d["ended"]

    def test_says_why_it_is_incomplete(self, write_log):
        d = report.describe(write_log([("heard", 1, "I want check in"),
                                       {"kind": "turn_error", "turn": 1, "said": "x", "error": "TimeoutError: slow"}]))
        assert d["problem"] == "TimeoutError: slow"

    def test_cache_follows_the_log(self, write_log):
        path = write_log([("heard", 1, "I want check in")])
        assert report.describe(path)["turns"] == 1
        with open(path, "a") as f:
            f.write('{"kind":"heard","turn":2,"said":"another line here"}\n')
        assert report.describe(path)["turns"] == 2


class TestBuild:
    def test_writes_html_and_markdown(self, write_log):
        path = write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in"), ("turn", 1, "I want check in")])
        out = report.build(path)
        assert os.path.exists(out["html"]) and os.path.exists(out["html"][:-5] + ".md")
        assert report.describe(path)["has_report"]



EVIL = '"><img src=x onerror=alert(1)><script>alert(2)</script>'


def full_log(text):
    """Every field a report shows, all holding `text`."""
    err = {"type": text, "original": text, "correction": text, "explain": text, "severity": text}
    turn = {"kind": "turn", "turn": 1, "said": text, "verdict": text, "corrected": text, "native_version": text,
            "good_note": text, "errors": [err]}
    return [
        {"kind": "session_start", "at": "2026-01-01T12:00:00", "level": "B1", "reply_mode": "immersive",
         "languages": {"target": {"id": "en"}, "native": {"id": "zh-CN"}, "report": {"id": "en"}},
         "scene": {"id": 8, "title": {"en": text}, "prompt": text, "hard": False}},
        {"kind": "partner", "turn": 0, "said": text, "aid": text},
        {"kind": "heard", "turn": 1, "said": text, "graded": True}, turn,
        {"kind": "help", "turn": 1, "hint": text, "say": [text]},
        {"kind": "summary", "level": text, "patterns": [text], "priorities": [text], "encouragement": text},
        {"kind": "vocab", "items": [{"term": text, "meaning": text, "example": text}]},
        {"kind": "session_end", "at": "2026-01-01T12:05:00"},
    ]


class Tags:
    """The tags and attributes of an HTML page."""

    def __init__(self, page):
        from html.parser import HTMLParser

        self.tags, self.attrs = [], []

        class P(HTMLParser):
            def handle_starttag(p, tag, attrs):
                self.tags.append(tag)
                self.attrs += [(tag, k, v) for k, v in attrs]

        P().feed(page)


class TestHostileText:
    """Anything the learner or the model wrote ends up as text, whichever field it is in."""

    def build(self, write_log, text):
        path = write_log(full_log(text))
        out = report.build(path)
        return open(out["html"], encoding="utf-8").read(), open(path[:-6] + ".md", encoding="utf-8").read()

    def test_html_gains_no_tags_or_handlers(self, write_log):
        calm, _ = self.build(write_log, "plain words")
        evil, _ = self.build(write_log, EVIL)
        a, b = Tags(calm), Tags(evil)
        assert sorted(b.tags) == sorted(a.tags)  # nothing new: no <img>, no second <script>
        assert sorted((t, k) for t, k, _ in b.attrs) == sorted((t, k) for t, k, _ in a.attrs)  # no new attribute, no handler
        assert "<img" not in evil and "alert(2)</script>" not in evil
        assert evil.count("&lt;img src=x onerror=alert(1)&gt;") >= 10  # shown, as text, in many places

    def test_markdown_has_no_raw_tags(self, write_log):
        import re

        _, md = self.build(write_log, EVIL)
        assert not re.search(r"(?<!\\)<", md) and "\\<img" in md  # no tag can open (the report's own "> " quotes are its markup)

    def test_markdown_table_survives_pipes_and_line_breaks(self, write_log):
        path = write_log(full_log("a | b\nc"))
        report.build(path)
        md = open(path[:-6] + ".md", encoding="utf-8").read()
        rows = [ln for ln in md.splitlines() if ln.startswith("| ")]
        assert len(rows) == 2 and all(r.count("|") - r.count("\\|") == 4 for r in rows)  # a header and one item, three cells each

    def test_markdown_marks_inside_text_stay_text(self, write_log):
        path = write_log([("partner", 0, "Say **hello** to [me](http://x) `now`"), ("heard", 1, "ok then", False)])
        report.build(path)
        md = open(path[:-6] + ".md", encoding="utf-8").read()
        assert "\\*\\*hello\\*\\*" in md and "\\[me\\]" in md and "\\`now\\`" in md


def test_full_report_shows_help_fixes_and_notes(write_log):
    turn = {"kind": "turn", "turn": 1, "said": "I want check in now", "verdict": "errors",
            "corrected": "I want to check in now", "native_version": "I'd like to check in now",
            "good_note": "Clear request", "errors": [
                {"type": "grammar", "original": "want check", "correction": "want to check", "severity": "high"},
                {"type": "grammar", "original": "want", "correction": "wish", "severity": "low"},
                {"type": "word-choice", "original": "not in the sentence", "correction": "x", "severity": "low"}]}
    path = write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in now"), turn,
                      {"kind": "help", "turn": 1, "hint": "Ask the price", "say": ["How much is it?"]}])
    html = open(report.build(path)["html"], encoding="utf-8").read()
    md = open(path[:-6] + ".md", encoding="utf-8").read()
    for text in ("Ask the price", "How much is it?", "I&#x27;d like to check in now", "Clear request"):
        assert text in html, text
    assert html.count("<mark") >= 1 and "I want to check in now" in md


def test_no_sessions_dir(monkeypatch, home):
    from openspeak import config

    monkeypatch.setattr(config, "SESSIONS_DIR", str(home / "missing"))
    assert report.list_sessions() == []


def test_reports_are_readable_by_their_owner_only(write_log):
    import stat

    out = report.build(write_log([("partner", 0, "Welcome"), ("heard", 1, "I want check in")]))
    assert all(stat.S_IMODE(os.stat(p).st_mode) == 0o600 for p in out.values())


class TestWhatTheReportShows:
    def page(self, write_log, records, report_lang="en"):
        records = [dict(r) for r in records]
        records[0]["languages"] = {"target": {"id": "en"}, "native": {"id": "zh-CN"}, "report": {"id": report_lang}}
        path = write_log(records)
        report.build(path)
        return open(path[:-6] + ".html", encoding="utf-8").read(), open(path[:-6] + ".md", encoding="utf-8").read()

    def test_the_newest_regrade_and_summary_win(self, write_log):
        records = full_log("x")[:4]
        records[3] = {**records[3], "corrected": "FIRST-GRADE"}
        records += [{**records[3], "corrected": "SECOND-GRADE"},
                    {"kind": "summary", "level": "OLD-SUMMARY", "patterns": [], "priorities": [], "encouragement": ""},
                    {"kind": "summary", "level": "NEW-SUMMARY", "patterns": [], "priorities": [], "encouragement": ""}]
        page, md = self.page(write_log, records)
        assert "SECOND-GRADE" in page and "FIRST-GRADE" not in page
        assert "NEW-SUMMARY" in page and "OLD-SUMMARY" not in page and "NEW-SUMMARY" in md and "OLD-SUMMARY" not in md

    @pytest.mark.parametrize("lang, heading", [("en", "Speaking report"), ("zh-CN", "口语练习报告"), ("ja", "スピーキング")])
    def test_the_page_is_in_the_report_language(self, write_log, lang, heading):
        page, md = self.page(write_log, full_log("x"), lang)
        assert heading in page and heading in md and f'lang="{lang}"' in page

    def test_a_language_with_no_translation_falls_back_to_english(self, write_log):
        page, _ = self.page(write_log, full_log("x"), "Swiss German")
        assert "Speaking report" in page

    @pytest.mark.parametrize("lang, direction", [("ar", "rtl"), ("he", "rtl"), ("en", "ltr"), ("zh-CN", "ltr")])
    def test_direction_follows_the_script(self, write_log, lang, direction):
        page, _ = self.page(write_log, full_log("x"), lang)
        assert f'dir="{direction}"' in page

    def test_each_kind_of_ungraded_line_says_why(self, write_log):
        page, _ = self.page(write_log, [
            {"kind": "session_start", "at": "2026-01-01T12:00:00", "languages": {"target": {"id": "en"}, "native": {"id": "zh-CN"}, "report": {"id": "en"}}},
            {"kind": "heard", "turn": 1, "said": "skipped line here", "graded": False},
            {"kind": "heard", "turn": 2, "said": "failed line here", "graded": True},
            {"kind": "turn_error", "turn": 2, "said": "failed line here", "error": "x"},
            {"kind": "heard", "turn": 3, "said": "line from an older log with no grading flag"}])
        en = report.L["en"]
        # too short; meant to be graded but wasn't (failed); and no record of whether it should have been
        assert page.count(en["skipped"]) == 1 and page.count(en["failed"]) == 1 and page.count(en["pending"]) == 1

    def test_prune_forgets_logs_that_are_gone(self, write_log):
        path = write_log([("heard", 1, "I want check in")])
        report.describe(path)
        assert path in report._described
        report.prune([])
        assert path not in report._described


class TestHandEditedLogs:
    """A log edited by hand, or written by an older version, still gives a report rather than an error."""

    START = {"kind": "session_start", "at": "2026-01-01T12:00:00", "scene": {"id": 1, "title": {"en": "Hotel"}},
             "languages": {"target": {"id": "en"}, "native": {"id": "zh-CN"}, "report": {"id": "en"}}}
    SAID = {"kind": "heard", "turn": 1, "said": "hello there my friend", "graded": True}

    @pytest.mark.parametrize("name, records", [
        ("scene title as plain text", [{**START, "scene": {"id": 1, "title": "Hotel"}}]),
        ("scene as plain text", [{**START, "scene": "Hotel"}]),
        ("scene with no title", [{**START, "scene": {"id": 1}}]),
        ("a language as plain text", [{**START, "languages": {"target": "en", "native": "zh-CN", "report": "en"}}]),
        ("languages as a list", [{**START, "languages": ["en"]}]),
        ("a time that is a number", [{**START, "at": 5}]),
        ("vocabulary that isn't a table", [START, SAID, {"kind": "vocab", "items": ["oops", {"meaning": "no term"}, {"term": "ok"}]}]),
        ("a summary of numbers", [START, SAID, {"kind": "summary", "level": 3, "patterns": [1, 2], "priorities": "text", "encouragement": None}]),
        ("a help line that isn't a list", [START, SAID, {"kind": "help", "turn": 1, "hint": 5, "say": "not a list"}]),
        ("an aid that is a number", [START, {"kind": "partner", "turn": 0, "said": "hi", "aid": 5}]),
    ], ids=lambda x: x if isinstance(x, str) else "")
    def test_the_report_is_still_built(self, write_log, name, records):
        path = write_log(records)
        assert report.describe(path)["id"]
        out = report.build(path)
        assert os.path.getsize(out["html"]) > 0 and os.path.getsize(out["md"]) > 0

    def test_the_good_parts_of_a_damaged_vocabulary_survive(self, write_log):
        path = write_log([self.START, self.SAID, {"kind": "vocab", "items": ["oops", {"meaning": "no term"}, {"term": "check in", "meaning": 5}]}])
        report.build(path)
        md = open(path[:-6] + ".md", encoding="utf-8").read()
        assert "check in" in md and "oops" not in md and "no term" not in md
