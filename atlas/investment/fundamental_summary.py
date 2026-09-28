"""M4 Step 4 — canonical fundamentals → deterministic validated summary.

No LLM. No raw XBRL parse. The fundamentals store is the source of truth.
UNKNOWN stays UNKNOWN. Conflicts stay recorded. Invalid evidence is not a metric.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from atlas.investment.nse_xbrl.calculations import DEBT_DEFINITION_ID
from atlas.investment.nse_xbrl.coverage import PLC_A_FIELDS, fundamentals_coverage
from atlas.investment.nse_xbrl.identity import resolve_identity, resolve_nse_code
from atlas.investment.plc_buy_gates import evaluate_fundamental_sanity

VERSION = "m4.step4.fundamental_summary.v1"
CLAIM_TYPE = "fundamental_summary"
KIND = "fundamental_summary"

CALCULATION_IDS = {
    "pe": "atlas.pe.price_over_eps.v1",
    "eps": "atlas.eps.v1",
    "roe": "atlas.roe.average_equity.v1",
    "debt_to_equity": DEBT_DEFINITION_ID,
    "fcf": "atlas.fcf.cfo_minus_capex.v1",
}

_PE_GAP = 0.05  # absolute PE points that count as a recorded conflict


def _f(v: Any) -> float | None:
    if v is None or v == "" or v == "UNKNOWN":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round(v: float, n: int) -> float:
    return round(float(v), n)


def _evidence_items(row: dict[str, Any], field: str) -> list[dict[str, Any]]:
    ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    items = ev.get(field) or []
    return [i for i in items if isinstance(i, dict)]


def _evidence_values(row: dict[str, Any], field: str) -> list[float]:
    out: list[float] = []
    for item in _evidence_items(row, field):
        val = _f(item.get("value"))
        if val is not None:
            out.append(val)
    return out


def _latest_recorded_at(row: dict[str, Any]) -> str | None:
    latest = ""
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    for items in evidence.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            ts = str(item.get("recorded_at") or "").strip()
            if ts > latest:
                latest = ts
    return latest or None


def _conflict_entries(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("evidence_conflicts") or row.get("conflicts") or []
    if not isinstance(raw, list):
        raw = [raw]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, dict):
            ctype = str(item.get("conflict_type") or item.get("type") or "").strip()
            field = str(item.get("field") or "").strip()
            note = str(item.get("note") or item.get("reason") or "").strip()
            key = f"{ctype}|{field}|{note}"
            if not ctype or key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "conflict_type": ctype,
                    "field": field or None,
                    "note": note or None,
                    "status": "CONFLICT",
                }
            )
            continue
        if isinstance(item, str) and item.strip():
            token = item.strip()
            if token in seen:
                continue
            seen.add(token)
            field = "pe" if token.lower().startswith("pe") else None
            out.append(
                {
                    "conflict_type": token,
                    "field": field,
                    "note": None,
                    "status": "CONFLICT",
                }
            )
    return out


def _pe_evidence_conflict(row: dict[str, Any]) -> dict[str, Any] | None:
    vals = _evidence_values(row, "pe")
    uniq: list[float] = []
    for v in vals:
        if not any(abs(v - u) < _PE_GAP for u in uniq):
            uniq.append(v)
    if len(uniq) < 2:
        return None
    shown = [_round(v, 2) for v in uniq]
    return {
        "conflict_type": "PE_EVIDENCE",
        "field": "pe",
        "values": shown,
        "note": f"PE evidence conflict: {shown[0]} vs {shown[1]}",
        "status": "CONFLICT",
    }


def _metric(
    *,
    field: str,
    status: str,
    value: float | None = None,
    reason: str | None = None,
    basis: str | None = None,
    source: str | None = None,
    raw_evidence_id: str | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "field": field,
        "status": status,
        "value": value if status != "UNKNOWN" else None,
        "reason": reason,
        "basis": basis,
        "source": source,
        "calculation_id": CALCULATION_IDS.get(field),
        "raw_evidence_id": raw_evidence_id,
    }
    if extras:
        out.update(extras)
    return out


def _fmt_pe(v: float) -> str:
    return f"{_round(v, 2):.2f}"


def _fmt_roe(v: float) -> str:
    return f"{_round(v, 2):.2f}%"


def _fmt_de(v: float) -> str:
    return f"{_round(v, 3):.3f}"


def _fmt_fcf(v: float) -> str:
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return str(v)


def snapshot_fingerprint(value: dict[str, Any]) -> str:
    """Stable hash of the canonical state. Excludes generated_at."""
    blob = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _build_statement(value: dict[str, Any]) -> str:
    sym = str(value.get("symbol") or "")
    ticker = sym.replace(".NS", "").replace(".BO", "")
    ident = value.get("identity") if isinstance(value.get("identity"), dict) else {}
    name = ident.get("name") or ticker
    sector = ident.get("sector") or "UNKNOWN"
    mets = value.get("metrics") if isinstance(value.get("metrics"), dict) else {}
    pe = mets.get("pe") or {}
    roe = mets.get("roe") or {}
    de = mets.get("debt_to_equity") or {}
    fcf = mets.get("fcf") or {}
    plc = str(value.get("plc_a_state") or "INCOMPLETE")
    parts: list[str] = [
        f"Validated fundamental_summary for {ticker} ({name}, sector {sector}).",
        f"evidence_as_of {value.get('evidence_as_of')} fundamental_as_of {value.get('fundamental_as_of')}.",
        f"source {value.get('source')} canonical_filing_id {value.get('canonical_filing_id')}.",
    ]
    if plc == "COMPLETE":
        parts.append(
            f"{ticker} PLC.A completeness COMPLETE: required PE ROE debt_to_equity sector "
            f"are present so {ticker} can pass PLC.A field completeness, subject to recorded "
            "conflicts. This finding does not authorize a BUY or SELL."
        )
    else:
        reason = value.get("plc_a_blocking_reason") or "fundamentals_incomplete"
        parts.append(
            f"{ticker} PLC.A completeness INCOMPLETE: {ticker} is still blocked "
            f"({reason}). This finding does not authorize a BUY or SELL."
        )
    if pe.get("status") == "UNKNOWN":
        reason = pe.get("reason") or "missing"
        stale = pe.get("stale_invalid")
        parts.append(
            f"{ticker} PE is UNKNOWN because {reason}. PE is not 0. "
            "Invalid or stale PE evidence must not be used as the canonical PE."
        )
        if stale is not None:
            parts.append(
                f"Stale invalid PE evidence {stale} is not canonical and must not be cited as PE."
            )
    elif pe.get("status") == "CONFLICT":
        parts.append(
            f"{ticker} PE canonical value is {pe.get('display')} "
            f"(basis {pe.get('basis')}, source {pe.get('source')}) and a PE conflict is recorded; "
            "do not silently choose a winner."
        )
    elif pe.get("value") is not None:
        parts.append(
            f"{ticker} PE is {pe.get('display')} basis {pe.get('basis')} source {pe.get('source')}."
        )
    if roe.get("status") in {"VALID", "CONFLICT"} and roe.get("value") is not None:
        parts.append(f"{ticker} ROE is {roe.get('display')} basis average equity.")
    if de.get("status") in {"VALID", "CONFLICT"} and de.get("value") is not None:
        parts.append(
            f"{ticker} D/E is {de.get('display')} definition_id {DEBT_DEFINITION_ID}."
        )
    if fcf.get("status") in {"VALID", "CONFLICT"} and fcf.get("value") is not None:
        parts.append(f"{ticker} FCF is {fcf.get('display')} (CFO minus CapEx).")
    conflicts = value.get("conflicts") or []
    if conflicts:
        labels = []
        for c in conflicts:
            if not isinstance(c, dict):
                continue
            note = c.get("note") or c.get("conflict_type")
            if note:
                labels.append(str(note))
        if labels:
            parts.append(f"Conflicts exist for {ticker}: " + "; ".join(labels) + ".")
    parts.append(str(value.get("interpretation") or ""))
    return " ".join(p for p in parts if p).strip()


def build_fundamental_summary(
    row: dict[str, Any] | None,
    *,
    generated_at: str | None = None,
    identity: dict[str, Any] | None = None,
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Construct a deterministic summary from one canonical store row. No LLM."""
    del generated_at  # provenance clock is applied by the publisher, not the body
    fund = dict(row) if isinstance(row, dict) else {}
    symbol = str(fund.get("symbol") or "").strip()
    ident = (
        identity
        if isinstance(identity, dict)
        else resolve_identity(symbol, data_dir=data_dir, fundamentals=fund)
    )
    source = str(fund.get("source") or "fundamentals_store")
    raw_id = str(fund.get("nse_raw_evidence_id") or fund.get("canonical_filing_id") or "") or None
    as_of = str(fund.get("as_of") or "").strip() or None
    evidence_as_of = _latest_recorded_at(fund) or as_of
    eps_basis = str(fund.get("eps_basis") or "").strip() or None

    conflicts = _conflict_entries(fund)
    pe_conflict = _pe_evidence_conflict(fund)
    if pe_conflict and not any(
        c.get("conflict_type") == "PE_EVIDENCE"
        or str(c.get("conflict_type", "")).lower() == "pe_conflict"
        for c in conflicts
    ):
        conflicts.append(pe_conflict)
    if pe_conflict:
        conflicts = [
            c
            for c in conflicts
            if str(c.get("conflict_type") or "").lower() != "pe_conflict"
        ]
        if not any(c.get("conflict_type") == "PE_EVIDENCE" for c in conflicts):
            conflicts.append(pe_conflict)

    raw_pe = _f(fund.get("pe") if fund.get("pe") is not None else fund.get("trailing_pe"))
    pe_val = raw_pe if raw_pe is not None and raw_pe > 0 else None
    roe_val = _f(fund.get("roe"))
    de_val = _f(
        fund.get("debt_to_equity")
        if fund.get("debt_to_equity") is not None
        else fund.get("debt_equity")
    )
    fcf_val = _f(fund.get("fcf") if fund.get("fcf") is not None else fund.get("free_cash_flow"))
    eps_val = _f(fund.get("eps"))

    pe_vals = _evidence_values(fund, "pe")
    stale_pe = None
    if pe_val is None and pe_vals:
        stale_pe = _round(pe_vals[-1], 2)

    pe_reason = None
    if pe_val is None:
        if eps_val is not None and eps_val <= 0:
            pe_reason = "non_positive_eps"
        elif stale_pe is not None and stale_pe < 0:
            pe_reason = "non_positive_eps"
        elif raw_pe is not None and raw_pe <= 0:
            pe_reason = "non_positive_pe"
        else:
            pe_reason = "missing"

    pe_status = "UNKNOWN" if pe_val is None else ("CONFLICT" if pe_conflict else "VALID")
    de_conflict = any(str(c.get("conflict_type") or "") == "DEBT_DEFINITION" for c in conflicts)
    de_status = "UNKNOWN" if de_val is None else ("CONFLICT" if de_conflict else "VALID")
    roe_status = "UNKNOWN" if roe_val is None else "VALID"
    fcf_status = "UNKNOWN" if fcf_val is None else "VALID"
    if eps_val is None:
        eps_status = "UNKNOWN"
        eps_reason = "not_on_canonical_row" if pe_reason == "non_positive_eps" else "missing"
    elif eps_val <= 0:
        eps_status = "VALID"
        eps_reason = "non_positive_eps"
    else:
        eps_status = "VALID"
        eps_reason = None

    metrics = {
        "pe": _metric(
            field="pe",
            status=pe_status,
            value=pe_val,
            reason=pe_reason,
            basis=eps_basis,
            source=source,
            raw_evidence_id=raw_id,
            extras={
                "display": _fmt_pe(pe_val) if pe_val is not None else "UNKNOWN",
                "stale_invalid": stale_pe,
            },
        ),
        "roe": _metric(
            field="roe",
            status=roe_status,
            value=roe_val,
            basis="average_equity",
            source=source,
            raw_evidence_id=raw_id,
            extras={"display": _fmt_roe(roe_val) if roe_val is not None else "UNKNOWN"},
        ),
        "debt_to_equity": _metric(
            field="debt_to_equity",
            status=de_status,
            value=de_val,
            source=source,
            raw_evidence_id=raw_id,
            extras={
                "display": _fmt_de(de_val) if de_val is not None else "UNKNOWN",
                "definition_id": DEBT_DEFINITION_ID,
            },
        ),
        "fcf": _metric(
            field="fcf",
            status=fcf_status,
            value=fcf_val,
            basis="cfo_minus_capex",
            source=source,
            raw_evidence_id=raw_id,
            extras={"display": _fmt_fcf(fcf_val) if fcf_val is not None else "UNKNOWN"},
        ),
        "eps": _metric(
            field="eps",
            status=eps_status,
            value=eps_val if eps_status != "UNKNOWN" else None,
            reason=eps_reason,
            basis=eps_basis,
            source=source,
            raw_evidence_id=raw_id,
        ),
    }

    sector = ident.get("sector") or fund.get("sector")
    coverage = fundamentals_coverage(fundamentals=fund, identity=ident)
    sanity = evaluate_fundamental_sanity(fund, sector=sector)
    plc_complete = bool(coverage.get("plc_a_complete") and sanity.get("ok"))
    missing = list(sanity.get("missing") or coverage.get("plc_a_missing") or [])
    blocking = None
    if not plc_complete:
        if "pe" in missing or pe_status == "UNKNOWN":
            blocking = "PE_UNKNOWN"
            if pe_reason:
                blocking = f"PE_UNKNOWN / {pe_reason}"
        else:
            blocking = str(sanity.get("code") or "fundamentals_incomplete")

    if conflicts:
        knowledge_status = "CONFLICT"
    elif any(metrics[f]["status"] == "UNKNOWN" for f in ("pe", "roe", "debt_to_equity")):
        knowledge_status = "UNKNOWN"
    else:
        knowledge_status = "VALID"

    interpretation = (
        "PLC.A-required fundamental fields are present, subject to recorded conflicts."
        if plc_complete
        else (
            "PLC.A is blocked until UNKNOWN required fields are resolved. "
            "Invalid evidence is not a substitute."
        )
    )
    value: dict[str, Any] = {
        "kind": KIND,
        "symbol": symbol,
        "knowledge_status": knowledge_status,
        "plc_a_state": "COMPLETE" if plc_complete else "INCOMPLETE",
        "plc_a_blocking_reason": blocking,
        "fundamental_as_of": as_of,
        "evidence_as_of": evidence_as_of,
        "canonical_filing_id": raw_id,
        "source": source,
        "identity": {
            "name": ident.get("name") or fund.get("name"),
            "sector": sector,
            "nse_code": resolve_nse_code(symbol) or ident.get("nse_symbol"),
            "source": ident.get("source"),
        },
        "metrics": metrics,
        "conflicts": conflicts,
        "interpretation": interpretation,
        "plc_a_fields": list(PLC_A_FIELDS),
        "version": VERSION,
    }
    statement = _build_statement(value)
    return {
        "statement": statement,
        "value": value,
        "claim_type": CLAIM_TYPE,
        "domain": "research",
        "fingerprint": snapshot_fingerprint(value),
        "version": VERSION,
    }
