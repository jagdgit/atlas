"""Tests for the LLM provider and service.

Provider behaviour is tested with httpx.MockTransport (no server). One integration
test hits a real Ollama and skips if it is unreachable.
"""

from __future__ import annotations

import json

import httpx
import pytest

from atlas.config import get_config
from atlas.llm.ollama_provider import OllamaError, OllamaProvider
from atlas.llm.provider import ChatMessage
from atlas.llm.service import LLMService
from atlas.services.base import HealthStatus


def _provider(handler, **kw) -> OllamaProvider:
    client = httpx.Client(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    return OllamaProvider(host="http://ollama.test", client=client, **kw)


# --- provider: generate / chat / embed ----------------------------------
def test_generate_returns_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"response": "pong", "eval_count": 3})

    provider = _provider(handler)
    res = provider.generate("ping")
    assert res.text == "pong"
    assert res.usage["eval_count"] == 3


def test_generate_strips_inline_thinking():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"response": "<think>reasoning here</think>The answer is 42."}
        )

    res = _provider(handler).generate("q")
    assert res.text == "The answer is 42."
    assert res.thinking == "reasoning here"


def test_generate_strips_orphan_closing_think_tag():
    # qwen3 with think disabled leaks reasoning ending in a stray </think>.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"response": "let me reason about this\n</think>\n\n4"}
        )

    res = _provider(handler).generate("q")
    assert res.text == "4"
    assert res.thinking == "let me reason about this"


def test_generate_uses_explicit_thinking_field():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"response": "final answer", "thinking": "deep thoughts"}
        )

    res = _provider(handler).generate("q")
    assert res.text == "final answer"
    assert res.thinking == "deep thoughts"


def test_chat_returns_message_content():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hi"}})

    res = _provider(handler).chat(
        [ChatMessage("system", "be brief"), ChatMessage("user", "hello")]
    )
    assert res.text == "hi"


def test_embed_returns_vectors():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    res = _provider(handler).embed(["hello"])
    assert res.dimension == 3
    assert res.vectors == [[0.1, 0.2, 0.3]]


def test_think_unsupported_falls_back():
    calls: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        has_think = "think" in body
        calls.append(has_think)
        if has_think:
            return httpx.Response(400, text="this model does not support thinking")
        return httpx.Response(200, json={"response": "ok"})

    res = _provider(handler, think=True).generate("q")
    assert res.text == "ok"
    assert calls == [True, False]  # tried with think, then retried without


def test_error_raises_ollama_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(OllamaError):
        _provider(handler).embed(["x"])


def test_health_true_when_tags_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]})

    assert _provider(handler).health() is True


def test_health_false_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    assert _provider(handler).health() is False


# --- service health -------------------------------------------------------
class FakeProvider:
    name = "fake"

    def __init__(self, models, healthy=True):
        self._models = models
        self._healthy = healthy
        self.closed = False

    def health(self):
        return self._healthy

    def list_models(self):
        return self._models

    def close(self):
        self.closed = True


def test_service_healthy_when_chat_model_present():
    svc = LLMService(
        FakeProvider(["qwen3:4b", "nomic-embed-text"]),
        model="qwen3:4b",
        embedding_model="nomic-embed-text",
    )
    status = svc.health_check()
    assert isinstance(status, HealthStatus)
    assert status.healthy
    assert status.data["chat_model_ready"]
    assert status.data["embedding_model_ready"]


def test_service_unhealthy_when_chat_model_missing():
    svc = LLMService(
        FakeProvider(["llama3:latest"]),
        model="qwen3:4b",
        embedding_model="nomic-embed-text",
    )
    status = svc.health_check()
    assert not status.healthy
    assert not status.data["embedding_model_ready"]


def test_service_unhealthy_when_provider_down():
    svc = LLMService(
        FakeProvider([], healthy=False), model="m", embedding_model="e"
    )
    assert not svc.health_check().healthy


def test_service_stop_closes_provider():
    provider = FakeProvider(["m"])
    svc = LLMService(provider, model="m", embedding_model="e")
    svc.stop()
    assert provider.closed


# --- roles (D7) + single lane (R4) ---------------------------------------
def test_for_role_resolves_configured_model():
    svc = LLMService(
        FakeProvider(["qwen3:4b", "qwen3:8b"]),
        model="qwen3:4b",
        embedding_model="nomic-embed-text",
        roles={"planner": "qwen3:8b"},
    )
    assert svc.for_role("planner").model == "qwen3:8b"
    # chat/embed are always seeded from the legacy scalar config (back-compat).
    assert svc.for_role("chat").model == "qwen3:4b"
    assert svc.for_role("embed").model == "nomic-embed-text"


def test_for_role_unknown_falls_back_to_chat_model():
    svc = LLMService(FakeProvider(["m"]), model="m", embedding_model="e")
    assert svc.for_role("researcher").model == "m"  # not configured => chat model


def test_health_reports_roles():
    svc = LLMService(
        FakeProvider(["qwen3:4b", "nomic-embed-text"]),
        model="qwen3:4b",
        embedding_model="nomic-embed-text",
        roles={"planner": "qwen3:8b"},
    )
    data = svc.health_check().data
    assert data["roles"]["planner"] == "qwen3:8b"
    assert data["roles_ready"]["chat"] is True
    assert data["roles_ready"]["planner"] is False  # 8b not installed in the fake
    assert data["max_concurrency"] == 1


class ConcurrencyProvider:
    """Records the max number of concurrent in-flight calls."""

    name = "conc"

    def __init__(self):
        import threading

        self.current = 0
        self.max_seen = 0
        self.models: list[str] = []
        self._lock = threading.Lock()

    def _enter(self):
        import time

        with self._lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)
        time.sleep(0.02)
        with self._lock:
            self.current -= 1

    def chat(self, messages, **options):
        from atlas.llm.provider import LLMResponse

        self.models.append(options.get("model", "?"))
        self._enter()
        return LLMResponse(text="ok", model=options.get("model", "m"))

    def generate(self, prompt, **options):
        return self.chat([], **options)

    def embed(self, texts, **options):
        from atlas.llm.provider import EmbeddingResponse

        self._enter()
        return EmbeddingResponse(vectors=[[0.0]], model=options.get("model", "e"))

    def health(self):
        return True


def test_single_lane_serialises_inference():
    import threading

    provider = ConcurrencyProvider()
    svc = LLMService(provider, model="m", embedding_model="e", max_concurrency=1)

    def call():
        svc.chat([ChatMessage("user", "hi")])

    threads = [threading.Thread(target=call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert provider.max_seen == 1  # never two models at once (R4)


def test_role_client_injects_model_into_provider_call():
    provider = ConcurrencyProvider()
    svc = LLMService(
        provider, model="m", embedding_model="e", roles={"planner": "qwen3:8b"}
    )
    svc.for_role("planner").chat([ChatMessage("user", "plan")])
    assert provider.models == ["qwen3:8b"]


# --- integration (real Ollama) -------------------------------------------
def _ollama_or_skip() -> OllamaProvider:
    host = get_config().llm.host
    try:
        httpx.get(f"{host}/api/tags", timeout=2.0).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ollama unreachable: {exc}")
    return OllamaProvider(
        host=host,
        model=get_config().llm.model,
        embedding_model=get_config().llm.embedding_model,
    )


def test_integration_generate():
    provider = _ollama_or_skip()
    models = provider.list_models()
    assert models  # at least one model installed
    res = provider.generate("Reply with exactly: OK", num_predict=256)
    assert res.model
    # Reasoning models may spend the budget in `thinking`; either proves the
    # round-trip worked and that our text/thinking separation is clean.
    assert res.text.strip() or res.thinking
    assert "<think>" not in res.text and "</think>" not in res.text
    provider.close()


def test_integration_embed():
    provider = _ollama_or_skip()
    installed = provider.list_models()
    # qwen3 doesn't support embeddings; pick a model that does.
    candidates = [get_config().llm.embedding_model, "llama3:latest", "llama3"]
    model = next((m for m in candidates if m in installed), None)
    if model is None:
        provider.close()
        pytest.skip(f"no embedding-capable model installed (have {installed})")
    res = provider.embed(["hello world"], model=model)
    assert res.dimension > 0
    provider.close()
