"""SI.2 — sector pack YAML loader + India seed packs."""

from __future__ import annotations

from atlas.investment.research import sector_packs as packs
from atlas.investment.research.pack_loader import load_pack_files, clear_pack_cache


def test_yaml_packs_loaded():
    clear_pack_cache()
    all_p = packs.all_packs()
    for pid in (
        "defence",
        "healthcare",
        "manufacturing",
        "saas_it",
        "banks",
        "consumer",
        "pharma",
        "energy_utilities",
        "generic",
    ):
        assert pid in all_p, pid
        row = all_p[pid]
        assert row.get("id") == pid
        assert row.get("primary_kpis"), pid
        assert row.get("extra_questions"), pid


def test_pharma_not_healthcare():
    ph = packs.pack_for("SUNPHARMA", sector="Pharmaceuticals")
    assert ph is not None
    assert ph["id"] == "pharma"
    hosp = packs.pack_for("APOLLOHOSP", sector="Healthcare")
    assert hosp is not None
    assert hosp["id"] == "healthcare"


def test_consumer_and_energy():
    c = packs.pack_for("ITC", sector="Consumer Staples")
    assert c and c["id"] == "consumer"
    e = packs.pack_for("RELIANCE", sector="Oil Gas & Fuels")
    assert e and e["id"] == "energy_utilities"


def test_generic_fallback_opt_in():
    assert packs.pack_for("XYZUNKNOWN") is None
    g = packs.pack_for("XYZUNKNOWN", allow_generic=True)
    assert g and g["id"] == "generic"
    assert g.get("weak") is True


def test_overlay_data_dir(tmp_path):
    clear_pack_cache()
    overlay = tmp_path / "investment" / "sector_packs"
    overlay.mkdir(parents=True)
    (overlay / "consumer.yaml").write_text(
        "id: consumer\nlabel: Operator consumer overlay\nprimary_kpis: [Custom KPI]\n",
        encoding="utf-8",
    )
    merged = load_pack_files(data_dir=tmp_path, builtins=packs.BUILTIN_PACKS)
    assert merged["consumer"]["label"] == "Operator consumer overlay"
    assert "Custom KPI" in (merged["consumer"].get("primary_kpis") or [])
