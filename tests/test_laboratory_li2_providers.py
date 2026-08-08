"""LI.2 — evidence tiers, provider conflict, Yahoo enrich (hermetic)."""

from __future__ import annotations

from atlas.investment.decision_packets import compute_unknowns
from atlas.investment.evidence_providers import (
    append_evidence,
    coverage_by_provider,
    make_evidence_value,
    reconcile_field,
)
from atlas.investment.fundamentals import (
    enrich_from_yahoo,
    fundamentals_view,
    get_symbol,
    import_csv_text,
)
from atlas.investment.yahoo_fundamentals import parse_quote_summary


def _fake_quote_summary(*, pe: float = 28.0, fcf: float = 1e9) -> dict:
    return {
        "quoteSummary": {
            "result": [
                {
                    "defaultKeyStatistics": {
                        "trailingPE": {"raw": pe},
                        "sharesOutstanding": {"raw": 1e9},
                    },
                    "financialData": {
                        "freeCashflow": {"raw": fcf},
                        "returnOnEquity": {"raw": 0.22},
                        "debtToEquity": {"raw": 35.0},
                        "operatingMargins": {"raw": 0.18},
                        "profitMargins": {"raw": 0.15},
                        "currentPrice": {"raw": 100.0},
                    },
                    "summaryDetail": {"trailingPE": {"raw": pe}},
                    "price": {"marketCap": {"raw": 2e12}, "regularMarketPrice": {"raw": 100.0}},
                }
            ]
        }
    }


def test_reconcile_prefers_filing_over_yahoo():
    yahoo = make_evidence_value(field="pe", value=28.0, provider="yahoo_fundamentals")
    filing = make_evidence_value(
        field="pe", value=27.3, provider="filing", confidence="very_high", verified=True
    )
    recon = reconcile_field([yahoo, filing])
    assert recon["preferred"]["provider"] == "filing"
    assert recon["value"] == 27.3
    assert recon["conflict"] is False  # ~2.5% gap < 15%


def test_reconcile_flags_large_conflict_no_blend():
    yahoo = make_evidence_value(field="pe", value=28.0, provider="yahoo_fundamentals")
    filing = make_evidence_value(
        field="pe", value=41.0, provider="filing", confidence="very_high", verified=True
    )
    recon = reconcile_field([yahoo, filing])
    assert recon["conflict"] is True
    assert recon["value"] == 41.0  # preferred tier kept — not averaged
    assert "pe_conflict" in recon["unknowns"]
    assert recon["down_weight"] is False  # preferred is filing


def test_yahoo_parse_and_enrich_store(tmp_path):
    parsed = parse_quote_summary(_fake_quote_summary(pe=30.0), symbol="CIPLA")
    assert parsed["fields"]["pe"] == 30.0
    assert parsed["fields"]["fcf"] == 1e9
    assert parsed["evidence"]

    def opener(url: str):
        assert "CIPLA" in url.upper() or "cipla" in url.lower()
        return _fake_quote_summary(pe=30.0, fcf=5e8)

    out = enrich_from_yahoo(
        tmp_path,
        ["CIPLA.NS"],
        enabled=True,
        opener=opener,
        only_gaps=True,
    )
    assert out["fetched"] == 1
    assert out["confidence"] == "medium"
    row = get_symbol(tmp_path, "CIPLA.NS")
    assert row is not None
    assert row["pe"] == 30.0
    assert row.get("evidence", {}).get("pe")
    assert row["evidence"]["pe"][0]["provider"] == "yahoo_fundamentals"
    assert row["evidence"]["pe"][0]["confidence"] == "medium"


def test_screener_outranks_yahoo_on_enrich(tmp_path):
    import_csv_text(
        tmp_path,
        "symbol,pe,fcf,roe\nCIPLA,25,900,22\n",
        source="screener_export",
        note="operator",
    )
    row = get_symbol(tmp_path, "CIPLA.NS")
    assert row["pe"] == 25.0

    def opener(_url: str):
        return _fake_quote_summary(pe=40.0)  # large conflict with screener

    enrich_from_yahoo(
        tmp_path,
        ["CIPLA.NS"],
        enabled=True,
        opener=opener,
        only_gaps=False,
    )
    row2 = get_symbol(tmp_path, "CIPLA.NS")
    # Preferred should remain screener/high after reconcile
    assert row2["pe"] == 25.0
    assert "pe_conflict" in (row2.get("evidence_conflicts") or [])
    unknowns = compute_unknowns(fundamentals=row2)
    assert "pe_conflict" in unknowns


def test_coverage_by_provider_and_view(tmp_path):
    def opener(_url: str):
        return _fake_quote_summary(pe=22.0)

    enrich_from_yahoo(
        tmp_path, ["INFY.NS"], enabled=True, opener=opener, only_gaps=True
    )
    view = fundamentals_view(tmp_path, limit=10)
    assert view["coverage"]["with_pe"] >= 1
    by = view["coverage"].get("by_provider") or {}
    assert (by.get("pe_by_provider") or {}).get("yahoo_fundamentals", 0) >= 1

    cov = coverage_by_provider(
        { "INFY.NS": get_symbol(tmp_path, "INFY.NS") }
    )
    assert cov["pe_by_provider"]["yahoo_fundamentals"] == 1


def test_append_evidence_keeps_history():
    row: dict = {"symbol": "X.NS"}
    row = append_evidence(
        row,
        make_evidence_value(field="pe", value=10, provider="yahoo_fundamentals"),
    )
    row = append_evidence(
        row,
        make_evidence_value(field="pe", value=11, provider="screener_export"),
    )
    assert len(row["evidence"]["pe"]) == 2
    assert row["pe"] == 11


def test_parse_chart_and_html_fallbacks():
    from atlas.investment.yahoo_fundamentals import parse_chart_meta, parse_quote_html

    chart = parse_chart_meta(
        {
            "chart": {
                "result": [
                    {"meta": {"regularMarketPrice": 1334.8, "symbol": "RELIANCE.NS"}}
                ]
            }
        },
        symbol="RELIANCE.NS",
    )
    assert chart["fields"]["price"] == 1334.8
    html = parse_quote_html(
        '<fin-streamer data-field="regularMarketPrice" value="1334.8"></fin-streamer>'
        'trailingPE" class="x">23.18 </fin-streamer>'
        r'forwardPE\":{\"raw\":17.9} returnOnEquity\":{\"raw\":0.11}',
        symbol="RELIANCE.NS",
    )
    assert html["fields"].get("pe") == 23.18
    assert html["fields"].get("price") == 1334.8
    assert html["fields"].get("roe") == 11.0
