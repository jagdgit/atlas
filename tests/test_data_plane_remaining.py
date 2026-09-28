"""DP-YAH2 / DP-BATCH1 / DP-THESIS1 / DP-FUND3 — data-plane remaining fixes."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from atlas.core.resources.host_guard import HostGuardService
from atlas.investment.research.service import InvestmentResearchService
from atlas.investment.yahoo_fundamentals import (
    YAHOO_PRIORITY_LIVE_MARKS,
    YAHOO_PRIORITY_OPEN_BOOK_ENRICH,
    YAHOO_PRIORITY_UNIVERSE,
    YahooRateGate,
    reset_yahoo_rate_gate_for_tests,
)


class _FakeResources:
    def can_admit_tick(self, **_kwargs):
        from atlas.core.resources.manager import AdmissionDecision

        return AdmissionDecision(
            allowed=True,
            reason="admitted",
            cost_units=0,
            expected_ram_mb=512,
            llm_slots=0,
            budget_units=20,
        )

    def host_guard_status(self, **_kwargs):
        return {"throttled": False}


def test_yahoo_priority_rth_live_only(monkeypatch, tmp_path):
    reset_yahoo_rate_gate_for_tests()
    monkeypatch.setattr(
        "atlas.trading.sessions.is_session_open", lambda *a, **k: True
    )
    gate = YahooRateGate(data_dir=tmp_path, min_interval_s=0.0)
    ok_live, _ = gate.may_network(YAHOO_PRIORITY_LIVE_MARKS)
    ok_enrich, reason = gate.may_network(YAHOO_PRIORITY_OPEN_BOOK_ENRICH)
    ok_uni, reason2 = gate.may_network(YAHOO_PRIORITY_UNIVERSE)
    assert ok_live is True
    assert ok_enrich is False and reason == "rth_live_only"
    assert ok_uni is False and reason2 == "rth_live_only"


def test_yahoo_priority_hold_beats_universe(monkeypatch, tmp_path):
    reset_yahoo_rate_gate_for_tests()
    monkeypatch.setattr(
        "atlas.trading.sessions.is_session_open", lambda *a, **k: False
    )
    gate = YahooRateGate(data_dir=tmp_path, min_interval_s=0.0)
    gate.wait(respect_cooldown=True, priority=YAHOO_PRIORITY_OPEN_BOOK_ENRICH)
    ok_uni, reason = gate.may_network(YAHOO_PRIORITY_UNIVERSE)
    assert ok_uni is False
    assert reason == "yield_to_higher_priority"
    ok_live, _ = gate.may_network(YAHOO_PRIORITY_LIVE_MARKS)
    assert ok_live is True


def test_archive_evening_clamp(monkeypatch):
    ist = ZoneInfo("Asia/Kolkata")
    evening = datetime(2026, 8, 24, 18, 0, tzinfo=ist)
    monkeypatch.setattr(
        "atlas.trading.sessions.is_session_open", lambda *a, **k: False
    )
    guard = HostGuardService(
        resources=_FakeResources(),
        max_archive_workers=2,
        archive_one_evening=True,
        archive_evening_until_hour_ist=22,
        clock=lambda: evening,
    )
    assert guard.status()["max_archive_workers"] == 1
    assert guard.status()["archive_rth_clamped"] is True

    late = datetime(2026, 8, 24, 22, 30, tzinfo=ist)
    guard2 = HostGuardService(
        resources=_FakeResources(),
        max_archive_workers=2,
        archive_one_evening=True,
        clock=lambda: late,
    )
    assert guard2.status()["max_archive_workers"] == 2


def test_host_guard_prefers_enrich_over_archive_when_clamped(monkeypatch):
    ist = ZoneInfo("Asia/Kolkata")
    evening = datetime(2026, 8, 24, 17, 0, tzinfo=ist)
    monkeypatch.setattr(
        "atlas.trading.sessions.is_session_open", lambda *a, **k: False
    )

    class _Workers:
        def __init__(self):
            self.resumed = []
            self.rows = [
                SimpleNamespace(
                    id="arch1",
                    type="owner_knowledge",
                    status="paused",
                    metadata={"queued_for_capacity": True},
                    created_at="2026-01-01",
                ),
                SimpleNamespace(
                    id="enrich1",
                    type="fundamentals_enrich",
                    status="paused",
                    metadata={"queued_for_capacity": True},
                    created_at="2026-01-02",
                ),
            ]

        def list_workers(self, status=None, **_kwargs):
            rows = list(self.rows)
            if status:
                rows = [w for w in rows if w.status == status]
            return rows

        def resume(self, worker_id, reason=""):
            self.resumed.append(str(worker_id))
            for w in self.rows:
                if str(w.id) == str(worker_id):
                    w.status = "running"
                    w.metadata = {}
                    return w
            raise KeyError(worker_id)

    workers = _Workers()
    guard = HostGuardService(
        resources=_FakeResources(),
        workers=workers,
        max_archive_workers=2,
        archive_one_evening=True,
        clock=lambda: evening,
    )
    out = guard.tick({})
    assert out["resumed"] == 1
    assert workers.resumed[0] == "enrich1"


def test_gate_buy_blocks_watch_insufficient_under_soft(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    doc = svc.get_or_create("WELCORP.NS")
    from atlas.investment.research.models import mark_section

    for name in ("business", "growth", "management", "financial_health", "valuation"):
        mark_section(
            doc,
            name,
            fields={"evidence": [{"claim": "seed", "level": "F", "status": "present"}]},
            confidence="medium",
            gaps=[],
            sources=["test"],
            status="present",
        )
    doc["valuation"] = {
        "method": "watch_insufficient",
        "path_kind": "watch_insufficient",
        "margin_of_safety_pct": None,
    }
    doc["thesis"] = {
        "id": "t_watch",
        "stance": "watch",
        "summary": "WATCH — not BUY (MoS unknown; method=watch_insufficient)",
    }
    svc._store.save(doc)

    gate = svc.gate_buy(
        "WELCORP.NS",
        require_mvr=False,
        require_thesis=True,
        mos_mode="soft",
    )
    assert gate["allowed"] is False
    assert "thesis_watch_insufficient" in gate["reasons"]
    assert gate["action"] == "watch"


def test_open_book_screener_ritual_stages_csv(tmp_path):
    from atlas.investment.fundamentals import upsert_rows
    from atlas.investment.open_book_screener_ritual import (
        stage_open_book_screener_template,
    )

    upsert_rows(
        tmp_path,
        [{"symbol": "WELCORP.NS", "source": "test", "roe": 12.0}],
        program_id="market_intelligence",
    )

    out = stage_open_book_screener_template(
        tmp_path,
        symbols=["WELCORP.NS"],
        only_gaps=True,
    )
    assert out["ok"] is True
    assert out["row_count"] >= 1
    path = tmp_path / "imports" / "fundamentals" / out["filename"]
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "WELCORP" in text

def test_screener_ritual_stages_material_challenger_when_flat(tmp_path):
    import json
    from pathlib import Path

    from atlas.investment.fundamentals import upsert_rows
    from atlas.investment.next_rupee import store_dir
    from atlas.investment.open_book_screener_ritual import (
        stage_open_book_screener_template,
    )

    upsert_rows(
        tmp_path,
        [{"symbol": "WELCORP.NS", "source": "universe_seed", "roe": 11.0}],
        program_id="market_intelligence",
        merge_screener=False,
    )
    root = store_dir(tmp_path, "india_equity_learner")
    root.mkdir(parents=True, exist_ok=True)
    (root / "_latest.json").write_text(
        json.dumps({"destination": "WELCORP.NS", "destination_action": "DEPLOY"}),
        encoding="utf-8",
    )
    out = stage_open_book_screener_template(
        tmp_path,
        portfolio=None,
        portfolio_key="india_equity_learner",
        only_gaps=True,
    )
    assert out["ok"] is True
    assert out["row_count"] >= 1
    assert "WELCORP" in Path(out["path"]).read_text(encoding="utf-8")
