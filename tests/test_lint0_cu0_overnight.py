"""OI-CU0 CU.C / CU.E — overnight densify + research ROI gate."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from atlas.investment.overnight_densify import (
    VERSION,
    format_overnight_morning_lines,
    resolve_overnight_symbol_set,
    run_overnight_densify,
)
from atlas.investment.research_intelligence import research_roi_gate

_IST = ZoneInfo("Asia/Kolkata")

_FAKE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test</title>
<item><title>PIB: CIPLA related policy note for markets</title>
<link>https://www.pib.gov.in/x</link>
<pubDate>Wed, 20 Aug 2026 12:00:00 GMT</pubDate>
</item>
</channel></rss>
"""


def test_research_roi_gate():
    assert research_roi_gate("fcf", symbol="CIPLA.NS", is_open=True)["admit"] is True
    assert research_roi_gate("news", symbol="CIPLA.NS", is_open=True)["admit"] is True
    defer = research_roi_gate("random_color", symbol="ZZ.NS", is_open=False)
    assert defer["admit"] is False
    assert defer["reason"] == "no_allocation_roi"
    block = research_roi_gate(
        "fcf",
        symbol="CIPLA.NS",
        is_open=False,
        allocation_blockers=[{"symbol": "CIPLA.NS", "unknown": "fcf"}],
    )
    assert block["admit"] is True
    assert block["priority"] == "high"


def test_symbol_set_open_plus_blockers(tmp_path):
    from atlas.investment.capital_allocation import persist_allocation_table

    table = {
        "laboratory_id": "india_equity_learner",
        "as_of_ist": "2026-08-20",
        "rows": [
            {
                "symbol": "CIPLA.NS",
                "role": "holding",
                "er_completeness": 0.3,
                "missing_er": True,
                "missing_terms": ["fcf"],
            }
        ],
    }
    persist_allocation_table(tmp_path, table)
    doc = resolve_overnight_symbol_set(
        tmp_path,
        open_symbols=["EICHERMOT.NS"],
        as_of_ist="2026-08-20",
    )
    assert "EICHERMOT.NS" in doc["symbols"]
    assert "CIPLA.NS" in doc["symbols"]
    assert doc["blockers"]


def test_overnight_run_with_fake_rss(tmp_path):
    night = datetime(2026, 8, 20, 22, 0, tzinfo=_IST)

    def opener(_url: str) -> str:
        return _FAKE_RSS

    doc = run_overnight_densify(
        tmp_path,
        as_of_ist="2026-08-20",
        now=night,
        open_symbols=["CIPLA.NS"],
        opener=opener,
        force=True,
    )
    assert doc["version"] == VERSION
    assert doc.get("skipped") is False
    assert doc["intake"]["attempted"] is True
    assert (tmp_path / "investment" / "overnight" / "2026-08-20.json").is_file()

    lines = format_overnight_morning_lines(doc)
    text = "\n".join(lines)
    assert "Overnight densify" in text
    assert "status=" in text


def test_outside_window_skips(tmp_path):
    day = datetime(2026, 8, 20, 11, 0, tzinfo=_IST)
    doc = run_overnight_densify(tmp_path, now=day, force=False)
    assert doc.get("skipped") is True
    assert doc.get("reason") == "outside_overnight_window"
