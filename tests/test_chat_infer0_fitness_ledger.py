"""OI-CHAT-INFER0 Stage 0 — LLM fitness ledger."""

from __future__ import annotations

from atlas.llm.fitness_ledger import (
    VERSION,
    format_fitness_evening_lines,
    load_day,
    record_inference,
    summarize_day,
)
from atlas.llm.service import LLMService
from atlas.llm.provider import ChatMessage, LLMResponse


class _FakeProvider:
    name = "fake"

    def __init__(self, *, delay_note: str = "ok") -> None:
        self.calls = 0
        self.delay_note = delay_note

    def generate(self, prompt: str, **options):
        self.calls += 1
        return LLMResponse(
            text="hi",
            model="fake-model",
            usage={"eval_count": 10, "eval_duration": 50_000_000},  # 50ms in ns
        )

    def chat(self, messages, **options):
        return self.generate("")

    def embed(self, texts, **options):
        from atlas.llm.provider import EmbeddingResponse

        return EmbeddingResponse(vectors=[[0.1, 0.2]], model="fake-embed")

    def health(self) -> bool:
        return True


def test_record_and_summarize(tmp_path):
    record_inference(
        tmp_path,
        lane="chat",
        role="chat",
        model="qwen3:4b",
        kind="chat",
        outcome="ok",
        queue_wait_ms=12.5,
        generate_ms=52000,
        prompt_tokens=40,
        output_tokens=20,
        purpose="joke",
    )
    record_inference(
        tmp_path,
        lane="chat",
        role="chat",
        model="qwen3:4b",
        kind="busy_preflight",
        outcome="busy",
        queue_wait_ms=0,
        generate_ms=0,
    )
    record_inference(
        tmp_path,
        lane="research",
        role="researcher",
        model="qwen3:4b",
        outcome="ok",
        generate_ms=80000,
    )
    rows = load_day(tmp_path)
    assert len(rows) == 3
    assert rows[0]["version"] == VERSION
    summary = summarize_day(rows)
    assert summary["inferences"] == 3
    assert summary["outcomes"]["ok"] == 2
    assert summary["outcomes"]["busy"] == 1
    chat = summary["by_lane"]["chat"]
    assert chat["n"] == 2
    assert chat["busy"] == 1
    assert chat["generate_p50_ms"] == 52000.0 or chat["generate_p95_ms"] == 52000.0
    lines = format_fitness_evening_lines(tmp_path)
    text = "\n".join(lines)
    assert "LLM fitness" in text
    assert "chat:" in text


def test_llm_service_records_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA", str(tmp_path))  # may be ignored
    # Force fitness ledger data_dir via monkeypatch of _data_dir
    import atlas.llm.fitness_ledger as fl

    monkeypatch.setattr(fl, "_data_dir", lambda: str(tmp_path))

    svc = LLMService(
        _FakeProvider(),
        model="fake-model",
        embedding_model="fake-embed",
        max_concurrency=1,
    )
    out = svc.for_role("chat").chat(
        [ChatMessage("user", "joke")], _atlas_purpose="test_joke"
    )
    assert out.text == "hi"
    rows = load_day(tmp_path)
    assert len(rows) >= 1
    last = rows[-1]
    assert last["outcome"] == "ok"
    assert last["lane"] == "chat"
    assert last["role"] == "chat"
    assert last["queue_wait_ms"] is not None
    assert last["generate_ms"] is not None
    assert last.get("output_tokens") == 10
    assert last.get("purpose") == "test_joke"


def test_timed_out_classified_as_timeout(tmp_path, monkeypatch):
    import atlas.llm.fitness_ledger as fl

    monkeypatch.setattr(fl, "_data_dir", lambda: str(tmp_path))

    class _TimeoutProvider(_FakeProvider):
        def chat(self, messages, **options):
            raise RuntimeError("request to /api/chat failed: timed out")

    svc = LLMService(
        _TimeoutProvider(),
        model="fake-model",
        embedding_model="fake-embed",
        max_concurrency=1,
    )
    try:
        svc.for_role("chat").chat(
            [ChatMessage("user", "x")], _atlas_purpose="assistant_compose"
        )
        assert False, "expected raise"
    except RuntimeError:
        pass
    last = load_day(tmp_path)[-1]
    assert last["outcome"] == "timeout"
    assert last["purpose"] == "assistant_compose"


def test_market_role_maps_to_market_lane(tmp_path, monkeypatch):
    import atlas.llm.fitness_ledger as fl

    monkeypatch.setattr(fl, "_data_dir", lambda: str(tmp_path))

    svc = LLMService(
        _FakeProvider(),
        model="fake-model",
        embedding_model="fake-embed",
        roles={"chat": "fake-model", "market": "fake-model", "embed": "fake-embed"},
        max_concurrency=1,
    )
    out = svc.for_role("market").chat(
        [ChatMessage("user", "decide")], _atlas_purpose="bre3_decide_rationale"
    )
    assert out.text == "hi"
    last = load_day(tmp_path)[-1]
    assert last["lane"] == "market"
    assert last["role"] == "market"
    assert last["purpose"] == "bre3_decide_rationale"
