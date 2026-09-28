"""Screener company xlsx → fundamentals row."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from atlas.investment.screener_xlsx import parse_screener_company_xlsx


def _write_mini_workbook(path: Path) -> None:
    wb = Workbook()
    # openpyxl creates a default sheet
    default = wb.active
    wb.remove(default)
    ws = wb.create_sheet("Data Sheet")
    rows = [
        ["COMPANY NAME", "WELSPUN CORP LTD"],
        ["Current Price", 2640.0],
        ["Market Capitalization", 69640.69],
        ["PROFIT & LOSS"],
        ["Net profit", 100.0, 1613.05],
        ["BALANCE SHEET"],
        ["Equity Share Capital", 50.0, 131.9],
        ["Reserves", 100.0, 9023.66],
        ["Borrowings", 10.0, 2355.45],
        ["No. of Equity Shares", 1e8, 263790645.0],
        ["CASH FLOW:"],
        ["Cash from Operating Activity", 1.0, 3204.28],
        ["Cash from Investing Activity", -1.0, -3713.9],
        ["Adjusted Equity Shares in Cr", 10.0, 26.38],
    ]
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_parse_screener_xlsx_derives_pe_leaves_fcf(tmp_path: Path):
    xlsx = tmp_path / "WELCORP.NS.xlsx"
    _write_mini_workbook(xlsx)
    out = parse_screener_company_xlsx(xlsx, symbol="WELCORP.NS")
    assert out["ok"] is True
    row = out["rows"][0]
    assert row["pe"] is not None
    assert 40 < row["pe"] < 50
    assert row["fcf"] is None  # never invent from CFO+CFI
    assert row["roe"] is not None
    assert row["debt_to_equity"] is not None


def test_parse_screener_xlsx_requires_symbol(tmp_path: Path):
    xlsx = tmp_path / "Welspun Corp.xlsx"
    _write_mini_workbook(xlsx)
    out = parse_screener_company_xlsx(xlsx)
    assert out["ok"] is False
    assert out["reason"] == "symbol_required"
