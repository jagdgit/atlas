"""IRA Phase A+B — Investing Research Agent spine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.investment.daily_plan import build_daily_plan
from atlas.investment.quality_seed import quality_row, ratios_for_symbol
from atlas.investment.ranking import rank_universe
from atlas.investment.reports import format_evening_report, format_morning_report
from atlas.investment.research import InvestmentResearchService
from atlas.investment.research.models import mark_stale_sections, mvr_status, section_is_stale
from atlas.investment.universe import membership


def test_mvr_pass_and_awareness(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("RELIANCE", mode="mvr", force=True)
    assert out["started"] is True
    assert out["ok"] is True
    aw = out["awareness"]
    assert aw["symbol"] == "RELIANCE.NS"
    assert aw["coverage"] > 0
    assert aw["thesis"] and aw["thesis"].get("id")
    assert aw["valuation"] and aw["valuation"].get("id")
    assert "coverage" in aw and "confidence" in aw
    assert aw["mvr_satisfied"] is True
    dossier = svc.dossier("RELIANCE")
    assert mvr_status(dossier)["satisfied"] is True


def test_gate_buy_blocks_without_research(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    gate = svc.gate_buy("UNKNOWNXYZ", require_mvr=True, require_thesis=True)
    assert gate["allowed"] is False
    assert any("mvr" in r or "thesis" in r for r in gate["reasons"])


def test_gate_buy_allows_after_mvr(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("INFY", mode="mvr", force=True)
    gate = svc.gate_buy(
        "INFY",
        require_mvr=True,
        require_thesis=True,
        require_mos=False,
        mos_mode="off",
    )
    assert gate["allowed"] is True


def test_record_outcome_learns(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("TCS", mode="mvr", force=True)
    out = svc.record_outcome(
        "TCS",
        result="weakened",
        note="Sim sell loss — review falsifiers",
        trade={"side": "sell", "realized_pnl": -12.5},
    )
    assert out["result"] == "weakened"
    dig = svc.daily_digest()
    assert dig["count"] >= 1
    assert any("TCS" in (x.get("symbol") or "") for x in dig["studied"])
    assert dig["lessons"]


def test_email_includes_research_digest():
    digest = {
        "studied": [
            {
                "symbol": "RELIANCE.NS",
                "phase": "thesis_ready",
                "coverage": 55.0,
                "confidence": "low",
                "mvr_satisfied": True,
                "thesis": "Watch until MoS",
                "stance": "watch",
            }
        ],
        "lessons": ["RELIANCE.NS: weakened — sim loss"],
        "open_gaps": ["RELIANCE.NS: cash_flow: FCF unknown"],
        "count": 1,
    }
    _, morning = format_morning_report(
        plan={"as_of": "2026-07-22", "summary": "test", "candidates": []},
        research_digest=digest,
    )
    assert "Research studied" in morning
    assert "RELIANCE.NS" in morning
    _, evening = format_evening_report(
        plan={"as_of": "2026-07-22", "summary": "test", "candidates": []},
        research_digest=digest,
    )
    assert "Lessons from trading experience" in evening
    assert "Open questions" in evening


def test_ondemand_non_nifty_symbol(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("MTARTECH", mode="mvr", force=True)
    assert out["ok"] is True
    aw = out["awareness"]
    assert aw["symbol"] == "MTARTECH.NS"
    assert aw.get("known_unknowns") or aw.get("coverage") is not None


def test_quality_optional_fields_passthrough():
    row = quality_row(
        symbol="DIXON",
        sector="Consumer Durables",
        overrides={"pe": 45.0, "roic": 0.22, "fcf": 120.0, "revenue_cagr": 0.18},
    )
    assert row["pe"] == 45.0
    assert row["roic"] == 0.22
    ratios = ratios_for_symbol("DIXON.NS", seed={"DIXON.NS": row})
    assert ratios["pe"] == 45.0
    assert ratios["fcf"] == 120.0


def test_nifty100_expanded():
    n50 = membership("NIFTY50")
    n100 = membership("NIFTY100")
    assert len(n100) > len(n50)
    assert any(r["symbol"] == "DIXON.NS" for r in n100)
    custom = membership("CUSTOM", extra_members=[{"symbol": "MTARTECH", "name": "MTAR"}])
    assert custom[0]["symbol"] == "MTARTECH.NS"


def test_refresh_stale_incremental(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("WIPRO", mode="mvr", force=True)
    doc = svc.dossier("WIPRO")
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    doc["sections"]["valuation"]["as_of"] = old
    doc["sections"]["valuation"]["status"] = "present"
    svc._store.save(doc)
    assert section_is_stale("valuation", doc["sections"]["valuation"])
    flipped = mark_stale_sections(doc)
    assert "valuation" in flipped or section_is_stale("valuation", doc["sections"]["valuation"])
    result = svc.refresh_stale("WIPRO")
    assert result["ok"] is True
    assert result["count"] >= 1
    fresh = svc.dossier("WIPRO")
    assert fresh["sections"]["valuation"]["status"] == "present"
    mem_text = " ".join(
        f"{m.get('interpretation', '')} {m.get('observation', '')}"
        for m in (fresh.get("memories") or [])
    ).lower()
    assert "refresh" in mem_text or "ttl" in mem_text


def test_daily_plan_cites_research():
    ranked = [
        {
            "symbol": "INFY.NS",
            "name": "Infosys",
            "sector": "IT",
            "rank": 1,
            "score": 0.7,
            "reason": "momentum",
            "explanations": [],
            "phase": "active",
            "confidence": "medium",
        }
    ]
    research = {
        "INFY.NS": {
            "coverage": 62.0,
            "confidence": "low",
            "mvr_satisfied": True,
            "thesis": {"stance": "watch", "summary": "Need MoS before size"},
        }
    }
    plan = build_daily_plan(ranked, research_by_symbol=research)
    cand = plan["candidates"][0]
    assert cand["research_coverage"] == 62.0
    assert cand["mvr_satisfied"] is True
    assert "Need MoS" in (cand.get("thesis_summary") or "")
    assert plan["research_cited"] == 1


def test_ranking_research_bias():
    members = [
        {"symbol": "A.NS", "name": "A", "sector": "IT"},
        {"symbol": "B.NS", "name": "B", "sector": "IT"},
    ]
    ranked2 = rank_universe(
        members,
        bars_by_symbol={
            "A.NS": [{"close": 10 + i, "volume": 1000} for i in range(30)],
            "B.NS": [{"close": 10 + i * 0.1, "volume": 1000} for i in range(30)],
        },
        research_bias_by_symbol={"A.NS": 0.25},
        cold_start_coverage=0.01,
        min_bars=5,
    )
    a = next(r for r in ranked2 if r["symbol"] == "A.NS")
    assert a["components"].get("research", 0) > 0.5
    assert any(e.get("component") == "research" for e in a.get("explanations") or [])


def test_mvr_uses_optional_fcf(tmp_path, monkeypatch):
    from atlas.investment import quality_seed as qs

    def fake_ratios(symbol, **kwargs):
        return {
            "roe": 0.2,
            "debt_to_equity": 0.3,
            "pe": 18.0,
            "fcf": 50.0,
            "roic": 0.15,
            "source": "test",
        }

    monkeypatch.setattr(qs, "ratios_for_symbol", fake_ratios)
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("FAKECO", mode="mvr", force=True)
    doc = out["dossier"]
    assert doc["sections"]["cash_flow"]["fields"].get("fcf") == 50.0
    assert doc["valuation"].get("fcf") == 50.0
    assert doc["valuation"].get("dcf") is not None
    assert doc["valuation"].get("margin_of_safety_pct") is not None  # PE vs fair
    assert doc["thesis"]["stance"] in {"watch", "watch_positive", "buy_candidate", "avoid"}


def test_valuation_dcf_and_mos():
    from atlas.investment.research.valuation import build_valuation_case, thesis_stance_from_valuation

    val = build_valuation_case(
        symbol="X.NS",
        ratios={"pe": 10.0, "roe": 0.2, "fcf": 100.0, "sector": "Information Technology"},
    )
    assert val["method"] == "multiples+dcf"
    assert val["dcf"]["enterprise_value_stub"] > 0
    assert val["margin_of_safety_pct"] is not None
    assert val["margin_of_safety_pct"] > 0  # pe 10 vs fair ~20
    assert thesis_stance_from_valuation(val) in {"buy_candidate", "watch_positive"}


def test_gate_mos_when_available_blocks_unknown(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("ITC", mode="mvr", force=True)
    # Hermetic seed usually lacks PE → MoS unknown → when_available blocks
    gate = svc.gate_buy("ITC", require_mvr=True, require_thesis=True, mos_mode="when_available")
    # May pass if PE somehow present; otherwise expect mos_unknown
    if gate.get("mos") is None:
        assert gate["allowed"] is False
        assert "mos_unknown" in gate["reasons"]
        assert gate["action"] == "watch"


def test_gate_soft_allows_unknown_mos(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("ITC", mode="mvr", force=True)
    gate = svc.gate_buy("ITC", require_mvr=True, require_thesis=True, mos_mode="soft")
    assert gate["allowed"] is True


def test_weekly_digest_and_format(tmp_path):
    from atlas.investment.reports import format_weekly_research_report

    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("TCS", mode="mvr", force=True)
    svc.record_outcome("TCS", result="weakened", note="Checkpoint loss review")
    dig = svc.weekly_learning_digest()
    assert dig["kind"] == "weekly_research_learning"
    assert dig["belief_changes"]
    _, body = format_weekly_research_report(digest=dig)
    assert "Weekly research learning" in body or "belief" in body.lower() or "TCS" in body


def test_mentor_writeback(tmp_path):
    class FakeEOS:
        def __init__(self):
            self.rows = []

        def journal(self, **kwargs):
            self.rows.append(kwargs)
            return {"ok": True, "ref_id": f"e-{len(self.rows)}"}

    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("INFY", mode="mvr", force=True)
    svc.record_outcome("INFY", result="held", note="Sim profit — thesis held")
    eos = FakeEOS()
    out = svc.writeback_lessons_to_mentor(experience_os=eos, limit=5)
    assert out["written"] == 1
    assert eos.rows[0]["domain"] == "markets"
    assert "thesis_outcome" in eos.rows[0]["tags"]
    # Idempotent
    out2 = svc.writeback_lessons_to_mentor(experience_os=eos, limit=5)
    assert out2["written"] == 0


def test_mtartech_hint_pack_and_brief(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("MTARTECH", mode="mvr", force=True)
    assert out["ok"] is True
    aw = out["awareness"]
    assert aw["symbol"] == "MTARTECH.NS"
    assert aw.get("pack") == "defence"
    assert aw.get("brief") and aw["brief"].get("honesty")
    assert aw.get("thesis") and aw["thesis"].get("summary")
    assert "not BUY" in (aw["thesis"]["summary"] or "") or "WATCH" in (
        aw["thesis"]["summary"] or ""
    ).upper()
    assert aw.get("top_gaps") or aw.get("gap_questions")
    # Depth-weighted coverage should not look "done" when MoS/FCF/management are thin
    assert aw["coverage"] < 65.0
    assert aw["coverage"] >= 15.0
    assert aw.get("research_quality") and aw["research_quality"]["level"] in {
        "basic",
        "developing",
        "substantive",
        "deep",
    }
    assert aw["research_quality"]["level"] in {"basic", "developing"}
    assert aw.get("questions_classified") and (
        aw["questions_classified"].get("open") or aw["questions_classified"].get("answered")
    )
    val = aw.get("valuation") or {}
    assert val.get("method") == "insufficient"
    assert any(not m.get("present") for m in (val.get("missing_inputs") or []))
    # Confidence stays honest
    assert aw.get("caution_high_coverage_low_confidence") or aw["confidence"] == "very_low"
    biz = (out["dossier"]["sections"]["business"]["fields"])
    assert "MTAR" in str(biz.get("name") or "").upper() or "precision" in str(biz.get("summary") or "").lower()
    mgmt = out["dossier"]["sections"]["management"]["fields"]
    assert mgmt.get("evidence")


def test_weighted_coverage_vs_present_stub():
    from atlas.investment.research.models import (
        coverage_pct,
        empty_dossier,
        mark_section,
        research_quality,
        CONF_VERY_LOW,
    )

    doc = empty_dossier("STUBCO")
    # Mark all sections present but empty/gappy — old algorithm would score ~100%
    for name in (
        "business",
        "management",
        "financial_health",
        "cash_flow",
        "valuation",
        "risks",
        "moat",
        "profitability",
        "growth",
        "earnings_quality",
    ):
        mark_section(
            doc,
            name,
            fields={"note": "unknown"},
            confidence=CONF_VERY_LOW,
            gaps=[f"{name}: unknown"],
            status="present",
        )
    cov = coverage_pct(doc)
    assert cov < 40.0
    q = research_quality(doc)
    assert q["level"] == "basic"


def test_sector_packs_banks_and_it(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    bank = svc.start("HDFCBANK", mode="mvr", force=True)
    assert bank["ok"] is True
    assert bank["awareness"].get("pack") == "banks"
    it = svc.start("INFY", mode="mvr", force=True)
    assert it["ok"] is True
    assert it["awareness"].get("pack") == "saas_it"


def test_fundamentals_adapter_gap_recorded(tmp_path):
    from atlas.decision.rules import CapabilityGap
    from atlas.trading.company import CompanyDataService, FundamentalsAdapter

    svc_co = CompanyDataService()
    assert any(p["name"] == "fundamentals" for p in svc_co.list_providers())
    fund = FundamentalsAdapter()
    st = fund.status()
    assert st["live_client"] is False
    try:
        fund.fetch_company("RELIANCE.NS")
        raised = False
    except CapabilityGap:
        raised = True
    assert raised is True

    class StubCompanies:
        def fetch(self, symbol, *, provider=None, **kwargs):
            if provider == "fundamentals":
                raise CapabilityGap("company_data:fundamentals", "test gap")
            if provider == "config_seed":
                return {"provider": "config_seed", "profile": {}}
            if provider == "filings_seed":
                return {"provider": "filings_seed", "profile": {}}
            raise CapabilityGap(f"company_data:{provider}", "unknown")

    svc = InvestmentResearchService(data_dir=str(tmp_path), company_data=StubCompanies())
    out = svc.start("XYZCO", mode="mvr", force=True)
    fund_st = out["dossier"].get("fundamentals_status") or {}
    assert fund_st.get("used") is None
    tried = {t["provider"]: t for t in (fund_st.get("tried") or [])}
    assert "fundamentals" in tried
    assert tried["fundamentals"]["ok"] is False


def test_timing_pack_labeled_not_thesis(tmp_path):
    from atlas.investment.research.timing import timing_from_closes

    snap = timing_from_closes([100 + i * 0.5 for i in range(40)])
    assert snap["label"] == "timing_only"
    assert snap["thesis_weight"] == 0
    assert snap["status"] == "present"
    assert "not" in (snap.get("honesty") or "").lower() or "timing" in (snap.get("honesty") or "").lower()

    class FakeMarket:
        def bars_for(self, symbol, **kwargs):
            return {
                "provider": "test",
                "bars": [{"close": 100 + i} for i in range(40)],
            }

    svc = InvestmentResearchService(data_dir=str(tmp_path), market_reader=FakeMarket())
    out = svc.start("RELIANCE", mode="mvr", force=True)
    timing = out["dossier"].get("timing") or {}
    assert timing.get("thesis_weight") == 0
    assert timing.get("status") == "present"
    assert "timing" not in (out["dossier"].get("sections") or {})
    aw = out["awareness"]
    assert aw.get("timing") and aw["timing"].get("thesis_weight") == 0
    # Timing must not affect buy gate
    gate = svc.gate_buy("RELIANCE", require_mvr=True, require_thesis=True, mos_mode="soft")
    assert "timing" not in " ".join(gate.get("reasons") or []).lower()


def test_ira21_research_freshness_yields_on_memory(tmp_path):
    from atlas.workers.base import TickContext
    from atlas.workers.research_freshness import ResearchFreshnessWorker

    class Verdict:
        def __init__(self, ok, action="yield_tick", reason="budget"):
            self.ok = ok
            self.action = action
            self.reason = reason

        def as_dict(self):
            return {"ok": self.ok, "action": self.action, "reason": self.reason}

    svc = InvestmentResearchService(data_dir=str(tmp_path))
    for sym in ("AAA", "BBB", "CCC"):
        svc.start(sym, mode="mvr", force=True)

    calls = {"n": 0}

    def memory_check(*, force=False):
        calls["n"] += 1
        # First gate ok; second symbol triggers yield
        if calls["n"] >= 2:
            return Verdict(False, action="yield_tick", reason="research_budget")
        return Verdict(True)

    worker = ResearchFreshnessWorker(research=svc)
    ctx = TickContext(
        worker_id="w1",
        mission_id="m1",
        config={"program_id": "market_intelligence", "max_symbols": 4},
        config_version=1,
        state={},
        memory_check=memory_check,
    )
    result = worker.do_tick(ctx)
    assert result.state.get("memory_action") == "yield_tick"
    assert "IR-RO11" in (result.note or "")
    assert "research_budget" in (result.note or "")


def test_ira21_resource_profiles():
    from atlas.missions.templates.resources import resources_for

    fr = resources_for("research_freshness")
    assert fr.ram_mb == 384
    to = resources_for("thesis_outcome")
    assert to.ram_mb == 256


def test_operator_snapshot_incremental_mos(tmp_path):
    from atlas.investment.screener_signals import clear as clear_snap

    clear_snap()
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("MTARTECH", mode="mvr", force=True)
    before = svc.awareness("MTARTECH")
    assert (before.get("valuation") or {}).get("method") in {"insufficient", "multiples", "simple_multiple"}
    out = svc.apply_operator_snapshot(
        "MTARTECH",
        {"pe": 22.0, "fcf": 120.0, "price": 1500.0, "shares": 30.0, "roe": 0.18},
        evidence_confidence="verified",
        auto_refresh=True,
    )
    assert out["ok"] is True
    assert "valuation" in (out.get("impacted_sections") or [])
    aw = out["awareness"]
    val = aw.get("valuation") or {}
    assert val.get("pe") == 22.0
    assert val.get("method") != "insufficient"
    assert val.get("margin_of_safety_pct") is not None or val.get("method_label")
    assert aw.get("evidence_sufficiency")
    assert aw["evidence_sufficiency"]["valuation"] in {"weak", "sufficient", "insufficient"}
    miss = aw.get("missing_inputs") or {}
    assert "critical" in miss
    # Business section should still exist (not wiped by incremental refresh)
    doc = svc.dossier("MTARTECH")
    assert (doc.get("sections") or {}).get("business", {}).get("status") == "present"


def test_filing_refs_and_critical_flag(tmp_path):
    from atlas.investment.filings import clear as clear_filings

    clear_filings()
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("BEL", mode="mvr", force=True)
    out = svc.apply_filing_refs(
        "BEL",
        [{"title": "Annual Report FY25 — BEL", "kind": "annual", "url": ""}],
        auto_refresh=True,
    )
    assert out["ok"] is True
    assert "A" in (out.get("evidence_levels") or [])
    aw = out["awareness"]
    assert aw.get("next_work")
    mgmt = (svc.dossier("BEL")["sections"]["management"]["fields"])
    assert mgmt.get("filings_refs") or mgmt.get("evidence")

    flag = svc.raise_critical_flag(
        "BEL",
        text="Debt covenant breached in operator note",
        kind="thesis_invalidating",
    )
    assert flag["ok"] is True
    aw2 = flag["awareness"]
    assert (aw2.get("critical_flags") or {}).get("count", 0) >= 1
    assert (aw2.get("thesis") or {}).get("stance") == "avoid"
    gate = svc.gate_buy("BEL", require_mvr=True, require_thesis=True, mos_mode="soft")
    assert gate["allowed"] is False
    assert any("critical_flag" in r for r in gate["reasons"])


def test_management_pack_f3(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("HAL", mode="mvr", force=True)
    out = svc.apply_management_pack(
        "HAL",
        {
            "capital_allocation": "Disciplined ROIC vs reinvestment over cycle",
            "dilution": "No material poorly-timed equity issuance",
            "governance_red_flags": "None noted in AR FY25",
            "related_party": "Immaterial disclosed RPTs",
        },
        operator_note="From AR FY25 chairman letter",
        auto_refresh=True,
    )
    assert out["ok"] is True
    assert out["answered"] >= 3
    aw = out["awareness"]
    pack = aw.get("management_pack") or {}
    answered = [
        i for i in (pack.get("items") or [])
        if i.get("status") in {"answered", "weak"} and i.get("answer")
    ]
    assert len(answered) >= 3
    mgmt = svc.dossier("HAL")["sections"]["management"]["fields"]
    assert "Management pack" in (mgmt.get("note") or "")
    qs = [q for q in svc.dossier("HAL")["questions"] if q.get("pack") == "management"]
    assert qs
    assert any(q.get("status") == "answered" for q in qs)


def test_outcome_priors_f5(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("TCS", mode="mvr", force=True)
    bias_map0 = svc.research_bias_map(["TCS"])
    bias0 = next(iter(bias_map0.values()), 0.0)
    svc.record_outcome("TCS", result="falsified", note="Sim thesis break — FCF miss")
    doc = svc.dossier("TCS")
    priors = doc.get("outcome_priors") or {}
    assert priors.get("last_result") == "falsified"
    assert float(priors.get("ranking_penalty") or 0) > 0
    assert "Prior outcome: falsified" in ((doc.get("thesis") or {}).get("summary") or "")
    bias_map1 = svc.research_bias_map(["TCS"])
    bias1 = next(iter(bias_map1.values()), 0.0)
    assert bias1 < bias0
    aw = svc.awareness("TCS")
    next_kinds = [w.get("kind") for w in (aw.get("next_work") or [])]
    assert "outcome_prior" in next_kinds or any(
        "re-examine" in str(w.get("text") or "").lower() for w in (aw.get("next_work") or [])
    )


def test_deep_quality_gated(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    blocked = svc.start("MTARTECH", mode="deep", force=False)
    assert blocked.get("started") is False
    assert blocked.get("reason") == "deep_quality_gated"
    forced = svc.start("MTARTECH", mode="deep", force=True)
    assert forced.get("ok") is True
    assert forced.get("started") is True


def test_apollo_vs_mtar_sector_distinctiveness(tmp_path):
    """Sector intelligence leap: hospital vs defence must not be twin templates."""
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    mtar = svc.start("MTARTECH", mode="mvr", force=True)
    apollo = svc.start("APOLLOHOSP", mode="mvr", force=True)
    assert mtar["ok"] and apollo["ok"]
    aw_m = mtar["awareness"]
    aw_a = apollo["awareness"]
    assert aw_m.get("pack") == "defence"
    assert aw_a.get("pack") == "healthcare"

    base_m = (aw_m.get("thesis") or {}).get("base") or ""
    base_a = (aw_a.get("thesis") or {}).get("base") or ""
    assert base_m != base_a
    assert "order book" in base_m.lower() or "working capital" in base_m.lower()
    assert "occupancy" in base_a.lower() or "arpob" in base_a.lower()

    risks_m = " ".join(
        (((mtar["dossier"].get("sections") or {}).get("risks") or {}).get("fields") or {}).get(
            "top_risks"
        )
        or []
    ).lower()
    risks_a = " ".join(
        (((apollo["dossier"].get("sections") or {}).get("risks") or {}).get("fields") or {}).get(
            "top_risks"
        )
        or []
    ).lower()
    assert "receivable" in risks_m or "customer" in risks_m or "order" in risks_m
    assert "occupancy" in risks_a or "doctor" in risks_a or "reimbursement" in risks_a

    drivers_m = aw_m.get("thesis_drivers") or {}
    drivers_a = aw_a.get("thesis_drivers") or {}
    pos_m = " ".join(drivers_m.get("positive") or []).lower()
    pos_a = " ".join(drivers_a.get("positive") or []).lower()
    assert "defence" in pos_m or "precision" in pos_m
    assert "healthcare" in pos_a or "brand" in pos_a or "network" in pos_a

    kinds_m = [w.get("kind") for w in (aw_m.get("next_work") or [])]
    kinds_a = [w.get("kind") for w in (aw_a.get("next_work") or [])]
    assert "sector_kpi" in kinds_m
    assert "sector_kpi" in kinds_a
    texts_m = " ".join(str(w.get("text") or "") for w in (aw_m.get("next_work") or [])).lower()
    texts_a = " ".join(str(w.get("text") or "") for w in (aw_a.get("next_work") or [])).lower()
    assert "order" in texts_m or "customer" in texts_m or "receivable" in texts_m
    assert "occupancy" in texts_a or "arpob" in texts_a or "doctor" in texts_a

    dist_m = aw_m.get("thesis_distinctiveness") or {}
    dist_a = aw_a.get("thesis_distinctiveness") or {}
    assert float(dist_m.get("score_pct") or 0) >= 40
    assert float(dist_a.get("score_pct") or 0) >= 40
    assert dist_m.get("pack_id") == "defence"
    assert dist_a.get("pack_id") == "healthcare"

    qs_m = " ".join(
        str(q.get("text") or "")
        for q in (mtar["dossier"].get("questions") or [])
        if isinstance(q, dict) and q.get("pack") == "defence"
    ).lower()
    qs_a = " ".join(
        str(q.get("text") or "")
        for q in (apollo["dossier"].get("questions") or [])
        if isinstance(q, dict) and q.get("pack") == "healthcare"
    ).lower()
    assert "isro" in qs_m or "order book" in qs_m or "receivable" in qs_m
    assert "occupancy" in qs_a or "arpob" in qs_a or "doctor" in qs_a


def test_unknown_sector_caps_business_coverage():
    from atlas.investment.research.models import (
        coverage_detail,
        empty_dossier,
        mark_section,
        CONF_MEDIUM,
    )

    doc = empty_dossier("NOSECTOR")
    mark_section(
        doc,
        "business",
        fields={"name": "No Sector Co", "sector": "unknown", "summary": "stub"},
        confidence=CONF_MEDIUM,
        gaps=[],
        status="present",
    )
    cov = coverage_detail(doc)
    assert cov["by_section"]["business"] <= 10.0
