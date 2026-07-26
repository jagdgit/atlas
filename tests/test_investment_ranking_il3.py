"""IL.3 — Ranking with WHY ± explanations + cold-start honesty."""

from __future__ import annotations

from atlas.investment.ranking import (
    CONF_HIGH,
    CONF_VERY_LOW,
    PHASE_ACTIVE,
    PHASE_LEARNING,
    rank_universe,
    summarize_phase,
)
from atlas.investment.watchlists import clear, instruments_for, latest
from atlas.workers.base import TickContext
from atlas.workers.investment_universe import InvestmentUniverseWorker


def _bars(closes: list[float], volumes: list[float] | None = None) -> list[dict]:
    vols = volumes or [1_000_000.0] * len(closes)
    out = []
    for i, c in enumerate(closes):
        out.append(
            {
                "t": f"2026-01-{i + 1:02d}",
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": vols[i] if i < len(vols) else vols[-1],
            }
        )
    return out


def test_cold_start_neutral_membership_order_labeled_learning():
    members = [
        {"symbol": "AAA.NS", "name": "Aaa", "sector": "X"},
        {"symbol": "BBB.NS", "name": "Bbb", "sector": "Y"},
        {"symbol": "CCC.NS", "name": "Ccc", "sector": "Z"},
    ]
    ranked = rank_universe(members, max_watchlist=3)
    assert [r["symbol"] for r in ranked] == ["AAA.NS", "BBB.NS", "CCC.NS"]
    assert all(r["phase"] == PHASE_LEARNING for r in ranked)
    assert all(r["confidence"] == CONF_VERY_LOW for r in ranked)
    assert all(
        any(e.get("component") == "cold_start" for e in r["explanations"]) for r in ranked
    )
    assert "Learning" in ranked[0]["reason"]
    summary = summarize_phase(ranked)
    assert summary["phase"] == PHASE_LEARNING
    assert summary["confidence"] == CONF_VERY_LOW


def test_momentum_ranks_rising_above_flat_with_why():
    members = [
        {"symbol": "FLAT.NS", "name": "Flat", "sector": "A"},
        {"symbol": "RISE.NS", "name": "Rise", "sector": "B"},
        {"symbol": "FALL.NS", "name": "Fall", "sector": "C"},
    ]
    # 25 closes so lookback_long=20 works
    flat = _bars([100.0] * 25, volumes=[5_000_000.0] * 25)
    rise = _bars([100.0 + i * 2.0 for i in range(25)], volumes=[8_000_000.0] * 25)
    fall = _bars([100.0 - i * 1.5 for i in range(25)], volumes=[2_000_000.0] * 25)
    ranked = rank_universe(
        members,
        bars_by_symbol={"FLAT.NS": flat, "RISE.NS": rise, "FALL.NS": fall},
        max_watchlist=3,
        cold_start_coverage=0.25,
    )
    assert ranked[0]["symbol"] == "RISE.NS"
    assert ranked[-1]["symbol"] == "FALL.NS"
    assert ranked[0]["phase"] == PHASE_ACTIVE
    assert ranked[0]["confidence"] in {CONF_HIGH, "medium", "high"}
    why = ranked[0]["explanations"]
    assert any(e["sign"] == "+" and "momentum" in e["component"] for e in why)
    assert ranked[0]["reason"].startswith("+") or "+" in ranked[0]["reason"]
    # Falling name should surface weak momentum
    fall_row = next(r for r in ranked if r["symbol"] == "FALL.NS")
    assert any(e["sign"] == "−" and e["component"] == "momentum" for e in fall_row["explanations"])


def test_policy_and_experience_show_in_explanations():
    members = [
        {"symbol": "PREF.NS", "name": "Pref", "sector": "A"},
        {"symbol": "AVOID.NS", "name": "Avoid", "sector": "B"},
    ]
    bars = {s["symbol"]: _bars([100.0 + i for i in range(25)]) for s in members}
    ranked = rank_universe(
        members,
        bars_by_symbol=bars,
        policy_delta_by_symbol={"PREF.NS": 0.15, "AVOID.NS": -0.15},
        experience_bias_by_symbol={"AVOID.NS": -0.3},
        max_watchlist=2,
    )
    pref = next(r for r in ranked if r["symbol"] == "PREF.NS")
    avoid = next(r for r in ranked if r["symbol"] == "AVOID.NS")
    assert any(e["component"] == "policy" and e["sign"] == "+" for e in pref["explanations"])
    assert any(e["component"] == "policy" and e["sign"] == "−" for e in avoid["explanations"])
    assert any(
        e["component"] == "experience" and e["sign"] == "−" for e in avoid["explanations"]
    )
    assert pref["rank"] < avoid["rank"]


def test_quality_proxy_optional():
    members = [
        {"symbol": "GOOD.NS", "name": "Good", "sector": "A"},
        {"symbol": "WEAK.NS", "name": "Weak", "sector": "B"},
    ]
    bars = {s["symbol"]: _bars([100.0] * 25) for s in members}
    ranked = rank_universe(
        members,
        bars_by_symbol=bars,
        quality_by_symbol={
            "GOOD.NS": {"roe": 0.25, "debt_to_equity": 0.2},
            "WEAK.NS": {"roe": 0.02, "debt_to_equity": 2.5},
        },
        max_watchlist=2,
    )
    assert ranked[0]["symbol"] == "GOOD.NS"
    assert any(e["component"] == "quality" and e["sign"] == "+" for e in ranked[0]["explanations"])


def test_worker_publishes_why_and_learning_without_reader():
    clear()
    worker = InvestmentUniverseWorker(events=None, market_reader=None)
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m1",
            config={"index": "NIFTY50", "max_watchlist": 5, "mode": "auto"},
            config_version=1,
            state={},
            inputs=[],
        )
    )
    assert result.state["phase"] == PHASE_LEARNING
    assert result.state["confidence"] == CONF_VERY_LOW
    assert "phase=learning" in result.note
    snap = latest()
    assert snap is not None
    ranked = snap["ranked"]
    assert len(ranked) == 5
    assert ranked[0]["explanations"]
    assert any(e.get("component") == "cold_start" for e in ranked[0]["explanations"])
    assert instruments_for(max_n=1)[0]["symbol"] == ranked[0]["symbol"]


def test_worker_ranks_with_fake_market_reader():
    clear()
    members_top = ["ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS"]

    class FakeReader:
        def bars_for(self, symbol, **kwargs):
            # Make APOLLOHOSP rise strongly; others flat
            if symbol == "APOLLOHOSP.NS":
                closes = [100.0 + i * 3.0 for i in range(30)]
            else:
                closes = [100.0] * 30
            return {"bars": _bars(closes), "count": 30}

    worker = InvestmentUniverseWorker(events=None, market_reader=FakeReader())
    result = worker.do_tick(
        TickContext(
            worker_id="w1",
            mission_id="m1",
            config={
                "index": "NIFTY50",
                "max_watchlist": 3,
                "mode": "auto",
                # Force active ranking: reader returns bars for every fetch
                "cold_start_coverage": 0.01,
            },
            config_version=1,
            state={},
            inputs=[],
        )
    )
    # Worker fetches bars for all 50 — coverage high → active
    assert result.state["phase"] == PHASE_ACTIVE
    assert result.state["watchlist_symbols"][0] == "APOLLOHOSP.NS"
    snap = latest()
    top = snap["ranked"][0]
    assert top["symbol"] == "APOLLOHOSP.NS"
    assert any(e["sign"] == "+" for e in top["explanations"])
    assert top["reason"]
    # sanity: fake covered the symbols we care about
    assert set(members_top) & set(result.state["watchlist_symbols"])
