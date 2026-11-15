"""
Settings live in one JSON file under the data directory, written by the settings
drawer. No .env to edit. API keys are stored there with owner-only permissions and
never sent back to the browser in full.

Each key belongs to the service it was entered for (scheme, host and port: an
origin) and is only ever sent there. Switching to another service uses that
service's key, or none: a key never follows a changed URL somewhere else. The
full URL last used with each is kept too, so the settings can switch back to it.

Environment variables override the file, which is handy for servers and CI:
    OPENSPEAK_HOME       data directory (default ~/.openspeak)
    OPENSPEAK_BASE_URL   LLM endpoint
    OPENSPEAK_API_KEY    key for OPENSPEAK_BASE_URL (ignored without it)
"""

import copy
import json
import math
import os
import threading
from urllib.parse import urlsplit, urlunsplit

from . import fsutil

DEFAULT_HOME = os.path.expanduser("~/.openspeak")
HOME = os.path.expanduser(os.getenv("OPENSPEAK_HOME", DEFAULT_HOME))
SESSIONS_DIR = os.path.join(HOME, "sessions")
CONFIG_PATH = os.path.join(HOME, "config.json")

# OpenSpeak was called SpeakLoop before.
OLD_HOME = os.path.expanduser("~/.speakloop")
OLD_ENV_PREFIX = "SPEAKLOOP_"

# Where model servers on this computer are. In a container that's the host, not "localhost" (see Dockerfile).
LOCAL_HOST = os.getenv("OPENSPEAK_LOCAL_HOST") or "localhost"

# Presets fill in the endpoint; the user only picks a model (and pastes a key for
# cloud ones). "local" marks providers that keep audio and text on this machine.
PROVIDERS = [
    {"id": "ollama", "name": "Ollama", "base_url": f"http://{LOCAL_HOST}:11434/v1", "local": True, "needs_key": False},
    {"id": "lmstudio", "name": "LM Studio", "base_url": f"http://{LOCAL_HOST}:1234/v1", "local": True, "needs_key": False},
    {"id": "llamacpp", "name": "llama.cpp / LocalAI", "base_url": f"http://{LOCAL_HOST}:8080/v1", "local": True, "needs_key": False},
    {"id": "vllm", "name": "vLLM", "base_url": f"http://{LOCAL_HOST}:8000/v1", "local": True, "needs_key": False},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "local": False, "needs_key": True},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "local": False, "needs_key": True},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "local": False, "needs_key": True},
    {"id": "custom", "name": "Custom (OpenAI-compatible)", "base_url": "", "local": False, "needs_key": True},
]

DEFAULTS = {
    "setup_done": False,
    "languages": {
        "target": "en",  # what you practise
        "native": "zh-CN",  # what hints and translations are written in
        "report": "zh-CN",  # what feedback and the report are written in
    },
    "ui_language": "auto",
    "reply_mode": "rescue",  # immersive | translate | rescue
    "level": "intermediate",  # beginner | intermediate | advanced
    "llm": {
        "provider": "ollama",
        "base_url": f"http://{LOCAL_HOST}:11434/v1",
        "chat_model": "",
        # Blank = same as chat. A stronger grader is worth it; see README.
        "grader_model": "",
    },
    "stt": {
        "engine": "local",  # local | api
        "local_model": "base",  # tiny | base | small | medium | large-v3
        # api: a blank base_url reuses the LLM's (and so its key)
        "base_url": "",
        "model": "whisper-1",
        "silence_ms": 1600,  # pause that ends a turn; learners pause mid-sentence
    },
    "tts": {
        "engine": "browser",  # browser | api | off
        "rate": 0.95,
        "browser_voice": "",
        "base_url": "",
        "model": "tts-1",
        "voice": "alloy",
    },
    "coach": {
        "enabled": True,
        # When to grade: "live" during the conversation, "after" once it ends, or
        # "auto": after for a local model (it shares one GPU with the partner, and
        # grading alongside makes every reply slow), live for a cloud service.
        "when": "auto",
        "max_concurrent": 3,
        "retries": 2,
        "timeout": 60,
        "finish_timeout": 180,
    },
    "keys": {},  # origin -> {"key": API key, "base_url": the full URL last used there}
}

# Settings with a fixed set of values. Anything else, say from a page bug or a hand
# edit, falls back to the default rather than reaching a prompt.
CHOICES = {
    "reply_mode": ("immersive", "translate", "rescue"),
    "level": ("beginner", "intermediate", "advanced"),
    "stt.engine": ("local", "api"),
    "stt.local_model": ("tiny", "base", "small", "medium", "large-v3"),
    "tts.engine": ("browser", "api", "off"),
    "coach.when": ("auto", "live", "after"),
}

# Numbers that must be at least this much: 0 concurrent grading calls waits forever, a 0 s timeout fails every call.
MINIMUMS = {"coach.max_concurrent": 1, "coach.timeout": 1, "coach.finish_timeout": 1, "stt.silence_ms": 200, "tts.rate": 0.1}

# Sections with an endpoint. The settings form sends a key as <section>.api_key;
# it's filed under that section's origin.
CONNECTIONS = ("llm", "stt", "tts")
MASK = "••••"

_lock = threading.Lock()


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# The endpoints OpenSpeak calls, by the path each adds to a service's base URL.
ENDPOINTS = ("/chat/completions", "/completions", "/audio/transcriptions", "/audio/speech", "/models")


def url(value):
    """A URL as typed, without the spaces pasted around it. Kept as is: a custom service may need its exact path."""
    return value.strip() if isinstance(value, str) else ""


def normalize_base_url(value):
    """
    The base of a URL as people paste it: '.../v1', '.../v1/', or a full
    '.../v1/chat/completions' copied from provider docs. For comparing URLs; requests go to endpoint().
    """
    value = url(value).rstrip("/")
    for suffix in ENDPOINTS:
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    return value


def endpoint(value, path):
    """
    Where a request for `path` ("/chat/completions", "/models", …) goes on the
    service at this URL. A URL naming that endpoint is used as typed, query and all
    (a gateway's "?api-version=…"); one naming another endpoint stands in for its
    base; any other gets the path added.
    """
    parts = urlsplit(url(value))
    base = parts.path.rstrip("/")
    for suffix in ENDPOINTS:
        if base.endswith(suffix):
            if suffix == path:
                return urlunsplit(parts)
            base = base[: -len(suffix)]
            break
    return urlunsplit(parts._replace(path=base + path))


def origin(url):
    """
    Which service a URL belongs to, as the browser judges it: scheme, host and
    port. Paths don't matter (/v1 and /api/v1 on one host share a key); anything
    else does. "" for something that isn't an http(s) URL.
    """
    try:
        parts = urlsplit(normalize_base_url(url))
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    if port and port != {"http": 80, "https": 443}[parts.scheme]:
        host += f":{port}"
    return f"{parts.scheme}://{host}"


def clean_key(key):
    """
    A key as pasted, without the spaces and line breaks that come along. One with
    anything else an HTTP header can't carry is refused: sending it would fail, and
    the failure would quote it.
    """
    key = "".join((key or "").split())
    if any(not 33 <= ord(c) <= 126 for c in key):
        raise ValueError("That API key has characters a key can't contain. Paste it again.")
    return key


def sent_key(value):
    """A key typed into the form, cleaned. "" if there's none: absent, not text, or the mask the browser was shown."""
    return clean_key(value) if isinstance(value, str) and MASK not in value else ""


def _env_url():
    return url(os.getenv("OPENSPEAK_BASE_URL"))


def _env_key():
    """(origin, entry) from the environment, if both the key and its endpoint are set."""
    base = _env_url()
    try:
        key = clean_key(os.getenv("OPENSPEAK_API_KEY"))
    except ValueError:
        return None
    o = origin(base)
    return (o, {"key": key, "base_url": base}) if o and key else None


def env_warnings():
    """Settings in the environment that won't be used, and why."""
    out = [f"{OLD_ENV_PREFIX}{name} is no longer read: it's OPENSPEAK_{name} now."
           for name in ("HOME", "BASE_URL", "API_KEY") if os.getenv(OLD_ENV_PREFIX + name)]
    if os.getenv("OPENSPEAK_API_KEY") and not _env_key():
        try:
            clean_key(os.getenv("OPENSPEAK_API_KEY"))
            out.append("OPENSPEAK_API_KEY is ignored: set OPENSPEAK_BASE_URL to the endpoint it's for.")
        except ValueError:
            out.append("OPENSPEAK_API_KEY is ignored: it has characters a key can't contain.")
    return out


def move_old_home():
    """Data kept under the old name moves to the new place, once. Says so if it did."""
    if HOME != DEFAULT_HOME or os.path.exists(HOME) or not os.path.isdir(OLD_HOME):
        return None
    os.rename(OLD_HOME, HOME)
    return f"Moved your data from {OLD_HOME} to {HOME}."


def load():
    with _lock:
        cfg = _checked(_merge(DEFAULTS, _stored()))
    cfg["llm"]["base_url"] = _env_url() or url(cfg["llm"]["base_url"])
    if env := _env_key():
        cfg["keys"][env[0]] = env[1]
    return cfg


def _typed(cfg, defaults):
    """Each setting of the type its default has, or the default: a page bug or a hand edit can't break a prompt or a timer."""
    for name, default in defaults.items():
        value = cfg.get(name)
        if isinstance(default, dict):
            if not isinstance(value, dict):
                cfg[name] = copy.deepcopy(default)
            elif name != "keys":  # its entries are checked as they're read
                _typed(value, default)
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                cfg[name] = default
        elif isinstance(default, (int, float)):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < math.inf
            cfg[name] = type(default)(value) if ok else default
        elif not isinstance(value, type(default)):
            cfg[name] = default
    return cfg


def _checked(cfg):
    _typed(cfg, DEFAULTS)
    for path, allowed in CHOICES.items():
        *parents, name = path.split(".")
        section, default = cfg, DEFAULTS
        for p in parents:
            section, default = section[p], default[p]
        if section.get(name) not in allowed:
            section[name] = default[name]
    for path, least in MINIMUMS.items():
        section, name = path.split(".")
        if cfg[section][name] < least:
            cfg[section][name] = DEFAULTS[section][name]
    return cfg


def _stored():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return _migrated(json.load(f))
    except (OSError, ValueError):
        return {}


def _migrated(data):
    """
    Older files, read in today's shape. Keys kept one per section go to the
    service each was used with then, the LLM's first, as speech borrowed it.
    Keys filed by service without their full URL get one from a section or a
    preset on that service, if any (the service's root otherwise).
    """
    if not isinstance(data, dict):
        return {}
    for name, value in list(data.items()):
        if isinstance(DEFAULTS.get(name), dict) and not isinstance(value, dict):
            del data[name]  # the rest of the file still counts, keys most of all
    keys = {o: ({"key": v} if isinstance(v, str) else dict(v))
            for o, v in data.get("keys", {}).items() if isinstance(v, (str, dict))}
    llm_base = data.get("llm", {}).get("base_url") or DEFAULTS["llm"]["base_url"]
    used = []
    for section in CONNECTIONS:
        s = data.get(section, {})
        key = s.pop("api_key", None)
        base = url(s.get("base_url") or llm_base)
        used.append(base)
        if key and (o := origin(base)):
            keys.setdefault(o, {"key": key, "base_url": base})
    known = used + [p["base_url"] for p in PROVIDERS if p["base_url"]]
    keys = {o: e for o, e in keys.items() if isinstance(e.get("key"), str) and isinstance(e.get("base_url", ""), str)}
    for o, e in keys.items():
        if normalize_base_url(e.get("base_url")) in ("", o):
            e["base_url"] = next((u for u in known if origin(u) == o and u != o), o)
    data["keys"] = {o: e for o, e in keys.items() if e.get("key")}
    return data


def save(update):
    """
    Merge a partial update from the UI into the stored file. A key is filed under
    the origin of its section's endpoint as it stands after this update; a masked
    or empty one means "unchanged", so the browser never needs to hold the real one.
    """
    with _lock:
        current = _merge(DEFAULTS, _stored())
        update.pop("keys", None)  # only through a section's api_key, so it lands where it's meant for
        sent = {s: update[s].pop("api_key", None) for s in CONNECTIONS if isinstance(update.get(s), dict)}
        sent = {s: sent_key(k) for s, k in sent.items()}
        # Values that came from the environment are shown in the UI and sent back
        # unchanged; they must not end up in the file.
        env_url = _env_url()
        llm_update = update.get("llm") if isinstance(update.get("llm"), dict) else {}
        if env_url and normalize_base_url(llm_update.get("base_url")) == normalize_base_url(env_url):
            llm_update.pop("base_url", None)
        merged = _typed(_merge(current, update), DEFAULTS)
        for section in CONNECTIONS:
            merged[section]["base_url"] = url(merged[section].get("base_url"))
        for section, key in sent.items():
            base = _base(merged, section, env_url)
            if key and (o := origin(base)):
                merged["keys"][o] = {"key": key, "base_url": base}
        # Remember where on its service the LLM was pointed last, to switch back to.
        base = _base(merged, "llm", env_url)
        if entry := merged["keys"].get(origin(base)):
            entry["base_url"] = base
        _write(_checked(merged))
    return load()


def _write(data):
    """Write to a temp file and rename over: a crash leaves the old file or the new, never half."""
    os.makedirs(HOME, mode=0o700, exist_ok=True)
    # Per process, so two OpenSpeak processes saving at once don't write into each other's temp file.
    tmp = f"{CONFIG_PATH}.{os.getpid()}.tmp"
    # Owner-only from the moment it exists: it may hold API keys.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    fsutil.replace(tmp, CONFIG_PATH)


def clear_key(url):
    """Forget the key stored for this URL's service (the UI's 'clear' action)."""
    o = origin(url)
    with _lock:
        data = _stored()
        if o in data.get("keys", {}):
            del data["keys"][o]
            _write(data)


def _mask(key):
    return (MASK + key[-4:]) if key else ""


def public(cfg):
    """
    The config as the browser may see it: no key in full. Each section shows the
    masked key it would use, and "keys" lists the services one is stored for.
    """
    out = copy.deepcopy(cfg)
    env = _env_key()
    out["keys"] = [{"origin": o, "base_url": e["base_url"], "hint": _mask(e["key"]), "env": bool(env and env[0] == o)}
                   for o, e in sorted(cfg["keys"].items())]
    for section in CONNECTIONS:
        out[section]["api_key"] = _mask(connection(cfg, section)[1])
    return out


def _base(cfg, section, env_url=None):
    llm = url(env_url) or cfg["llm"]["base_url"]
    return llm if section == "llm" else url(cfg[section].get("base_url")) or llm


def key_for(cfg, url):
    """The key stored for this URL's service, or "". The only way to get one."""
    o = origin(url)
    try:
        return clean_key(cfg["keys"].get(o, {}).get("key")) if o else ""
    except ValueError:  # a hand-edited file
        return ""


def connection(cfg, section):
    """
    Endpoint + key for 'llm', 'stt' or 'tts'. Speech left blank uses the LLM's
    endpoint, and so its key; one of its own gets the key stored for it, if any.
    """
    base = _base(cfg, section)
    return base, key_for(cfg, base)
