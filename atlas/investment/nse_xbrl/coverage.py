"""PLC.A + swing completeness field coverage (L37). Do not stop after the first ratio."""

from __future__ import annotations

from typing import Any

# Every field this vertical slice must attempt for a swing PLC.A candidate.
PLC_A_FIELDS = ("pe", "roe", "debt_to_equity", "sector")
SLICE_FIELDS = ("pe", "roe", "debt_to_equity", "fcf", "sector", "identity")
IRA_ONLY = ("mos",)
RESEARCH_ONLY = ("thesis",)


def _present(v: Any) -> bool:
    if v is None or v == "" or v == "UNKNOWN":
        return False
    return True


def fundamentals_coverage(
    *,
    fundamentals: dict[str, Any] | None,
    identity: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    ident = identity if isinstance(identity, dict) else {}
    mets = (metrics or {}).get("metrics") if isinstance(metrics, dict) else {}
    if not isinstance(mets, dict):
        mets = {}

    def _status(field: str) -> dict[str, Any]:
        if field == "sector":
            ok = bool(ident.get("sector_ok") or _present(fund.get("sector")))
            return {
                "field": field,
                "ok": ok,
                "value": ident.get("sector") or fund.get("sector"),
                "source": ident.get("source") or fund.get("source"),
            }
        if field == "identity":
            ok = bool(ident.get("identity_ok"))
            return {
                "field": field,
                "ok": ok,
                "value": ident.get("name"),
                "source": ident.get("source"),
            }
        m = mets.get(field) if isinstance(mets.get(field), dict) else {}
        if m.get("status") == "VALID" and m.get("value") is not None:
            return {
                "field": field,
                "ok": True,
                "value": m.get("value"),
                "source": "nse_xbrl_calc",
            }
        aliases = {
            "fcf": ("fcf", "free_cash_flow"),
            "debt_to_equity": ("debt_to_equity", "debt_equity", "d_e"),
        }
        for a in aliases.get(field, (field,)):
            if _present(fund.get(a)):
                return {"field": field, "ok": True, "value": fund.get(a), "source": fund.get("source")}
        return {
            "field": field,
            "ok": False,
            "value": None,
            "reason": (m.get("reason") if m else "missing"),
        }

    rows = [_status(f) for f in SLICE_FIELDS]
    missing = [r["field"] for r in rows if not r["ok"]]
    plc_missing = [f for f in PLC_A_FIELDS if f in missing or (
        f == "sector" and not (ident.get("sector_ok") or _present(fund.get("sector")))
    )]
    return {
        "version": "nse.coverage.v1",
        "required": list(SLICE_FIELDS),
        "plc_a": list(PLC_A_FIELDS),
        "fields": rows,
        "missing": missing,
        "plc_a_missing": [r["field"] for r in rows if r["field"] in PLC_A_FIELDS and not r["ok"]],
        "complete": not missing,
        "plc_a_complete": not [r for r in rows if r["field"] in PLC_A_FIELDS and not r["ok"]],
        "ira_not_nse": list(IRA_ONLY),
        "research_not_nse": list(RESEARCH_ONLY),
        "honesty": (
            "Slice attempts PE/ROE/D/E/FCF/sector/identity. MoS is IRA. "
            "Thesis is research. A ratio-only pass is not N1."
        ),
    }
