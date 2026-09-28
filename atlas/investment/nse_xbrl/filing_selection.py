"""Deterministic filing selection (L32). Two runs must pick the same canonical filing."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

VERSION = "nse.filing_selection.v1"
DEFAULT_SCOPE = "CONSOLIDATED"


def _d(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _scope(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if "STAND" in s:
        return "STANDALONE"
    return "CONSOLIDATED"


def is_fy_filing(filing: dict[str, Any] | None) -> bool:
    """Annual / FY statement vs a quarter. Do not treat Q1 as canonical for PE/ROE/D/E/FCF."""
    f = filing if isinstance(filing, dict) else {}
    kind = str(f.get("period_kind") or f.get("period_type") or "").upper()
    if kind in {"FY", "ANNUAL", "YEARLY", "Y"}:
        return True
    ftype = str(f.get("filing_type") or f.get("submission_type") or "").upper()
    if "ANNUAL" in ftype:
        return True
    try:
        dur = f.get("duration_days")
        if dur is not None and float(dur) >= 300:
            return True
    except (TypeError, ValueError):
        pass
    start = _d(f.get("period_start") or f.get("from_date"))
    end = _d(f.get("period_end"))
    if start and end and (end - start).days + 1 >= 300:
        return True
    audited = str(f.get("audited") or "").strip().lower() in {"audited", "true", "1"}
    if audited and end is not None and end.month in {3, 12} and end.day >= 28:
        return True
    return False


def select_canonical_filing(
    filings: list[dict[str, Any]] | None,
    *,
    scope: str = DEFAULT_SCOPE,
    period_end: str | date | None = None,
    evidence_as_of: str | date | None = None,
    prefer_audited: bool = False,
) -> dict[str, Any]:
    """Pick one canonical filing; keep superseded in the input list (caller stores all raw).

    Order:
    1. identity already bound on each filing (symbol)
    2. required scope (CONSOLIDATED default; STANDALONE only if that is all that exists)
    3. required period_end when given
    4. available_at / filed_at ≤ evidence_as_of when given
    5. reject superseded
    6. annual / FY over later quarterly
    7. latest revision (revision_n, then broadcast/available_at)
    8. audited when prefer_audited
    """
    want_scope = _scope(scope)
    want_end = _d(period_end)
    as_of = _d(evidence_as_of)
    rows = [dict(f) for f in (filings or []) if isinstance(f, dict)]
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for f in rows:
        reason = None
        if f.get("superseded") or str(f.get("status") or "").lower() in {
            "superseded",
            "withdrawn",
        }:
            reason = "superseded"
        avail = _d(f.get("available_at") or f.get("filed_at") or f.get("broadcast_time"))
        if reason is None and as_of is not None and avail is not None and avail > as_of:
            reason = "available_after_evidence_as_of"
        if reason is None and want_end is not None:
            end = _d(f.get("period_end"))
            if end is not None and end != want_end:
                reason = "period_mismatch"
        if reason:
            rejected.append({**f, "reject_reason": reason})
            continue
        eligible.append(f)

    scoped = [f for f in eligible if _scope(f.get("scope")) == want_scope]
    if not scoped:
        scoped = list(eligible)
        used_scope = _scope((scoped[0].get("scope") if scoped else want_scope))
    else:
        used_scope = want_scope

    def _key(f: dict[str, Any]) -> tuple[Any, ...]:
        audited = 1 if str(f.get("audited") or f.get("submission_type") or "").lower() in {
            "audited",
            "true",
            "1",
        } else 0
        rev = int(f.get("revision_n") or f.get("revision") or 0)
        avail = _d(f.get("available_at") or f.get("filed_at") or f.get("broadcast_time"))
        end = _d(f.get("period_end")) or date.min
        return (
            1 if is_fy_filing(f) else 0,
            audited if prefer_audited else 0,
            rev,
            avail or date.min,
            end,
        )

    scoped.sort(key=_key, reverse=True)
    canonical = dict(scoped[0]) if scoped else None
    if canonical is not None:
        canonical["canonical"] = True
        canonical["filing_selection"] = VERSION
        canonical["selected_scope"] = used_scope
    return {
        "version": VERSION,
        "ok": canonical is not None,
        "canonical": canonical,
        "eligible_n": len(scoped),
        "rejected": rejected,
        "reason": None if canonical is not None else "no_eligible_filing",
    }
