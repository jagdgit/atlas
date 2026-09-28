"""Explicit data-provider → destination contract (Zerodha ≠ fundamentals).

Observability for swing thesis: what each field requires, who supplies it,
where Atlas stores it, and whether the current symbol packet is complete.
Does not invent values. Does not authorize trades.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "data.plane.contract.v1"
_IST = ZoneInfo("Asia/Kolkata")

# Field → intended provider(s), durable destination, why required.
# Zerodha is market marks only — never PE/FCF/MoS.
PROVIDER_CONTRACT: tuple[dict[str, Any], ...] = (
    {
        "field": "ltp",
        "providers": ("zerodha", "bar_store", "yahoo_chart"),
        "destination": "market_marks / bar_store",
        "required_for": "technical / live marks",
        "zerodha_role": "primary_live",
    },
    {
        "field": "ohlc",
        "providers": ("zerodha", "bar_store", "yahoo_chart"),
        "destination": "bar_store",
        "required_for": "technical / price_history",
        "zerodha_role": "primary_live",
    },
    {
        "field": "volume",
        "providers": ("zerodha", "bar_store", "yahoo_chart"),
        "destination": "bar_store",
        "required_for": "technical",
        "zerodha_role": "primary_live",
    },
    {
        "field": "pe",
        "providers": ("screener_export", "yahoo_fundamentals", "operator_import"),
        "destination": "fundamentals_store",
        "required_for": "MoS / valuation",
        "zerodha_role": "never",
        "mos_buy_preferred": "screener_export",
    },
    {
        "field": "fcf",
        "providers": ("yahoo_fundamentals", "screener_export", "operator_import", "filings"),
        "destination": "fundamentals_store",
        "required_for": "thesis / MoS (DCF path)",
        "zerodha_role": "never",
    },
    {
        "field": "roe",
        "providers": ("yahoo_fundamentals", "universe_seed", "screener_export"),
        "destination": "fundamentals_store",
        "required_for": "thesis",
        "zerodha_role": "never",
    },
    {
        "field": "debt",
        "providers": ("yahoo_fundamentals", "universe_seed", "screener_export"),
        "destination": "fundamentals_store",
        "required_for": "thesis",
        "zerodha_role": "never",
    },
    {
        "field": "mos",
        "providers": ("ira_valuation",),
        "destination": "thesis_packet / valuation",
        "required_for": "authorization (swing)",
        "zerodha_role": "never",
        "note": "Computed from PE/FCF + price — never fetched from a market feed.",
    },
)


def data_provider_contract() -> dict[str, Any]:
    """Static architecture contract — not a live quote."""
    return {
        "version": VERSION,
        "kind": "DATA_PROVIDER_CONTRACT",
        "honesty": (
            "Zerodha supplies LTP/OHLC/volume only. PE/FCF/ROE/debt come from "
            "Yahoo enrich / Screener import / universe seed. MoS is IRA-computed. "
            "Paid market API ≠ fundamental evidence."
        ),
        "rows": [dict(r) for r in PROVIDER_CONTRACT],
        "authorization_chain": [
            "market/bar_store → technical",
            "FEA planner → Yahoo/Screener-operator/filings → fundamentals_store",
            "IRA valuation → MoS",
            "thesis stance",
            "evidence completeness",
            "lab_policy (deterministic gate)",
            "order (only if authorized)",
        ],
    }


def _present(v: Any) -> bool:
    if v is None or v == "" or v == "UNKNOWN" or v == "missing":
        return False
    if isinstance(v, (list, dict)) and not v:
        return False
    return True


def _field_row(
    name: str,
    *,
    value: Any = None,
    source: str | None = None,
    status: str,
    as_of: Any = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "field": name,
        "value": value if status == "available" else None,
        "source": source,
        "status": status,
        "as_of": as_of,
        "note": note,
    }


def build_symbol_evidence_view(
    data_dir: str | Path | None,
    symbol: str,
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    awareness: dict[str, Any] | None = None,
    technical: str | None = None,
) -> dict[str, Any]:
    """Observable per-symbol evidence packet (stores + completeness + gate hint).

    Never invents PE/FCF/MoS. Stops honestly at the first missing authorization input.
    """
    from atlas.investment.evidence_completeness import (
        evaluate_evidence_completeness,
        format_why_not_evaluable,
        hydrate_completeness_inputs,
    )
    from atlas.investment.lab_contracts import apply_lab_policy, lab_kind

    sym = str(symbol or "").strip().upper()
    fund: dict[str, Any] = {}
    mkt: dict[str, Any] = {}
    if data_dir:
        fund, mkt = hydrate_completeness_inputs(
            data_dir,
            sym,
            program_id=program_id,
            fundamentals=fund,
            market=mkt,
        )
    aw = awareness if isinstance(awareness, dict) else {}
    if not aw and data_dir:
        # Lightweight dossier read — no full research start
        try:
            from atlas.investment.research.store import ResearchStore

            store = ResearchStore(data_dir=str(data_dir))
            doc = store.get(sym, program_id=program_id)
            if isinstance(doc, dict):
                aw = {
                    "thesis": doc.get("thesis") if isinstance(doc.get("thesis"), dict) else {},
                    "valuation": doc.get("valuation")
                    if isinstance(doc.get("valuation"), dict)
                    else {},
                    "brief": {
                        "business": (
                            ((doc.get("sections") or {}).get("business") or {}).get("fields")
                            or {}
                        ).get("summary")
                        or ((doc.get("sections") or {}).get("business") or {}).get("fields", {}).get(
                            "business"
                        )
                    },
                    "identity": doc.get("identity")
                    if isinstance(doc.get("identity"), dict)
                    else {},
                    "fundamentals": {
                        k: fund.get(k)
                        for k in ("pe", "fcf", "roe", "debt_to_equity", "sector")
                        if fund.get(k) is not None
                    },
                }
        except Exception:  # noqa: BLE001
            aw = {}

    val = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {}
    thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}

    price = mkt.get("ltp") or mkt.get("price") or mkt.get("close") or mkt.get("last_price")
    pe = fund.get("pe") if _present(fund.get("pe")) else val.get("pe")
    fcf = fund.get("fcf") if _present(fund.get("fcf")) else fund.get("free_cash_flow")
    if not _present(fcf):
        fcf = None
    roe = fund.get("roe")
    debt = fund.get("debt_to_equity")
    if debt is None:
        debt = fund.get("debt_equity")
    mos = val.get("margin_of_safety_pct")

    market_block = {
        "price": _field_row(
            "price",
            value=price,
            source=str(mkt.get("provider") or "bar_store") if _present(price) else None,
            status="available" if _present(price) else "missing",
            as_of=mkt.get("as_of"),
        ),
        "ohlc_plane": "zerodha_or_bar_store",
    }
    fundamentals_block = {
        "pe": _field_row(
            "pe",
            value=pe,
            source=str(fund.get("source") or "valuation") if _present(pe) else None,
            status="available" if _present(pe) else "missing",
            as_of=fund.get("as_of") or val.get("as_of"),
            note="MoS BUY prefers screener_export over yahoo_fundamentals",
        ),
        "fcf": _field_row(
            "fcf",
            value=fcf,
            source=str(fund.get("source") or "fundamentals") if _present(fcf) else None,
            status="available" if _present(fcf) else "missing",
            as_of=fund.get("as_of"),
        ),
        "roe": _field_row(
            "roe",
            value=roe,
            source=str(fund.get("source") or "fundamentals") if _present(roe) else None,
            status="available" if _present(roe) else "missing",
            as_of=fund.get("as_of"),
        ),
        "debt": _field_row(
            "debt",
            value=debt,
            source=str(fund.get("source") or "fundamentals") if _present(debt) else None,
            status="available" if _present(debt) else "missing",
            as_of=fund.get("as_of"),
        ),
    }
    valuation_block = {
        "mos": _field_row(
            "mos",
            value=mos,
            source="ira_valuation" if mos is not None else None,
            status="available" if mos is not None else "missing",
            as_of=val.get("as_of"),
            note=str(val.get("mos_method") or "") or None,
        ),
        "pe": val.get("pe"),
        "method": val.get("method") or val.get("method_label"),
    }

    completeness = evaluate_evidence_completeness(
        symbol=sym,
        laboratory_id=laboratory_id,
        awareness=aw,
        market=mkt,
        fundamentals=fund,
        data_dir=None,  # already hydrated
        program_id=program_id,
    )
    stance = str(thesis.get("stance") or "ABSENT").upper()
    tech = str(technical or "HOLD").upper()
    kind = lab_kind(laboratory_id)
    policy = apply_lab_policy(
        lab_kind_s=kind,
        technical=tech,
        thesis=stance,
        held=0.0,
        identity=str(
            (aw.get("identity") or {}).get("identity")
            if isinstance(aw.get("identity"), dict)
            else "NAMED"
        ),
    )
    final = str(policy.get("final_decision") or "").upper()

    # Chain stop arrow — first real blocker toward authorization
    chain_stops_at: str | None = None
    if not _present(price):
        chain_stops_at = "price"
    elif not _present(pe):
        chain_stops_at = "pe"
    elif not _present(fcf):
        chain_stops_at = "fcf"
    elif mos is None:
        chain_stops_at = "mos"
    elif not completeness.get("decision_evaluable"):
        chain_stops_at = "completeness:" + ",".join(
            completeness.get("required_missing") or []
        )
    elif stance in {"WATCH", "ABSENT", "AVOID", "INVALID"} and tech == "BUY":
        chain_stops_at = f"thesis:{stance}"
    elif final != "BUY":
        chain_stops_at = f"lab_policy:{final}"
    else:
        chain_stops_at = None  # authorization candidate

    as_of_ist = datetime.now(_IST).date().isoformat()
    return {
        "version": VERSION,
        "kind": "SYMBOL_EVIDENCE_VIEW",
        "symbol": sym,
        "laboratory_id": laboratory_id,
        "as_of_ist": as_of_ist,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "contract": data_provider_contract(),
        "market": market_block,
        "fundamentals": fundamentals_block,
        "valuation": valuation_block,
        "thesis": {
            "stance": stance,
            "completeness": completeness.get("decision"),
            "summary": (thesis.get("summary") or "")[:240] or None,
        },
        "completeness": completeness,
        "why_not_evaluable": format_why_not_evaluable(completeness),
        "lab_policy": {
            "technical": tech,
            "thesis": stance,
            "final": final,
            "contradictions": policy.get("contradictions") or [],
            "never_orders_from_llm": True,
        },
        "chain_stops_at": chain_stops_at,
        "authorization_candidate": chain_stops_at is None and final == "BUY",
        "honesty": (
            "Observability only. MoS available ≠ MoS positive. "
            "Gate remains deterministic; LLM cannot authorize."
        ),
    }


def format_symbol_evidence_view(view: dict[str, Any]) -> str:
    """Operator-facing one-screen summary."""
    sym = view.get("symbol") or "?"
    lines = [
        f"{sym}  as_of={view.get('as_of_ist')}",
        f"  market.price: {((view.get('market') or {}).get('price') or {})}",
        f"  pe: {((view.get('fundamentals') or {}).get('pe') or {})}",
        f"  fcf: {((view.get('fundamentals') or {}).get('fcf') or {})}",
        f"  roe: {((view.get('fundamentals') or {}).get('roe') or {})}",
        f"  debt: {((view.get('fundamentals') or {}).get('debt') or {})}",
        f"  mos: {((view.get('valuation') or {}).get('mos') or {})}",
        f"  thesis: {(view.get('thesis') or {})}",
        f"  chain_stops_at: {view.get('chain_stops_at')}",
        f"  lab_policy.final: {((view.get('lab_policy') or {}).get('final'))}",
    ]
    return "\n".join(lines)
