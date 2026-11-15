"""
Each API key belongs to the service it was entered for and is only ever sent
there: switching services switches keys, and a changed URL never takes a key
somewhere else.
"""

import json

import pytest

from openspeak import config

GATEWAY = "https://gateway.example.invalid/v1"
OTHER = "https://other.example.invalid/v1"


def stored():
    with open(config.CONFIG_PATH) as f:
        return json.load(f)


def keys(entries):
    """origin -> key, leaving out the URLs."""
    return {o: e["key"] for o, e in entries.items()}


def use(base_url, key=None):
    """What the settings form sends: the URL, and maybe a key typed with it."""
    llm = {"base_url": base_url} | ({"api_key": key} if key is not None else {})
    return config.save({"llm": llm})


def key_now():
    return config.connection(config.load(), "llm")[1]


class TestOrigin:
    @pytest.mark.parametrize("url", [
        "https://openrouter.ai/api/v1", "https://openrouter.ai/v1/", "https://OpenRouter.ai:443/x",
        "https://openrouter.ai/api/v1/chat/completions", " https://openrouter.ai ",
    ])
    def test_one_service_whatever_the_path(self, url):
        assert config.origin(url) == "https://openrouter.ai"

    @pytest.mark.parametrize("a, b", [
        ("https://a.example.invalid", "https://b.example.invalid"),
        ("https://example.invalid", "https://api.example.invalid"),  # a subdomain is someone else
        ("http://example.invalid", "https://example.invalid"),
        ("http://localhost:11434", "http://localhost:1234"),  # Ollama and LM Studio
    ])
    def test_different_services(self, a, b):
        assert config.origin(a) != config.origin(b)

    def test_ports_and_ipv6(self):
        assert config.origin("http://localhost:80/v1") == "http://localhost"
        assert config.origin("http://LOCALHOST:11434/v1") == "http://localhost:11434"
        assert config.origin("http://[::1]:8080/v1") == "http://[::1]:8080"

    @pytest.mark.parametrize("url", [None, "", "localhost:11434/v1", "ftp://x.invalid", "https://", "http://x:port"])
    def test_not_a_service(self, url):
        assert config.origin(url) == ""


class TestSwitching:
    def test_each_service_keeps_its_own_key(self):
        use(GATEWAY, "sk-gateway")
        use(OTHER, "sk-other")
        assert key_now() == "sk-other"
        use(GATEWAY)
        assert key_now() == "sk-gateway"

    def test_a_new_service_starts_with_no_key(self):
        use(GATEWAY, "sk-gateway")
        cfg = use(OTHER)
        assert key_now() == "" and config.public(cfg)["llm"]["api_key"] == ""

    def test_the_masked_key_sent_back_with_a_new_url_isnt_moved_there(self):
        # The form still shows the old service's masked key as the URL changes.
        masked = config.public(use(GATEWAY, "sk-gateway"))["llm"]["api_key"]
        use(OTHER, masked)
        assert key_now() == "" and keys(stored()["keys"]) == {config.origin(GATEWAY): "sk-gateway"}

    def test_a_key_typed_with_a_new_url_is_filed_under_it(self):
        use(GATEWAY, "sk-gateway")
        use(OTHER, "sk-other")
        assert keys(config.load()["keys"]) == {config.origin(GATEWAY): "sk-gateway", config.origin(OTHER): "sk-other"}

    def test_paths_on_one_host_share_a_key(self):
        use("https://openrouter.ai/api/v1", "sk-or")
        use("https://openrouter.ai/v1")
        assert key_now() == "sk-or"

    def test_a_new_key_replaces_the_old_one_for_that_service(self):
        use(GATEWAY, "sk-1")
        use(GATEWAY, " sk-2 ")
        assert keys(stored()["keys"]) == {config.origin(GATEWAY): "sk-2"}

    @pytest.mark.parametrize("unchanged", ["", "masked"])
    def test_blank_or_masked_means_unchanged(self, unchanged):
        cfg = use(GATEWAY, "sk-gateway")
        use(GATEWAY, config.public(cfg)["llm"]["api_key"] if unchanged else "")
        assert key_now() == "sk-gateway"

    def test_spaces_and_line_breaks_pasted_with_a_key_are_dropped(self):
        use(GATEWAY, " sk-gate\nway\t")
        assert key_now() == "sk-gateway"

    @pytest.mark.parametrize("bad", ["sk-\x00x", "sk-ключ", "sk-\x7f"])
    def test_a_key_no_header_can_carry_is_refused(self, bad):
        use(GATEWAY, "sk-gateway")
        with pytest.raises(ValueError):
            use(GATEWAY, bad)
        assert key_now() == "sk-gateway"

    def test_a_bad_key_in_a_hand_edited_file_isnt_sent(self):
        with open(config.CONFIG_PATH, "w") as f:
            json.dump({"keys": {config.origin(GATEWAY): {"key": "sk-\x00", "base_url": GATEWAY}}, "llm": {"base_url": GATEWAY}}, f)
        assert key_now() == ""

    def test_keys_cant_be_written_directly(self):
        config.save({"keys": {config.origin(OTHER): "sk-planted"}})
        assert config.load()["keys"] == {}

    def test_a_key_for_no_valid_url_is_dropped(self):
        use("not a url", "sk-x")
        assert config.load()["keys"] == {}


class TestSwitchingBack:
    """The settings list each service with the URL last used there, to switch back to."""

    def listed(self):
        return {k["origin"]: k["base_url"] for k in config.public(config.load())["keys"]}

    def test_a_key_remembers_the_url_as_typed(self):
        # A custom gateway may need its exact path and query: nothing is cut off.
        typed = GATEWAY + "/chat/completions?api-version=2024-06-01"
        use(typed, "sk-gateway")
        use(OTHER, "sk-other")
        assert self.listed()[config.origin(GATEWAY)] == typed
        use(self.listed()[config.origin(GATEWAY)])  # what picking it in the list sends
        assert config.connection(config.load(), "llm") == (typed, "sk-gateway")

    def test_the_latest_path_on_a_service_is_the_one_kept(self):
        use("https://openrouter.ai/v1", "sk-or")
        use("https://openrouter.ai/api/v1")
        use(OTHER)
        assert self.listed()["https://openrouter.ai"] == "https://openrouter.ai/api/v1"

    def test_a_service_without_a_key_isnt_listed(self):
        use(GATEWAY, "sk-gateway")
        use("http://localhost:11434/v1")
        assert list(self.listed()) == [config.origin(GATEWAY)]

    def test_a_key_typed_for_speech_is_listed_with_its_url(self):
        config.save({"tts": {"base_url": OTHER + "/audio/speech", "api_key": "sk-tts"}})
        assert self.listed() == {config.origin(OTHER): OTHER + "/audio/speech"}

    def test_speech_urls_dont_move_it(self):
        use(GATEWAY, "sk-gateway")
        config.save({"tts": {"base_url": "https://gateway.example.invalid/speech/v1"}})
        assert self.listed()[config.origin(GATEWAY)] == GATEWAY


class TestSpeech:
    def test_same_service_as_the_llm_shares_its_key(self):
        use(GATEWAY, "sk-gateway")
        config.save({"tts": {"base_url": "https://gateway.example.invalid/v1/audio/speech"}})
        cfg = config.load()
        assert config.connection(cfg, "stt") == (GATEWAY, "sk-gateway")  # blank: the LLM's
        assert config.connection(cfg, "tts") == (GATEWAY + "/audio/speech", "sk-gateway")

    def test_another_service_doesnt_get_the_llm_key(self):
        use(GATEWAY, "sk-gateway")
        config.save({"tts": {"base_url": OTHER}})
        assert config.connection(config.load(), "tts") == (OTHER, "")

    def test_a_key_typed_for_speech_goes_to_its_own_service(self):
        use(GATEWAY, "sk-gateway")
        config.save({"tts": {"base_url": OTHER, "api_key": "sk-tts"}})
        cfg = config.load()
        assert config.connection(cfg, "tts") == (OTHER, "sk-tts")
        assert config.connection(cfg, "llm") == (GATEWAY, "sk-gateway")


class TestClear:
    def test_forgets_only_that_service(self):
        use(GATEWAY, "sk-gateway")
        use(OTHER, "sk-other")
        config.clear_key("https://other.example.invalid")  # as the saved-keys list sends it
        assert keys(stored()["keys"]) == {config.origin(GATEWAY): "sk-gateway"}

    @pytest.mark.parametrize("url", ["https://nothing.example.invalid", None])
    def test_nothing_to_clear(self, url):
        config.clear_key(url)
        use(GATEWAY, "sk-gateway")
        before = stored()
        config.clear_key(url)
        assert stored() == before


class TestBrowser:
    def test_never_sees_a_key_in_full(self):
        use(GATEWAY, "sk-gateway-1234")
        use(OTHER, "sk-other-5678")
        out = config.public(config.load())
        assert "sk-" not in json.dumps(out)
        assert out["keys"] == [
            {"origin": "https://gateway.example.invalid", "base_url": GATEWAY, "hint": config.MASK + "1234", "env": False},
            {"origin": "https://other.example.invalid", "base_url": OTHER, "hint": config.MASK + "5678", "env": False},
        ]
        assert out["llm"]["api_key"] == config.MASK + "5678"  # the one in use


class TestEnvironment:
    def test_the_key_belongs_to_the_environments_url_only(self, monkeypatch):
        monkeypatch.setenv("OPENSPEAK_BASE_URL", GATEWAY)
        monkeypatch.setenv("OPENSPEAK_API_KEY", "sk-env-not-real")
        assert key_now() == "sk-env-not-real"
        cfg = config.load()
        cfg["tts"]["base_url"] = OTHER
        assert config.connection(cfg, "tts") == (OTHER, "")
        assert config.public(cfg)["keys"] == [
            {"origin": config.origin(GATEWAY), "base_url": GATEWAY, "hint": config.MASK + "real", "env": True}]
        assert config.env_warnings() == []

    def test_is_never_written_to_the_file(self, monkeypatch):
        monkeypatch.setenv("OPENSPEAK_BASE_URL", GATEWAY)
        monkeypatch.setenv("OPENSPEAK_API_KEY", "sk-env-not-real")
        config.save({"llm": {"chat_model": "m"}})
        config.clear_key(GATEWAY)
        assert "sk-env-not-real" not in open(config.CONFIG_PATH).read()

    def test_a_key_without_its_url_is_ignored(self, monkeypatch):
        monkeypatch.setenv("OPENSPEAK_API_KEY", "sk-env-not-real")
        use(GATEWAY)
        assert key_now() == "" and not config.load()["keys"]
        assert "OPENSPEAK_BASE_URL" in config.env_warnings()[0]

    def test_a_key_that_cant_be_sent_is_ignored(self, monkeypatch):
        monkeypatch.setenv("OPENSPEAK_BASE_URL", GATEWAY)
        monkeypatch.setenv("OPENSPEAK_API_KEY", "sk-ключ")
        assert key_now() == "" and "characters" in config.env_warnings()[0]

    def test_no_key_no_warning(self):
        assert config.env_warnings() == []


class TestOldFiles:
    """Before keys were filed by service, each section held one."""

    def write(self, data):
        with open(config.CONFIG_PATH, "w") as f:
            json.dump(data, f)

    def test_each_key_goes_to_the_service_it_was_used_with(self):
        self.write({"llm": {"base_url": GATEWAY + "/", "api_key": "sk-llm"},
                    "stt": {"api_key": "sk-stt"},  # used the LLM's URL: the LLM's key wins
                    "tts": {"base_url": OTHER, "api_key": "sk-tts"}})
        cfg = config.load()
        assert cfg["keys"] == {config.origin(GATEWAY): {"key": "sk-llm", "base_url": GATEWAY + "/"},
                               config.origin(OTHER): {"key": "sk-tts", "base_url": OTHER}}
        assert all("api_key" not in cfg[s] for s in config.CONNECTIONS)

    def test_no_url_means_the_default_one(self):
        self.write({"llm": {"api_key": "sk-old"}})
        assert keys(config.load()["keys"]) == {config.origin(config.DEFAULTS["llm"]["base_url"]): "sk-old"}

    def test_saving_rewrites_it_in_the_new_shape(self):
        self.write({"llm": {"base_url": GATEWAY, "api_key": "sk-llm"}, "stt": {"api_key": ""}})
        config.save({"level": "advanced"})
        data = stored()
        assert keys(data["keys"]) == {config.origin(GATEWAY): "sk-llm"}
        assert "api_key" not in data["llm"] and "api_key" not in data["stt"]
        config.save({"level": "beginner"})  # and once moved, stays put
        assert stored()["keys"] == data["keys"]

    def test_keys_filed_without_their_url(self):
        # The shape for a short while: origin -> key. The service's root stands in.
        self.write({"keys": {"https://gateway.example.invalid": "sk-1", "https://x.invalid": "", "https://y.invalid": 5,
                             "https://z.invalid": {"key": "sk-2"}}})
        assert config.load()["keys"] == {
            "https://gateway.example.invalid": {"key": "sk-1", "base_url": "https://gateway.example.invalid"},
            "https://z.invalid": {"key": "sk-2", "base_url": "https://z.invalid"},
        }

    def test_keys_filed_without_their_url_get_it_back_from_where_it_was_used(self):
        # Switching back to a bare root failed the connection test: the path was lost.
        self.write({"keys": {"https://gateway.example.invalid": "sk-1", "https://openrouter.ai": "sk-2"},
                    "llm": {"base_url": GATEWAY + "/chat/completions"}})
        assert {o: e["base_url"] for o, e in config.load()["keys"].items()} == {
            "https://gateway.example.invalid": GATEWAY + "/chat/completions", "https://openrouter.ai": "https://openrouter.ai/api/v1"}

    def test_a_root_without_its_path_is_mended_by_using_the_full_url_once(self):
        self.write({"keys": {"https://gateway.example.invalid": {"key": "sk-1", "base_url": "https://gateway.example.invalid"}}})
        use(GATEWAY + "/chat/completions")
        use(OTHER)
        assert config.public(config.load())["keys"][0]["base_url"] == GATEWAY + "/chat/completions"

    def test_not_an_object_falls_back_to_defaults(self):
        self.write([1, 2])
        assert config.load()["keys"] == {}
