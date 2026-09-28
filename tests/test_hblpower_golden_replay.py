"""HBLPOWER N1 golden replay fixture — LOCKED.

Future NSE/XBRL changes must keep:
  BEFORE = PLC.A INCOMPLETE (pe, roe, debt_to_equity, sector)
  AFTER  = COMPLETE with the locked calculations + DEBT_DEFINITION
  kind   = CANDIDATE_REPLAY
  not_a_fill = True
  writes_experience = False

Do not turn this replay into a paper fill, reward, or learning experience.
Do not re-engineer HBLPOWER unless this file regresses.
"""

from __future__ import annotations

from pathlib import Path

from atlas.investment.fundamentals import get_symbol
from atlas.investment.nse_xbrl.replay import (
    GOLDEN_AFTER,
    GOLDEN_CANONICAL_SHA256,
    GOLDEN_DEBT_DEFINITION_ID,
    GOLDEN_EVIDENCE_AS_OF,
    GOLDEN_PRICE,
    GOLDEN_PRIOR_SHA256,
    GOLDEN_SYMBOL,
    replay_hblpower_candidate,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nse_xbrl"
CANONICAL_XML = FIXTURE_DIR / "hblpower_replay_canonical.xml"
PRIOR_XML = FIXTURE_DIR / "hblpower_replay_prior.xml"


def _golden_xml() -> list[str]:
    return [
        PRIOR_XML.read_text(encoding="utf-8"),
        CANONICAL_XML.read_text(encoding="utf-8"),
    ]


def _replay(tmp_path: Path):
    return replay_hblpower_candidate(
        tmp_path,
        xml_text=_golden_xml(),
        price=GOLDEN_PRICE,
        evidence_as_of=GOLDEN_EVIDENCE_AS_OF,
    )


def test_golden_xml_hashes_are_locked():
    import hashlib

    assert hashlib.sha256(CANONICAL_XML.read_bytes()).hexdigest() == GOLDEN_CANONICAL_SHA256
    assert hashlib.sha256(PRIOR_XML.read_bytes()).hexdigest() == GOLDEN_PRIOR_SHA256


def test_golden_replay_before_after_semantics(tmp_path: Path):
    result = _replay(tmp_path)
    assert result["kind"] == "CANDIDATE_REPLAY"
    assert result["symbol"] == GOLDEN_SYMBOL
    assert result["not_a_fill"] is True
    assert result["writes_experience"] is False
    assert result["isolated"] is True
    assert result["reevaluated"] is True

    before = result["before"]
    assert before["plc_a"] == "INCOMPLETE"
    assert before["code"] == "fundamentals_incomplete"
    assert before["missing"] == ["pe", "roe", "debt_to_equity", "sector"]
    assert before["pe"] is None
    assert before["roe"] is None
    assert before["debt_to_equity"] is None
    assert before["fcf"] is None
    assert before["sector"] is None
    assert before["identity"] is None
    assert before["source"] is None
    assert before["nse_raw_evidence_id"] is None
    assert before["conflicts"] == []
    assert before["eps_basis"] is None

    after = result["after"]
    assert after["plc_a"] == GOLDEN_AFTER["plc_a"]
    assert after["code"] == GOLDEN_AFTER["code"]
    assert after["missing"] == []
    assert after["pe"] == GOLDEN_AFTER["pe"]
    assert after["roe"] == GOLDEN_AFTER["roe"]
    assert after["debt_to_equity"] == GOLDEN_AFTER["debt_to_equity"]
    assert after["fcf"] == GOLDEN_AFTER["fcf"]
    assert after["sector"] == GOLDEN_AFTER["sector"]
    assert after["identity"] == GOLDEN_AFTER["identity"]
    assert after["source"] == GOLDEN_AFTER["source"]
    assert after["eps_basis"] == GOLDEN_AFTER["eps_basis"]
    assert after["nse_raw_evidence_id"] == GOLDEN_CANONICAL_SHA256

    plc_after = result["plc_a_after"]
    assert plc_after["ok"] is True
    assert plc_after["missing"] == []
    assert plc_after["sector"] == "Capital Goods"

    acquired = set(result["acquire"].get("acquired") or [])
    assert {"pe", "roe", "debt_to_equity", "fcf", "sector", "identity"} <= acquired


def test_golden_replay_preserves_debt_definition_conflict(tmp_path: Path):
    result = _replay(tmp_path)
    assert result["after"]["plc_a"] == "COMPLETE"
    conflicts = result["after"].get("conflicts") or []
    assert any(
        isinstance(c, dict) and c.get("conflict_type") == "DEBT_DEFINITION"
        for c in conflicts
    )
    notes = " ".join(str(c.get("note") or "") for c in conflicts if isinstance(c, dict))
    assert GOLDEN_DEBT_DEFINITION_ID in notes
    row = get_symbol(tmp_path / "investment" / "trade_loop0" / "replay" / "sandbox", "HBLPOWER") or {}
    stored = row.get("evidence_conflicts") or []
    assert any(
        isinstance(c, dict) and c.get("conflict_type") == "DEBT_DEFINITION" for c in stored
    )


def test_golden_replay_is_not_an_experience(tmp_path: Path):
    result = _replay(tmp_path)
    assert result["not_a_fill"] is True
    assert result["writes_experience"] is False
    assert result["kind"] == "CANDIDATE_REPLAY"
    learning = tmp_path / "investment" / "learning"
    paper = tmp_path / "investment" / "paper"
    assert not learning.exists() or not any(learning.rglob("*experience*"))
    assert not paper.exists() or not any(paper.rglob("*fill*"))
    assert not any(tmp_path.rglob("*reward*"))
    assert not any(tmp_path.rglob("lab.loop0.reward*"))


def test_golden_replay_does_not_leak_live_complete_into_before(tmp_path: Path):
    from atlas.investment.fundamentals import upsert_rows

    upsert_rows(
        tmp_path,
        [
            {
                "symbol": "HBLPOWER",
                "pe": 25.86,
                "roe": 44.0,
                "debt_to_equity": 0.02,
                "fcf": 1.0,
                "sector": "Capital Goods",
                "name": "HBL Power",
            }
        ],
        source="nse_xbrl",
    )
    result = _replay(tmp_path)
    assert result["before"]["plc_a"] == "INCOMPLETE"
    assert result["before"]["pe"] is None
    live = get_symbol(tmp_path, "HBLPOWER") or {}
    assert live.get("pe") == 25.86
    sandbox = get_symbol(
        tmp_path / "investment" / "trade_loop0" / "replay" / "sandbox", "HBLPOWER"
    ) or {}
    assert sandbox.get("pe") == GOLDEN_AFTER["pe"]
    assert sandbox.get("pe") != live.get("pe")
