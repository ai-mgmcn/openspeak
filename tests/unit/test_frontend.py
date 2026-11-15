"""
The page and its strings agree: every language has every string once, the page
only asks for strings and elements that exist, and the settings offer exactly
the choices the server accepts.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

from openspeak import config

STATIC = os.path.join(os.path.dirname(config.__file__), "web", "static")
DATA = os.path.join(os.path.dirname(config.__file__), "data")


def read(name, folder=STATIC):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return f.read()


APP, PAGE = read("app.js"), read("index.html")
START = APP.index("const I18N = {") + len("const I18N = ")
END = APP.index("\n};\n", START) + 2
I18N_SRC = APP[START:END]


class Literal:
    """Reads the keys of a JS object literal: just enough syntax for the string tables."""

    def __init__(self, src):
        self.src, self.i, self.twice = src, 0, []

    def ws(self):
        while self.src[self.i].isspace():
            self.i += 1

    def string(self):
        quote = self.src[self.i]
        self.i += 1
        while self.src[self.i] != quote:
            if self.src[self.i] == "\\":
                self.i += 1
            elif quote == "`" and self.src.startswith("${", self.i):
                self.i += 2
                self.expr("}")
            self.i += 1
        self.i += 1

    def expr(self, *stops):
        """Skip a value up to a stop character at its own depth."""
        depth = 0
        while depth or self.src[self.i] not in stops:
            ch = self.src[self.i]
            if ch in "\"'`":
                self.string()
                continue
            depth += (ch in "([{") - (ch in ")]}")
            self.i += 1

    def obj(self, path=()):
        """{ key: value, ... } -> {key: nested keys, or None for any other value}."""
        keys = {}
        self.i += 1
        while True:
            self.ws()
            if self.src[self.i] == "}":
                self.i += 1
                return keys
            key = re.match(r"\w+", self.src[self.i:]).group()
            self.i += len(key)
            self.ws()
            assert self.src[self.i] == ":", f"after {'.'.join(path + (key,))}"
            self.i += 1
            self.ws()
            if key in keys:
                self.twice.append(".".join(path + (key,)))
            if self.src[self.i] == "{":
                keys[key] = self.obj(path + (key,))
            else:
                keys[key] = None
                self.expr(",", "}")
            self.ws()
            if self.src[self.i] == ",":
                self.i += 1


@pytest.fixture(scope="module")
def tables():
    lit = Literal(I18N_SRC)
    return lit.obj(), lit.twice


@pytest.fixture(scope="module")
def en(tables):
    return tables[0]["en"]


def shape(keys):
    return {k: shape(v) if v else None for k, v in keys.items()}


class TestStrings:
    def test_the_reader_sees_every_table(self, tables):
        assert list(tables[0]) == ["en", "zh", "ja"]

    def test_no_string_is_defined_twice(self, tables):
        # A second one silently wins: how "How the partner replies" once showed "F", "r".
        assert tables[1] == []

    @pytest.mark.parametrize("lang", ["zh", "ja"])
    def test_every_language_has_every_string(self, tables, en, lang):
        assert shape(tables[0][lang]) == shape(en)

    def test_the_page_only_names_strings_that_exist(self, en):
        named = set(re.findall(r'data-i18n(?:-ph|-label)?="(\w+)"', PAGE))
        assert named and named - set(en) == set()

    def test_the_script_only_uses_strings_that_exist(self, en):
        used = set(re.findall(r"\bT\.(\w+)(?:\.(\w+))?", APP))
        assert used
        for key, sub in used:
            assert key in en, key
            if sub and en[key]:
                assert sub in en[key], f"{key}.{sub}"


class TestChoices:
    """Each list of options in the settings is exactly what the server will save."""

    @pytest.mark.parametrize("strings, setting", [
        ("modes", "reply_mode"), ("levels", "level"), ("whens", "coach.when"),
        ("sttEngines", "stt.engine"), ("ttsEngines", "tts.engine"),
    ])
    def test_match_the_server(self, en, strings, setting):
        assert list(en[strings]) == list(config.CHOICES[setting])

    def test_scene_categories_have_names(self, en):
        scenes = json.loads(read("scenes.json", DATA))
        scenes = scenes["scenes"] if isinstance(scenes, dict) else scenes
        assert {s["cat"] for s in scenes} == set(en["cats"])


def test_the_script_never_builds_markup_from_text():
    # Everything on the page is made with createElement and textContent, so text from the
    # model or the learner can't become markup.
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(", APP)


def test_the_script_only_looks_up_elements_on_the_page():
    ids = set(re.findall(r'\bid="([\w-]+)"', PAGE)) | set(re.findall(r'\bid: "([\w-]+)"', APP))
    wanted = set(re.findall(r'\$\$?\("#([\w-]+)', APP))
    assert wanted and wanted - ids == set()


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="needs Node.js")
class TestInNode:
    def run(self, body):
        script = f"const I18N = {I18N_SRC};\n{body}"
        out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def test_the_script_parses(self):
        out = subprocess.run([NODE, "--check", os.path.join(STATIC, "app.js")], capture_output=True, text=True, check=False)
        assert out.returncode == 0, out.stderr

    def test_every_string_reads_well(self):
        # Every string, and every function called with sample numbers, in every language.
        bad = self.run("""
            const bad = [];
            const walk = (v, path) => {
              if (typeof v === "function") v = v(...Array(v.length).fill(2));
              if (typeof v === "string") { if (!v.trim() || /undefined|NaN|\\[object/.test(v)) bad.push(path); }
              else if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${path}[${i}]`));
              else if (v && typeof v === "object") for (const k in v) walk(v[k], `${path}.${k}`);
              else bad.push(path);
            };
            walk(I18N, "I18N");
            console.log(JSON.stringify(bad));
        """)
        assert bad == []

    def test_english_counts(self):
        assert self.run("""
            const T = I18N.en;
            console.log(JSON.stringify([T.nTurns(1), T.nTurns(2), T.nMistakes(1), T.nMistakes(0)]));
        """) == ["1 turn", "2 turns", "1 mistake", "0 mistakes"]
