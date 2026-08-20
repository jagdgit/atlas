"""OI-LINT0 Phase 1 — laboratory instrument contracts (architectural invariants).

A position may only be created, switched, or replaced with an instrument
permitted by its originating laboratory. ``skip_cash_alts_for_lab`` is not
sufficient: UTS switch / allocation / apply_trade must use this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

VERSION = "lint0.lab_contracts.v1"

CLASS_INDEX_PROXY = "index_proxy"
CLASS_FNO_CONTRACT = "fno_contract"
CLASS_CASH_EQUITY = "cash_equity"

LAB_SWING = "swing"
LAB_INTRADAY = "intraday"
LAB_FNO = "fno"
LAB_UNCONSTRAINED = "unconstrained"

POLICY_THESIS_GATED = "thesis_gated"
POLICY_TECHNICAL_ONLY = "technical_only"
POLICY_INDEX_PROXY_ONLY = "index_proxy_only"
POLICY_UNCONSTRAINED = "unconstrained"

PATH_BUY = "buy"
PATH_SWITCH = "switch"
PATH_ALT = "alternative"
PATH_ALLOCATION = "allocation"
PATH_REPLACE = "replace"

REASON_LAB_INSTRUMENT = "lab_instrument_rejected"
REASON_EOD_FLATTEN = "eod_flatten"
CONTRADICTION_TECH_VS_THESIS = "technical_buy_vs_fundamental_watch"

_IST = ZoneInfo("Asia/Kolkata")
FLATTEN_START = time(15, 20)
SESSION_OPEN = time(9, 15)

_FNO_PK = frozenset({"india_fno_learner", "fno_learner", "fno_paper"})


@dataclass(frozen=True)
class InstrumentVerdict:
    allowed: bool
    laboratory_id: str
    lab_kind: str
    symbol: str
    instrument_class: str
    path: str
    reason: str
    strategy_contract: str


def _norm_sym(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _norm_pk(laboratory_id: str | None, cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or {}
    return str(
        laboratory_id or cfg.get("portfolio_key") or cfg.get("laboratory_id") or ""
    ).strip()


def lab_kind(
    laboratory_id: str | None = None,
    *,
    cfg: dict[str, Any] | None = None,
) -> str:
    cfg = cfg or {}
    pk = _norm_pk(laboratory_id, cfg).lower()
    ac = str(cfg.get("asset_class") or "").strip().lower()
    pack = str(cfg.get("instrument_pack") or "").strip().lower()
    if (
        pk in _FNO_PK
        or "fno" in pk
        or pk.endswith("_futures")
        or ac in {"futures", "options"}
        or pack in {"futures", "options", "fno"}
    ):
        return LAB_FNO
    horizon = ""
    person = cfg.get("persona") if isinstance(cfg.get("persona"), dict) else {}
    horizon = str(person.get("time_horizon") or cfg.get("time_horizon") or "").strip().lower()
    if "intraday" in pk or horizon == "intraday":
        return LAB_INTRADAY
    if pk in {"india_equity_learner", "equity_swing_learner"} or (
        "equity" in pk and "learner" in pk and "intraday" not in pk
    ):
        return LAB_SWING
    return LAB_UNCONSTRAINED


def strategy_contract(kind: str) -> str:
    if kind == LAB_FNO:
        return POLICY_INDEX_PROXY_ONLY
    if kind == LAB_INTRADAY:
        return POLICY_TECHNICAL_ONLY
    if kind == LAB_SWING:
        return POLICY_THESIS_GATED
    return POLICY_UNCONSTRAINED


def instrument_class(
    symbol: str,
    *,
    instrument: dict[str, Any] | None = None,
) -> str:
    from atlas.investment.index_proxy_lot import underlier_family

    if underlier_family(symbol):
        return CLASS_INDEX_PROXY
    row = instrument if isinstance(instrument, dict) else {}
    ac = str(row.get("asset_class") or "").strip().lower()
    if ac in {"futures", "options"}:
        return CLASS_FNO_CONTRACT
    return CLASS_CASH_EQUITY


def is_instrument_permitted(
    laboratory_id: str | None,
    symbol: str,
    *,
    cfg: dict[str, Any] | None = None,
    instrument: dict[str, Any] | None = None,
    path: str = PATH_BUY,
) -> InstrumentVerdict:
    """Hard gate for create / switch / replace / alt / allocation."""
    lid = _norm_pk(laboratory_id, cfg) or "unknown"
    kind = lab_kind(lid, cfg=cfg)
    cls = instrument_class(symbol, instrument=instrument)
    contract = strategy_contract(kind)
    p = str(path or PATH_BUY).strip().lower() or PATH_BUY
    if kind != LAB_FNO:
        return InstrumentVerdict(
            allowed=True,
            laboratory_id=lid,
            lab_kind=kind,
            symbol=_norm_sym(symbol),
            instrument_class=cls,
            path=p,
            reason="ok",
            strategy_contract=contract,
        )
    ok = cls in {CLASS_INDEX_PROXY, CLASS_FNO_CONTRACT}
    return InstrumentVerdict(
        allowed=ok,
        laboratory_id=lid,
        lab_kind=kind,
        symbol=_norm_sym(symbol),
        instrument_class=cls,
        path=p,
        reason="ok" if ok else REASON_LAB_INSTRUMENT,
        strategy_contract=contract,
    )


def reject_message(verdict: InstrumentVerdict) -> str:
    return (
        f"{verdict.symbol}: {REASON_LAB_INSTRUMENT} "
        f"(lab={verdict.laboratory_id} contract={verdict.strategy_contract} "
        f"class={verdict.instrument_class} path={verdict.path})"
    )


def filter_symbols_for_lab(
    laboratory_id: str | None,
    rows: Iterable[dict[str, Any] | None],
    *,
    cfg: dict[str, Any] | None = None,
    path: str = PATH_ALT,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").strip()
        if not sym:
            continue
        v = is_instrument_permitted(
            laboratory_id, sym, cfg=cfg, instrument=row, path=path
        )
        if v.allowed:
            out.append(row)
    return out


def skip_cash_alts_for_lab(
    cfg: dict[str, Any] | None,
    *,
    pack_id: str = "",
    portfolio_key: str = "",
) -> bool:
    """FNO must not inject cash alts. Intraday still skips (Yahoo 5m budget)."""
    merged = dict(cfg or {})
    if pack_id and not merged.get("instrument_pack"):
        merged["instrument_pack"] = pack_id
    kind = lab_kind(portfolio_key or merged.get("portfolio_key"), cfg=merged)
    return kind in {LAB_FNO, LAB_INTRADAY}


def to_ist(now: datetime | None) -> datetime:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    return clock.astimezone(_IST)


def ist_calendar_date(now: datetime | None) -> str:
    return to_ist(now).strftime("%Y-%m-%d")


def intraday_must_be_flat(now: datetime | None) -> bool:
    """True from 15:20 IST through next 09:15 (and all weekend)."""
    ist = to_ist(now)
    if ist.weekday() >= 5:
        return True
    t = ist.time().replace(tzinfo=None)
    return t >= FLATTEN_START or t < SESSION_OPEN


def flatten_session_date(now: datetime | None) -> str:
    """IST date the overnight flatten belongs to (before 09:15 → previous day)."""
    ist = to_ist(now)
    if ist.time().replace(tzinfo=None) < SESSION_OPEN:
        from datetime import timedelta

        return (ist.date() - timedelta(days=1)).isoformat()
    return ist.date().isoformat()


def normalize_thesis_stance(raw: Any) -> str:
    if raw is None:
        return "ABSENT"
    if isinstance(raw, dict):
        raw = (
            raw.get("stance")
            or raw.get("current_conclusion")
            or raw.get("action")
            or raw.get("status")
        )
    s = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not s:
        return "ABSENT"
    if s in {"invalid", "thesis_invalid", "quarantined"}:
        return "INVALID"
    if s in {"avoid", "sell", "no_buy"}:
        return "AVOID"
    if s in {"buy", "buy_candidate", "accumulate"}:
        return "BUY"
    if "watch" in s or s in {"not_buy", "hold"}:
        return "WATCH"
    if s in {"absent", "unknown", "none"}:
        return "ABSENT"
    return "WATCH"


def thesis_stance_from_awareness(awareness: dict[str, Any] | None) -> str:
    if not isinstance(awareness, dict):
        return "ABSENT"
    thesis = awareness.get("thesis")
    if isinstance(thesis, dict):
        st = normalize_thesis_stance(thesis)
        if st != "ABSENT":
            return st
    val = awareness.get("valuation") if isinstance(awareness.get("valuation"), dict) else None
    if val is not None:
        try:
            from atlas.investment.research.valuation import thesis_stance_from_valuation

            return normalize_thesis_stance(thesis_stance_from_valuation(val))
        except Exception:  # noqa: BLE001
            pass
    return "ABSENT"


def technical_signal_from_action(action: str | None, *, kind: str | None = None) -> str:
    a = str(action or kind or "").strip().lower()
    if a == "buy":
        return "BUY"
    if a in {"sell", "reduce"}:
        return "SELL"
    if a in {"watch"}:
        return "HOLD"
    return "HOLD"


def apply_lab_policy(
    *,
    lab_kind_s: str,
    technical: str,
    thesis: str,
    held: float = 0.0,
    identity: str = "UNKNOWN",
) -> dict[str, Any]:
    """Resolve which layer wins. Does not place an order."""
    tech = str(technical or "HOLD").upper()
    th = str(thesis or "ABSENT").upper()
    ident = str(identity or "UNKNOWN").upper()
    contract = strategy_contract(lab_kind_s)
    contradictions: list[str] = []
    if tech == "BUY" and th in {"WATCH", "AVOID", "INVALID", "ABSENT"}:
        contradictions.append(CONTRADICTION_TECH_VS_THESIS)
    if ident == "QUARANTINED":
        contradictions.append("identity_quarantined")

    final = tech
    add_incumbent = False
    if lab_kind_s == LAB_INTRADAY:
        # Technical-only experiment: BUY allowed despite WATCH.
        final = tech
    elif lab_kind_s == LAB_FNO:
        final = tech
    elif lab_kind_s == LAB_SWING and tech == "BUY":
        if ident == "QUARANTINED" or th in {"AVOID", "INVALID"}:
            final = "HOLD"
        elif th in {"WATCH", "ABSENT"} and float(held or 0) <= 1e-12:
            final = "HOLD"
        elif th in {"WATCH", "ABSENT"} and float(held or 0) > 1e-12:
            final = "BUY"
            add_incumbent = True
        else:
            final = "BUY"

    return {
        "technical_signal": tech,
        "fundamental_thesis": th,
        "identity": ident,
        "lab_policy": contract,
        "lab_kind": lab_kind_s,
        "final_decision": final,
        "add_to_incumbent": add_incumbent,
        "contradictions": contradictions,
        "winner": (
            "technical"
            if lab_kind_s == LAB_INTRADAY
            else ("instrument_gate" if lab_kind_s == LAB_FNO else "thesis_gated")
        ),
    }


def decompose_decision(
    *,
    laboratory_id: str | None,
    symbol: str,
    action: str,
    cfg: dict[str, Any] | None = None,
    awareness: dict[str, Any] | None = None,
    held: float = 0.0,
    research_confidence: Any = None,
    identity: str = "UNKNOWN",
    risk_gate: str = "PASS",
    challenger_vs_book: str | None = None,
    instrument: dict[str, Any] | None = None,
    path: str = PATH_BUY,
) -> dict[str, Any]:
    kind = lab_kind(laboratory_id, cfg=cfg)
    ident_row: dict[str, Any] | None = None
    try:
        from atlas.investment.thesis_identity import validate_thesis_identity

        ident_row = validate_thesis_identity(symbol, awareness)
        if ident_row.get("identity") in {"QUARANTINED", "VALID"}:
            identity = str(ident_row["identity"])
    except Exception:  # noqa: BLE001
        ident_row = None
    thesis = thesis_stance_from_awareness(awareness)
    if identity == "QUARANTINED":
        thesis = "INVALID"
    tech = technical_signal_from_action(action)
    policy = apply_lab_policy(
        lab_kind_s=kind,
        technical=tech,
        thesis=thesis,
        held=held,
        identity=identity,
    )
    inst = is_instrument_permitted(
        laboratory_id, symbol, cfg=cfg, instrument=instrument, path=path
    )
    if not inst.allowed and str(action).lower() == "buy":
        policy["final_decision"] = "HOLD"
        policy["contradictions"] = list(policy.get("contradictions") or []) + [
            REASON_LAB_INSTRUMENT
        ]
    return {
        **policy,
        "research_confidence": research_confidence,
        "risk_gate": risk_gate,
        "challenger_vs_book": challenger_vs_book,
        "instrument_class": inst.instrument_class,
        "instrument_allowed": inst.allowed,
        "identity_check": ident_row,
        "version": VERSION,
    }
