"""Section 23 — paper closed loop. No network, no live order.

Fails if a value is stored without evidence, if an order capability runs,
or if PLC.A is bypassed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas.agent_kernel.kernel import AgentKernel
from atlas.agent_kernel.safety import capability_allowed
from atlas.investment.data_quality import (
    commit_record,
    current_capability,
    decision_may_consume,
    envelope,
    note_capability_gap,
)
from atlas.investment.fel.promotion import LIVE_CONTROL, assert_not_live, promotion_for
from atlas.investment.plc_buy_gates import evaluate_fundamental_sanity, plc_a_enabled
from atlas.investment.uncertainty_queue import list_tasks, make_acquisition_task, upsert_task
from atlas.trading.strategy import StrategyDecisionRule

NOW = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
PERIOD = "2026-03-31"
GOAL = "Determine whether {symbol} has a usable PE and, if not, what is missing. Do not trade."


class _Journal:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def journal(self, **kwargs):
        self.entries.append(kwargs)
        return {"ok": True, "result": {"id": f"exp-{len(self.entries)}"}}


def _advice(packet: dict) -> dict:
    known = " ".join(str(x) for x in (packet.get("known") or packet.get("evidence") or []))
    usable = "evidence_id" in known
    return {
        "review_status": "REVIEWED",
        "conclusion": "usable" if usable else "not_usable",
        "uncertainty": "fixture envelope only",
        "falsifiers": ["filing restated"],
        "action": "BUY",
        "orders": [{"side": "SELL", "quantity": 1}],
    }


def _kernel(tmp_path: Path, journal: _Journal) -> AgentKernel:
    return AgentKernel(tmp_path, experience_os=journal, cognitive_fn=_advice)


def _goal(symbol: str) -> str:
    return GOAL.format(symbol=symbol)


def _observe(tmp_path: Path, symbol: str, *, name: str) -> None:
    inbox = tmp_path / "agent_kernel" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / name).write_text(
        json.dumps(
            {
                "source": "inbox",
                "domain": "investment",
                "symbol": symbol,
                "objective": _goal(symbol),
                "required": ["pe"],
                "priority_class": "P0",
                "constraints": {"never_orders": True},
                "decision_impact": False,
            }
        ),
        encoding="utf-8",
    )


def _book(tmp_path: Path, symbol: str) -> Path:
    path = tmp_path / "investment" / "paper" / f"{symbol}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"cash": 1000, "positions": []}\n', encoding="utf-8")
    return path


def _assert_no_order(task: dict, book: Path, before: bytes) -> None:
    assert book.read_bytes() == before
    assert capability_allowed("place_order") is False
    assert "place_order" not in (task.get("attempted_capabilities") or [])
    cognitive = task.get("cognitive") or {}
    assert cognitive.get("action") is None
    assert cognitive.get("orders") is None
    assert cognitive.get("never_orders") is True
    blob = json.dumps(task.get("decision") or "")
    assert "BUY" not in blob
    assert "SELL" not in blob


def test_trusted_pe_finishes_without_an_order_and_plc_a_still_blocks(tmp_path: Path):
    symbol = "SYMA.NS"
    note_capability_gap(
        tmp_path,
        symbol=symbol,
        metric="pe",
        reason="pe_missing",
        attempted=["local_market_store"],
        now=NOW,
    )
    upsert_task(
        tmp_path,
        make_acquisition_task(
            laboratory_id="india_equity_learner",
            symbol=symbol,
            unknown_code="pe_missing",
        ),
    )
    saved = commit_record(
        tmp_path,
        envelope(
            symbol=symbol,
            metric="pe",
            value=25.0,
            unit="ratio",
            period=PERIOD,
            period_end=PERIOD,
            period_type="FY",
            eps_basis="FY",
            price_as_of="2026-10-01",
            provider="nse_xbrl",
            source="NSE filing",
            evidence_id="ev-syma-pe",
            components={"price": 100.0, "eps": 4.0, "eps_basis": "FY"},
            calculation_method="price / EPS",
            now=NOW,
        ),
        now=NOW,
    )
    record = saved["record"]
    assert record["value"] == 25.0
    assert record["value"] != 0
    assert decision_may_consume(record) is True
    current = current_capability(tmp_path, symbol, "pe")
    assert any(row.get("current_state") == "CAPABILITY_GAP" for row in current["history"])
    pending = [
        row
        for row in list_tasks(tmp_path, "india_equity_learner", status="PENDING")
        if row.get("unknown") == "pe_missing" and row.get("symbol") == symbol
    ]
    assert pending == []

    journal = _Journal()
    book = _book(tmp_path, symbol)
    before = book.read_bytes()
    _observe(tmp_path, symbol, name="syma.json")
    kernel = _kernel(tmp_path, journal)
    report = kernel.cycle(mode="tick", allow_external=False, max_investigations=1)
    task = kernel.task(report["ran"][0])
    assert task is not None
    assert task["symbol"] == symbol
    assert _goal(symbol) in task["objective"]
    assert task["status"] == "SUCCESS"
    assert task["evidence"]["pe"]["evidence_id"] == "ev-syma-pe"
    assert task["evidence"]["pe"]["value"] == 25.0
    assert task["cognitive"]["conclusion"] == "usable"
    _assert_no_order(task, book, before)
    assert journal.entries
    experience = kernel.state["experiences"][0]
    assert experience["work_id"] == task["id"]
    assert experience["episode_id"] == task["episode_id"]
    assert "ev-syma-pe" in json.dumps(task["evidence"])
    again = current_capability(tmp_path, symbol, "pe")
    assert any(row.get("current_state") == "CAPABILITY_GAP" for row in again["history"])
    assert plc_a_enabled({}, "india_equity_learner") is True
    gate = evaluate_fundamental_sanity({"pe": record["value"]}, sector="Power")
    assert gate["ok"] is False
    assert "roe" in gate["missing"]
    assert StrategyDecisionRule.VERSION == "1.0.0"
    assert promotion_for(result="improve", operator_level10=True) != LIVE_CONTROL
    with pytest.raises(ValueError):
        assert_not_live(LIVE_CONTROL)


def test_snippet_is_rejected_and_another_symbol_can_still_run(tmp_path: Path):
    symbol = "SYMB.NS"
    other = "SYMC.NS"
    snippet = commit_record(
        tmp_path,
        envelope(
            symbol=symbol,
            metric="pe",
            value=99.5,
            provider="duckduckgo",
            source="web_snippet",
            evidence_id="ev-snippet",
            now=NOW,
        ),
        now=NOW,
    )
    assert snippet["record"]["value"] is None
    assert decision_may_consume(snippet["record"]) is False
    upsert_task(
        tmp_path,
        make_acquisition_task(
            laboratory_id="india_equity_learner",
            symbol=symbol,
            unknown_code="pe_missing",
        ),
    )
    journal = _Journal()
    book = _book(tmp_path, symbol)
    before = book.read_bytes()
    _observe(tmp_path, symbol, name="symb.json")
    kernel = _kernel(tmp_path, journal)
    first = kernel.cycle(mode="tick", allow_external=False, max_investigations=1)
    task = kernel.task(first["ran"][0])
    assert task is not None
    assert task["symbol"] == symbol
    assert task["status"] == "CAPABILITY_GAP"
    assert task["cognitive"]["conclusion"] == "not_usable"
    assert "web_snippets_are_not_a_structured_value" in json.dumps(task.get("failed"))
    _assert_no_order(task, book, before)
    experience = kernel.state["experiences"][0]
    assert experience["work_id"] == task["id"]
    assert any(
        "web_snippets_are_not_a_structured_value" in json.dumps(entry)
        for entry in journal.entries
    )
    current = current_capability(tmp_path, symbol, "pe")
    assert current["value"] is None
    assert current["retry_condition"] == "trusted_acquisition"
    assert "99.5" not in (tmp_path / "investment" / "data_quality" / "registry.json").read_text()
    pending = [
        row
        for row in list_tasks(tmp_path, "india_equity_learner", status="PENDING")
        if row.get("unknown") == "pe_missing" and row.get("symbol") == symbol
    ]
    assert pending

    _observe(tmp_path, other, name="symc.json")
    second = kernel.cycle(mode="tick", allow_external=False, max_investigations=1)
    nxt = kernel.task(second["ran"][0])
    assert nxt is not None
    assert nxt["symbol"] == other
    assert nxt["symbol"] != symbol
    assert kernel.task(task["id"])["status"] == "CAPABILITY_GAP"
    assert decision_may_consume(current_capability(tmp_path, symbol, "pe")) is False
    assert plc_a_enabled({}, "india_equity_learner") is True
    blocked = evaluate_fundamental_sanity(None, sector=None)
    assert blocked["ok"] is False
