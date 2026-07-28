"""SI.1 — Business Identity Engine + MVR gate."""

from __future__ import annotations

from atlas.investment.research import business_identity as bi
from atlas.investment.research import InvestmentResearchService


def test_resolve_hinted_symbols():
    apollo = bi.resolve_identity("APOLLOHOSP")
    assert apollo["status"] == bi.STATUS_RESOLVED
    assert apollo["pack_id"] == "healthcare"
    assert "Hospital" in (apollo.get("business_type") or "") or apollo.get("sector")

    mtar = bi.resolve_identity("MTARTECH")
    assert mtar["status"] == bi.STATUS_RESOLVED
    assert mtar["pack_id"] in {"defence", "manufacturing"}


def test_unknown_symbol_blocks_without_force(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    blocked = svc.start("XYZUNKNOWN", mode="mvr", force=False)
    assert blocked["ok"] is False
    assert blocked["reason"] == "identity_unknown"
    assert blocked["started"] is False
    assert (blocked.get("business_identity") or {}).get("status") == bi.STATUS_UNKNOWN
    assert "identity_unknown" in (blocked["dossier"].get("blocked_on") or [])


def test_force_bypasses_identity_gate(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("XYZUNKNOWN", mode="mvr", force=True)
    assert out["ok"] is True
    assert out["started"] is True


def test_operator_identity_then_mvr(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    set_out = svc.set_identity(
        "NEWCO",
        {
            "business_type": "Hospital chain",
            "sector": "Healthcare",
            "capital_intensity": "capital_heavy",
            "key_drivers": ["occupancy", "ARPOB"],
            "pack_id": "healthcare",
        },
        start_mvr=True,
    )
    assert set_out["ok"] is True
    ident = set_out["business_identity"]
    assert ident["status"] == bi.STATUS_RESOLVED
    assert ident["operator_confirmed"] is True
    assert ident["confidence"]["business_identity"] == bi.CONF_HIGH
    mvr = set_out.get("mvr") or {}
    assert mvr.get("ok") is True
    aw = set_out["awareness"]
    assert aw.get("business_identity", {}).get("pack_id") == "healthcare"


def test_awareness_includes_identity(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    svc.start("APOLLOHOSP", mode="mvr", force=True)
    aw = svc.awareness("APOLLOHOSP")
    ident = aw.get("business_identity") or {}
    assert ident.get("status") == bi.STATUS_RESOLVED
    assert ident.get("pack_id") == "healthcare"


def test_weak_sector_allows_mvr(tmp_path):
    """Universe sector alone → weak identity → gate allows (not unknown)."""
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    # RELIANCE has quality-seed sector but no midcap hint → weak
    out = svc.start("RELIANCE", mode="mvr", force=False)
    assert out.get("reason") != "identity_unknown"
    assert out["ok"] is True
    status = (out["dossier"].get("business_identity") or {}).get("status")
    assert status in {bi.STATUS_RESOLVED, bi.STATUS_WEAK}


def test_identity_gate_helpers():
    unknown = bi.empty_identity("X")
    assert bi.identity_gate(unknown)["ok"] is False
    assert bi.identity_gate(unknown, force=True)["ok"] is True
    resolved = bi.resolve_identity("MTARTECH")
    assert bi.identity_gate(resolved)["ok"] is True
