"""OI-F1 Decision Knowledge helpers + soft-bias wiring."""

from __future__ import annotations

from atlas.decision.knowledge import (
    bias_recommendations,
    decision_knowledge_tags,
    experience_id_from_result,
    link_metadata,
    outcome_label,
    should_enable_decision_bias,
)


def test_outcome_label_and_bias_gate():
    assert outcome_label(1.5) == "profit"
    assert outcome_label(-0.1) == "loss"
    assert outcome_label(0.0) == "flat"
    assert should_enable_decision_bias("profit") is True
    assert should_enable_decision_bias("loss") is True
    assert should_enable_decision_bias("flat") is False


def test_tags_and_metadata_link_decision():
    tags = decision_knowledge_tags("AAPL", "profit", decision_id="dec-1")
    assert "aapl" in tags
    assert "decision_knowledge" in tags
    assert "decision:dec-1" in tags
    assert "sell:aapl" in tags
    meta = link_metadata(decision_id="dec-1", symbol="AAPL", outcome="profit", pnl=12.5)
    assert meta["decision_id"] == "dec-1"
    assert meta["action_key"] == "sell:aapl"
    assert meta["decision_knowledge"] is True


def test_bias_recommendations_for_profit_and_loss():
    profit = bias_recommendations("MSFT", "profit", 3.0)
    assert any(r["title"] == "buy" for r in profit)
    assert any(r["title"] == "msft" for r in profit)
    loss = bias_recommendations("MSFT", "loss", -2.0)
    assert any(r["title"] == "hold" for r in loss)


def test_experience_id_from_journal_result():
    wrapped = {"ok": True, "result": {"event": {"ref_id": "exp-9"}, "applied": True}}
    assert experience_id_from_result(wrapped) == "exp-9"
    assert experience_id_from_result({"event": {"ref_id": "exp-2"}}) == "exp-2"
    assert experience_id_from_result({}) is None


def test_remember_outcome_enables_bias_on_profit():
    """PaperTradingWorker stamps decision link and enables soft-bias for profits."""
    from atlas.workers.paper_trading import PaperTradingWorker

    class FakeOS:
        def __init__(self):
            self.last = None

        def journal(self, **kw):
            self.last = kw
            return {"ok": True, "result": {"event": {"ref_id": "exp-profit"}, "applied": True}}

    class FakeLearning:
        def __init__(self):
            self.enabled = []

        def enable_bias(self, experience_id, *, enabled=True):
            self.enabled.append((experience_id, enabled))
            return {"bias_enabled": enabled}

    decision = type("D", (), {"id": "dec-42", "why": "momentum exit"})()
    os_ = FakeOS()
    learn = FakeLearning()
    worker = PaperTradingWorker(
        assets=None, market_data=None, decision_engine=None, portfolio=None,
        learning=learn, experience_os=os_,
    )
    worker._remember_outcome(
        "NVDA",
        {"realized_pnl": 25.0},
        decision,
        cfg={"enable_decision_soft_bias": True},
    )
    assert os_.last is not None
    assert os_.last["metadata"]["decision_id"] == "dec-42"
    assert "decision_knowledge" in os_.last["tags"]
    assert learn.enabled == [("exp-profit", True)]


def test_remember_outcome_skips_bias_on_flat():
    from atlas.workers.paper_trading import PaperTradingWorker

    class FakeOS:
        def journal(self, **kw):
            return {"ok": True, "result": {"event": {"ref_id": "exp-flat"}, "applied": True}}

    class FakeLearning:
        def __init__(self):
            self.enabled = []

        def enable_bias(self, experience_id, *, enabled=True):
            self.enabled.append(experience_id)

    worker = PaperTradingWorker(
        assets=None, market_data=None, decision_engine=None, portfolio=None,
        learning=FakeLearning(), experience_os=FakeOS(),
    )
    worker._remember_outcome("X", {"realized_pnl": 0.0}, type("D", (), {"id": "d", "why": ""})())
    assert worker._learning.enabled == []
