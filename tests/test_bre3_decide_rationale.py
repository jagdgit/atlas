"""BRE.3 — decide-time async LLM rationale hermetic tests."""

from __future__ import annotations

from atlas.investment.decide_rationale import (
    budget_for_decision,
    drain_pending_rationales,
    format_decide_rationale_lines,
    load_rationale,
    schedule_decide_rationale,
)


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeRole:
    def __init__(self, text: str) -> None:
        self._text = text

    def chat(self, messages, **kwargs):  # noqa: ANN001
        return _FakeResp(self._text)


class _FakeLLM:
    def __init__(self, text: str, *, busy: bool = False) -> None:
        self._text = text
        self._busy = busy
        self.calls = 0

    def lane_busy(self) -> bool:
        return self._busy

    def for_role(self, role: str) -> _FakeRole:
        self.calls += 1
        return _FakeRole(self._text)


_JSON = (
    '{"rationale_text":"Buy on thesis strength with PE known.",'
    '"falsifiers":["FCF stays missing","sector RS breaks"],'
    '"expected_outcome":"outperform peers over 30d",'
    '"claims":[{"text":"thesis ok","evidence_ids":["obs-1"]}]}'
)


def test_budget_buy_high():
    bud = budget_for_decision(action="buy", unknowns=["fcf", "news", "de"], is_open_book=True)
    assert bud["llm_budget"] >= 1


def test_schedule_pending_no_llm(tmp_path):
    packet = {
        "decision_id": "dec-bre3-1",
        "symbol": "EICHERMOT.NS",
        "action": "buy",
        "reasons_for": ["thesis trigger"],
        "unknowns": ["fcf"],
        "observation_ids": ["obs-1"],
        "meta": {"llm_pending": True},
    }
    row = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-bre3-1",
        symbol="EICHERMOT.NS",
        action="buy",
        laboratory_id="india_equity_learner",
        packet=packet,
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["llm"] is False
    # Idempotent
    row2 = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-bre3-1",
        symbol="EICHERMOT.NS",
        action="buy",
        laboratory_id="india_equity_learner",
        packet=packet,
    )
    assert row2["rationale_id"] == row["rationale_id"]


def test_drain_fills_sidecar_packet_unchanged(tmp_path):
    packet = {
        "decision_id": "dec-bre3-2",
        "symbol": "APOLLOHOSP.NS",
        "action": "buy",
        "reasons_for": ["rank1"],
        "unknowns": ["fcf"],
        "observation_ids": ["obs-1"],
    }
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-bre3-2",
        symbol="APOLLOHOSP.NS",
        action="buy",
        laboratory_id="lab",
        packet=packet,
    )
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=3
    )
    assert out["done"] == 1
    assert llm.calls >= 1
    row = load_rationale(tmp_path, "dec-bre3-2", laboratory_id="lab")
    assert row is not None
    assert row["status"] == "done"
    assert "thesis" in (row.get("rationale_text") or "").lower() or row.get("rationale_text")
    assert row.get("falsifiers")
    # Packet dict not mutated by drain
    assert packet.get("meta") is None or "rationale_text" not in (packet.get("meta") or {})


def test_drain_defers_when_lane_busy(tmp_path):
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-busy",
        symbol="TCS.NS",
        action="sell",
        laboratory_id="lab",
        packet={"decision_id": "dec-busy", "action": "sell", "symbol": "TCS.NS", "unknowns": ["x"]},
    )
    llm = _FakeLLM(_JSON, busy=True)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=3
    )
    assert out["deferred"] >= 1
    assert llm.calls == 0
    row = load_rationale(tmp_path, "dec-busy", laboratory_id="lab")
    assert row["status"] == "deferred_lane_busy"


def test_drain_skips_below_budget(tmp_path):
    # Force zero budget by writing a hold-like low-importance then overriding
    row = schedule_decide_rationale(
        tmp_path,
        decision_id="dec-low",
        symbol="INFY.NS",
        action="buy",
        laboratory_id="lab",
        packet={"decision_id": "dec-low", "action": "buy", "symbol": "INFY.NS", "unknowns": []},
    )
    assert row is not None
    # Cap max_passes to 0 effectively by setting budget 0 on disk
    path = tmp_path / "investment" / "decide_rationale" / "lab" / "by_id" / "dec-low.json"
    import json

    doc = json.loads(path.read_text())
    doc["llm_budget"] = 0
    path.write_text(json.dumps(doc))
    llm = _FakeLLM(_JSON)
    out = drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=llm, max_passes=3
    )
    assert out["skipped"] >= 1
    assert llm.calls == 0


def test_evening_formatter_joins(tmp_path):
    schedule_decide_rationale(
        tmp_path,
        decision_id="dec-fmt",
        symbol="RELIANCE.NS",
        action="buy",
        laboratory_id="lab",
        packet={
            "decision_id": "dec-fmt",
            "action": "buy",
            "symbol": "RELIANCE.NS",
            "unknowns": ["fcf"],
            "observation_ids": ["obs-1"],
        },
    )
    drain_pending_rationales(
        tmp_path, laboratory_id="lab", llm=_FakeLLM(_JSON), max_passes=3
    )
    packets = [
        {
            "decision_id": "dec-fmt",
            "action": "buy",
            "symbol": "RELIANCE.NS",
            "meta": {"llm_pending": True},
        }
    ]
    lines = format_decide_rationale_lines(
        tmp_path, packets, laboratory_id="lab"
    )
    assert any("Decide-time rationale" in x for x in lines)
    assert any("RELIANCE" in x for x in lines)
    assert any("falsifiers" in x for x in lines)


def test_schedule_skips_holds(tmp_path):
    assert (
        schedule_decide_rationale(
            tmp_path,
            decision_id="h1",
            symbol="X.NS",
            action="hold",
            laboratory_id="lab",
        )
        is None
    )
