"""DAV densify — RS vs NIFTY into what_changed + FCF enrich priority / cashflow derive."""

from __future__ import annotations

from atlas.investment.decision_timeline import what_changed
from atlas.investment.fundamentals import enrich_watchlist_gaps, import_csv_text
from atlas.investment.yahoo_fundamentals import parse_quote_summary
from atlas.investment import watchlists as wl


def test_what_changed_stamps_sector_rel_from_open_book_pack():
    packet = {
        "action": "buy",
        "prices": {"fill_price": 100.0},
        "observation_ids": [],
        "unknowns": [],
    }
    obs = [
        {
            "id": "pack-1",
            "kind": "market_event",
            "payload": {
                "kind": "open_book_daily_pack",
                "market": {"rs_vs_nifty": 3.5, "return_pct": 5.0},
                "thesis": {"status": "unchanged"},
            },
        }
    ]
    diff = what_changed(
        packet,
        current_mark=108.0,
        recent_observations=obs,
        checkpoint="week1",
    )
    assert diff["rs_vs_nifty"] == 3.5
    assert diff["sector_rel_pct"] == 3.5
    assert diff["sector_rel_source"] == "open_book_rs_vs_nifty"
    assert any("rs_vs_nifty" in d for d in (diff.get("deltas") or []))


def test_fcf_derived_from_cashflow_statement():
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "defaultKeyStatistics": {"trailingPE": {"raw": 20.0}},
                    "financialData": {
                        # freeCashflow absent on purpose
                        "returnOnEquity": {"raw": 0.18},
                        "debtToEquity": {"raw": 40.0},
                        "currentPrice": {"raw": 100.0},
                    },
                    "summaryDetail": {},
                    "price": {"regularMarketPrice": {"raw": 100.0}},
                    "cashflowStatementHistory": {
                        "cashflowStatements": [
                            {
                                "totalCashFromOperatingActivities": {"raw": 5_000_000_000},
                                "capitalExpenditures": {"raw": -1_500_000_000},
                            }
                        ]
                    },
                }
            ]
        }
    }
    parsed = parse_quote_summary(payload, symbol="GAPCO.NS")
    assert parsed["fields"]["pe"] == 20.0
    assert parsed["fields"]["fcf"] == 3_500_000_000
    fcf_ev = next(e for e in parsed["evidence"] if e.get("field") == "fcf")
    assert fcf_ev["raw_ref"]["module"] == "cashflowStatementHistory"


def test_enrich_prioritizes_fcf_gaps_and_open_books(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHLIST_DIR", str(tmp_path / "wl"))
    wl.clear(disk=True)
    wl.publish(
        program_id="market_intelligence",
        index="TEST",
        watchlist=[
            {"symbol": "HASPE.NS"},
            {"symbol": "NEEDFCF.NS"},
            {"symbol": "OPENFCF.NS"},
        ],
        ranked=[
            {"symbol": "HASPE.NS", "rank": 1},
            {"symbol": "NEEDFCF.NS", "rank": 2},
            {"symbol": "OPENFCF.NS", "rank": 3},
        ],
    )
    # HASPE: pe only (missing fcf/roe/de) — lower priority than pure open-book fcf
    import_csv_text(
        tmp_path,
        "symbol,pe,fcf,roe,debt_to_equity\n"
        "HASPE,18,,, \n"
        "NEEDFCF,,,,\n",
        source="screener_export",
        note="partial",
    )

    seen: list[str] = []

    def opener(url: str):
        u = url.upper()
        for sym in ("OPENFCF", "NEEDFCF", "HASPE"):
            if sym in u:
                seen.append(f"{sym}.NS")
                break
        return {
            "quoteSummary": {
                "result": [
                    {
                        "defaultKeyStatistics": {"trailingPE": {"raw": 15.0}},
                        "financialData": {
                            "freeCashflow": {"raw": 1e8},
                            "returnOnEquity": {"raw": 0.2},
                            "debtToEquity": {"raw": 25.0},
                            "currentPrice": {"raw": 50.0},
                        },
                        "summaryDetail": {},
                        "price": {"regularMarketPrice": {"raw": 50.0}},
                    }
                ]
            }
        }

    out = enrich_watchlist_gaps(
        tmp_path,
        program_id="market_intelligence",
        enabled=True,
        opener=opener,
        limit=40,
        batch_size=1,
        priority_symbols=["OPENFCF.NS"],
    )
    gaps = out.get("gap_symbols") or []
    assert gaps[0] == "OPENFCF.NS"
    assert out["fetched"] >= 1
    assert seen and seen[0] == "OPENFCF.NS"
