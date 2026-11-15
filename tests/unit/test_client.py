import json

import httpx
import pytest

from openspeak.ai import client
from openspeak.ai.client import LLMError

from ..conftest import CLOUD, LOCAL

pytestmark = pytest.mark.anyio

MSGS = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def fresh_memory(monkeypatch):
    # What servers rejected is remembered per process; each test starts clean.
    monkeypatch.setattr(client, "_rejected", {})


def reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def bad_param(param, status=400):
    return httpx.Response(status, json={"error": {"message": f"unsupported: {param}", "param": param}})


def sent(request):
    return json.loads(request.content)


class TestDescribeError:
    @pytest.mark.parametrize("error, says", [
        (httpx.ReadTimeout(""), "didn't answer in time"),
        (httpx.ConnectTimeout("x"), "didn't answer in time"),
        (json.JSONDecodeError("Expecting value", "<html>", 0), "isn't JSON"),
        (httpx.RemoteProtocolError("closed"), "RemoteProtocolError"),
        (LLMError("model is down"), "model is down"),
        (RuntimeError(), "RuntimeError"),
    ])
    def test_always_something_to_act_on(self, error, says):
        assert says in client.describe_error(error)


class TestChat:
    async def test_returns_the_text_without_inline_thinking(self, http):
        http.on("POST", "/chat/completions", reply("<think>hmm</think>\n Hello!"))
        assert await client.chat(CLOUD, "sk-x", "m", MSGS) == "Hello!"
        req = http.requests[0]
        assert req.headers["authorization"] == "Bearer sk-x"
        body = sent(req)
        assert body["model"] == "m" and "response_format" not in body and "reasoning_effort" not in body

    async def test_a_custom_endpoint_is_called_as_typed(self, http):
        typed = "https://gw.example.invalid/openai/deployments/m/chat/completions?api-version=2024-06-01"
        http.on("POST", "/chat/completions", reply("ok"))
        await client.chat(typed, "", "m", MSGS)
        assert str(http.requests[0].url) == typed

    async def test_a_timeout_stays_a_timeout_for_the_retrying_grader(self, http):
        http.on("POST", "/chat/completions", httpx.ReadTimeout("slow"))
        with pytest.raises(httpx.TimeoutException):
            await client.chat(CLOUD, "", "m", MSGS)

    async def test_no_key_sends_no_authorization(self, http):
        http.on("POST", "/chat/completions", reply("ok"))
        await client.chat(CLOUD, "", "m", MSGS)
        assert "authorization" not in http.requests[0].headers

    async def test_json_mode_is_requested(self, http):
        http.on("POST", "/chat/completions", reply("{}"))
        await client.chat(CLOUD, "", "m", MSGS, want_json=True)
        assert sent(http.requests[0])["response_format"] == {"type": "json_object"}

    @pytest.mark.parametrize("base, model, msg", [("", "m", "No AI service"), (CLOUD, "", "No model")])
    async def test_needs_a_service_and_a_model(self, base, model, msg):
        with pytest.raises(LLMError, match=msg):
            await client.chat(base, "", model, MSGS)

    async def test_local_servers_are_told_not_to_think(self, http):
        http.on("POST", "/chat/completions", reply("ok"))
        await client.chat(LOCAL, "", "m", MSGS)
        assert sent(http.requests[0])["reasoning_effort"] == "none"

    async def test_a_server_elsewhere_on_your_network_is_told_not_to_think_either(self, http):
        # A 27B model thinking for a minute with no bytes sent is what made grading time out over the LAN.
        http.on("POST", "/chat/completions", reply("ok"))
        await client.chat("http://192.168.0.13:1234/v1", "", "m", MSGS)
        assert sent(http.requests[0])["reasoning_effort"] == "none"

    async def test_a_rejected_param_is_dropped_and_remembered(self, http):
        http.on("POST", "/chat/completions", bad_param("reasoning_effort"), reply("ok"))
        assert await client.chat(LOCAL, "", "m", MSGS) == "ok"
        assert "reasoning_effort" not in sent(http.requests[1])
        await client.chat(LOCAL, "", "m", MSGS)  # next call: no second 400
        assert len(http.requests) == 3 and "reasoning_effort" not in sent(http.requests[2])

    async def test_a_param_named_only_in_the_message_is_dropped(self, http):
        http.on("POST", "/chat/completions",
                httpx.Response(400, text="response_format is not supported"), reply("{}"))
        assert await client.chat(CLOUD, "", "m", MSGS, want_json=True) == "{}"
        assert "response_format" not in sent(http.requests[1])

    async def test_model_and_messages_are_never_dropped(self, http):
        http.on("POST", "/chat/completions", bad_param("model"))
        with pytest.raises(LLMError, match="HTTP 400: unsupported: model"):
            await client.chat(CLOUD, "", "m", MSGS)
        assert len(http.requests) == 1

    async def test_unreachable(self, http):
        http.on("POST", "/chat/completions", httpx.ConnectError("refused"))
        with pytest.raises(LLMError, match="Can't reach"):
            await client.chat(CLOUD, "", "m", MSGS)

    async def test_a_request_that_cant_be_sent_doesnt_quote_the_key(self, http):
        # h11's message names the header it refused, and so the key in it.
        http.on("POST", "/chat/completions", httpx.LocalProtocolError("Illegal header value b'Bearer sk-secret\\n'"))
        with pytest.raises(LLMError, match="stray characters") as e:
            await client.chat(CLOUD, "sk-secret", "m", MSGS)
        assert "sk-secret" not in str(e.value)

    async def test_server_error_shows_the_providers_message(self, http):
        http.on("POST", "/chat/completions", httpx.Response(401, json={"error": {"message": "bad key"}}))
        with pytest.raises(LLMError, match="HTTP 401: bad key"):
            await client.chat(CLOUD, "", "m", MSGS)

    async def test_unexpected_body(self, http):
        http.on("POST", "/chat/completions", httpx.Response(200, json={"choices": []}))
        with pytest.raises(LLMError, match="Unexpected response"):
            await client.chat(CLOUD, "", "m", MSGS)


@pytest.mark.parametrize("resp, msg", [
    (httpx.Response(500, json={"error": {"message": "boom"}}), "HTTP 500: boom"),
    (httpx.Response(500, json={"error": "plain"}), "HTTP 500: plain"),
    (httpx.Response(500, json={"message": "top"}), "HTTP 500: top"),
    (httpx.Response(422, json={"detail": "why"}), "HTTP 422: why"),
    (httpx.Response(502, text="<html>gateway</html>"), "HTTP 502: <html>gateway</html>"),
    (httpx.Response(503, json={}), "HTTP 503: Service Unavailable"),
])
def test_explain(resp, msg):
    assert client._explain(resp) == msg


def test_offending_param():
    assert client._offending_param(bad_param("temperature")) == "temperature"
    assert client._offending_param(httpx.Response(400, json={"error": {"param": None}})) is None
    assert client._offending_param(httpx.Response(400, text="not json")) is None


@pytest.mark.parametrize("url, local", [
    ("http://localhost:11434/v1", True), ("http://127.0.0.1:1234/v1", True), ("http://[::1]:8000", True),
    ("http://box.local:11434/v1", True), ("https://api.openai.com/v1", False), ("", False), (None, False),
    # your own network: a GPU box in the next room is local too
    ("http://192.168.0.13:1234/v1", True), ("http://10.0.0.5:8000/v1", True), ("http://172.20.1.1:8080/v1", True),
    ("http://100.64.1.2:1234/v1", True), ("http://mac-studio:1234/v1", True), ("http://[fd00::1]:1234/v1", True),
    # the internet is not
    ("http://8.8.8.8:1234/v1", False), ("https://openrouter.ai/api/v1", False), ("http://172.32.0.1/v1", False),
])
def test_is_local(url, local):
    assert client.is_local(url) is local


def test_in_a_container_the_host_is_local(monkeypatch):
    # OPENSPEAK_LOCAL_HOST (set by the Dockerfile) names where LM Studio / Ollama live from inside.
    assert not client.is_local("http://host.docker.internal:1234/v1")
    monkeypatch.setattr(client.config, "LOCAL_HOST", "host.docker.internal")
    assert client.is_local("http://host.docker.internal:1234/v1")


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    '```\n{"a": 1}\n```',
    'Sure! Here it is: {"a": 1} Hope that helps.',
    '<think>{"no": 0}</think>{"a": 1}',
])
def test_parse_json_salvages_the_object(text):
    assert client.parse_json(text) == {"a": 1}


@pytest.mark.parametrize("text", ["no json here", "[1, 2]", '"a"'])
def test_parse_json_without_an_object_fails(text):
    with pytest.raises(ValueError):
        client.parse_json(text)


@pytest.mark.parametrize("value, out", [(" a ", "a"), (None, ""), (3, ""), (["a"], ""), ({"a": 1}, "")])
def test_text_fields(value, out):
    assert client.text(value) == out


class TestModels:
    async def test_chat_models_sorted_without_embeddings(self, http):
        http.on("GET", "/models", httpx.Response(200, json={"data": [
            {"id": "zeta"}, {"id": "nomic-embed-text"}, {"id": "alpha"}, {"nope": 1}, "junk"]}))
        assert await client.list_models(CLOUD, "k") == ["alpha", "zeta"]

    async def test_error(self, http):
        http.on("GET", "/models", httpx.Response(401, json={"error": {"message": "bad key"}}))
        with pytest.raises(LLMError, match="bad key"):
            await client.list_models(CLOUD, "k")

    async def test_unreachable(self, http):
        http.on("GET", "/models", httpx.ConnectError("refused"))
        with pytest.raises(LLMError, match="Can't reach"):
            await client.list_models(CLOUD, "k")

    async def test_detect_local_lists_only_servers_that_answer(self, http):
        http.on("GET", "localhost:11434", httpx.Response(200, json={"data": [{"id": "qwen3"}]}))
        for port in (1234, 8080, 8000):
            http.on("GET", f"localhost:{port}", httpx.ConnectError("refused"))
        found = await client.detect_local()
        assert found == [{"provider": "ollama", "base_url": "http://localhost:11434/v1", "models": ["qwen3"]}]

    async def test_detect_local_finds_every_server_that_is_up(self, http):
        http.on("GET", "localhost:11434", httpx.ConnectError("refused"))
        http.on("GET", "localhost:1234", httpx.ConnectError("refused"))
        http.on("GET", "localhost:8080", httpx.Response(200, json={"data": [{"id": "gguf"}]}))
        http.on("GET", "localhost:8000", httpx.Response(200, json={"data": [{"id": "qwen"}]}))
        found = await client.detect_local()
        assert [f["provider"] for f in found] == ["llamacpp", "vllm"]
        assert all(client.is_local(str(r.url)) for r in http.requests)  # never asks a cloud provider
