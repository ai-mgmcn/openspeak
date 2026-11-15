"""
One client for every provider. Ollama, LM Studio, OpenAI, DeepSeek, OpenRouter and
most company gateways all speak the OpenAI chat-completions protocol, so there is
exactly one code path to keep working.
"""

import asyncio
import ipaddress
import json
import re

from urllib.parse import urlparse

import httpx

from .. import config


class LLMError(Exception):
    """A provider error with the provider's own message, fit to show a user."""


def _headers(key):
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _explain(resp):
    try:
        body = resp.json()
        err = body.get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        msg = msg or body.get("message") or body.get("detail")
    except Exception:
        msg = resp.text[:300]
    return f"HTTP {resp.status_code}: {msg or resp.reason_phrase}"


def _offending_param(resp):
    try:
        err = resp.json().get("error") or {}
        param = err.get("param")
    except Exception:
        return None
    return param if isinstance(param, str) and param else None


# Parameters a given server/model rejected once, so later calls don't pay for the
# same 400 again.
_rejected = {}


def is_local(url):
    """
    Whether the model server is on this computer or this network, not out on the internet:
    a localhost, a private or Tailscale-style address (192.168.x.x, 10.x.x.x, 100.x.x.x),
    a bare machine name or a .local one. Those are your own GPU, which is slow and shared,
    so they get the "local" treatment: thinking off, longer timeouts, one request at a time.
    """
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return False
    if host in ("localhost", config.LOCAL_HOST) or "." not in host or host.endswith((".local", ".lan", ".home.arpa")):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


async def post_endpoint(http, base_url, path, **kw):
    """POST to `path` of the service at base_url. A request that can't be sent says so, without quoting the key."""
    try:
        return await http.post(config.endpoint(base_url, path), **kw)
    except httpx.LocalProtocolError as e:
        raise unsendable(base_url) from e


def unsendable(base_url):
    # Not the error's own text: it quotes the header that failed, the key with it.
    return LLMError(f"Couldn't send a request to {base_url}: check its URL and API key for stray characters.")


_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def clean_text(text):
    """Local reasoning models (Qwen3, DeepSeek-R1) put their thinking inline."""
    return _THINK.sub("", text or "").strip()


async def chat(base_url, key, model, messages, want_json=False, timeout=60):
    """
    Return the assistant text.

    Models disagree about optional knobs: reasoning models reject temperature, some
    local servers reject json_object mode. Instead of hardcoding quirks per model,
    drop whichever parameter a 400 names and try again.
    """
    if not base_url:
        raise LLMError("No AI service configured — open Settings.")
    if not model:
        raise LLMError("No model selected — open Settings.")
    payload = {"model": model, "messages": list(messages), "stream": False}
    if want_json:
        payload["response_format"] = {"type": "json_object"}
    if is_local(base_url):
        # Local reasoning models (Qwen3 and friends) otherwise think for hundreds
        # of tokens before every reply: 48s instead of 1s for "Hi there!" on a 27B.
        # Servers that don't know the knob reject it once and it's remembered.
        payload["reasoning_effort"] = "none"
    seen = _rejected.setdefault((base_url, model), set())
    for p in seen:
        payload.pop(p, None)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(4):
            try:
                resp = await post_endpoint(client, base_url, "/chat/completions", headers=_headers(key), json=payload)
            except httpx.ConnectError as e:
                raise LLMError(f"Can't reach {base_url} — is the server running?") from e
            if resp.status_code == 400:
                bad = _offending_param(resp)
                if bad and bad in payload and bad not in ("model", "messages"):
                    payload.pop(bad)
                    seen.add(bad)
                    continue
                # Some servers reject a knob without naming it in "param".
                named = next((p for p in ("response_format", "reasoning_effort") if p in payload and p in resp.text), None)
                if named:
                    payload.pop(named)
                    seen.add(named)
                    continue
            if resp.status_code >= 400:
                raise LLMError(_explain(resp))
            data = resp.json()
            try:
                return clean_text(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as e:
                raise LLMError(f"Unexpected response: {str(data)[:200]}") from e
    raise LLMError(_explain(resp))


def describe_error(e):
    """What to tell the user about a failed call. Never empty: a timeout has no message of its own."""
    if isinstance(e, httpx.TimeoutException):
        return "The service didn't answer in time. Is it overloaded or the URL wrong? Try again, or pick a faster model."
    if isinstance(e, json.JSONDecodeError):
        return "The service answered with something that isn't JSON. Is the URL an API address (usually ending in /v1)?"
    if isinstance(e, httpx.TransportError):
        return f"Network problem talking to the service ({type(e).__name__}). Is it reachable?"
    return str(e).strip() or f"{type(e).__name__} (no further details)"


def text(value):
    """A string field of a model's JSON, which may hold anything: stripped, or ""."""
    return value.strip() if isinstance(value, str) else ""


def parse_json(text):
    """Salvage a JSON object from fenced or chatty model output. ValueError if there isn't one."""
    text = clean_text(text)
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")
    return data


async def list_models(base_url, key, timeout=5):
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(config.endpoint(base_url, "/models"), headers=_headers(key))
        except httpx.HTTPError as e:
            raise LLMError(f"Can't reach {base_url}") from e
    if resp.status_code >= 400:
        raise LLMError(_explain(resp))
    data = resp.json().get("data") or []
    ids = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
    # Embedding models can't chat; hide the obvious ones.
    return sorted(i for i in ids if "embed" not in i.lower())


async def detect_local():
    """Which local model servers are up right now, and what they have loaded."""
    async def probe(p):
        try:
            return {"provider": p["id"], "base_url": p["base_url"], "models": await list_models(p["base_url"], "", timeout=1.5)}
        except Exception:
            return None

    # All at once: a closed port refuses at once, but a filtered one takes the whole timeout.
    found = await asyncio.gather(*(probe(p) for p in config.PROVIDERS if p["local"]))
    return [f for f in found if f]
