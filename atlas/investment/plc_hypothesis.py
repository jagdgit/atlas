"""PLC.D — hypothesis-first learning on every buy.

Creates a lab-scoped LI.5b hypothesis, stamps ``hypothesis_id`` on the Decision
Packet, and schedules checks at 7d / 30d / 90d / exit. Verdicts stay gated
(≥3 linked observations) via ``hypothesis_learning.record_verdict``.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.hypothesis_learning import (
    VERDICT_MIN_LINKS,
    create_hypothesis,
    get_hypothesis,
    link_decision,
    list_hypotheses,
    record_verdict,
    store_dir,
)

_log = logging.getLogger("atlas.investment.plc_hypothesis")
VERSION = "plc.d.hypothesis_on_buy"
_IST = ZoneInfo("Asia/Kolkata")

# Calendar offsets from buy IST day. ``exit`` is event-driven (sell), not timed.
HYPOTHESIS_CHECK_OFFSETS: dict[str, int | None] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "exit": None,
}


def plc_d_enabled(cfg: dict[str, Any] | None, portfolio_key: str | None) -> bool:
    cfg = cfg or {}
    if cfg.get("plc_d_hypothesis") is not None:
        return bool(cfg.get("plc_d_hypothesis"))
    if cfg.get("plc_d_gates") is not None:
        return bool(cfg.get("plc_d_gates"))
    pk = (portfolio_key or "").lower()
    return "learner" in pk or "laboratory" in pk


def ist_today(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).date().isoformat()


def buy_hypothesis_statement(
    symbol: str,
    *,
    thesis_trigger: str | None = None,
    horizon_days: int = 90,
) -> str:
    sym = str(symbol or "").strip().upper() or "SYMBOL"
    trigger = (thesis_trigger or "").strip()
    if trigger:
        because = trigger[:180]
    else:
        because = "control SMA/RSI signal (thesis trigger unknown at buy)"
    return (
        f"{sym} outperforms NIFTY over {int(horizon_days)}d because {because}"
    )[:500]


def _schedule_from_buy_day(buy_ist: str) -> list[dict[str, Any]]:
    base = date.fromisoformat(str(buy_ist)[:10])
    rows: list[dict[str, Any]] = []
    for name, offset in HYPOTHESIS_CHECK_OFFSETS.items():
        rows.append(
            {
                "checkpoint": name,
                "due_ist": (base + timedelta(days=int(offset))).isoformat()
                if offset is not None
                else None,
                "status": "pending",
                "completed_at": None,
                "observation_links": 0,
                "note": None,
            }
        )
    return rows


def create_buy_hypothesis(
    data_dir: str | None,
    *,
    symbol: str,
    thesis_trigger: str | None = None,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
    strategy_tag: str | None = None,
    decision_id: str | None = None,
    buy_ist: str | None = None,
) -> dict[str, Any]:
    """Create open hypothesis + 7/30/90/exit schedule. Best-effort durable."""
    day = buy_ist or ist_today()
    lab = laboratory_id or portfolio_key or "india_equity_learner"
    stmt = buy_hypothesis_statement(symbol, thesis_trigger=thesis_trigger)
    tags = ["plc.d", "buy", "relative_return"]
    if thesis_trigger:
        tags.append("thesis_trigger")
    return create_hypothesis(
        data_dir,
        statement=stmt,
        domain_tags=tags,
        laboratory_id=lab,
        transfer_class="strategy",
        linked_decision_ids=[decision_id] if decision_id else None,
        extra={
            "plc_d": True,
            "symbol": str(symbol).strip().upper(),
            "portfolio_key": portfolio_key or lab,
            "strategy_tag": strategy_tag,
            "thesis_trigger": (thesis_trigger or "")[:240] or None,
            "buy_ist": day,
            "checks": _schedule_from_buy_day(day),
            "version": VERSION,
        },
    )


def attach_decision_to_hypothesis(
    data_dir: str | None,
    *,
    hypothesis_id: str,
    decision_id: str,
    laboratory_id: str | None = None,
) -> dict[str, Any] | None:
    if not hypothesis_id or not decision_id:
        return None
    try:
        return link_decision(
            data_dir,
            hypothesis_id=hypothesis_id,
            decision_id=decision_id,
            laboratory_id=laboratory_id,
        )
    except Exception:  # noqa: BLE001
        _log.debug("PLC.D link_decision failed", exc_info=True)
        return None


def find_open_buy_hypothesis_for_symbol(
    data_dir: str | None,
    *,
    symbol: str,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    lab = laboratory_id or portfolio_key
    sym = str(symbol or "").strip().upper()
    for row in list_hypotheses(
        data_dir, laboratory_id=lab, include_world=False, status="open", limit=80
    ):
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if not extra.get("plc_d"):
            continue
        if str(extra.get("symbol") or "").upper() == sym:
            return row
    return None


def _persist_hypothesis(data_dir: str | None, row: dict[str, Any]) -> None:
    if not data_dir or not row.get("hypothesis_id"):
        return
    lab = row.get("laboratory_id")
    root = store_dir(data_dir, laboratory_id=lab)
    path = root / "by_id" / f"{row['hypothesis_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")


def _count_linked_observations(
    observations: Any | None,
    *,
    symbol: str,
    since_hours: float = 24.0 * 100,
) -> int:
    if observations is None:
        return 0
    try:
        rows = (
            observations.list_symbol(
                symbol=symbol, limit=40, since_hours=since_hours
            )
            or []
        )
        return len([r for r in rows if isinstance(r, dict)])
    except Exception:  # noqa: BLE001
        return 0


def complete_hypothesis_check(
    data_dir: str | None,
    *,
    hypothesis_id: str,
    checkpoint: str,
    laboratory_id: str | None = None,
    observation_links: int | None = None,
    note: str = "",
    mark_exit: bool = False,
) -> dict[str, Any]:
    """Mark one scheduled check done. Does not invent a strong verdict."""
    row = get_hypothesis(data_dir, hypothesis_id, laboratory_id=laboratory_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    extra = dict(row.get("extra") or {})
    checks = list(extra.get("checks") or [])
    found = False
    for c in checks:
        if not isinstance(c, dict):
            continue
        if str(c.get("checkpoint") or "") != checkpoint:
            continue
        if str(c.get("status") or "") == "done" and not mark_exit:
            return {
                "ok": True,
                "skipped": True,
                "hypothesis": row,
                "checkpoint": checkpoint,
            }
        c["status"] = "done"
        c["completed_at"] = ist_today()
        if observation_links is not None:
            c["observation_links"] = int(observation_links)
        if note:
            c["note"] = note[:300]
        found = True
        break
    if not found and checkpoint == "exit":
        checks.append(
            {
                "checkpoint": "exit",
                "due_ist": None,
                "status": "done",
                "completed_at": ist_today(),
                "observation_links": int(observation_links or 0),
                "note": (note or "exit fill")[:300],
            }
        )
        found = True
    if not found:
        return {"ok": False, "error": f"checkpoint {checkpoint} missing"}
    extra["checks"] = checks
    row["extra"] = extra
    row["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _persist_hypothesis(data_dir, row)

    n_done = sum(1 for c in checks if isinstance(c, dict) and c.get("status") == "done")
    n_obs = int(observation_links or 0)
    n_links = len(row.get("linked_decision_ids") or []) + n_obs
    verdict_meta = None
    if checkpoint in {"90d", "exit"}:
        try:
            verdict_meta = record_verdict(
                data_dir,
                hypothesis_id=hypothesis_id,
                verdict="inconclusive",
                laboratory_id=row.get("laboratory_id"),
                evidence_n=n_links,
                note=(
                    f"PLC.D {checkpoint} check — inconclusive pending attribution "
                    f"(links={n_links}, min={VERDICT_MIN_LINKS})"
                ),
            )
        except Exception:  # noqa: BLE001
            _log.debug("PLC.D auto-verdict skipped", exc_info=True)

    return {
        "ok": True,
        "version": VERSION,
        "hypothesis_id": hypothesis_id,
        "checkpoint": checkpoint,
        "checks_done": n_done,
        "observation_links": n_obs,
        "verdict": verdict_meta,
        "hypothesis": get_hypothesis(
            data_dir, hypothesis_id, laboratory_id=laboratory_id
        ),
    }


def run_due_hypothesis_checks(
    data_dir: str | None,
    *,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
    as_of_ist: str | None = None,
    limit: int = 10,
    observations: Any | None = None,
) -> dict[str, Any]:
    """Drain timed (7/30/90) hypothesis checks that are due."""
    if not data_dir:
        return {"ok": False, "completed": 0, "reason": "no_data_dir"}
    lab = laboratory_id or portfolio_key or "india_equity_learner"
    today = as_of_ist or ist_today()
    completed: list[dict[str, Any]] = []
    due_n = 0
    for row in list_hypotheses(
        data_dir, laboratory_id=lab, include_world=False, status="open", limit=80
    ):
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        if not extra.get("plc_d"):
            continue
        sym = str(extra.get("symbol") or "")
        for c in list(extra.get("checks") or []):
            if not isinstance(c, dict):
                continue
            cp = str(c.get("checkpoint") or "")
            if cp == "exit" or str(c.get("status") or "") == "done":
                continue
            due = c.get("due_ist")
            if not due or str(due) > today:
                continue
            due_n += 1
            if len(completed) >= limit:
                continue
            obs_n = _count_linked_observations(observations, symbol=sym)
            out = complete_hypothesis_check(
                data_dir,
                hypothesis_id=str(row.get("hypothesis_id")),
                checkpoint=cp,
                laboratory_id=lab,
                observation_links=obs_n,
                note=f"due check as_of={today}",
            )
            if out.get("ok"):
                completed.append(out)
    return {
        "ok": True,
        "version": VERSION,
        "as_of_ist": today,
        "due": due_n,
        "completed": len(completed),
        "items": completed,
    }


def format_hypothesis_digest_lines(
    data_dir: str | None,
    *,
    laboratory_id: str | None = None,
    portfolio_key: str | None = None,
    limit: int = 8,
) -> list[str]:
    """Evening / status snippet — open PLC.D hypotheses."""
    if not data_dir:
        return []
    lab = laboratory_id or portfolio_key
    rows = list_hypotheses(
        data_dir, laboratory_id=lab, include_world=False, status="open", limit=limit
    )
    plc = [
        r
        for r in rows
        if isinstance((r.get("extra") or {}), dict)
        and (r.get("extra") or {}).get("plc_d")
    ]
    if not plc:
        return ["  Hypotheses (PLC.D): none open"]
    lines = [f"  Hypotheses (PLC.D): {len(plc)} open"]
    for r in plc[:limit]:
        extra = r.get("extra") or {}
        checks = extra.get("checks") or []
        done = sum(
            1 for c in checks if isinstance(c, dict) and c.get("status") == "done"
        )
        pending = sum(
            1 for c in checks if isinstance(c, dict) and c.get("status") != "done"
        )
        lines.append(
            f"    · {extra.get('symbol') or '?'}: "
            f"{str(r.get('statement') or '')[:70]}… "
            f"checks {done}/{done + pending} "
            f"id={str(r.get('hypothesis_id') or '')[:8]}"
        )
    return lines
