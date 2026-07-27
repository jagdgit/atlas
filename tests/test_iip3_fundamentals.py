"""IIP.3 fundamentals import — normalize, CSV, store, screener merge."""

from __future__ import annotations

from atlas.investment.fundamentals import (
    as_quality_map,
    fundamentals_view,
    import_csv_text,
    import_drop_folder,
    import_json_payload,
    normalize_row,
    normalize_symbol,
)


def test_normalize_symbol_and_row():
    assert normalize_symbol("infy") == "INFY.NS"
    assert normalize_symbol("RELIANCE.NS") == "RELIANCE.NS"
    row = normalize_row(
        {
            "NSE Code": "INFY",
            "ROE": "28",
            "Return on Capital Employed": "0.32",
            "Debt to equity": "0.12",
            "Operating margin": "24%",
            "Promoter holding": "15",
        }
    )
    assert row is not None
    assert row["symbol"] == "INFY.NS"
    assert row["roe"] == 28.0
    assert row["roce"] == 32.0  # fraction → percent
    assert row["roic"] == 32.0  # mirrored from roce
    assert row["debt_to_equity"] == 0.12
    assert "roe" in row["fields_present"]
    assert row["evidence_sufficiency"] in {"weak", "sufficient"}
    assert "financial_health" in row["strengthens_sections"]


def test_csv_import_and_view(tmp_path):
    csv = (
        "symbol,roe,roce,debt_to_equity,pe,operating_margin,promoter_holding\n"
        "TCS,25,30,0.05,28,22,72\n"
        "INFY,28,32,0.1,25,24,15\n"
    )
    result = import_csv_text(tmp_path, csv, note="test")
    assert result["imported"] == 2
    assert result["store_count"] == 2
    assert result["screener"]["merged"] is True
    view = fundamentals_view(tmp_path, limit=10)
    assert view["count"] == 2
    assert view["drop_dir"]
    syms = {r["symbol"] for r in view["rows"]}
    assert "TCS.NS" in syms and "INFY.NS" in syms
    q = as_quality_map(tmp_path)
    assert abs(float(q["INFY.NS"]["roe"]) - 0.28) < 1e-9  # fraction for ranking


def test_json_and_drop_folder(tmp_path):
    result = import_json_payload(
        tmp_path,
        [{"symbol": "BEL", "roe": 20, "roce": 22, "debt_to_equity": 0.0, "pe": 40, "fcf": 100}],
    )
    assert result["imported"] == 1
    drop = tmp_path / "imports" / "fundamentals"
    drop.mkdir(parents=True)
    (drop / "batch.csv").write_text(
        "symbol,roe,roce,debt_to_equity\nHAL,18,20,0.2\n",
        encoding="utf-8",
    )
    out = import_drop_folder(tmp_path)
    assert out["imported"] >= 1
    assert (drop / "done" / "batch.csv").is_file()
    view = fundamentals_view(tmp_path)
    assert view["count"] >= 2
