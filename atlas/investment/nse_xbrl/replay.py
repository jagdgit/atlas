"""TRADE-LOOP0 candidate replay — not a paper fill (L35).

Always evaluates BEFORE against an empty sandbox. The live COMPLETE store
must not masquerade as the 18-Sep incomplete packet.

HBLPOWER N1 is LOCKED as the golden end-to-end fixture. Do not re-engineer
this symbol unless the golden test regresses. The replay is candidate
re-evaluation, not a paper trade, outcome, or reward.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPLAY_REL = Path("investment") / "trade_loop0" / "replay"
GOLDEN_SYMBOL = "HBLPOWER"
GOLDEN_EVIDENCE_AS_OF = "2026-09-18"
GOLDEN_PRICE = 760.0  # bar close that produced the locked PE (EPS 29.39 FY)
GOLDEN_CANONICAL_SHA256 = (
    "ea71f0eab3516163bee183b9629ef0cb336e380d04bbe2ee0c4b41588063e9e6"
)
GOLDEN_PRIOR_SHA256 = (
    "97e733b0b8439a34c30b7376b17b51b052cb776f4ec4bc3b44ffe60e83769a14"
)
GOLDEN_DEBT_DEFINITION_ID = "atlas.debt.total_borrowings.v1"
GOLDEN_AFTER = {
    "plc_a": "COMPLETE",
    "code": "fundamentals_ok",
    "missing": [],
    "pe": 25.859135760462742,
    "roe": 44.08399367041512,
    "debt_to_equity": 0.019866861767468748,
    "fcf": 6_293_200_000.0,
    "sector": "Capital Goods",
    "identity": "HBL Power",
    "source": "nse_xbrl",
    "eps_basis": "FY",
}
HBLPOWER_PACKET = {
    "symbol": GOLDEN_SYMBOL,
    "action": "buy",
    "as_of": GOLDEN_EVIDENCE_AS_OF,
    "laboratory_id": "india_equity_learner",
    "reason": "sma_buy",
    "plc_a": {
        "ok": False,
        "code": "fundamentals_incomplete",
        "missing": ["pe", "roe", "debt_to_equity", "sector"],
    },
    "not_a_fill": True,
}


def _metrics_snapshot(
    row: dict[str, Any] | None,
    ident: dict[str, Any] | None,
    plc: dict[str, Any] | None,
) -> dict[str, Any]:
    fund = row if isinstance(row, dict) else {}
    ident = ident if isinstance(ident, dict) else {}
    plc = plc if isinstance(plc, dict) else {}
    return {
        "plc_a": "COMPLETE" if plc.get("ok") else "INCOMPLETE",
        "code": plc.get("code"),
        "missing": list(plc.get("missing") or []),
        "pe": fund.get("pe"),
        "roe": fund.get("roe"),
        "debt_to_equity": fund.get("debt_to_equity"),
        "fcf": fund.get("fcf") if fund.get("fcf") is not None else fund.get("free_cash_flow"),
        "sector": ident.get("sector") or fund.get("sector"),
        "identity": ident.get("name") or fund.get("name"),
        "source": fund.get("source"),
        "nse_raw_evidence_id": fund.get("nse_raw_evidence_id"),
        "conflicts": fund.get("evidence_conflicts") or [],
        "eps_basis": fund.get("eps_basis"),
    }


def _price_from_bars(data_dir: str | Path | None, symbol: str) -> float | None:
    if not data_dir:
        return None
    try:
        from atlas.investment.bar_store import load_bars

        bars = load_bars(data_dir, symbol, limit=1) or load_bars(
            data_dir, str(symbol).replace(".NS", ""), limit=1
        )
        last = bars[-1] if bars else None
        if isinstance(last, dict) and last.get("close") is not None:
            return float(last["close"])
    except Exception:  # noqa: BLE001
        return None
    return None


def replay_hblpower_candidate(
    data_dir: str | Path,
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    xml_text: str | list[str] | tuple[str, ...] | None = None,
    price: float | None = 500.0,
    evidence_as_of: str = "2026-09-18",
    opener: Any | None = None,
    source_data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """18-Sep HBLPOWER BUY packet → UQ → FEA/NSE → PLC.A reread. No ledger fill.

    Acquisition runs in ``trade_loop0/replay/sandbox`` so a live COMPLETE
    fundamentals row cannot be used as BEFORE.
    """
    from atlas.investment.fundamental_evidence.runner import acquire_for_symbol
    from atlas.investment.fundamentals import get_symbol
    from atlas.investment.nse_xbrl.coverage import fundamentals_coverage
    from atlas.investment.nse_xbrl.identity import resolve_identity
    from atlas.investment.nse_xbrl.raw_store import load_stored_xml
    from atlas.investment.plc_buy_gates import evaluate_fundamental_sanity, sector_from_sources
    from atlas.investment.uncertainty_queue import enqueue_from_unknowns

    root = Path(data_dir) / REPLAY_REL
    sandbox = root / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    packet = dict(HBLPOWER_PACKET)
    packet["replayed_at"] = datetime.now(timezone.utc).isoformat()
    packet["evidence_as_of"] = evidence_as_of
    (root / "HBLPOWER_2026-09-18.json").write_text(
        json.dumps(packet, indent=2) + "\n", encoding="utf-8"
    )

    source = Path(source_data_dir) if source_data_dir else Path(data_dir)
    stored = [] if xml_text else load_stored_xml(source, "HBLPOWER")
    if xml_text is None and stored:
        xml_text = [d["xml"] for d in stored]
        if price is None:
            price = _price_from_bars(source, "HBLPOWER")

    before = {
        "ok": False,
        "code": "fundamentals_incomplete",
        "missing": list(HBLPOWER_PACKET["plc_a"]["missing"]),
        "sector": None,
        "reason": "fundamentals_incomplete:" + ",".join(HBLPOWER_PACKET["plc_a"]["missing"]),
    }
    uq = enqueue_from_unknowns(
        sandbox,
        laboratory_id=laboratory_id,
        symbol="HBLPOWER",
        unknowns=[
            "pe_missing",
            "roe_missing",
            "debt_missing",
            "fcf_missing",
            "sector_missing",
            "identity_unknown",
        ],
    )
    acq = acquire_for_symbol(
        sandbox,
        "HBLPOWER",
        laboratory_id=laboratory_id,
        program_id=program_id,
        required_fields=["pe", "fcf", "roe", "debt_to_equity", "sector", "identity"],
        purpose="trade_loop0_replay",
        enabled=True,
        opener=opener,
        push_to_ira=False,
        nse_xml_text=xml_text,
        nse_price=price,
        evidence_as_of=evidence_as_of,
        nse_available_at="2026-05-15",
    )
    after_row = get_symbol(sandbox, "HBLPOWER", program_id=program_id) or {}
    after_ident = resolve_identity("HBLPOWER", data_dir=str(sandbox), fundamentals=after_row)
    after = evaluate_fundamental_sanity(
        after_row,
        sector=sector_from_sources(fundamentals=after_row) or after_ident.get("sector"),
    )
    cov = fundamentals_coverage(
        fundamentals=after_row,
        identity=after_ident,
    )
    before_metrics = {
        "plc_a": "INCOMPLETE",
        "code": "fundamentals_incomplete",
        "missing": list(HBLPOWER_PACKET["plc_a"]["missing"]),
        "pe": None,
        "roe": None,
        "debt_to_equity": None,
        "fcf": None,
        "sector": None,
        "identity": None,
        "source": None,
        "nse_raw_evidence_id": None,
        "conflicts": [],
        "eps_basis": None,
    }
    after_metrics = _metrics_snapshot(after_row, after_ident, after)
    result = {
        "version": "trade_loop0.replay.v2",
        "kind": "CANDIDATE_REPLAY",
        "symbol": "HBLPOWER",
        "not_a_fill": True,
        "writes_experience": False,
        "isolated": True,
        "sandbox": str(sandbox),
        "packet": packet,
        "plc_a_before": before,
        "plc_a_after": after,
        "before": before_metrics,
        "after": after_metrics,
        "stored_raw_n": len(stored),
        "stored_raw_ids": [d.get("sha256") for d in stored],
        "acquire": {
            "reason": acq.get("reason"),
            "acquired": [a.get("field") for a in (acq.get("acquired") or [])],
            "still_missing": acq.get("still_missing"),
            "nse": (acq.get("nse") or {}).get("reason") if isinstance(acq.get("nse"), dict) else None,
        },
        "coverage": cov,
        "uq": {"created_n": len(uq.get("created_ids") or []), "pending_n": uq.get("pending_n")},
        "reevaluated": bool(before.get("ok") is False and after.get("ok") is True),
    }
    (root / "HBLPOWER_2026-09-18_result.json").write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    try:
        from atlas.investment.nse_xbrl.digest import save_observation

        save_observation(
            data_dir,
            {
                "plc_a_reevaluated": 1 if result.get("reevaluated") else 0,
                "nse_xbrl_success": 1 if result.get("plc_a_after", {}).get("ok") else 0,
                "last_fea_reason": (result.get("acquire") or {}).get("reason"),
                "technical_buys": 1,
                "plc_a_incomplete": 0 if result.get("plc_a_after", {}).get("ok") else 1,
            },
        )
    except Exception:
        pass
    return result
