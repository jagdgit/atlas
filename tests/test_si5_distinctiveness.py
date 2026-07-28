"""SI.5 — distinctiveness block on awareness (RC5)."""

from __future__ import annotations

from atlas.investment.research import business_identity as bi
from atlas.investment.research import distinctiveness as dist
from atlas.investment.research import sector_packs as packs
from atlas.investment.research import InvestmentResearchService


def test_defence_pack_builds_rc5_fields():
    pack = packs.pack_by_id("defence")
    ident = bi.resolve_identity("MTARTECH")
    block = dist.build_distinctiveness(
        symbol="MTARTECH",
        identity=ident,
        pack=pack,
        company_name="MTAR Technologies",
    )
    assert block["version"] == "si.5"
    assert block["status"] in {dist.STATUS_RESOLVED, dist.STATUS_WEAK}
    assert block["reason_to_exist"]
    assert not block["reason_to_exist"].startswith("unknown")
    assert block["position"]
    assert block["value_drivers"]
    assert block["falsifiers"]
    blob = " ".join(block["falsifiers"]).lower()
    assert "order" in blob or "receivable" in blob or "execution" in blob


def test_unknown_identity_explicit_gaps():
    block = dist.build_distinctiveness(
        symbol="XYZUNKNOWN",
        identity=bi.empty_identity("XYZUNKNOWN"),
        pack=packs.pack_by_id("generic"),
    )
    assert block["status"] == dist.STATUS_UNKNOWN
    assert "reason_to_exist" in block["gaps"]
    assert block["reason_to_exist"].startswith("unknown")
    assert block["generic"] is True


def test_mvr_stamps_distinctiveness(tmp_path):
    svc = InvestmentResearchService(data_dir=str(tmp_path))
    out = svc.start("APOLLOHOSP", mode="mvr", force=True)
    assert out["ok"] is True
    d = out["dossier"].get("distinctiveness") or {}
    assert d.get("version") == "si.5"
    assert d.get("reason_to_exist")
    assert d.get("position")
    thesis_d = (out["dossier"].get("thesis") or {}).get("distinctiveness") or {}
    assert thesis_d.get("version") == "si.5"
    aw = svc.awareness("APOLLOHOSP")
    assert (aw.get("distinctiveness") or {}).get("version") == "si.5"
    # Present before valuation use — awareness carries both
    assert aw.get("valuation") is not None
    assert aw["distinctiveness"]["reason_to_exist"]


def test_hospital_vs_defence_differ():
    hosp = dist.build_distinctiveness(
        symbol="APOLLOHOSP",
        identity=bi.resolve_identity("APOLLOHOSP"),
        pack=packs.pack_by_id("healthcare"),
    )
    defn = dist.build_distinctiveness(
        symbol="MTARTECH",
        identity=bi.resolve_identity("MTARTECH"),
        pack=packs.pack_by_id("defence"),
    )
    assert hosp["reason_to_exist"] != defn["reason_to_exist"]
    assert set(hosp["falsifiers"]) != set(defn["falsifiers"])
