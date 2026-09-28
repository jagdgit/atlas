"""Decision Evidence Completeness Engine — data contract per lab decision.

WHAT DECISION? → REQUIRED EVIDENCE → AVAILABLE vs MISSING → COMPLETE / INCOMPLETE

Deterministic only. Ollama never decides completeness.
Does not download everything — only checks what this decision requires.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.lab_contracts import (
    LAB_FNO,
    LAB_INTRADAY,
    LAB_SWING,
    LAB_UNCONSTRAINED,
    instrument_class,
    lab_kind,
    strategy_contract,
    CLASS_CASH_EQUITY,
    CLASS_FNO_CONTRACT,
    CLASS_INDEX_PROXY,
)

VERSION = "learn.evidence_contract.v1"
STORE_REL = Path("investment") / "evidence_completeness"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.evidence_completeness")

ST_AVAILABLE = "AVAILABLE"
ST_STALE = "STALE"
ST_MISSING = "MISSING"
ST_CONFLICTING = "CONFLICTING"
ST_INVALID = "INVALID"
ST_NOT_APPLICABLE = "NOT_APPLICABLE"
ST_PENDING = "PENDING_ACQUISITION"

_UQ_CODE = {
    "fcf": "fcf_missing",
    "pe": "pe_missing",
    "mos": "mos_unknown",
    "roe": "roe_missing",
    "identity": "identity_unknown",
    "pb": "pb_missing",
    "debt": "debt_missing",
    "sector": "sector_missing",
}


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _present(v: Any) -> bool:
    if v is None or v == "" or v == "UNKNOWN" or v == "missing":
        return False
    if isinstance(v, (list, dict)) and not v:
        return False
    return True


def decision_data_contract(
    laboratory_id: str | None,
    *,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Required evidence checklist for this lab's decision type.

    Derived from strategy_contract — not an invented mega-checklist.
    """
    kind = lab_kind(laboratory_id, cfg=cfg)
    contract = strategy_contract(kind)
    if kind == LAB_INTRADAY:
        items = [
            ("live_ltp", True, True, "Live LTP / mark"),
            ("bars_intraday", True, True, "Intraday OHLCV (e.g. 5m)"),
            ("technical_state", True, True, "Technical state"),
            ("session", True, False, "Session open/context"),
            ("instrument", True, True, "Instrument identity"),
            ("liquidity", False, False, "Liquidity band"),
        ]
        plane = "zerodha_authoritative_market"
    elif kind == LAB_FNO:
        items = [
            ("live_ltp", True, True, "Live LTP / mark"),
            ("bars_intraday", True, True, "Intraday OHLCV"),
            ("instrument", True, True, "Contract / index proxy identity"),
            ("underlying", True, True, "Underlying / family"),
            ("expiry_or_proxy", True, True, "Expiry (contract) or index proxy"),
            ("cash_equity_excluded", True, True, "No cash-equity contamination"),
            ("session", True, False, "Session open/context"),
        ]
        plane = "zerodha_authoritative_market"
    elif kind == LAB_SWING:
        items = [
            ("price_history", True, True, "Price / history"),
            ("technical_state", False, False, "Technical state"),
            ("pe", True, True, "PE / valuation multiple"),
            ("fcf", True, True, "Free cash flow"),
            ("mos", True, True, "Margin of safety"),
            ("roe", False, True, "ROE / profitability"),
            ("debt", False, True, "Debt / leverage"),
            ("sector", True, True, "Sector / industry"),
            ("thesis", True, True, "Thesis stance"),
            ("news", False, False, "Recent news / events"),
            ("identity", True, True, "Company identity"),
        ]
        plane = "mixed_fundamentals_research"
    else:
        items = [
            ("price_history", False, False, "Price"),
            ("thesis", False, False, "Thesis / question evidence"),
        ]
        plane = "research"
    return {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "lab_kind": kind,
        "strategy_contract": contract,
        "market_data_plane": plane,
        "required_keys": [k for k, req, _, _ in items if req],
        "material_keys": [k for k, _, mat, _ in items if mat],
        "items": [
            {"key": k, "required": req, "material": mat, "label": lab}
            for k, req, mat, lab in items
        ],
        "honesty": (
            "Contract lists what THIS decision needs — not a mandate to download "
            "everything about every stock."
        ),
    }


def _item(
    key: str,
    *,
    status: str,
    required: bool,
    material: bool,
    label: str,
    value: Any = None,
    source: str | None = None,
    as_of: str | None = None,
    retrieved_at: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "status": status,
        "required": required,
        "material": material,
        "value": value if status == ST_AVAILABLE else None,
        "source": source,
        "as_of": as_of,
        "retrieved_at": retrieved_at,
        "note": note,
    }


def _from_fundamentals(fund: dict[str, Any], key: str) -> tuple[Any, str | None]:
    aliases = {
        "fcf": ("fcf", "free_cash_flow"),
        "pe": ("pe", "trailing_pe"),
        "roe": ("roe", "return_on_equity"),
        "pb": ("pb", "price_to_book"),
        "debt": ("debt_to_equity", "debt_equity", "d_e"),
    }
    for a in aliases.get(key, (key,)):
        if _present(fund.get(a)):
            return fund.get(a), str(
                fund.get("source") or fund.get("provider") or "fundamentals"
            )
    return None, None


def hydrate_completeness_inputs(
    data_dir: str | Path | None,
    symbol: str,
    *,
    program_id: str = "market_intelligence",
    fundamentals: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fill completeness inputs from durable stores when call sites omit them.

    Zerodha / live marks are market-only. PE/FCF/ROE live in the fundamentals
    store (Yahoo enrich / Screener import) — never invent. Price may come from
    ``bar_store`` last close when LTP is absent (flat book / swing lab).
    """
    fund = dict(fundamentals) if isinstance(fundamentals, dict) else {}
    mkt = dict(market) if isinstance(market, dict) else {}
    if not data_dir:
        return fund, mkt
    sym = str(symbol or "").strip().upper()
    if not sym:
        return fund, mkt
    try:
        from atlas.investment.fundamentals import get_symbol

        row = get_symbol(data_dir, sym, program_id=program_id)
        if isinstance(row, dict) and row:
            for k, v in row.items():
                if v is None or v == "":
                    continue
                if fund.get(k) is None:
                    fund[k] = v
            if fund.get("source") is None and row.get("source"):
                fund["source"] = row.get("source")
            if fund.get("as_of") is None and row.get("as_of"):
                fund["as_of"] = row.get("as_of")
    except Exception:  # noqa: BLE001
        _log.debug("completeness fund hydrate skipped", exc_info=True)
    px = mkt.get("ltp") or mkt.get("price") or mkt.get("close") or mkt.get("last_price")
    if not _present(px):
        try:
            from atlas.investment.bar_store import load_bars

            bars = load_bars(data_dir, sym, limit=1)
            last = bars[-1] if bars else None
            if isinstance(last, dict) and _present(last.get("close")):
                mkt["close"] = last.get("close")
                mkt["last_price"] = last.get("close")
                if mkt.get("provider") is None:
                    mkt["provider"] = "bar_store"
                if mkt.get("as_of") is None and last.get("date"):
                    mkt["as_of"] = last.get("date")
                mkt["hist_ok"] = True
        except Exception:  # noqa: BLE001
            _log.debug("completeness bar hydrate skipped", exc_info=True)
    return fund, mkt


def _assess_swing_item(
    key: str,
    *,
    awareness: dict[str, Any],
    market: dict[str, Any],
    fundamentals: dict[str, Any],
    meta: dict[str, Any],
) -> tuple[str, Any, str | None, str | None]:
    val = awareness.get("valuation") if isinstance(awareness.get("valuation"), dict) else {}
    thesis = awareness.get("thesis") if isinstance(awareness.get("thesis"), dict) else {}
    brief = awareness.get("brief") if isinstance(awareness.get("brief"), dict) else {}
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    aw_fund = (
        awareness.get("fundamentals")
        if isinstance(awareness.get("fundamentals"), dict)
        else {}
    )
    merged_fund = {**aw_fund, **fund}

    if key == "price_history":
        px = (
            market.get("ltp")
            or market.get("price")
            or market.get("close")
            or market.get("last_price")
        )
        if _present(px):
            return (
                ST_AVAILABLE,
                px,
                str(market.get("provider") or "market"),
                market.get("as_of"),
            )
        return ST_MISSING, None, None, None
    if key == "technical_state":
        tech = market.get("technical") or awareness.get("technical") or meta.get("technical")
        if isinstance(tech, dict) and tech:
            return (
                ST_AVAILABLE,
                tech.get("label") or tech.get("state") or "present",
                "technical",
                None,
            )
        ind = meta.get("indicators") if isinstance(meta.get("indicators"), dict) else {}
        if ind.get("rsi") is not None or ind.get("sma_fast") is not None:
            return ST_AVAILABLE, "indicators", "indicators", None
        return ST_MISSING, None, None, None
    if key == "pe":
        v, src = _from_fundamentals(merged_fund, "pe")
        if v is not None:
            return ST_AVAILABLE, v, src, merged_fund.get("as_of")
        if _present(val.get("pe")):
            return ST_AVAILABLE, val.get("pe"), "valuation", val.get("as_of")
        conflicts = merged_fund.get("evidence_conflicts") or []
        if any("pe" in str(c).lower() for c in conflicts):
            return ST_CONFLICTING, None, "fundamentals", None
        return ST_MISSING, None, None, None
    if key == "fcf":
        v, src = _from_fundamentals(merged_fund, "fcf")
        if v is not None:
            return ST_AVAILABLE, v, src, merged_fund.get("as_of")
        return ST_MISSING, None, None, None
    if key == "mos":
        mos = val.get("margin_of_safety_pct")
        if mos is not None:
            return ST_AVAILABLE, mos, "valuation", val.get("as_of")
        return ST_MISSING, None, None, None
    if key == "roe":
        v, src = _from_fundamentals(merged_fund, "roe")
        if v is not None:
            return ST_AVAILABLE, v, src, merged_fund.get("as_of")
        return ST_MISSING, None, None, None
    if key == "debt":
        v, src = _from_fundamentals(merged_fund, "debt")
        if v is not None:
            return ST_AVAILABLE, v, src, merged_fund.get("as_of")
        return ST_MISSING, None, None, None
    if key == "sector":
        sector = (
            brief.get("business")
            or merged_fund.get("sector")
            or awareness.get("sector")
            or market.get("sector")
        )
        if _present(sector):
            return ST_AVAILABLE, sector, "research", None
        return ST_MISSING, None, None, None
    if key == "thesis":
        stance = thesis.get("stance") or awareness.get("stance")
        if _present(stance) and str(stance).upper() not in {"", "ABSENT", "UNKNOWN"}:
            return ST_AVAILABLE, stance, "thesis", None
        if _present(thesis.get("summary")) or _present(brief.get("thesis")):
            return ST_AVAILABLE, "present", "thesis", None
        return ST_MISSING, None, None, None
    if key == "news":
        news = awareness.get("news") or awareness.get("recent_news")
        if _present(news):
            return ST_AVAILABLE, "present", "research", None
        return ST_MISSING, None, None, None
    if key == "identity":
        ident = awareness.get("identity") or (awareness.get("thesis_identity") or {})
        if isinstance(ident, dict):
            st = str(ident.get("identity") or ident.get("status") or "").upper()
            if st and st not in {"UNKNOWN", ""}:
                return ST_AVAILABLE, st, "identity", None
            if st == "UNKNOWN":
                return ST_MISSING, None, "identity", None
        if _present(brief.get("business")):
            return ST_AVAILABLE, "named", "research", None
        return ST_MISSING, None, None, None
    return ST_MISSING, None, None, None


def _assess_live_item(
    key: str,
    *,
    symbol: str,
    market: dict[str, Any],
    provider_health: dict[str, Any] | None,
    kind: str,
) -> tuple[str, Any, str | None, str | None]:
    ph = provider_health if isinstance(provider_health, dict) else {}
    if key == "live_ltp":
        px = market.get("ltp") or market.get("price") or market.get("last_price")
        if _present(px):
            fresh = str(market.get("freshness") or ph.get("freshness") or "").upper()
            if fresh == "STALE":
                return (
                    ST_STALE,
                    px,
                    str(market.get("provider") or "zerodha"),
                    market.get("as_of"),
                )
            return (
                ST_AVAILABLE,
                px,
                str(market.get("provider") or "zerodha"),
                market.get("as_of"),
            )
        return ST_MISSING, None, None, None
    if key == "bars_intraday":
        bars = market.get("bars") or market.get("ohlcv")
        if isinstance(bars, list) and len(bars) > 0:
            return ST_AVAILABLE, len(bars), str(market.get("provider") or "zerodha"), None
        if _f(market.get("bar_count")) and float(market["bar_count"]) > 0:
            return (
                ST_AVAILABLE,
                market.get("bar_count"),
                str(market.get("provider") or "bars"),
                None,
            )
        if market.get("bars_ok") is True or market.get("hist_ok") is True:
            return ST_AVAILABLE, True, str(market.get("provider") or "zerodha"), None
        if ph.get("hist_probe") == "PASS" and _present(
            market.get("ltp") or market.get("price")
        ):
            return ST_AVAILABLE, "provider_hist_ok", "zerodha", None
        return ST_MISSING, None, None, None
    if key == "technical_state":
        tech = market.get("technical") or market.get("indicators")
        if isinstance(tech, dict) and tech:
            return ST_AVAILABLE, tech.get("label") or "present", "technical", None
        return ST_MISSING, None, None, None
    if key == "session":
        sess = market.get("session") or market.get("session_open")
        if sess is not None:
            return ST_AVAILABLE, sess, "session", None
        return ST_AVAILABLE, "assumed", "session", None
    if key == "instrument":
        if _present(symbol):
            return ST_AVAILABLE, symbol, "instrument", None
        return ST_MISSING, None, None, None
    if key == "liquidity":
        liq = market.get("liquidity") or market.get("liquidity_band")
        if _present(liq):
            return ST_AVAILABLE, liq, "market", None
        return ST_MISSING, None, None, None
    if key == "underlying":
        from atlas.investment.index_proxy_lot import underlier_family

        fam = underlier_family(symbol)
        if fam:
            return ST_AVAILABLE, fam, "index_proxy", None
        row = market.get("instrument") if isinstance(market.get("instrument"), dict) else {}
        und = row.get("underlying") or row.get("name")
        if _present(und):
            return ST_AVAILABLE, und, "instrument", None
        return ST_MISSING, None, None, None
    if key == "expiry_or_proxy":
        from atlas.investment.index_proxy_lot import underlier_family

        if underlier_family(symbol):
            return ST_AVAILABLE, "index_proxy", "index_proxy", None
        row = market.get("instrument") if isinstance(market.get("instrument"), dict) else {}
        exp = row.get("expiry") or market.get("expiry")
        if _present(exp):
            return ST_AVAILABLE, exp, "contract", None
        cls = instrument_class(symbol, instrument=row)
        if cls == CLASS_INDEX_PROXY:
            return ST_AVAILABLE, "index_proxy", "index_proxy", None
        if cls == CLASS_FNO_CONTRACT:
            return ST_MISSING, None, None, None
        return ST_MISSING, None, None, None
    if key == "cash_equity_excluded":
        cls = instrument_class(
            symbol,
            instrument=market.get("instrument")
            if isinstance(market.get("instrument"), dict)
            else None,
        )
        if cls == CLASS_CASH_EQUITY and kind == LAB_FNO:
            return ST_INVALID, cls, "lab_contract", None
        if cls in {CLASS_INDEX_PROXY, CLASS_FNO_CONTRACT}:
            return ST_AVAILABLE, cls, "lab_contract", None
        return ST_MISSING, cls, "lab_contract", None
    return ST_MISSING, None, None, None


def build_candidate_evidence_packet(
    *,
    symbol: str,
    laboratory_id: str,
    awareness: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    provider_health: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
    program_id: str = "market_intelligence",
) -> dict[str, Any]:
    """Normalized CandidateEvidencePacket: planes + completeness gate."""
    aw = awareness if isinstance(awareness, dict) else {}
    mkt = market if isinstance(market, dict) else {}
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    if data_dir:
        fund, mkt = hydrate_completeness_inputs(
            data_dir,
            symbol,
            program_id=program_id,
            fundamentals=fund,
            market=mkt,
        )
    completeness = evaluate_evidence_completeness(
        symbol=symbol,
        laboratory_id=laboratory_id,
        awareness=aw,
        market=mkt,
        fundamentals=fund,
        provider_health=provider_health,
        cfg=cfg,
        meta=meta,
        # already hydrated above — avoid double IO
        data_dir=None,
        program_id=program_id,
    )
    pkt = {
        "version": VERSION,
        "kind": "CANDIDATE_EVIDENCE_PACKET",
        "symbol": str(symbol or "").strip().upper(),
        "laboratory_id": laboratory_id,
        "market": {
            "ltp": mkt.get("ltp") or mkt.get("price") or mkt.get("close") or mkt.get("last_price"),
            "provider": mkt.get("provider"),
            "as_of": mkt.get("as_of"),
            "freshness": mkt.get("freshness"),
            "bars_ok": mkt.get("bars_ok") or mkt.get("hist_ok"),
        },
        "technical": mkt.get("technical") or aw.get("technical") or (meta or {}).get("technical"),
        "fundamental": {
            **(
                aw.get("fundamentals")
                if isinstance(aw.get("fundamentals"), dict)
                else {}
            ),
            **fund,
            "valuation": aw.get("valuation"),
        },
        "research": {
            "thesis": aw.get("thesis"),
            "brief": aw.get("brief"),
            "sector": (aw.get("brief") or {}).get("business")
            if isinstance(aw.get("brief"), dict)
            else aw.get("sector"),
            "news": aw.get("news") or aw.get("recent_news"),
            "identity": aw.get("identity"),
        },
        "completeness": completeness,
        "why_not_evaluable": format_why_not_evaluable(completeness),
        "honesty": (
            "One packet per candidate for the decision engine. "
            "Completeness is deterministic; Ollama advises on bounded evidence only."
        ),
    }
    if data_dir:
        try:
            from atlas.investment.data_plane_contract import build_symbol_evidence_view

            pkt["evidence_view"] = build_symbol_evidence_view(
                data_dir,
                symbol,
                laboratory_id=laboratory_id,
                program_id=program_id,
                awareness=aw,
            )
        except Exception:  # noqa: BLE001
            _log.debug("evidence_view attach skipped", exc_info=True)
    return pkt


def evaluate_evidence_completeness(
    *,
    symbol: str,
    laboratory_id: str,
    awareness: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    provider_health: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
    program_id: str = "market_intelligence",
) -> dict[str, Any]:
    """Deterministic completeness for one candidate under one lab contract."""
    sym = str(symbol or "").strip().upper()
    aw = awareness if isinstance(awareness, dict) else {}
    mkt = market if isinstance(market, dict) else {}
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    meta = meta if isinstance(meta, dict) else {}
    if data_dir:
        fund, mkt = hydrate_completeness_inputs(
            data_dir,
            sym,
            program_id=program_id,
            fundamentals=fund,
            market=mkt,
        )
    contract = decision_data_contract(laboratory_id, cfg=cfg)
    kind = str(contract.get("lab_kind") or LAB_UNCONSTRAINED)

    assessed: list[dict[str, Any]] = []
    for spec in contract.get("items") or []:
        key = str(spec.get("key") or "")
        req = bool(spec.get("required"))
        mat = bool(spec.get("material"))
        label = str(spec.get("label") or key)
        if kind in {LAB_INTRADAY, LAB_FNO}:
            status, value, source, as_of = _assess_live_item(
                key, symbol=sym, market=mkt, provider_health=provider_health, kind=kind
            )
        else:
            status, value, source, as_of = _assess_swing_item(
                key,
                awareness=aw,
                market=mkt,
                fundamentals=fund,
                meta=meta,
            )
        assessed.append(
            _item(
                key,
                status=status,
                required=req,
                material=mat,
                label=label,
                value=value,
                source=source,
                as_of=as_of,
            )
        )

    missing = [x for x in assessed if x["status"] == ST_MISSING]
    stale = [x for x in assessed if x["status"] == ST_STALE]
    conflicting = [x for x in assessed if x["status"] == ST_CONFLICTING]
    invalid = [x for x in assessed if x["status"] == ST_INVALID]
    required_missing = [x for x in missing if x.get("required")]
    material_missing = [x for x in missing if x.get("material")]

    required_n = sum(1 for x in assessed if x.get("required"))
    required_ok = sum(
        1
        for x in assessed
        if x.get("required") and x["status"] in {ST_AVAILABLE, ST_NOT_APPLICABLE}
    )
    usable_pct = round(100.0 * required_ok / required_n, 1) if required_n else 100.0

    evaluable = not required_missing and not invalid and not conflicting
    if any(x.get("required") and x["status"] == ST_STALE for x in assessed):
        if kind in {LAB_INTRADAY, LAB_FNO}:
            evaluable = False

    paths: list[str] = []
    if evaluable:
        paths.append("COMPLETE → evaluate")
    else:
        for x in material_missing:
            paths.append(f"INCOMPLETE → acquire {x['key']} (material)")
        for x in required_missing:
            if x not in material_missing:
                paths.append(f"INCOMPLETE → acquire {x['key']} (required)")
        for x in conflicting:
            paths.append(f"INCOMPLETE → resolve conflict {x['key']}")
        for x in invalid:
            paths.append(f"INCOMPLETE → reject invalid {x['key']}")
        for x in missing:
            if not x.get("material") and not x.get("required"):
                paths.append(f"NOT_WORTHWHILE → {x['key']} optional")

    return {
        "version": VERSION,
        "kind": "EVIDENCE_COMPLETENESS",
        "symbol": sym,
        "laboratory_id": laboratory_id,
        "lab_kind": kind,
        "strategy_contract": contract.get("strategy_contract"),
        "as_of_ist": ist_today(),
        "recorded_at": _now_iso(),
        "decision_evaluable": evaluable,
        "decision": "EVALUABLE" if evaluable else "NOT_EVALUABLE",
        "usable_evidence_pct": usable_pct,
        "required_n": required_n,
        "required_ok_n": required_ok,
        "items": assessed,
        "missing": [x["key"] for x in missing],
        "required_missing": [x["key"] for x in required_missing],
        "material_missing": [x["key"] for x in material_missing],
        "stale": [x["key"] for x in stale],
        "conflicting": [x["key"] for x in conflicting],
        "invalid": [x["key"] for x in invalid],
        "paths": paths,
        "acquisition_codes": [
            _UQ_CODE[k]
            for k in dict.fromkeys(
                [x["key"] for x in material_missing]
                + [x["key"] for x in required_missing]
            )
            if k in _UQ_CODE
        ],
        "market_data_plane": contract.get("market_data_plane"),
        "honesty": (
            "Deterministic data contract — Ollama does not decide completeness. "
            "Missing required evidence → NOT_EVALUABLE, not silent HOLD-as-knowing."
        ),
        "never_invents": True,
    }


def format_why_not_evaluable(doc: dict[str, Any]) -> str:
    """Operator-facing mechanical answer: why can't you decide?"""
    sym = doc.get("symbol") or "?"
    if doc.get("decision_evaluable"):
        return (
            f"{sym}: EVALUABLE — required evidence {doc.get('required_ok_n')}/"
            f"{doc.get('required_n')} ({doc.get('usable_evidence_pct')}%)."
        )
    lines = [
        f"{sym}: NOT_EVALUABLE",
        f"  required_missing: {', '.join(doc.get('required_missing') or []) or '—'}",
        f"  material_missing: {', '.join(doc.get('material_missing') or []) or '—'}",
        f"  stale: {', '.join(doc.get('stale') or []) or '—'}",
        f"  conflicting: {', '.join(doc.get('conflicting') or []) or '—'}",
        f"  invalid: {', '.join(doc.get('invalid') or []) or '—'}",
        f"  usable_evidence: {doc.get('usable_evidence_pct')}%",
    ]
    codes = doc.get("acquisition_codes") or []
    if codes:
        lines.append(f"  acquisition: PENDING ({', '.join(codes)})")
    return "\n".join(lines)


def apply_completeness_to_uncertainty(
    data_dir: str | Path | None,
    doc: dict[str, Any],
) -> dict[str, Any]:
    """Material missing → acquisition tasks."""
    if not data_dir or not isinstance(doc, dict):
        return {"ok": False, "created_ids": []}
    from atlas.investment.uncertainty_queue import enqueue_from_unknowns

    lab = str(doc.get("laboratory_id") or "")
    sym = str(doc.get("symbol") or "")
    codes = list(doc.get("acquisition_codes") or [])
    created = enqueue_from_unknowns(
        data_dir, laboratory_id=lab, symbol=sym, unknowns=codes
    )
    optional_missing = [
        x["key"]
        for x in (doc.get("items") or [])
        if x.get("status") == ST_MISSING
        and not x.get("required")
        and not x.get("material")
    ]
    return {
        "ok": True,
        "created_ids": created.get("created_ids") or [],
        "optional_missing": optional_missing,
        "pending_n": created.get("pending_n"),
    }


def persist_completeness(
    data_dir: str | Path | None,
    doc: dict[str, Any],
) -> Path | None:
    if not data_dir or not isinstance(doc, dict):
        return None
    lab = _safe(str(doc.get("laboratory_id") or "lab"))
    sym = _safe(str(doc.get("symbol") or "SYM"))
    day = str(doc.get("as_of_ist") or ist_today())
    root = Path(data_dir) / STORE_REL / lab
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{day}_{sym}.json"
    try:
        text = json.dumps(doc, indent=2, default=str) + "\n"
        path.write_text(text, encoding="utf-8")
        (root / f"{sym}_latest.json").write_text(text, encoding="utf-8")
        return path
    except OSError:
        _log.debug("completeness persist failed", exc_info=True)
        return None


def lab_completeness_rollup(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Aggregate usable_evidence_pct for a lab/day — not a fake IQ score."""
    day = as_of_ist or ist_today()
    root = Path(data_dir or "") / STORE_REL / _safe(laboratory_id)
    rows: list[dict[str, Any]] = []
    if root.is_dir():
        for p in root.glob(f"{day}_*.json"):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict):
                rows.append(doc)
    if not rows:
        return {
            "version": VERSION,
            "laboratory_id": laboratory_id,
            "as_of_ist": day,
            "n": 0,
            "avg_usable_evidence_pct": None,
            "evaluable_n": 0,
            "not_evaluable_n": 0,
            "honesty": "No completeness packets yet — not an IQ score.",
        }
    pcts = [float(r.get("usable_evidence_pct") or 0) for r in rows]
    return {
        "version": VERSION,
        "laboratory_id": laboratory_id,
        "as_of_ist": day,
        "n": len(rows),
        "avg_usable_evidence_pct": round(sum(pcts) / len(pcts), 1),
        "evaluable_n": sum(1 for r in rows if r.get("decision_evaluable")),
        "not_evaluable_n": sum(1 for r in rows if not r.get("decision_evaluable")),
        "symbols": [
            {
                "symbol": r.get("symbol"),
                "decision": r.get("decision"),
                "pct": r.get("usable_evidence_pct"),
                "missing": r.get("material_missing"),
            }
            for r in rows[:20]
        ],
        "honesty": (
            "required evidence vs usable evidence — gaps have reasons; "
            "not a composite IQ / activity score."
        ),
    }
