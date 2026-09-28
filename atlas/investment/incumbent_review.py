"""OI-ICR2 — EXIT_REVIEW densify (deterministic ladder, not AVOID=instant sell).

Resolves Allocation Comparison Packets in EXIT_REVIEW / SWITCH_REVIEW into:

* ``WAIT`` — stay under review; list ``waiting_for``
* ``SWITCH_TO`` — challenger cleared costs (handoff to switch execution)
* ``EXIT_TO_CASH`` — no viable challenger; cash preferred; or quarantine aged out

Does **not** replace PLC.B risk stops.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.allocation_comparison import (
    DECISION_EXIT_REVIEW,
    DECISION_SWITCH_REVIEW,
)

VERSION = "icr.2.exit_review.v1"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.incumbent_review")

ACTION_WAIT = "WAIT"
ACTION_SWITCH_TO = "SWITCH_TO"
ACTION_EXIT_TO_CASH = "EXIT_TO_CASH"

DEFAULT_QUARANTINE_EXIT_DAYS = 3


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def icr2_enabled(cfg: dict[str, Any] | None, laboratory_id: str | None) -> bool:
    cfg = cfg or {}
    if cfg.get("icr2_enabled") is False:
        return False
    if cfg.get("icr2_enabled") is True:
        return True
    try:
        from atlas.investment.lab_contracts import LAB_SWING, lab_kind

        return lab_kind(laboratory_id, cfg=cfg) == LAB_SWING
    except Exception:  # noqa: BLE001
        pk = str(laboratory_id or "").lower()
        return pk in {"india_equity_learner", "equity_swing_learner"} or "equity_learner" in pk


def quarantine_clock_path(data_dir: str | Path, laboratory_id: str) -> Path:
    lab = str(laboratory_id or "unknown").strip() or "unknown"
    return Path(data_dir) / "investment" / "allocation" / lab / "quarantine_clock.json"


def load_quarantine_clock(data_dir: str | Path | None, laboratory_id: str) -> dict[str, Any]:
    if not data_dir:
        return {"version": VERSION, "symbols": {}}
    path = quarantine_clock_path(data_dir, laboratory_id)
    if not path.is_file():
        return {"version": VERSION, "symbols": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            doc.setdefault("symbols", {})
            return doc
    except Exception:  # noqa: BLE001
        pass
    return {"version": VERSION, "symbols": {}}


def save_quarantine_clock(
    data_dir: str | Path | None,
    laboratory_id: str,
    clock: dict[str, Any],
) -> None:
    if not data_dir:
        return
    path = quarantine_clock_path(data_dir, laboratory_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clock, indent=2, default=str), encoding="utf-8")
    except OSError:
        _log.debug("quarantine clock save failed", exc_info=True)


def _days_between(start_ist: str, end_ist: str) -> int | None:
    try:
        a = datetime.strptime(str(start_ist)[:10], "%Y-%m-%d").date()
        b = datetime.strptime(str(end_ist)[:10], "%Y-%m-%d").date()
        return max(0, (b - a).days)
    except Exception:  # noqa: BLE001
        return None


def note_quarantine_day(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbol: str,
    *,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Stamp first-seen IST day for quarantine; return {first_seen, days}."""
    day = (as_of_ist or ist_today())[:10]
    sym = str(symbol or "").strip().upper()
    clock = load_quarantine_clock(data_dir, laboratory_id)
    symbols = clock.setdefault("symbols", {})
    row = symbols.get(sym) if isinstance(symbols.get(sym), dict) else {}
    first = str(row.get("first_seen_ist") or "")[:10]
    if not first:
        first = day
        symbols[sym] = {
            "first_seen_ist": first,
            "last_seen_ist": day,
            "status": "QUARANTINED",
        }
    else:
        symbols[sym] = {
            **row,
            "first_seen_ist": first,
            "last_seen_ist": day,
            "status": "QUARANTINED",
        }
    save_quarantine_clock(data_dir, laboratory_id, clock)
    days = _days_between(first, day)
    return {"first_seen_ist": first, "days": days, "as_of_ist": day}


def clear_quarantine_day(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbol: str,
) -> None:
    if not data_dir:
        return
    clock = load_quarantine_clock(data_dir, laboratory_id)
    symbols = clock.get("symbols") if isinstance(clock.get("symbols"), dict) else {}
    sym = str(symbol or "").strip().upper()
    if sym in symbols:
        symbols.pop(sym, None)
        clock["symbols"] = symbols
        save_quarantine_clock(data_dir, laboratory_id, clock)


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _challenger_clears(acp: dict[str, Any]) -> tuple[bool, str | None, float | None]:
    """True when ACP already decided SWITCH_REVIEW or switch advantage cleared."""
    if str(acp.get("decision") or "") == DECISION_SWITCH_REVIEW:
        best = None
        for c in acp.get("challengers") or []:
            if isinstance(c, dict) and c.get("is_best"):
                best = str(c.get("symbol") or "")
                break
        if not best:
            best = str(
                ((acp.get("provenance") or {}).get("switch_review") or {}).get(
                    "challenger_symbol"
                )
                or ""
            )
        adv = ((acp.get("provenance") or {}).get("switch_review") or {}).get(
            "expected_advantage"
        )
        return bool(best), best or None, _f(adv)
    sw = (acp.get("provenance") or {}).get("switch_review") or {}
    if str(sw.get("decision") or "").lower() == "switch":
        return True, str(sw.get("challenger_symbol") or "") or None, _f(sw.get("expected_advantage"))
    for c in acp.get("challengers") or []:
        if isinstance(c, dict) and c.get("is_best"):
            adv = _f(c.get("expected_advantage"))
            thr = _f((acp.get("switch_cost") or {}).get("min_advantage")) or 0.02
            if adv is not None and adv > thr:
                return True, str(c.get("symbol") or "") or None, adv
    return False, None, None


def _cash_preferred(acp: dict[str, Any]) -> bool:
    """Incumbent does not beat cash after costs (honest competitor)."""
    vs = acp.get("incumbent_vs_cash") if isinstance(acp.get("incumbent_vs_cash"), dict) else {}
    if vs.get("ok") and vs.get("advantage") is not None:
        try:
            return float(vs["advantage"]) <= 0.0
        except (TypeError, ValueError):
            pass
    inc = acp.get("incumbent") if isinstance(acp.get("incumbent"), dict) else {}
    cash = acp.get("cash") if isinstance(acp.get("cash"), dict) else {}
    er_i = _f(inc.get("expected_return"))
    er_c = _f(cash.get("expected_return"))
    if er_i is not None and er_c is not None:
        return er_i <= er_c
    # AVOID with unknown ER vs cash → prefer cash honesty (do not invent edge for incumbent)
    stance = str(inc.get("thesis_stance") or "").upper()
    if stance in {"AVOID", "INVALID"}:
        return True
    return False


def resolve_exit_review(
    acp: dict[str, Any],
    *,
    data_dir: str | Path | None = None,
    cfg: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    """Deterministic densify of EXIT_REVIEW / SWITCH_REVIEW."""
    cfg = cfg or {}
    day = (as_of_ist or str(acp.get("as_of_ist") or ist_today()))[:10]
    lab = str(acp.get("laboratory_id") or "")
    inc = acp.get("incumbent") if isinstance(acp.get("incumbent"), dict) else {}
    sym = str(inc.get("symbol") or "").upper()
    stance = str(inc.get("thesis_stance") or "").upper()
    identity = str(inc.get("identity") or "").upper()
    decision = str(acp.get("decision") or "")
    q_days = int(cfg.get("icr2_quarantine_exit_days") or DEFAULT_QUARANTINE_EXIT_DAYS)

    base: dict[str, Any] = {
        "version": VERSION,
        "symbol": sym,
        "laboratory_id": lab,
        "as_of_ist": day,
        "acp_id": acp.get("acp_id"),
        "acp_decision": decision,
        "action": ACTION_WAIT,
        "reason_code": "exit_review_wait",
        "waiting_for": [],
        "challenger_symbol": None,
        "execute": False,
        "curiosity": None,
        "operator_line": None,
    }

    if decision not in {DECISION_EXIT_REVIEW, DECISION_SWITCH_REVIEW}:
        base["reason_code"] = "not_exit_review"
        base["operator_line"] = f"{sym}: ICR.2 skip (ACP={decision})"
        return base

    clears, chal_sym, adv = _challenger_clears(acp)
    if clears and chal_sym:
        base.update(
            action=ACTION_SWITCH_TO,
            reason_code="exit_review_switch_to_challenger",
            challenger_symbol=chal_sym,
            expected_advantage=adv,
            execute=True,
            waiting_for=[],
            operator_line=(
                f"{sym}: EXIT_REVIEW→SWITCH_TO {chal_sym}"
                + (f" adv={adv:+.4f}" if adv is not None else "")
            ),
        )
        return base

    if identity == "QUARANTINED":
        clock = note_quarantine_day(data_dir, lab, sym, as_of_ist=day)
        days = clock.get("days")
        base["quarantine"] = clock
        base["curiosity"] = {
            "symbol": sym,
            "unknown": "thesis_identity",
            "reason": "identity_quarantined",
            "priority": "high",
            "goal": "Re-establish business identity / clear hospital-vs-pharma contamination",
        }
        if days is not None and days >= q_days:
            base.update(
                action=ACTION_EXIT_TO_CASH,
                reason_code="exit_quarantine_aged",
                execute=True,
                waiting_for=[],
                operator_line=(
                    f"{sym}: EXIT_REVIEW→EXIT_TO_CASH "
                    f"(quarantine {days}d ≥ {q_days}d; identity unrepaired)"
                ),
            )
            return base
        wait_n = None if days is None else max(0, q_days - int(days))
        base.update(
            action=ACTION_WAIT,
            reason_code="exit_review_quarantine_wait",
            execute=False,
            waiting_for=[
                "identity_repair",
                f"quarantine_age>={q_days}d_or_challenger_clears",
            ],
            operator_line=(
                f"{sym}: EXIT_REVIEW WAIT identity repair "
                f"(day {days}/{q_days}"
                + (f"; {wait_n}d left" if wait_n is not None else "")
                + ")"
            ),
        )
        return base

    # Clear quarantine clock if identity healed
    if data_dir and identity != "QUARANTINED":
        clear_quarantine_day(data_dir, lab, sym)

    if stance in {"AVOID", "INVALID"} or str(acp.get("reason_code") or "").startswith(
        "exit_review"
    ):
        if _cash_preferred(acp):
            base.update(
                action=ACTION_EXIT_TO_CASH,
                reason_code="exit_avoid_to_cash",
                execute=True,
                waiting_for=[],
                operator_line=(
                    f"{sym}: EXIT_REVIEW→EXIT_TO_CASH "
                    f"(thesis={stance or 'review'}; no viable challenger; cash preferred)"
                ),
            )
            return base
        base.update(
            action=ACTION_WAIT,
            reason_code="exit_review_waiting_challenger_or_cash",
            execute=False,
            waiting_for=["viable_challenger_or_cash_preference_clear"],
            operator_line=(
                f"{sym}: EXIT_REVIEW WAIT "
                "(AVOID but incumbent still scores above cash — need denser E[R]/challenger)"
            ),
        )
        return base

    if decision == DECISION_SWITCH_REVIEW and not clears:
        base.update(
            action=ACTION_WAIT,
            reason_code="switch_review_incomplete",
            waiting_for=["challenger_symbol_or_advantage"],
            operator_line=f"{sym}: SWITCH_REVIEW WAIT (no challenger stamped)",
        )
        return base

    base["operator_line"] = f"{sym}: EXIT_REVIEW WAIT (no ladder rule fired)"
    base["waiting_for"] = ["evidence_densify"]
    return base


def attach_exit_resolution(
    data_dir: str | Path | None,
    acp: dict[str, Any],
    resolution: dict[str, Any],
) -> None:
    """Stamp exit_resolution onto ACP and re-persist for UI / evening."""
    if not isinstance(acp, dict) or not isinstance(resolution, dict):
        return
    slim = {
        "action": resolution.get("action"),
        "reason_code": resolution.get("reason_code"),
        "waiting_for": resolution.get("waiting_for") or [],
        "challenger_symbol": resolution.get("challenger_symbol"),
        "execute": bool(resolution.get("execute")),
        "operator_line": resolution.get("operator_line"),
        "quarantine": resolution.get("quarantine"),
        "version": VERSION,
    }
    acp["exit_resolution"] = slim
    if data_dir:
        try:
            from atlas.investment.allocation_comparison import persist_acp

            persist_acp(data_dir, acp)
        except Exception:  # noqa: BLE001
            _log.debug("ICR.2 ACP exit_resolution persist skipped", exc_info=True)


def resolve_lab_exit_reviews(
    packets: list[dict[str, Any]] | None,
    *,
    data_dir: str | Path | None = None,
    cfg: dict[str, Any] | None = None,
    as_of_ist: str | None = None,
) -> dict[str, Any]:
    resolutions: list[dict[str, Any]] = []
    by_sym = {
        str((p.get("incumbent") or {}).get("symbol") or "").upper(): p
        for p in (packets or [])
        if isinstance(p, dict)
    }
    for acp in packets or []:
        if not isinstance(acp, dict):
            continue
        if str(acp.get("decision") or "") not in {
            DECISION_EXIT_REVIEW,
            DECISION_SWITCH_REVIEW,
        }:
            continue
        res = resolve_exit_review(acp, data_dir=data_dir, cfg=cfg, as_of_ist=as_of_ist)
        resolutions.append(res)
        attach_exit_resolution(data_dir, acp, res)
        # Keep by_sym packet in sync (same object)
        _ = by_sym
    return {
        "version": VERSION,
        "count": len(resolutions),
        "execute_n": sum(1 for r in resolutions if r.get("execute")),
        "resolutions": resolutions,
        "lines": [r.get("operator_line") for r in resolutions if r.get("operator_line")],
    }


def enqueue_identity_curiosity(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    curiosity: dict[str, Any] | None,
) -> None:
    """Best-effort: push identity repair onto curiosity queue."""
    if not data_dir or not isinstance(curiosity, dict):
        return
    try:
        from atlas.investment.curiosity import STORE_REL

        day = ist_today()
        path = Path(data_dir) / STORE_REL / f"{day}.json"
        doc: dict[str, Any] = {"items": []}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    doc = loaded
            except Exception:  # noqa: BLE001
                pass
        items = [i for i in (doc.get("items") or []) if isinstance(i, dict)]
        sym = str(curiosity.get("symbol") or "")
        unk = str(curiosity.get("unknown") or "thesis_identity")
        if any(
            str(i.get("symbol")) == sym and str(i.get("unknown")) == unk for i in items
        ):
            return
        items.append(
            {
                **curiosity,
                "laboratory_id": laboratory_id,
                "status": "queued",
                "allocation_blocking": True,
                "icr2": True,
                "created_at": datetime.now(_IST).isoformat(),
            }
        )
        doc["items"] = items[-200:]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    except Exception:  # noqa: BLE001
        _log.debug("ICR.2 curiosity enqueue skipped", exc_info=True)


# Re-export helpers
__all__ = [
    "ACTION_EXIT_TO_CASH",
    "ACTION_SWITCH_TO",
    "ACTION_WAIT",
    "VERSION",
    "clear_quarantine_day",
    "enqueue_identity_curiosity",
    "icr2_enabled",
    "note_quarantine_day",
    "resolve_exit_review",
    "resolve_lab_exit_reviews",
]
