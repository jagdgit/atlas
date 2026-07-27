"""IIP.4 company documents — extract + IRA attach."""

from __future__ import annotations

from atlas.investment.company_documents import (
    extract_company_claims,
    import_drop_folder,
    ingest_path,
    normalize_kind,
    parse_drop_filename,
)
from atlas.investment.research.evidence import level_for_filing
from atlas.investment.research.service import InvestmentResearchService


def test_parse_filename_and_kinds():
    meta = parse_drop_filename("INFY__annual__FY25.pdf")
    assert meta["symbol"] == "INFY.NS"
    assert meta["kind"] == "annual"
    assert meta["period"] == "FY25"
    assert normalize_kind("deck") == "deck"
    assert level_for_filing("deck") == "C"
    assert level_for_filing("transcript") == "D"
    assert level_for_filing("annual") == "A"


def test_extract_claims_guidance_risk_kpi():
    text = (
        "Management guidance: we expect mid-teens revenue growth next year. "
        "Key risks include commodity price volatility and execution delays. "
        "ROCE 22%. Debt to equity 0.15. Operating margin 18%."
    )
    claims = extract_company_claims(text)
    kinds = {c["kind"] for c in claims}
    assert "guidance" in kinds
    assert "risk" in kinds
    assert "kpi" in kinds
    fields = {c.get("field") for c in claims if c.get("field")}
    assert "roce" in fields
    assert "debt_to_equity" in fields


def test_ingest_text_and_ira_lift(tmp_path):
    text = (
        "Investor presentation. Outlook: we expect double-digit sales growth. "
        "Risk factors include regulatory change. ROE 25%. Free cash flow 1200. "
        "Promoter holding 40%."
    )
    result = ingest_path(
        tmp_path,
        "",
        symbol="INFY",
        kind="presentation",
        text_override=text,
        note="test",
    )
    assert result["ok"]
    assert result["claims_count"] >= 2
    assert result["path"]

    svc = InvestmentResearchService(data_dir=str(tmp_path))
    before = svc.awareness("INFY.NS")
    out = svc.apply_company_document(
        "INFY",
        kind="presentation",
        text=text,
        auto_refresh=True,
        apply_numeric_fields=True,
    )
    assert out["ok"]
    assert out["claims_count"] >= 2
    assert out["evidence_level"] == "C"
    doc = svc.get_or_create("INFY.NS")
    sections = doc.get("sections") or {}
    has_ev = False
    for name in (
        "management",
        "growth",
        "risks",
        "financial_health",
        "cash_flow",
        "profitability",
    ):
        sec = sections.get(name) or {}
        fields = (sec.get("fields") or {}) if isinstance(sec, dict) else {}
        ev = fields.get("evidence") or []
        if isinstance(ev, list) and any(
            isinstance(e, dict) and e.get("source") == "company_document" for e in ev
        ):
            has_ev = True
            break
    assert has_ev
    assert out["lifted"] or out["coverage_after"] >= float(before.get("coverage") or 0)


def test_drop_folder(tmp_path):
    drop = tmp_path / "imports" / "company_documents"
    drop.mkdir(parents=True)
    (drop / "BEL__annual__FY25.txt").write_text(
        "Guidance: we expect capacity expansion. Key risks include input costs. ROCE 20%.",
        encoding="utf-8",
    )
    out = import_drop_folder(tmp_path)
    assert out["imported"] >= 1
    assert (drop / "done" / "BEL__annual__FY25.txt").is_file()
