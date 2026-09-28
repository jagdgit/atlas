"""Atlas-calculated PE / ROE / D/E / FCF with explicit formulas (L27–L30)."""

from __future__ import annotations

from typing import Any

DEBT_DEFINITION_ID = "atlas.debt.total_borrowings.v1"
EPS_TTM = "TTM"
EPS_FY = "FY"
EPS_UNKNOWN = "UNKNOWN"

_DEBT_COMPONENTS = (
    "SHORT_TERM_BORROWINGS",
    "LONG_TERM_BORROWINGS",
    "CURRENT_MATURITIES_LT_DEBT",
)
_DEBT_EXCLUDED = (
    "LEASE_LIABILITIES",
    "TRADE_PAYABLES",
    "OTHER_FINANCIAL_LIABILITIES",
    "TOTAL_LIABILITIES",
    "DEPOSITS",
)


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_capex(reported: Any) -> dict[str, Any]:
    """Canonical CAPEX is a positive economic outflow. Keep original sign."""
    raw = _f(reported)
    if raw is None:
        return {
            "ok": False,
            "reason": "capex_missing",
            "reported": None,
            "capex_normalized": None,
        }
    if raw < 0:
        return {
            "ok": True,
            "reported": raw,
            "capex_normalized": abs(raw),
            "normalization": "NEGATIVE_OUTFLOW_TO_POSITIVE",
        }
    return {
        "ok": True,
        "reported": raw,
        "capex_normalized": raw,
        "normalization": "ALREADY_POSITIVE",
    }


def _facts_by_field(facts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        key = str(f.get("canonical_field") or "").upper()
        if not key:
            continue
        out.setdefault(key, []).append(f)
    return out


def _latest(
    rows: list[dict[str, Any]],
    *,
    period_type: str | None = None,
    strict: bool = False,
) -> dict[str, Any] | None:
    cand = list(rows or [])
    if period_type:
        want = str(period_type).upper()
        filtered = [r for r in cand if str(r.get("period_type") or "").upper() == want]
        if filtered:
            cand = filtered
        elif strict:
            return None
    cand.sort(key=lambda r: str(r.get("period_end") or ""), reverse=True)
    return cand[0] if cand else None


def _equity_snapshots(
    rows: list[dict[str, Any]],
    *,
    prefer: str = "owners",
) -> list[dict[str, Any]]:
    """One TOTAL_EQUITY fact per period_end.

    prefer=owners → EquityAttributableToOwnersOfParent over total Equity.
    prefer=total → generic Equity / TotalEquity over owners-of-parent.
    """
    want_owners = prefer != "total"
    by_end: dict[str, tuple[int, dict[str, Any]]] = {}
    for r in rows or []:
        end = str(r.get("period_end") or "")
        if not end:
            continue
        mid = str(r.get("mapping_id") or "").replace("_", "").lower()
        is_owners = "ownersofparent" in mid or "attributabletoowners" in mid
        is_total = mid in {"equity", "totalequity"}
        if want_owners:
            score = 2 if is_owners else (0 if is_total else 1)
        else:
            score = 2 if is_total else (0 if is_owners else 1)
        prev = by_end.get(end)
        if prev is None or score > prev[0]:
            by_end[end] = (score, r)
    out = [pair[1] for pair in by_end.values()]
    out.sort(key=lambda r: str(r.get("period_end") or ""))
    return out


def _relative_gap(a: float | None, b: float | None) -> float:
    if a is None or b is None:
        return 0.0
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom


def _ifindas_borrowings_tag(mapping_id: str | None) -> bool:
    mid = "".join(ch for ch in str(mapping_id or "") if ch.isalnum()).lower()
    return mid in {"borrowingscurrent", "borrowingsnoncurrent"}


def _collapse_period(
    rows: list[dict[str, Any]],
    *,
    prefer_mapping: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """One fact per (period_end, period_type, scope). Prefer listed local-names."""
    prefer = tuple(p.lower() for p in prefer_mapping)
    by: dict[tuple[str, str, str], tuple[int, dict[str, Any]]] = {}
    for r in rows or []:
        key = (
            str(r.get("period_end") or ""),
            str(r.get("period_type") or "").upper(),
            str(r.get("scope") or "").upper(),
        )
        if not key[0]:
            continue
        mid = "".join(ch for ch in str(r.get("mapping_id") or "") if ch.isalnum()).lower()
        score = 0
        for i, token in enumerate(prefer):
            if mid == token:
                score = 1000 - i
                break
        if score == 0:
            for i, token in enumerate(prefer):
                if token and token in mid:
                    score = 100 - i
                    break
        prev = by.get(key)
        if prev is None or score > prev[0]:
            by[key] = (score, r)
    out = [pair[1] for pair in by.values()]
    out.sort(key=lambda r: str(r.get("period_end") or ""))
    return out


def calculate_metrics(
    facts: list[dict[str, Any]] | None,
    *,
    price: float | None = None,
    eps_fy_fallback: bool = False,
    evidence_as_of: str | None = None,
) -> dict[str, Any]:
    """Return derived metrics. Missing inputs → UNKNOWN, never 0."""
    from atlas.investment.nse_xbrl.as_of import fact_usable_as_of

    usable: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for f in facts or []:
        chk = fact_usable_as_of(f, evidence_as_of=evidence_as_of)
        if chk.get("ok"):
            usable.append(f)
        else:
            excluded.append({**f, "as_of_reject": chk.get("reason")})
    by = _facts_by_field(usable)
    out: dict[str, Any] = {
        "version": "nse.calc.v1",
        "excluded_look_ahead_n": len(excluded),
        "metrics": {},
        "unknown": [],
        "conflicts": [],
    }

    # --- EPS / PE ---
    ni_rows = _collapse_period(
        by.get("NET_INCOME") or [],
        prefer_mapping=("profitlossforperiod", "profitaftertax", "profitloss"),
    )
    q_pat = [
        f
        for f in ni_rows
        if str(f.get("period_type") or "").upper() in {"Q", "QUARTER"}
    ]
    q_pat.sort(key=lambda r: str(r.get("period_end") or ""))
    q_ends = []
    q_unique: list[dict[str, Any]] = []
    for f in q_pat:
        end = str(f.get("period_end") or "")
        if end and end not in q_ends:
            q_ends.append(end)
            q_unique.append(f)
    q_pat = q_unique
    fy_pat = _latest(ni_rows, period_type="FY", strict=True)
    shares = _latest(by.get("SHARES_OUTSTANDING") or []) or _latest(
        by.get("DILUTED_SHARES") or []
    )
    shares_n = _f((shares or {}).get("value"))
    if shares_n is None or shares_n <= 0:
        paid = _latest(by.get("PAID_UP_EQUITY_CAPITAL") or [])
        face = _latest(by.get("FACE_VALUE_PER_SHARE") or [])
        paid_v = _f((paid or {}).get("value"))
        face_v = _f((face or {}).get("value"))
        if paid_v is not None and face_v is not None and face_v > 0:
            shares_n = paid_v / face_v
            shares = {
                "value": shares_n,
                "mapping_id": "paid_up_div_face_value",
                "period_end": (paid or {}).get("period_end"),
            }
    reported_rows = _collapse_period(
        by.get("REPORTED_EPS") or [],
        prefer_mapping=(
            "dilutedearningslosspersharefromcontinuinganddiscontinuedoperations",
            "dilutedeps",
        ),
    )
    reported_eps = _latest(reported_rows, period_type="TTM", strict=True) or _latest(
        reported_rows, period_type="FY", strict=True
    )
    if reported_eps is not None and abs(_f(reported_eps.get("value")) or 0.0) <= 1e-12:
        reported_eps = None
    eps_basis = EPS_UNKNOWN
    eps_val: float | None = None
    eps_inputs: dict[str, Any] = {}
    if len(q_pat) >= 4 and shares_n and shares_n > 0:
        ttm_pat = sum(_f(x.get("value")) or 0.0 for x in q_pat[-4:])
        eps_val = ttm_pat / shares_n
        eps_basis = EPS_TTM
        eps_inputs = {
            "pat_quarters": [_f(x.get("value")) for x in q_pat[-4:]],
            "shares": shares_n,
            "periods": [x.get("period_end") for x in q_pat[-4:]],
        }
    elif reported_eps is not None and str(reported_eps.get("period_type") or "").upper() in {
        "TTM",
        "FY",
    }:
        eps_val = _f(reported_eps.get("value"))
        eps_basis = str(reported_eps.get("period_type") or EPS_FY).upper()
        if eps_basis == "TTM":
            eps_basis = EPS_TTM
        eps_inputs = {"reported_eps": eps_val, "source_fact": reported_eps.get("mapping_id")}
    elif eps_fy_fallback and fy_pat is not None and shares_n and shares_n > 0:
        pat = _f(fy_pat.get("value"))
        if pat is not None:
            eps_val = pat / shares_n
            eps_basis = EPS_FY
            eps_inputs = {
                "pat_fy": pat,
                "shares": shares_n,
                "period": fy_pat.get("period_end"),
                "eps_fy_fallback": True,
            }
    elif fy_pat is not None and len(q_pat) == 1:
        out["unknown"].append("eps_quarterly_as_annual_rejected")
    if eps_val is None:
        out["unknown"].append("eps")
        out["metrics"]["eps"] = {
            "status": "UNKNOWN",
            "eps_basis": eps_basis,
            "reason": "ttm_incomplete" if not eps_fy_fallback else "no_pat_shares",
        }
    else:
        if eps_basis == EPS_TTM:
            formula = "TTM_PAT / shares"
        elif "reported_eps" in eps_inputs:
            formula = "reported_diluted_eps"
        else:
            formula = "FY_PAT / shares"
        out["metrics"]["eps"] = {
            "status": "VALID",
            "value": eps_val,
            "eps_basis": eps_basis,
            "formula": formula,
            "inputs": eps_inputs,
            "value_type": "derived",
        }
    px = _f(price)
    if eps_val is not None and eps_val <= 0:
        out["metrics"]["pe"] = {
            "status": "UNKNOWN",
            "reason": "non_positive_eps",
            "eps_basis": eps_basis,
            "eps": eps_val,
        }
        out["unknown"].append("pe")
    elif px is None or px <= 0 or eps_val is None or eps_val == 0:
        out["metrics"]["pe"] = {
            "status": "UNKNOWN",
            "reason": "price_or_eps_missing",
            "eps_basis": eps_basis,
        }
        out["unknown"].append("pe")
    else:
        out["metrics"]["pe"] = {
            "status": "VALID",
            "value": px / eps_val,
            "eps_basis": eps_basis,
            "formula": "price / EPS",
            "inputs": {"price": px, "eps": eps_val, "price_source": "zerodha_or_replay"},
            "value_type": "derived",
        }

    # --- ROE: average equity, same income/equity scope (L28) ---
    owners_eq = _equity_snapshots(by.get("TOTAL_EQUITY") or [], prefer="owners")
    total_eq = _equity_snapshots(by.get("TOTAL_EQUITY") or [], prefer="total")
    owners_ni = _latest(by.get("NET_INCOME_OWNERS") or [], period_type="FY", strict=True)
    owners_end = _f((owners_eq[-1].get("value") if owners_eq else None))
    total_end = _f((total_eq[-1].get("value") if total_eq else None))
    end_eq = owners_eq[-1] if owners_eq else (total_eq[-1] if total_eq else None)
    end_pe = str((end_eq or {}).get("period_end") or "")
    if owners_ni is not None and end_pe and str(owners_ni.get("period_end") or "") != end_pe:
        # Prior-year attributable PAT is not this year's ROE numerator.
        owners_ni = None
    if fy_pat is not None and end_pe and str(fy_pat.get("period_end") or "") != end_pe:
        matched = [
            r
            for r in ni_rows
            if str(r.get("period_type") or "").upper() == "FY"
            and str(r.get("period_end") or "") == end_pe
        ]
        fy_pat = matched[0] if matched else None
    nci_material = _relative_gap(owners_end, total_end) > 0.02
    ni = None
    equity_rows: list[dict[str, Any]] = []
    roe_scope = None
    if owners_ni is not None and len(owners_eq) >= 2:
        ni = owners_ni
        equity_rows = owners_eq
        roe_scope = "owners_of_parent"
    elif fy_pat is not None and nci_material and owners_ni is None and len(owners_eq) >= 2:
        out["conflicts"].append(
            {
                "conflict_type": "SCOPE",
                "field": "roe",
                "note": (
                    "Group PAT with parent equity while NCI is material and "
                    "attributable PAT is missing."
                ),
            }
        )
        out["metrics"]["roe"] = {
            "status": "UNKNOWN",
            "reason": "scope_mismatch",
            "honesty": "Do not mix consolidated PAT with equity attributable to owners.",
        }
        out["unknown"].append("roe")
    elif fy_pat is not None and len(owners_eq) >= 2:
        ni = fy_pat
        equity_rows = owners_eq
        roe_scope = "owners_of_parent_immaterial_nci"
    elif fy_pat is not None and len(total_eq) >= 2:
        ni = fy_pat
        equity_rows = total_eq
        roe_scope = "consolidated_total"
    ni_v = _f((ni or {}).get("value"))
    if out["metrics"].get("roe"):
        pass
    elif len(equity_rows) >= 2 and ni_v is not None:
        begin = equity_rows[-2]
        end = equity_rows[-1]
        b = _f(begin.get("value"))
        e = _f(end.get("value"))
        scope_ok = str(begin.get("scope") or "") == str(end.get("scope") or "") and str(
            (ni or {}).get("scope") or ""
        ) in {str(begin.get("scope") or ""), ""}
        if b is None or e is None or (b + e) == 0:
            out["metrics"]["roe"] = {"status": "UNKNOWN", "reason": "zero_equity"}
            out["unknown"].append("roe")
        elif not scope_ok and str(begin.get("scope") or "") != str(end.get("scope") or ""):
            out["metrics"]["roe"] = {"status": "UNKNOWN", "reason": "scope_mismatch"}
            out["unknown"].append("roe")
        else:
            avg = (b + e) / 2.0
            out["metrics"]["roe"] = {
                "status": "VALID",
                "value": (ni_v / avg) * 100.0 if abs(avg) > 1e-12 else None,
                "unit": "pct",
                "formula": (
                    "NET_INCOME_OWNERS / ((begin_equity + end_equity) / 2)"
                    if roe_scope == "owners_of_parent"
                    else "NET_INCOME / ((begin_equity + end_equity) / 2)"
                ),
                "inputs": {
                    "net_income": ni_v,
                    "beginning_equity": b,
                    "ending_equity": e,
                    "average_equity": avg,
                    "begin_period": begin.get("period_end"),
                    "end_period": end.get("period_end"),
                    "numerator_period": (ni or {}).get("period_end"),
                    "numerator_mapping": (ni or {}).get("mapping_id"),
                    "scope": roe_scope or end.get("scope"),
                },
                "value_type": "derived",
            }
            if out["metrics"]["roe"]["value"] is None:
                out["metrics"]["roe"] = {"status": "UNKNOWN", "reason": "zero_equity"}
                out["unknown"].append("roe")
    else:
        out["metrics"]["roe"] = {
            "status": "UNKNOWN",
            "reason": "need_beginning_and_ending_equity",
        }
        out["unknown"].append("roe")

    # --- D/E ---
    eq_snaps = _equity_snapshots(by.get("TOTAL_EQUITY") or [], prefer="owners")
    end_eq = eq_snaps[-1] if eq_snaps else None
    eq_v = _f((end_eq or {}).get("value"))
    debt_parts: dict[str, float] = {}
    debt_maps: list[str] = []
    for name in _DEBT_COMPONENTS:
        row = _latest(by.get(name) or [])
        val = _f((row or {}).get("value"))
        if val is not None:
            debt_parts[name] = val
            debt_maps.append(str((row or {}).get("mapping_id") or name))
    total_debt_fact = _latest(by.get("TOTAL_DEBT") or [])
    lease_rows = [
        r
        for r in (by.get("LEASE_LIABILITIES") or [])
        if str(r.get("period_end") or "") == str((end_eq or {}).get("period_end") or "")
        or not (end_eq or {}).get("period_end")
    ]
    lease_total = 0.0
    lease_found = False
    for r in lease_rows:
        lv = _f(r.get("value"))
        if lv is None:
            continue
        lease_found = True
        lease_total += lv
    if debt_parts:
        total_debt = sum(debt_parts.values())
        mapping = "sum_components"
        ifindas = any(_ifindas_borrowings_tag(m) for m in debt_maps)
        if lease_found and ifindas and total_debt >= lease_total:
            total_debt = total_debt - lease_total
            mapping = "ifindas_borrowings_minus_leases"
            debt_parts["LEASE_LIABILITIES_EXCLUDED"] = lease_total
        elif lease_found and not ifindas:
            debt_parts["LEASE_LIABILITIES_NOT_IN_DEBT"] = lease_total
        elif ifindas and not lease_found and total_debt is not None and total_debt > 1e-9:
            out["conflicts"].append(
                {
                    "conflict_type": "DEBT_DEFINITION",
                    "field": "debt_to_equity",
                    "note": (
                        "IFIndAs BorrowingsCurrent/Noncurrent may include Ind AS 116 "
                        "lease liabilities; no separate lease fact in this instance. "
                        f"{DEBT_DEFINITION_ID} excludes leases."
                    ),
                }
            )
    elif total_debt_fact is not None:
        total_debt = _f(total_debt_fact.get("value"))
        mapping = "TOTAL_DEBT_fact"
    else:
        total_debt = None
        mapping = None
    liab = _latest(by.get("TOTAL_LIABILITIES") or [])
    liab_v = _f((liab or {}).get("value"))
    if (
        total_debt is not None
        and liab_v is not None
        and abs(total_debt - liab_v) < 1e-6
        and mapping != "TOTAL_DEBT_fact"
    ):
        out["conflicts"].append(
            {
                "conflict_type": "DEBT_DEFINITION",
                "note": "component sum equals TOTAL_LIABILITIES — review mapping",
            }
        )
    # Hard fail if the only "debt" fact is TOTAL_LIABILITIES
    if total_debt is None and liab_v is not None and not debt_parts:
        out["metrics"]["debt_to_equity"] = {
            "status": "UNKNOWN",
            "reason": "total_liabilities_is_not_total_debt",
            "definition_id": DEBT_DEFINITION_ID,
            "excluded": list(_DEBT_EXCLUDED),
        }
        out["unknown"].append("debt_to_equity")
    elif total_debt is None or eq_v is None or eq_v == 0:
        out["metrics"]["debt_to_equity"] = {
            "status": "UNKNOWN",
            "reason": "debt_or_equity_missing",
            "definition_id": DEBT_DEFINITION_ID,
        }
        out["unknown"].append("debt_to_equity")
    else:
        out["metrics"]["debt_to_equity"] = {
            "status": "VALID",
            "value": total_debt / eq_v,
            "definition_id": DEBT_DEFINITION_ID,
            "formula": "TOTAL_DEBT / TOTAL_EQUITY",
            "inputs": {
                "total_debt": total_debt,
                "equity": eq_v,
                "components": debt_parts,
                "mapping": mapping,
                "total_liabilities": liab_v,
                "leases_separable": lease_found,
            },
            "excluded": list(_DEBT_EXCLUDED),
            "value_type": "derived",
        }

    # --- FCF ---
    cfo_f = _latest(by.get("OPERATING_CASH_FLOW") or [], period_type="FY", strict=True)
    cap_f = _latest(by.get("CAPITAL_EXPENDITURE") or [], period_type="FY", strict=True)
    cfo = _f((cfo_f or {}).get("value"))
    cap_n = normalize_capex((cap_f or {}).get("value") if cap_f else None)
    if cfo is None or not cap_n.get("ok"):
        out["metrics"]["fcf"] = {
            "status": "UNKNOWN",
            "reason": "cfo_or_capex_missing",
            "formula": "cfo - capex_normalized",
        }
        out["unknown"].append("fcf")
    else:
        capex = float(cap_n["capex_normalized"])
        fcf = cfo - capex
        out["metrics"]["fcf"] = {
            "status": "VALID",
            "value": fcf,
            "value_type": "derived",
            "formula": "cfo - capex_normalized",
            "inputs": {
                "operating_cash_flow": cfo,
                "capital_expenditures_reported": cap_n["reported"],
                "capex_normalized": capex,
                "normalization": cap_n["normalization"],
            },
        }

    return out
