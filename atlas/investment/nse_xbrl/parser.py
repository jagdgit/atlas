"""XBRL/XML → canonical facts. Taxonomy-agnostic local-name map (not one-company XML)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

CONCEPT_MAP: dict[str, str] = {
    "profitaftertax": "NET_INCOME",
    "profitloss": "NET_INCOME",
    "profitfortheperiod": "NET_INCOME",
    "profitlossforperiod": "NET_INCOME",
    "profitlossforperiodfromcontinuingoperations": "NET_INCOME",
    "netprofit": "NET_INCOME",
    "profitfromcontinuingoperations": "NET_INCOME",
    "profitorlossattributabletoownersofparent": "NET_INCOME_OWNERS",
    "profitorlossattributabletononcontrollinginterests": "NET_INCOME_NCI",
    "totalequity": "TOTAL_EQUITY",
    "equity": "TOTAL_EQUITY",
    "shareholdersequity": "TOTAL_EQUITY",
    "equityattributabletoowners": "TOTAL_EQUITY",
    "equityattributabletoownersofparent": "TOTAL_EQUITY",
    "shorttermborrowings": "SHORT_TERM_BORROWINGS",
    "borrowingscurrent": "SHORT_TERM_BORROWINGS",
    "longtermborrowings": "LONG_TERM_BORROWINGS",
    "borrowingsnoncurrent": "LONG_TERM_BORROWINGS",
    "currentmaturitiesoflongtermdebt": "CURRENT_MATURITIES_LT_DEBT",
    "totalborrowings": "TOTAL_DEBT",
    "totaldebt": "TOTAL_DEBT",
    "totalliabilities": "TOTAL_LIABILITIES",
    "liabilities": "TOTAL_LIABILITIES",
    "leaseliabilities": "LEASE_LIABILITIES",
    "leaseliabilitiescurrent": "LEASE_LIABILITIES",
    "leaseliabilitiesnoncurrent": "LEASE_LIABILITIES",
    "currentleaseliabilities": "LEASE_LIABILITIES",
    "noncurrentleaseliabilities": "LEASE_LIABILITIES",
    "cashflowsfromoperatingactivities": "OPERATING_CASH_FLOW",
    "cashflowsfromusedinoperatingactivities": "OPERATING_CASH_FLOW",
    "netcashfromoperatingactivities": "OPERATING_CASH_FLOW",
    "operatingcashflow": "OPERATING_CASH_FLOW",
    "purchaseofppe": "CAPITAL_EXPENDITURE",
    "purchaseofpropertyplantequipment": "CAPITAL_EXPENDITURE",
    "purchaseofpropertyplantandequipmentclassifiedasinvestingactivities": "CAPITAL_EXPENDITURE",
    "capitalexpenditure": "CAPITAL_EXPENDITURE",
    "capex": "CAPITAL_EXPENDITURE",
    "dilutedeps": "REPORTED_EPS",
    "basiceps": "REPORTED_EPS",
    "earningspershare": "REPORTED_EPS",
    "dilutedearningslosspersharefromcontinuinganddiscontinuedoperations": "REPORTED_EPS",
    "basicearningslosspersharefromcontinuinganddiscontinuedoperations": "REPORTED_EPS",
    "weightedaveragenumberofdilutedshares": "SHARES_OUTSTANDING",
    "dilutedshares": "SHARES_OUTSTANDING",
    "numberofshares": "SHARES_OUTSTANDING",
    "paidupsharecapitalshares": "SHARES_OUTSTANDING",
    "paidupvalueofequitysharecapital": "PAID_UP_EQUITY_CAPITAL",
    "facevalueofequitysharecapital": "FACE_VALUE_PER_SHARE",
}


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if ":" in tag:
        return tag.split(":", 1)[-1]
    return tag


def _norm_name(tag: str) -> str:
    return "".join(ch for ch in _local(tag).lower() if ch.isalnum())


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_xbrl(
    xml_text: str | bytes,
    *,
    symbol: str,
    source_document: str | None = None,
    filed_at: str | None = None,
    available_at: str | None = None,
    default_scope: str = "CONSOLIDATED",
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    raw = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    rid = _hash(raw)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {
            "ok": False,
            "status": "RETRY",
            "reason": "malformed_xbrl",
            "error": str(exc)[:200],
            "raw_evidence_id": rid,
            "facts": [],
        }

    contexts: dict[str, dict[str, Any]] = {}
    for el in root.iter():
        if _norm_name(el.tag) != "context":
            continue
        cid = el.get("id") or ""
        period_type = "FY"
        start = end = instant = None
        for child in el.iter():
            n = _norm_name(child.tag)
            if n == "startdate" and child.text:
                start = child.text.strip()[:10]
            elif n == "enddate" and child.text:
                end = child.text.strip()[:10]
            elif n == "instant" and child.text:
                instant = child.text.strip()[:10]
                period_type = "INSTANT"
        if start and end:
            try:
                from datetime import date as _date

                a = _date.fromisoformat(start)
                b = _date.fromisoformat(end)
                days = (b - a).days
                period_type = "Q" if days <= 120 else "FY"
            except ValueError:
                period_type = "FY"
        if instant and not end:
            end = instant
            start = instant
        scope = default_scope
        scen = " ".join((el.itertext() or []))
        if "STANDALONE" in scen.upper() or "STAND ALONE" in scen.upper():
            scope = "STANDALONE"
        if "CONSOLIDATED" in scen.upper():
            scope = "CONSOLIDATED"
        contexts[cid] = {
            "period_start": start,
            "period_end": end,
            "period_type": period_type,
            "scope": scope,
        }

    facts: list[dict[str, Any]] = []
    errors: list[str] = []
    for el in root.iter():
        field = CONCEPT_MAP.get(_norm_name(el.tag))
        if not field:
            continue
        ctx = contexts.get(el.get("contextRef") or "", {})
        text = (el.text or "").strip().replace(",", "")
        if not text:
            errors.append(f"empty:{field}")
            continue
        try:
            value = float(text)
        except ValueError:
            errors.append(f"non_numeric:{field}")
            continue
        unit = (el.get("unitRef") or "INR").upper()
        dec = el.get("decimals")
        scale = 1
        try:
            if dec is not None and str(dec) not in {"INF", "inf"}:
                d = int(dec)
                if d < 0:
                    scale = 10 ** abs(d)
        except ValueError:
            pass
        facts.append(
            {
                "symbol": str(symbol or "").upper(),
                "canonical_field": field,
                "value": value,
                "unit": unit,
                "scale": scale,
                "period_start": ctx.get("period_start"),
                "period_end": ctx.get("period_end"),
                "period_type": ctx.get("period_type") or "FY",
                "scope": ctx.get("scope") or default_scope,
                "source": "NSE_XBRL",
                "source_document": source_document,
                "filed_at": filed_at,
                "available_at": available_at or filed_at,
                "retrieved_at": retrieved,
                "raw_evidence_id": rid,
                "mapping_id": _local(el.tag),
            }
        )

    if not facts:
        return {
            "ok": False,
            "status": "RETRY",
            "reason": "no_mapped_facts",
            "raw_evidence_id": rid,
            "facts": [],
            "errors": errors[:12],
        }
    return {
        "ok": True,
        "status": "PARSED",
        "raw_evidence_id": rid,
        "facts": facts,
        "errors": errors[:12],
        "fact_n": len(facts),
    }
