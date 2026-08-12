"""GENE.1 / OI-GENE0 — Decision genealogy hermetic tests."""

from __future__ import annotations

from atlas.investment.decision_genealogy import (
    VERSION,
    build_genealogy,
    by_id_path,
    completeness_summary,
    find_parent_decision_id,
    format_genealogy_evening_lines,
)
from atlas.investment.decision_packets import DecisionPacketStore, build_packet
from atlas.investment.reports import format_evening_report


class _MemStore:
    def __init__(self, packets: list[dict]):
        self._packets = list(packets)

    def get(self, decision_id: str):
        for p in self._packets:
            if p.get("decision_id") == decision_id:
                return p
        return None

    def list_symbol(self, *, symbol: str, limit: int = 20, portfolio_key=None):
        out = []
        for p in self._packets:
            if p.get("symbol") != symbol:
                continue
            if portfolio_key and p.get("portfolio_key") != portfolio_key:
                continue
            out.append(p)
            if len(out) >= limit:
                break
        return out


def test_find_parent_skips_hold():
    store = _MemStore(
        [
            {
                "decision_id": "hold-1",
                "symbol": "TCS.NS",
                "action": "hold",
                "portfolio_key": "lab",
            },
            {
                "decision_id": "buy-1",
                "symbol": "TCS.NS",
                "action": "buy",
                "portfolio_key": "lab",
            },
        ]
    )
    assert find_parent_decision_id(store, symbol="TCS.NS", portfolio_key="lab") == "buy-1"


def test_build_genealogy_honest_gaps(tmp_path):
    pkt = build_packet(
        action="buy",
        symbol="EICHERMOT.NS",
        portfolio_key="india_equity_learner",
        strategy_tag="learner_primary",
        observation_ids=["obs-1"],
        hypothesis_id="hyp-1",
        decision_id="dec-gene-1",
    )
    # Minimal features already stamped by build_packet
    store = DecisionPacketStore(data_dir=tmp_path, repo=None)
    store.save(pkt)

    doc = build_genealogy(
        "dec-gene-1",
        data_dir=tmp_path,
        packet=pkt,
        packets_store=store,
        laboratory_id="india_equity_learner",
        persist=True,
    )
    assert doc["version"] == VERSION
    assert doc["decision_id"] == "dec-gene-1"
    assert "lesson" in doc["gaps"]
    assert "next" in doc["gaps"]
    assert "outcome" in doc["gaps"]
    assert doc["completeness_pct"] < 100.0
    hops = {h["hop"]: h for h in doc["hops"]}
    assert hops["decision"]["present"] is True
    assert hops["evidence"]["present"] is True
    assert hops["strategy"]["present"] is True
    assert hops["experiment"]["present"] is True
    assert hops["lesson"]["present"] is False
    assert hops["next"]["present"] is False
    assert by_id_path(tmp_path, "dec-gene-1").is_file()


def test_parent_child_next_hop(tmp_path):
    parent = build_packet(
        action="buy",
        symbol="INFY.NS",
        portfolio_key="lab",
        strategy_tag="learner_primary",
        observation_ids=["o1"],
        decision_id="parent-1",
    )
    child = build_packet(
        action="sell",
        symbol="INFY.NS",
        portfolio_key="lab",
        strategy_tag="learner_exit",
        observation_ids=["o2"],
        parent_decision_id="parent-1",
        decision_id="child-1",
    )
    store = DecisionPacketStore(data_dir=tmp_path, repo=None)
    store.save(parent)
    store.save(child)

    doc = build_genealogy(
        "parent-1",
        data_dir=tmp_path,
        packet=parent,
        packets_store=store,
        laboratory_id="lab",
        persist=False,
    )
    hops = {h["hop"]: h for h in doc["hops"]}
    assert hops["next"]["present"] is True
    assert "child-1" in (hops["next"]["detail"] or {}).get("child_decision_ids", [])


def test_missing_packet_zero_completeness(tmp_path):
    doc = build_genealogy("missing-id", data_dir=tmp_path, persist=False)
    assert doc["completeness_pct"] == 0.0
    assert "decision" in doc["gaps"]


def test_evening_section():
    gens = [
        {
            "decision_id": "aaaaaaaa-bbbb",
            "symbol": "TCS.NS",
            "action": "buy",
            "completeness_pct": 62.5,
            "gaps": ["lesson", "next"],
        }
    ]
    assert completeness_summary(gens)["mean_completeness_pct"] == 62.5
    lines = format_genealogy_evening_lines(gens)
    assert any("GENE.1" in x for x in lines)
    body = format_evening_report(
        plan={"as_of": "2026-08-10", "candidates": [], "summary": {}},
        portfolio={"genealogies": gens, "equity": 1_000_000},
        program_id="market_intelligence",
    )[1]
    assert "Decision genealogy (GENE.1)" in body
