import json
import os
import stat

import pytest

from openspeak import config


def stored():
    with open(config.CONFIG_PATH) as f:
        return json.load(f)


def test_saved_with_owner_only_permissions():
    config.save({"llm": {"chat_model": "m"}})
    assert stat.S_IMODE(os.stat(config.CONFIG_PATH).st_mode) == 0o600
    assert stored()["llm"]["chat_model"] == "m"


def test_environment_values_are_used_but_not_saved(monkeypatch):
    monkeypatch.setenv("OPENSPEAK_BASE_URL", "https://gateway.example.invalid/v1")
    monkeypatch.setenv("OPENSPEAK_API_KEY", "sk-test-not-real")
    cfg = config.load()
    assert cfg["llm"]["base_url"] == "https://gateway.example.invalid/v1"
    # The UI sends back what it was shown; that must not write the env values to disk.
    config.save({"llm": {"base_url": cfg["llm"]["base_url"], "chat_model": "m"}})
    text = open(config.CONFIG_PATH).read()
    assert "gateway.example.invalid" not in text and "sk-test-not-real" not in text


class TestLimits:
    @pytest.mark.parametrize("path, bad", [
        ("coach.max_concurrent", 0), ("coach.timeout", 0), ("coach.finish_timeout", -5), ("stt.silence_ms", 10), ("tts.rate", 0),
        ("coach.timeout", True), ("coach.timeout", "60"), ("coach.max_concurrent", float("inf")),
    ])
    def test_a_setting_that_would_hang_or_fail_every_call_falls_back_to_its_default(self, path, bad):
        # max_concurrent 0 made grading wait forever; a 0 s timeout failed every call.
        section, name = path.split(".")
        config.save({section: {name: bad}})
        assert config.load()[section][name] == config.DEFAULTS[section][name]

    def test_a_good_value_is_kept(self):
        config.save({"coach": {"max_concurrent": 5}, "tts": {"rate": 1.2}})
        assert config.load()["coach"]["max_concurrent"] == 5 and config.load()["tts"]["rate"] == 1.2

    def test_a_blank_base_url_in_the_environment_is_no_url(self, monkeypatch):
        monkeypatch.setenv("OPENSPEAK_BASE_URL", "   ")
        config.save({"llm": {"base_url": "", "chat_model": "m"}})  # used to raise KeyError
        assert config.load()["llm"]["chat_model"] == "m"


def test_pasted_endpoints_are_trimmed_to_the_base():
    for url in ("https://x.invalid/v1/", "https://x.invalid/v1/chat/completions", "https://x.invalid/v1/models",
                " https://x.invalid/v1/audio/speech "):
        assert config.normalize_base_url(url) == "https://x.invalid/v1"
    assert config.normalize_base_url(None) == ""


def test_a_corrupt_file_falls_back_to_defaults():
    with open(config.CONFIG_PATH, "w") as f:
        f.write("{not json")
    assert config.load()["llm"] == config.DEFAULTS["llm"] | {"base_url": config.normalize_base_url(config.DEFAULTS["llm"]["base_url"])}
    config.save({"llm": {"chat_model": "m"}})  # and saving repairs it
    assert stored()["llm"]["chat_model"] == "m"


class TestFormerName:
    """OpenSpeak was SpeakLoop: its data moves over, and its settings are pointed out."""

    @pytest.fixture
    def homes(self, tmp_path, monkeypatch):
        old, new = tmp_path / "old", tmp_path / "new"
        monkeypatch.setattr(config, "OLD_HOME", str(old))
        monkeypatch.setattr(config, "HOME", str(new))
        monkeypatch.setattr(config, "DEFAULT_HOME", str(new))
        (old / "sessions").mkdir(parents=True)
        (old / "sessions" / "session_1.jsonl").write_text("{}")
        return old, new

    def test_data_moves_to_the_new_place(self, homes):
        old, new = homes
        assert str(new) in config.move_old_home()
        assert (new / "sessions" / "session_1.jsonl").exists() and not old.exists()
        assert config.move_old_home() is None  # once

    def test_existing_new_data_is_left_alone(self, homes):
        old, new = homes
        new.mkdir()
        assert config.move_old_home() is None and old.exists()

    def test_a_chosen_data_dir_is_left_alone(self, homes, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "HOME", str(tmp_path / "chosen"))
        assert config.move_old_home() is None and homes[0].exists()

    def test_nothing_to_move(self, homes):
        import shutil

        shutil.rmtree(homes[0])
        assert config.move_old_home() is None

    def test_old_variables_are_pointed_out(self, monkeypatch):
        monkeypatch.setenv("SPEAKLOOP_API_KEY", "sk-env-not-real")
        monkeypatch.setenv("SPEAKLOOP_BASE_URL", "https://gateway.example.invalid/v1")
        assert config.env_warnings() == [
            "SPEAKLOOP_BASE_URL is no longer read: it's OPENSPEAK_BASE_URL now.",
            "SPEAKLOOP_API_KEY is no longer read: it's OPENSPEAK_API_KEY now.",
        ]
        assert config.connection(config.load(), "llm")[1] == ""  # and not used


class TestChoices:
    """A value the app doesn't offer falls back to the default instead of reaching a prompt."""

    def test_an_unknown_value_is_replaced(self):
        with open(config.CONFIG_PATH, "w") as f:
            json.dump({"reply_mode": "free", "coach": {"when": "sometimes"}, "level": "advanced"}, f)
        cfg = config.load()
        assert cfg["reply_mode"] == "rescue" and cfg["coach"]["when"] == "auto"
        assert cfg["level"] == "advanced"  # a valid one is kept

    def test_and_is_not_saved(self):
        config.save({"reply_mode": "free", "tts": {"engine": "loud"}})
        assert stored()["reply_mode"] == "rescue" and stored()["tts"]["engine"] == "browser"

    def test_every_default_is_allowed(self):
        cfg = config.load()
        for path, allowed in config.CHOICES.items():
            value = cfg
            for part in path.split("."):
                value = value[part]
            assert value in allowed, path


class TestTypes:
    """A setting of the wrong type, from a page bug or a hand edit, reads as its default."""

    def test_wrong_types_are_not_saved(self):
        config.save({"coach": {"timeout": None, "retries": "a", "enabled": "yes", "max_concurrent": -1},
                     "languages": "en", "stt": {"silence_ms": 1200.0}, "tts": {"rate": 1}, "setup_done": 1})
        data = stored()
        assert data["coach"] | {"when": "auto"} == config.DEFAULTS["coach"]
        assert data["languages"] == config.DEFAULTS["languages"] and data["setup_done"] is False
        assert data["stt"]["silence_ms"] == 1200 and data["tts"]["rate"] == 1.0

    def test_a_section_that_isnt_an_object_costs_only_that_section(self):
        with open(config.CONFIG_PATH, "w") as f:
            json.dump({"llm": "x", "stt": [1], "level": "advanced", "coach": {"timeout": "Infinity"},
                       "keys": {"https://gateway.example.invalid": {"key": "sk-1", "base_url": "https://gateway.example.invalid/v1"},
                                "https://bad.example.invalid": {"key": 5}}}, f)
        cfg = config.load()
        assert cfg["llm"] == config.DEFAULTS["llm"] and cfg["stt"] == config.DEFAULTS["stt"]
        assert cfg["level"] == "advanced" and cfg["coach"]["timeout"] == 60
        assert list(cfg["keys"]) == ["https://gateway.example.invalid"]
        config.save({"level": "beginner"})
        assert list(stored()["keys"]) == ["https://gateway.example.invalid"]  # not wiped by the save

    def test_a_url_that_isnt_text(self):
        config.save({"llm": {"base_url": 5}})
        assert config.load()["llm"]["base_url"] == config.DEFAULTS["llm"]["base_url"]


class TestEndpoint:
    """URLs are kept as typed; each request finds its endpoint from one."""

    @pytest.mark.parametrize("typed", ["https://x.invalid/v1", "https://x.invalid/v1/", " https://x.invalid/v1 "])
    def test_a_base_gets_the_path_added(self, typed):
        assert config.endpoint(typed, "/chat/completions") == "https://x.invalid/v1/chat/completions"

    def test_the_endpoint_itself_is_used_as_typed(self):
        typed = "https://gw.invalid/openai/deployments/m/chat/completions?api-version=2024-06-01"
        assert config.endpoint(typed, "/chat/completions") == typed

    def test_another_endpoint_stands_in_for_its_base(self):
        typed = "https://gw.invalid/openai/v1/chat/completions?api-version=1"
        assert config.endpoint(typed, "/models") == "https://gw.invalid/openai/v1/models?api-version=1"
        assert config.endpoint("https://x.invalid/v1/audio/speech", "/audio/transcriptions") == "https://x.invalid/v1/audio/transcriptions"

    def test_saved_as_typed(self):
        typed = "https://gw.invalid/custom/path/chat/completions?api-version=1"
        config.save({"llm": {"base_url": "  " + typed + " "}})
        assert config.load()["llm"]["base_url"] == typed


def test_local_servers_are_found_at_the_configured_host(monkeypatch):
    import importlib

    monkeypatch.setenv("OPENSPEAK_LOCAL_HOST", "host.docker.internal")
    try:
        importlib.reload(config)
        urls = {p["id"]: p["base_url"] for p in config.PROVIDERS}
        assert urls["lmstudio"] == "http://host.docker.internal:1234/v1"
        assert urls["ollama"] == "http://host.docker.internal:11434/v1"
        assert urls["openai"] == "https://api.openai.com/v1"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
