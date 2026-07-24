"""World Models framework + packs (WM.1)."""

from __future__ import annotations

from atlas.missions.programs import ProgramService
from atlas.world_models import default_world_model_registry
from atlas.world_models.framework import WorldFact, WorldModelRegistry
from atlas.world_models.packs.indian_markets import indian_markets_pack
from atlas.world_models.packs.solar_plant import solar_plant_pack


def test_indian_markets_pack_structure():
    pack = indian_markets_pack()
    assert pack.id == "indian_markets"
    kinds = {f.kind for f in pack.facts()}
    assert "exchange" in kinds
    assert "settlement" in kinds
    assert "sector" in kinds
    nse = next(f for f in pack.facts() if f.id == "ex.nse")
    assert nse.attributes["currency"] == "INR"


def test_solar_plant_pack_proves_framework():
    """Solar-plant test: same framework loads non-market structure."""
    pack = solar_plant_pack()
    assert pack.program_hint == "solar"
    assert any(f.kind == "control" for f in pack.facts())
    reg = WorldModelRegistry()
    reg.register(pack)
    facts = reg.facts(q="mppt")
    assert facts and "MPPT" in facts[0]["label"]


def test_default_registry_both_packs():
    reg = default_world_model_registry()
    ids = {p["id"] for p in reg.list_packs()}
    assert ids == {"indian_markets", "solar_plant"}
    assert reg.VERSION == "wm.1"


def test_context_for_market_topic():
    reg = default_world_model_registry()
    rows = reg.context_for("NSE settlement", program_id="market", limit=5)
    assert rows
    assert all(r.get("item_kind") == "world_fact" for r in rows)


def test_program_context_includes_world_facts():
    reg = default_world_model_registry()
    svc = ProgramService(world_models=reg)
    out = svc.context("T+1 settlement", program_id="market", limit=10)
    assert out["spike"] is False
    assert any(i.get("item_kind") == "world_fact" for i in out["items"])
    assert "World Model" in out["note"]


def test_world_fact_matches():
    fact = WorldFact(
        id="ex.nse",
        kind="exchange",
        label="NSE",
        attributes={"country": "IN"},
        tags=("india",),
    )
    assert fact.matches("nse")
    assert fact.matches("india")
    assert not fact.matches("mppt")
