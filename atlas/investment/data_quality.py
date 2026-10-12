"""Canonical data-quality envelope and current capability state.

A number that exists in a store is not a trusted decision input.
Web snippets are never financial facts. Missing stays unknown, never zero.
Historical capability failures stay in the audit trail.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "data.quality.v1"
STORE_REL = Path("investment") / "data_quality"
_log = logging.getLogger("atlas.investment.data_quality")

Q_UNKNOWN = "UNKNOWN"
Q_AVAILABLE = "AVAILABLE"
Q_TRUSTED = "TRUSTED"
Q_STALE = "STALE"
Q_INVALID = "INVALID"
Q_CONFLICT = "CONFLICT"
Q_PENDING = "PENDING_VALIDATION"
Q_BLOCKED = "BLOCKED"

V_PASSED = "PASSED"
V_FAILED = "FAILED"
V_REJECTED = "REJECTED"
V_NOT_RUN = "NOT_RUN"

F_PASS = "PASS"
F_FAIL = "FAIL"

# Current capability lifecycle. History is append-only.
C_UNKNOWN = "UNKNOWN"
C_INVESTIGATING = "INVESTIGATING"
C_GAP = "CAPABILITY_GAP"
C_WAITING = "WAITING_FOR_CAPABILITY"
C_ACQUIRED = "CAPABILITY_ACQUIRED"
C_VALIDATING = "VALIDATING"
C_AVAILABLE = "AVAILABLE"
C_TRUSTED = "TRUSTED"
C_USABLE = "DECISION_USABLE"

_WEB_PROVIDERS = frozenset(
    {
        "web",
        "web_search",
        "duckduckgo",
        "snippet",
        "web_snippet",
        "news_search",
    }
)
_METRIC_ALIAS = {
    "debt": "debt_to_equity",
    "d_e": "debt_to_equity",
    "debt_equity": "debt_to_equity",
    "free_cash_flow": "fcf",
    "return_on_equity": "roe",
    "trailing_pe": "pe",
}
_UNKNOWN_CODE = {
    "pe": "pe_missing",
    "fcf": "fcf_missing",
    "roe": "roe_missing",
    "debt_to_equity": "debt_missing",
}
_DEBT_DEFINITIONS = {
    "total_borrowings": "atlas.debt.total_borrowings.v1",
    "total_debt": "atlas.debt.total_debt.v1",
    "net_debt": "atlas.debt.net_debt.v1",
}
# Fundamental period is usable while the reporting period end is within this age.
_FUNDAMENTAL_MAX_AGE_DAYS = 548
_PE_PRICE_MAX_AGE_DAYS = 5
_REL_TOL = 1e-4
_CONFLICT_REL = 0.01


def canonical_metric(metric: str | None) -> str:
    key = str(metric or "").strip().lower()
    return _METRIC_ALIAS.get(key, key)


def _now(now: datetime | None = None) -> datetime:
    clock = now if isinstance(now, datetime) else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(timezone.utc)


def _iso(now: datetime | None = None) -> str:
    return _now(now).isoformat()


def _f(v: Any) -> float | None:
    try:
        if v is None or v == "" or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_dt(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return _now(raw)
    text = str(raw or "").strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-":
        try:
            return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        return _now(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def is_web_source(provider: str | None, source: str | None = None) -> bool:
    blob = f"{provider or ''} {source or ''}".lower()
    return any(tok in blob.split() or tok in blob for tok in _WEB_PROVIDERS)


def freshness_policy(metric: str) -> dict[str, Any]:
    """Metric-specific freshness. There is no single global TTL."""
    key = canonical_metric(metric)
    if key in {"ltp", "live_price", "price"}:
        return {"metric": key, "kind": "max_age_seconds", "max_age_seconds": 180}
    if key in {"intraday_bar", "bars_intraday"}:
        return {"metric": key, "kind": "bar_interval_seconds", "max_age_seconds": 300}
    if key in {"daily_bar", "price_history"}:
        return {"metric": key, "kind": "trading_day", "max_age_days": 5}
    if key == "pe":
        return {
            "metric": key,
            "kind": "financial_period_plus_price",
            "max_period_age_days": _FUNDAMENTAL_MAX_AGE_DAYS,
            "max_price_age_days": _PE_PRICE_MAX_AGE_DAYS,
        }
    if key in {"roe", "debt_to_equity", "fcf"}:
        return {
            "metric": key,
            "kind": "financial_period",
            "max_period_age_days": _FUNDAMENTAL_MAX_AGE_DAYS,
        }
    if key in {"news", "company_news"}:
        return {"metric": key, "kind": "event_timestamp", "max_age_days": 7}
    if key in {"sector_rs", "relative_strength"}:
        return {"metric": key, "kind": "lookback_window", "max_age_days": 30}
    return {"metric": key, "kind": "unspecified", "max_age_days": None}


def _age_days(moment: datetime | None, now: datetime) -> float | None:
    if moment is None:
        return None
    return (now - moment).total_seconds() / 86400.0


def assess_freshness(record: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    clock = _now(now)
    policy = freshness_policy(str(record.get("metric") or ""))
    kind = policy.get("kind")
    period = _parse_dt(record.get("period_end") or record.get("as_of") or record.get("period"))
    price_as_of = _parse_dt(record.get("price_as_of"))
    retrieved = _parse_dt(record.get("retrieved_at"))
    if kind == "max_age_seconds":
        anchor = retrieved or price_as_of or period
        if anchor is None:
            return {"freshness": F_FAIL, "reason": "timestamp_missing", "policy": policy}
        age = (clock - anchor).total_seconds()
        if age < -5:
            return {"freshness": F_FAIL, "reason": "timestamp_in_future", "policy": policy}
        if age > float(policy["max_age_seconds"]):
            return {"freshness": F_FAIL, "reason": "STALE", "policy": policy, "age_seconds": age}
        return {"freshness": F_PASS, "policy": policy, "age_seconds": age}
    if kind == "financial_period_plus_price":
        if period is None:
            return {"freshness": F_FAIL, "reason": "period_missing", "policy": policy}
        if _age_days(period, clock) is not None and _age_days(period, clock) > float(
            policy["max_period_age_days"]
        ):
            return {"freshness": F_FAIL, "reason": "STALE", "policy": policy}
        if price_as_of is None:
            return {"freshness": F_FAIL, "reason": "price_date_missing", "policy": policy}
        if _age_days(price_as_of, clock) > float(policy["max_price_age_days"]):
            return {"freshness": F_FAIL, "reason": "STALE", "policy": policy}
        return {"freshness": F_PASS, "policy": policy}
    if kind == "financial_period":
        if period is None:
            return {"freshness": F_FAIL, "reason": "period_missing", "policy": policy}
        age = _age_days(period, clock)
        if age is not None and age > float(policy["max_period_age_days"]):
            return {"freshness": F_FAIL, "reason": "STALE", "policy": policy}
        return {"freshness": F_PASS, "policy": policy}
    if retrieved is None and period is None:
        return {"freshness": F_FAIL, "reason": "timestamp_missing", "policy": policy}
    return {"freshness": F_PASS, "policy": policy}


def _close(a: float | None, b: float | None, *, tol: float = _REL_TOL) -> bool:
    if a is None or b is None:
        return False
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= tol


def validate_fundamental(record: dict[str, Any]) -> dict[str, Any]:
    """Deterministic checks. Failure never substitutes zero or another metric."""
    metric = canonical_metric(record.get("metric"))
    components = record.get("components") if isinstance(record.get("components"), dict) else {}
    value = _f(record.get("value"))
    if is_web_source(record.get("provider"), record.get("source")):
        return {
            "validation_status": V_REJECTED,
            "reason": "web_snippets_are_not_a_structured_value",
            "trusted": False,
        }
    if metric == "pe":
        price = _f(components.get("price"))
        eps = _f(components.get("eps"))
        if record.get("period_type") in {None, ""} or record.get("eps_basis") in {None, ""}:
            if not components.get("eps_basis") and not record.get("period_type"):
                return {"validation_status": V_NOT_RUN, "reason": "eps_period_undefined", "trusted": False}
        basis = str(record.get("period_type") or record.get("eps_basis") or components.get("eps_basis") or "")
        if "TTM" in basis.upper() and "FY" in basis.upper():
            return {"validation_status": V_FAILED, "reason": "mixed_eps_periods", "trusted": False}
        if eps is None or price is None:
            return {"validation_status": V_NOT_RUN, "reason": "pe_inputs_missing", "trusted": False}
        if eps == 0:
            return {"validation_status": V_FAILED, "reason": "zero_or_invalid_eps", "trusted": False}
        unit = str(record.get("unit") or "ratio").lower()
        if unit not in {"ratio", "x", "multiple", ""}:
            return {"validation_status": V_FAILED, "reason": "unit_mismatch", "trusted": False}
        calc = price / eps
        if value is None or not _close(value, calc, tol=1e-3):
            return {
                "validation_status": V_FAILED,
                "reason": "pe_calculation_inconsistent",
                "trusted": False,
                "calculated": calc,
            }
        if not record.get("evidence_id"):
            return {"validation_status": V_FAILED, "reason": "missing_evidence", "trusted": False}
        return {"validation_status": V_PASSED, "reason": "pe_price_over_eps", "trusted": True, "calculated": calc}
    if metric == "roe":
        profit = _f(components.get("profit") if "profit" in components else components.get("net_income"))
        equity = _f(components.get("equity"))
        if profit is None or equity is None:
            return {"validation_status": V_NOT_RUN, "reason": "roe_inputs_missing", "trusted": False}
        if equity == 0:
            return {"validation_status": V_FAILED, "reason": "zero_equity", "trusted": False}
        if not (record.get("period") or record.get("period_end")):
            return {"validation_status": V_FAILED, "reason": "accounting_period_missing", "trusted": False}
        calc = profit / equity
        unit = str(record.get("unit") or "").lower()
        if unit in {"pct", "percent", "%"}:
            calc = calc * 100.0
        if value is None or not _close(value, calc, tol=1e-3):
            return {"validation_status": V_FAILED, "reason": "roe_calculation_inconsistent", "trusted": False}
        if not record.get("evidence_id"):
            return {"validation_status": V_FAILED, "reason": "missing_evidence", "trusted": False}
        return {"validation_status": V_PASSED, "reason": "roe_profit_over_equity", "trusted": True}
    if metric == "debt_to_equity":
        definition = str(
            components.get("debt_definition") or record.get("debt_definition") or ""
        ).strip().lower()
        if definition not in _DEBT_DEFINITIONS:
            return {
                "validation_status": V_NOT_RUN,
                "reason": "debt_definition_undefined",
                "trusted": False,
            }
        debt = _f(components.get("debt"))
        equity = _f(components.get("equity"))
        if components.get("substituted_from"):
            return {
                "validation_status": V_FAILED,
                "reason": "debt_definition_substituted",
                "trusted": False,
            }
        if debt is None or equity is None:
            return {"validation_status": V_NOT_RUN, "reason": "debt_inputs_missing", "trusted": False}
        if equity == 0:
            return {"validation_status": V_FAILED, "reason": "zero_equity", "trusted": False}
        calc = debt / equity
        if value is None or not _close(value, calc, tol=1e-3):
            return {"validation_status": V_FAILED, "reason": "debt_calculation_inconsistent", "trusted": False}
        if not record.get("evidence_id"):
            return {"validation_status": V_FAILED, "reason": "missing_evidence", "trusted": False}
        return {
            "validation_status": V_PASSED,
            "reason": _DEBT_DEFINITIONS[definition],
            "trusted": True,
            "debt_definition": definition,
        }
    if metric == "fcf":
        ocf = _f(components.get("operating_cash_flow"))
        capex_raw = components.get("capex")
        if ocf is None or capex_raw is None:
            return {"validation_status": V_NOT_RUN, "reason": "fcf_inputs_missing", "trusted": False}
        from atlas.investment.nse_xbrl.calculations import normalize_capex

        capex = normalize_capex(capex_raw)
        if not capex.get("ok"):
            return {"validation_status": V_FAILED, "reason": "capex_missing", "trusted": False}
        calc = ocf - float(capex["capex_normalized"])
        if value is None or not _close(value, calc, tol=1e-4):
            return {"validation_status": V_FAILED, "reason": "fcf_calculation_inconsistent", "trusted": False}
        if not record.get("evidence_id"):
            return {"validation_status": V_FAILED, "reason": "missing_evidence", "trusted": False}
        return {
            "validation_status": V_PASSED,
            "reason": "fcf_ocf_minus_capex",
            "trusted": True,
            "components": {
                "operating_cash_flow": ocf,
                "capex_normalized": capex.get("capex_normalized"),
                "capex_reported": capex.get("reported"),
            },
        }
    if value is None:
        return {"validation_status": V_NOT_RUN, "reason": "value_missing", "trusted": False}
    return {"validation_status": V_NOT_RUN, "reason": "no_validator", "trusted": False}


def classify_cross_source(
    left: float | None,
    right: float | None,
    *,
    kind: str = "fundamental",
) -> str:
    """MATCH, EXPECTED_DIFFERENCE, SUSPICIOUS, or CONFLICT. Does not pick a winner."""
    a = _f(left)
    b = _f(right)
    if a is None or b is None:
        return "CONFLICT"
    denom = max(abs(a), abs(b), 1e-12)
    gap = abs(a - b) / denom
    if kind == "price":
        if gap <= 0.002:
            return "MATCH"
        if gap <= 0.01:
            return "EXPECTED_DIFFERENCE"
        if gap <= 0.03:
            return "SUSPICIOUS"
        return "CONFLICT"
    if gap <= _REL_TOL:
        return "MATCH"
    if gap <= _CONFLICT_REL:
        return "EXPECTED_DIFFERENCE"
    return "CONFLICT"


def envelope(
    *,
    symbol: str,
    metric: str,
    value: Any = None,
    unit: str | None = None,
    currency: str | None = None,
    period: str | None = None,
    period_type: str | None = None,
    period_end: str | None = None,
    as_of: str | None = None,
    price_as_of: str | None = None,
    retrieved_at: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    evidence_id: str | None = None,
    calculation_method: str | None = None,
    components: dict[str, Any] | None = None,
    debt_definition: str | None = None,
    eps_basis: str | None = None,
    laboratory_id: str = "india_equity_learner",
    now: datetime | None = None,
) -> dict[str, Any]:
    metric_key = canonical_metric(metric)
    rec: dict[str, Any] = {
        "version": VERSION,
        "symbol": str(symbol or "").strip().upper(),
        "metric": metric_key,
        "laboratory_id": laboratory_id,
        "value": _f(value) if metric_key in {"pe", "roe", "fcf", "debt_to_equity", "ltp", "price"} else value,
        "unit": unit,
        "currency": currency,
        "period": period,
        "period_type": period_type or eps_basis,
        "period_end": period_end or (period if period and len(str(period)) == 10 else None),
        "as_of": as_of,
        "price_as_of": price_as_of,
        "retrieved_at": retrieved_at or _iso(now),
        "provider": provider,
        "source": source,
        "evidence_id": evidence_id,
        "calculation_method": calculation_method,
        "components": dict(components or {}),
        "debt_definition": debt_definition,
        "eps_basis": eps_basis,
        "freshness_policy": freshness_policy(metric_key),
        "quality_status": Q_UNKNOWN,
        "validation_status": V_NOT_RUN,
        "confidence": None,
        "acquired": False,
        "fresh": False,
        "decision_compatible": False,
        "usable": False,
        "reason": None,
    }
    return classify_record(rec, now=now)


def classify_record(record: dict[str, Any], *, now: datetime | None = None, peers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rec = dict(record)
    rec["metric"] = canonical_metric(rec.get("metric"))
    if is_web_source(rec.get("provider"), rec.get("source")):
        rec["value"] = None
        rec["acquired"] = False
        rec["quality_status"] = Q_BLOCKED
        rec["validation_status"] = V_REJECTED
        rec["fresh"] = False
        rec["decision_compatible"] = False
        rec["usable"] = False
        rec["confidence"] = None
        rec["reason"] = "web_snippets_are_not_a_structured_value"
        return rec
    validation = validate_fundamental(rec)
    fresh = assess_freshness(rec, now=now)
    rec["validation_status"] = validation.get("validation_status")
    rec["calculation_method"] = rec.get("calculation_method") or validation.get("reason")
    peer_class = None
    for peer in peers or []:
        if is_web_source(peer.get("provider"), peer.get("source")):
            continue
        if canonical_metric(peer.get("metric")) != rec["metric"]:
            continue
        if str(peer.get("provider") or "") == str(rec.get("provider") or ""):
            continue
        peer_class = classify_cross_source(rec.get("value"), peer.get("value"))
        if peer_class == "CONFLICT":
            break
    if rec.get("value") is None and validation.get("validation_status") != V_PASSED:
        rec["acquired"] = False
        rec["quality_status"] = Q_UNKNOWN
        rec["usable"] = False
        rec["fresh"] = False
        rec["decision_compatible"] = False
        rec["reason"] = rec.get("reason") or validation.get("reason") or "value_missing"
        return rec
    rec["acquired"] = rec.get("value") is not None or validation.get("validation_status") == V_PASSED
    if validation.get("validation_status") == V_FAILED or validation.get("validation_status") == V_REJECTED:
        rec["quality_status"] = Q_INVALID
        rec["usable"] = False
        rec["fresh"] = fresh.get("freshness") == F_PASS
        rec["decision_compatible"] = False
        rec["reason"] = validation.get("reason")
        rec["confidence"] = None
        return rec
    if peer_class == "CONFLICT":
        rec["quality_status"] = Q_CONFLICT
        rec["usable"] = False
        rec["fresh"] = fresh.get("freshness") == F_PASS
        rec["decision_compatible"] = False
        rec["reason"] = "provider_conflict"
        rec["confidence"] = None
        return rec
    if fresh.get("freshness") != F_PASS and validation.get("validation_status") == V_PASSED:
        rec["quality_status"] = Q_STALE
        rec["acquired"] = True
        rec["fresh"] = False
        rec["decision_compatible"] = False
        rec["usable"] = False
        rec["reason"] = fresh.get("reason") or "STALE"
        rec["confidence"] = "historical"
        return rec
    if validation.get("validation_status") == V_PASSED and fresh.get("freshness") == F_PASS:
        rec["quality_status"] = Q_TRUSTED
        rec["acquired"] = True
        rec["fresh"] = True
        rec["decision_compatible"] = True
        rec["usable"] = True
        rec["reason"] = validation.get("reason")
        rec["confidence"] = "validated"
        return rec
    rec["quality_status"] = Q_PENDING
    rec["acquired"] = rec.get("value") is not None
    rec["fresh"] = False
    rec["decision_compatible"] = False
    rec["usable"] = False
    rec["reason"] = validation.get("reason") or fresh.get("reason") or "pending_validation"
    rec["confidence"] = None
    return rec


def decision_may_consume(record: dict[str, Any] | None) -> bool:
    """Decision inputs may use only a fresh trusted record. Never unknown/stale/invalid/conflict."""
    if not isinstance(record, dict):
        return False
    if record.get("value") is None:
        return False
    if str(record.get("quality_status") or "") != Q_TRUSTED:
        return False
    if str(record.get("validation_status") or "") != V_PASSED:
        return False
    if record.get("usable") is not True or record.get("fresh") is not True:
        return False
    if record.get("decision_compatible") is not True:
        return False
    if is_web_source(record.get("provider"), record.get("source")):
        return False
    return True


def _registry_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL / "registry.json"


def _audit_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL / "audit.jsonl"


def load_registry(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {"version": VERSION, "current": {}}
    path = _registry_path(data_dir)
    if not path.is_file():
        return {"version": VERSION, "current": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": VERSION, "current": {}}
    if not isinstance(doc, dict):
        return {"version": VERSION, "current": {}}
    doc.setdefault("current", {})
    return doc


def _key(laboratory_id: str, symbol: str, metric: str) -> str:
    return f"{laboratory_id}|{str(symbol or '').upper()}|{canonical_metric(metric)}"


def _save_registry(data_dir: str | Path, doc: dict[str, Any]) -> None:
    path = _registry_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")


def _append_audit(data_dir: str | Path, event: dict[str, Any]) -> None:
    path = _audit_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def _capability_state_for(record: dict[str, Any]) -> str:
    if record.get("usable") and record.get("quality_status") == Q_TRUSTED:
        return C_USABLE
    if record.get("quality_status") == Q_TRUSTED:
        return C_TRUSTED
    if record.get("quality_status") == Q_AVAILABLE:
        return C_AVAILABLE
    if record.get("acquired") and record.get("quality_status") == Q_PENDING:
        return C_ACQUIRED
    if record.get("quality_status") == Q_STALE:
        return C_AVAILABLE
    if record.get("quality_status") in {Q_INVALID, Q_CONFLICT, Q_BLOCKED}:
        return C_WAITING
    return C_UNKNOWN


def commit_record(
    data_dir: str | Path,
    record: dict[str, Any],
    *,
    laboratory_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist current capability. Prior failures stay in the audit and on the row history."""
    lab = laboratory_id or str(record.get("laboratory_id") or "india_equity_learner")
    reg = load_registry(data_dir)
    key = _key(lab, str(record.get("symbol") or ""), str(record.get("metric") or ""))
    prev = reg["current"].get(key) if isinstance(reg["current"].get(key), dict) else None
    prev_rec = prev.get("record") if isinstance(prev, dict) else None
    peers = [prev_rec] if isinstance(prev_rec, dict) else []
    rec = classify_record(record, now=now, peers=peers)
    rec["laboratory_id"] = lab
    if (
        prev
        and prev.get("quality_status") == Q_TRUSTED
        and rec.get("quality_status") == Q_CONFLICT
    ):
        # Keep the trusted row as history and surface the conflict as current.
        pass
    if (
        prev
        and prev.get("quality_status") in {Q_TRUSTED, Q_CONFLICT}
        and rec.get("validation_status") != V_PASSED
        and not rec.get("usable")
    ):
        _append_audit(
            data_dir,
            {
                "at": _iso(now),
                "key": key,
                "event": "rejected_candidate",
                "reason": rec.get("reason"),
                "provider": rec.get("provider"),
            },
        )
        return {"ok": False, "rejected": True, "current": prev, "candidate": rec}
    history = list((prev or {}).get("history") or [])
    if prev:
        history.append(
            {
                "at": prev.get("validated_at") or prev.get("updated_at"),
                "current_state": prev.get("current_state"),
                "quality_status": prev.get("quality_status"),
                "failure_reason": prev.get("failure_reason"),
                "evidence_id": prev.get("evidence_id"),
            }
        )
    state = _capability_state_for(rec)
    current = {
        "symbol": rec.get("symbol"),
        "metric": rec.get("metric"),
        "laboratory_id": lab,
        "current_state": state,
        "acquired": bool(rec.get("acquired")),
        "quality_status": rec.get("quality_status"),
        "validation_status": rec.get("validation_status"),
        "fresh": bool(rec.get("fresh")),
        "decision_compatible": bool(rec.get("decision_compatible")),
        "usable": bool(rec.get("usable")),
        "tradable": bool(decision_may_consume(rec)),
        "value": rec.get("value") if decision_may_consume(rec) or rec.get("quality_status") == Q_STALE else (
            rec.get("value") if rec.get("acquired") else None
        ),
        "provider": rec.get("provider"),
        "source": rec.get("source"),
        "evidence_id": rec.get("evidence_id"),
        "period": rec.get("period") or rec.get("period_end"),
        "as_of": rec.get("as_of"),
        "last_success": _iso(now) if rec.get("quality_status") in {Q_TRUSTED, Q_STALE, Q_PENDING, Q_AVAILABLE} and rec.get("acquired") else (prev or {}).get("last_success"),
        "last_failure": (prev or {}).get("last_failure"),
        "failure_reason": (prev or {}).get("failure_reason"),
        "validated_at": _iso(now) if rec.get("quality_status") == Q_TRUSTED else (prev or {}).get("validated_at"),
        "retry_condition": None if rec.get("usable") else (rec.get("reason") or "await_trusted_acquisition"),
        "reason": rec.get("reason"),
        "updated_at": _iso(now),
        "history": history[-30:],
        "record": rec,
    }
    if rec.get("quality_status") in {Q_INVALID, Q_BLOCKED, Q_CONFLICT} or not rec.get("acquired"):
        current["last_failure"] = _iso(now)
        current["failure_reason"] = rec.get("reason")
    reg["current"][key] = current
    _save_registry(data_dir, reg)
    _append_audit(
        data_dir,
        {
            "at": _iso(now),
            "key": key,
            "event": "capability_update",
            "previous_state": (prev or {}).get("current_state"),
            "current_state": state,
            "quality_status": rec.get("quality_status"),
            "reason": rec.get("reason"),
            "evidence_id": rec.get("evidence_id"),
        },
    )
    _sync_uncertainty(data_dir, current)
    return {"ok": True, "current": current, "record": rec}


def note_capability_gap(
    data_dir: str | Path,
    *,
    symbol: str,
    metric: str,
    laboratory_id: str = "india_equity_learner",
    reason: str | None = None,
    attempted: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record a gap without erasing a later trusted current state."""
    reg = load_registry(data_dir)
    key = _key(laboratory_id, symbol, metric)
    prev = reg["current"].get(key) if isinstance(reg["current"].get(key), dict) else None
    # An acquired pending, conflict, stale, or trusted row is the current state.
    # A later "missing" note must not turn it back into a capability gap.
    preserved = prev and (
        (prev.get("usable") and prev.get("quality_status") == Q_TRUSTED)
        or (
            prev.get("quality_status") in {Q_PENDING, Q_CONFLICT, Q_STALE, Q_INVALID, Q_TRUSTED}
            and (prev.get("acquired") or prev.get("value") is not None)
        )
    )
    if preserved:
        _append_audit(
            data_dir,
            {
                "at": _iso(now),
                "key": key,
                "event": "gap_ignored_current_state",
                "quality_status": prev.get("quality_status"),
                "reason": reason,
            },
        )
        return {"ok": True, "current": prev, "ignored": True}
    history = list((prev or {}).get("history") or [])
    if prev:
        history.append(
            {
                "at": prev.get("updated_at"),
                "current_state": prev.get("current_state"),
                "quality_status": prev.get("quality_status"),
                "failure_reason": prev.get("failure_reason"),
            }
        )
    current = {
        "symbol": str(symbol or "").upper(),
        "metric": canonical_metric(metric),
        "laboratory_id": laboratory_id,
        "current_state": C_GAP,
        "acquired": False,
        "quality_status": Q_UNKNOWN,
        "validation_status": V_NOT_RUN,
        "fresh": False,
        "decision_compatible": False,
        "usable": False,
        "tradable": False,
        "value": None,
        "provider": None,
        "last_success": (prev or {}).get("last_success"),
        "last_failure": _iso(now),
        "failure_reason": reason or "capability_gap",
        "evidence_id": None,
        "validated_at": None,
        "retry_condition": "trusted_acquisition",
        "attempted": list(attempted or []),
        "reason": reason or "capability_gap",
        "updated_at": _iso(now),
        "history": history[-30:],
    }
    reg["current"][key] = current
    _save_registry(data_dir, reg)
    _append_audit(
        data_dir,
        {
            "at": _iso(now),
            "key": key,
            "event": "capability_gap",
            "reason": reason,
            "attempted": list(attempted or []),
            "previous_state": (prev or {}).get("current_state"),
        },
    )
    return {"ok": True, "current": current}


def current_capability(
    data_dir: str | Path | None,
    symbol: str,
    metric: str,
    *,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any] | None:
    reg = load_registry(data_dir)
    row = reg["current"].get(_key(laboratory_id, symbol, metric))
    return dict(row) if isinstance(row, dict) else None


def lookup_usability(
    data_dir: str | Path | None,
    symbol: str,
    metric: str,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any] | None:
    row = current_capability(data_dir, symbol, metric, laboratory_id=laboratory_id)
    if not row:
        return None
    rec = row.get("record") if isinstance(row.get("record"), dict) else None
    return {
        "acquired": bool(row.get("acquired")),
        "quality": row.get("quality_status"),
        "fresh": bool(row.get("fresh")),
        "decision_compatible": bool(row.get("decision_compatible")),
        "usable": bool(decision_may_consume(rec)) if rec else (
            bool(row.get("usable")) and row.get("quality_status") == Q_TRUSTED
        ),
        "tradable": bool(decision_may_consume(rec)) if rec else False,
        "value": row.get("value") if (
            bool(decision_may_consume(rec)) if rec else False
        ) else None,
        "reason": row.get("reason") or row.get("failure_reason"),
        "evidence_id": row.get("evidence_id"),
        "provider": row.get("provider"),
        "current_state": row.get("current_state"),
    }


def _sync_uncertainty(data_dir: str | Path, current: dict[str, Any]) -> None:
    code = _UNKNOWN_CODE.get(canonical_metric(current.get("metric")))
    if not code:
        return
    try:
        from atlas.investment.uncertainty_queue import (
            STATUS_CONFLICT,
            STATUS_DONE,
            STATUS_PENDING_VALIDATION,
            list_tasks,
            mark_task,
        )
    except Exception:  # noqa: BLE001
        return
    lab = str(current.get("laboratory_id") or "")
    sym = str(current.get("symbol") or "").upper()
    try:
        tasks = list_tasks(data_dir, lab, status=None)
    except Exception:  # noqa: BLE001
        return
    for task in tasks:
        if str(task.get("symbol") or "").upper() != sym:
            continue
        if str(task.get("unknown") or "") != code:
            continue
        if current.get("usable") and current.get("quality_status") == Q_TRUSTED:
            desired = STATUS_DONE
            desired_note = "resolved_by_trusted_capability"
        elif current.get("quality_status") == Q_CONFLICT:
            desired = STATUS_CONFLICT
            desired_note = "provider_conflict"
        elif current.get("acquired") or current.get("quality_status") == Q_PENDING:
            desired = STATUS_PENDING_VALIDATION
            desired_note = str(current.get("reason") or "pending_validation")
        else:
            continue
        if task.get("status") == desired and task.get("note") == desired_note:
            continue
        mark_task(
            data_dir,
            str(task.get("id")),
            laboratory_id=lab,
            status=desired,
            note=desired_note,
            provider=current.get("provider"),
        )


# These current states already have a value or a disagreement. They are not "missing".
_NOT_MISSING = frozenset({Q_PENDING, Q_CONFLICT, Q_TRUSTED, Q_STALE, Q_INVALID, Q_AVAILABLE})


def blocks_missing_code(data_dir: str | Path | None, laboratory_id: str, symbol: str, code: str) -> bool:
    """True when the code is still a real acquisition gap and may be queued as missing.

    False when the registry already holds the metric as pending, conflict, or trusted.
    """
    inv = {v: k for k, v in _UNKNOWN_CODE.items()}
    metric = inv.get(str(code or ""))
    if not metric:
        return True
    row = current_capability(data_dir, symbol, metric, laboratory_id=laboratory_id)
    if not row:
        return True
    quality = str(row.get("quality_status") or Q_UNKNOWN)
    if quality in _NOT_MISSING and (
        row.get("acquired") or row.get("value") is not None or quality in {Q_PENDING, Q_CONFLICT, Q_TRUSTED}
    ):
        return False
    if quality == Q_UNKNOWN or not row.get("acquired"):
        return True
    return True


def reconcile_symbol_from_store(
    data_dir: str | Path | None,
    *,
    symbol: str,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Classify the fundamentals row. Presence is acquisition, not trust."""
    if not data_dir or not symbol:
        return {"ok": False}
    try:
        from atlas.investment.fundamentals import get_symbol
    except Exception:  # noqa: BLE001
        return {"ok": False}
    row = get_symbol(data_dir, symbol, program_id=program_id) or {}
    if not row:
        return {"ok": True, "records": []}
    out = []
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    for metric, aliases in (
        ("pe", ("pe",)),
        ("roe", ("roe",)),
        ("debt_to_equity", ("debt_to_equity",)),
        ("fcf", ("fcf", "free_cash_flow")),
    ):
        value = None
        for alias in aliases:
            if row.get(alias) is not None:
                value = row.get(alias)
                break
        ev_rows = evidence.get(metric) if isinstance(evidence.get(metric), list) else []
        latest = ev_rows[-1] if ev_rows and isinstance(ev_rows[-1], dict) else {}
        provider = str(latest.get("provider") or row.get("source") or "")
        evidence_id = row.get("nse_raw_evidence_id")
        rec = envelope(
            symbol=symbol,
            metric=metric,
            value=value,
            provider=provider,
            source=str(latest.get("source") or row.get("source") or ""),
            as_of=str(row.get("as_of") or latest.get("as_of") or "") or None,
            period=None,
            evidence_id=str(evidence_id) if evidence_id else None,
            retrieved_at=latest.get("recorded_at"),
            laboratory_id=laboratory_id,
            unit="ratio" if metric != "fcf" else "INR",
            currency="INR" if metric == "fcf" else None,
            eps_basis=row.get("eps_basis") if metric == "pe" else None,
            now=now,
        )
        # Store numbers without formula inputs stay pending. Do not invent components.
        if not rec.get("components"):
            rec["components"] = {}
        committed = commit_record(data_dir, rec, laboratory_id=laboratory_id, now=now)
        out.append(committed.get("current") or committed.get("candidate"))
    return {"ok": True, "records": out}


def sync_fundamental_queue(
    data_dir: str | Path | None,
    laboratory_id: str = "india_equity_learner",
) -> int:
    """Move queue rows onto the registry's current state. Does not invent trust."""
    if not data_dir:
        return 0
    reg = load_registry(data_dir)
    n = 0
    for row in (reg.get("current") or {}).values():
        if not isinstance(row, dict):
            continue
        if str(row.get("laboratory_id") or "") != laboratory_id:
            continue
        if canonical_metric(row.get("metric")) not in _UNKNOWN_CODE:
            continue
        _sync_uncertainty(data_dir, row)
        n += 1
    return n


def align_kernel_fundamental_tasks(
    state: dict[str, Any],
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
) -> list[str]:
    """Kernel tasks for PE/ROE/D/E/FCF must name the registry state, not "missing".

    PENDING_VALIDATION and CONFLICT stay blocked and not tradable.
    A real UNKNOWN gap stays CAPABILITY_GAP. History on the task is kept.
    """
    if not isinstance(state, dict) or not data_dir:
        return []
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return []
    changed: list[str] = []
    for task in tasks.values():
        if not isinstance(task, dict) or task.get("status") != "CAPABILITY_GAP":
            continue
        symbol = str(task.get("symbol") or "")
        names: list[str] = []
        if task.get("missing_requirement"):
            names.append(str(task.get("missing_requirement")))
        for req in task.get("required") or []:
            names.append(str(req))
        metrics: list[str] = []
        for name in names:
            metric = canonical_metric(name)
            if metric in _UNKNOWN_CODE and metric not in metrics:
                metrics.append(metric)
        if not metrics:
            continue
        holds: list[tuple[str, dict[str, Any]]] = []
        gaps: list[str] = []
        for metric in metrics:
            row = current_capability(
                data_dir, symbol, metric, laboratory_id=laboratory_id
            )
            quality = str((row or {}).get("quality_status") or Q_UNKNOWN)
            acquired = bool((row or {}).get("acquired")) or (row or {}).get("value") is not None
            if quality in {Q_PENDING, Q_CONFLICT} or (
                acquired and quality in {Q_STALE, Q_INVALID}
            ):
                holds.append((metric, row or {}))
            elif quality == Q_TRUSTED and (row or {}).get("usable"):
                continue
            else:
                gaps.append(metric)
        if not holds or gaps:
            continue
        primary, row = holds[0]
        quality = str(row.get("quality_status") or Q_PENDING)
        hist = list(task.get("status_history") or [])
        hist.append(
            {
                "status": task.get("status"),
                "missing_requirement": task.get("missing_requirement"),
                "reason": task.get("reason"),
                "at": task.get("updated_at"),
            }
        )
        task["status_history"] = hist[-30:]
        task["status"] = "BLOCKED"
        task["missing_requirement"] = None
        task["registry_state"] = quality
        task["acquired"] = True
        task["usable"] = False
        task["tradable"] = False
        task["reason"] = (
            f"registry_{quality}: {primary} is acquired and not missing"
            if quality == Q_PENDING
            else f"registry_{quality}: {primary} is not usable and not tradable"
        )
        task["next_action"] = (
            "await_validation" if quality == Q_PENDING else "await_conflict_resolution"
        )
        task["retry_policy"] = "on_capability_change"
        task["last_error"] = str(row.get("reason") or quality)
        changed.append(str(task.get("id") or ""))
    return [item for item in changed if item]


_XBRL_METRICS = ("pe", "roe", "debt_to_equity", "fcf")


def _xbrl_period(metric: dict[str, Any], fallback: str | None) -> str | None:
    inputs = metric.get("inputs") if isinstance(metric.get("inputs"), dict) else {}
    for key in ("end_period", "period", "numerator_period"):
        if inputs.get(key):
            return str(inputs[key])[:10]
    periods = inputs.get("periods")
    if isinstance(periods, list) and periods:
        last = periods[-1]
        if last:
            return str(last)[:10]
    return str(fallback)[:10] if fallback else None


def commit_xbrl_calculation(
    data_dir: str | Path,
    *,
    symbol: str,
    calculation: dict[str, Any],
    evidence_id: str | None,
    period_end: str | None = None,
    price_as_of: str | None = None,
    laboratory_id: str = "india_equity_learner",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Commit calculator output. A passed check can be TRUSTED. A missing input stays UNKNOWN.

    Does not invent a component, and does not write zero in place of a missing input.
    An existing acquired row is left in place when this calculation is UNKNOWN.
    """
    mets = calculation.get("metrics") if isinstance(calculation.get("metrics"), dict) else {}
    committed: list[dict[str, Any]] = []
    for metric in _XBRL_METRICS:
        block = mets.get(metric) if isinstance(mets.get(metric), dict) else {}
        status = str(block.get("status") or "UNKNOWN")
        reason = str(block.get("reason") or "calc_unknown")
        period = _xbrl_period(block, period_end)
        inputs = block.get("inputs") if isinstance(block.get("inputs"), dict) else {}
        value = block.get("value") if status == "VALID" else None
        if value is None:
            existing = current_capability(
                data_dir, symbol, metric, laboratory_id=laboratory_id
            )
            if existing and (
                existing.get("acquired") or existing.get("value") is not None
            ) and str(existing.get("quality_status") or "") != Q_UNKNOWN:
                committed.append(
                    {
                        "metric": metric,
                        "skipped": True,
                        "reason": reason,
                        "quality_status": existing.get("quality_status"),
                    }
                )
                continue
        components: dict[str, Any] = {}
        unit = "ratio"
        debt_definition = None
        eps_basis = block.get("eps_basis")
        if metric == "pe" and value is not None:
            components = {
                "price": inputs.get("price"),
                "eps": inputs.get("eps"),
                "eps_basis": eps_basis,
            }
        elif metric == "roe" and value is not None:
            unit = str(block.get("unit") or "pct")
            components = {
                "profit": inputs.get("net_income"),
                "equity": inputs.get("average_equity"),
            }
        elif metric == "debt_to_equity" and value is not None:
            definition_id = str(block.get("definition_id") or "")
            if definition_id == "atlas.debt.total_borrowings.v1":
                debt_definition = "total_borrowings"
            components = {
                "debt": inputs.get("total_debt"),
                "equity": inputs.get("equity"),
                "debt_definition": debt_definition,
            }
        elif metric == "fcf" and value is not None:
            unit = "INR"
            components = {
                "operating_cash_flow": inputs.get("operating_cash_flow"),
                "capex": inputs.get("capital_expenditures_reported"),
            }
        rec = envelope(
            symbol=symbol,
            metric=metric,
            value=value,
            unit=unit,
            currency="INR" if metric == "fcf" else None,
            period=period,
            period_end=period,
            period_type=str(eps_basis) if metric == "pe" and eps_basis else None,
            eps_basis=str(eps_basis) if metric == "pe" and eps_basis else None,
            as_of=period,
            price_as_of=price_as_of if metric == "pe" else None,
            provider="nse_xbrl",
            source="nse_xbrl",
            evidence_id=str(evidence_id) if evidence_id else None,
            calculation_method=block.get("formula"),
            components=components,
            debt_definition=debt_definition,
            laboratory_id=laboratory_id,
            now=now,
        )
        if value is None:
            rec["reason"] = reason
            rec["value"] = None
        saved = commit_record(
            data_dir, rec, laboratory_id=laboratory_id, now=now
        )
        current = saved.get("current") or saved.get("candidate") or {}
        committed.append(
            {
                "metric": metric,
                "ok": bool(saved.get("ok")),
                "quality_status": current.get("quality_status"),
                "reason": current.get("reason") or current.get("failure_reason"),
                "value": current.get("value"),
                "evidence_id": current.get("evidence_id"),
                "formula": block.get("formula"),
                "period": current.get("period"),
                "usable": current.get("usable"),
            }
        )
    return {"ok": True, "symbol": symbol, "evidence_id": evidence_id, "metrics": committed}


def release_blocked_kernel_tasks(
    state: dict[str, Any],
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
) -> list[str]:
    """Mark CAPABILITY_GAP tasks retryable once the metric is trusted. Does not invent the value."""
    if not isinstance(state, dict) or not data_dir:
        return []
    tasks = state.get("tasks")
    if not isinstance(tasks, dict):
        return []
    released: list[str] = []
    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        status = task.get("status")
        if status not in {"CAPABILITY_GAP", "BLOCKED", "RETRY_SCHEDULED"}:
            continue
        symbol = str(task.get("symbol") or "")
        names = []
        if task.get("missing_requirement"):
            names.append(str(task.get("missing_requirement")))
        for req in task.get("required") or []:
            names.append(str(req))
        trusted_name = None
        trusted_use = None
        for name in names:
            use = lookup_usability(data_dir, symbol, name, laboratory_id)
            if use and use.get("usable") and use.get("quality") == Q_TRUSTED:
                trusted_name = name
                trusted_use = use
                break
        if trusted_name is None or trusted_use is None:
            continue
        # The ladder remembers the old miss. A trusted record is a capability
        # change, so that memory must not skip the local lookup on the retry.
        memory = state.get("failure_memory")
        if isinstance(memory, dict):
            prefixes = {str(trusted_name).strip().lower(), canonical_metric(trusted_name)}
            for key in list(memory):
                head = str(key).split("|", 1)[0].strip().lower()
                if head in prefixes:
                    memory.pop(key, None)
        if status == "RETRY_SCHEDULED":
            task["plan"] = None
            continue
        hist = list(task.get("status_history") or [])
        hist.append(
            {
                "status": status,
                "missing_requirement": task.get("missing_requirement"),
                "reason": task.get("reason"),
            }
        )
        task["status_history"] = hist[-30:]
        task["status"] = "RETRY_SCHEDULED"
        task["next_action"] = "resume_after_capability_change"
        task["reason"] = "trusted capability recovered; historical gap kept"
        task["plan"] = None
        task["retry_policy"] = "next_tick"
        task["missing_requirement"] = None
        task["evidence_id"] = trusted_use.get("evidence_id")
        task["usable"] = True
        task["tradable"] = True
        released.append(str(task.get("id") or ""))
    return [r for r in released if r]


def format_capability_lines(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    limit: int = 8,
) -> list[str]:
    reg = load_registry(data_dir)
    rows = [r for r in (reg.get("current") or {}).values() if isinstance(r, dict)]
    rows = [r for r in rows if str(r.get("laboratory_id") or laboratory_id) == laboratory_id]
    if not rows:
        return []
    rows.sort(key=lambda r: (str(r.get("symbol") or ""), str(r.get("metric") or "")))
    lines = ["", "Data capability (current — history kept in audit)"]
    for row in rows[:limit]:
        prev = ""
        hist = row.get("history") or []
        if hist:
            prev = f"  previous: {hist[-1].get('current_state') or hist[-1].get('quality_status')}"
        lines.append(
            f"  {row.get('symbol')} {row.get('metric')}: "
            f"acquisition={'AVAILABLE' if row.get('acquired') else 'MISSING'}  "
            f"quality={row.get('quality_status')}  provider={row.get('provider') or '—'}  "
            f"freshness={'PASS' if row.get('fresh') else 'FAIL'}  "
            f"current={row.get('current_state')}  evidence={row.get('evidence_id') or '—'}"
        )
        if prev:
            lines.append(prev)
        if row.get("reason") and not row.get("usable"):
            lines.append(f"    reason: {row.get('reason')}  retry: {row.get('retry_condition')}")
    return lines
