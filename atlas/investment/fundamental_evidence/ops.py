"""FEA operational metrics — queue/throughput/NSE, not a completeness dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fea.ops.v1"
EVENTS_REL = Path("investment") / "fundamental_intelligence" / "fea_events.jsonl"
WINDOW_S = 3600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_fea_event(data_dir: str | Path | None, event: dict[str, Any]) -> None:
    if not data_dir or not isinstance(event, dict):
        return
    path = Path(data_dir) / EVENTS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(event)
    row.setdefault("t", _now_iso())
    row.setdefault("version", VERSION)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


def load_fea_events(
    data_dir: str | Path | None,
    *,
    window_s: int = WINDOW_S,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    path = Path(data_dir) / EVENTS_REL
    if not path.is_file():
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - max(60, int(window_s))
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-400:]:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(doc, dict):
                continue
            raw = str(doc.get("t") or "")
            try:
                ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts.timestamp() < cutoff:
                    continue
            except ValueError:
                pass
            out.append(doc)
    except OSError:
        return []
    return out


def summarize_fea_ops(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from atlas.investment.fundamental_evidence.dispatch import plan_batch_acquisition
    from atlas.investment.nse_xbrl.digest import load_observation

    batch = plan if isinstance(plan, dict) else None
    if batch is None:
        try:
            batch = plan_batch_acquisition(
                data_dir, laboratory_id=laboratory_id, limit=12
            )
        except Exception:  # noqa: BLE001
            batch = {}
    events = load_fea_events(data_dir)
    nse_ok = sum(1 for e in events if e.get("nse_ok"))
    nse_miss = sum(
        1
        for e in events
        if str(e.get("nse_reason") or e.get("reason") or "") == "nse_unavailable"
    )
    parse_fail = sum(1 for e in events if e.get("parse_failure"))
    conflicts = sum(int(e.get("conflicts") or 0) for e in events)
    acquired = sum(int(e.get("acquired_n") or 0) for e in events)
    completed = sum(1 for e in events if e.get("reason") == "complete")
    times = [float(e["ms"]) for e in events if e.get("ms") is not None]
    times.sort()
    median_ms = times[len(times) // 2] if times else None
    nse_n = nse_ok + nse_miss
    obs = load_observation(data_dir) if data_dir else {}
    return {
        "version": VERSION,
        "kind": "FEA_OPS",
        "queue_depth": int((batch or {}).get("queue_depth") or 0),
        "due_now": int((batch or {}).get("due_n") or 0),
        "backing_off": int((batch or {}).get("backing_off_n") or 0),
        "priority_due": dict((batch or {}).get("priority_due") or {}),
        "acquisitions_hour": acquired,
        "completed_hour": completed,
        "nse_success": nse_ok,
        "nse_unavailable": nse_miss,
        "nse_success_pct": round(100.0 * nse_ok / nse_n, 1) if nse_n else None,
        "parse_failures": parse_fail + int(obs.get("nse_parse_failures") or 0)
        if not events
        else parse_fail,
        "validation_conflicts": conflicts,
        "median_ms": median_ms,
        "yahoo_suppressed": True,
        "event_n": len(events),
    }


def format_fea_ops_lines(ops: dict[str, Any] | None) -> list[str]:
    o = ops if isinstance(ops, dict) else {}
    pct = o.get("nse_success_pct")
    pct_s = f"{pct}%" if pct is not None else "n/a"
    med = o.get("median_ms")
    med_s = f"{med:.0f}ms" if isinstance(med, (int, float)) else "n/a"
    pri = o.get("priority_due") if isinstance(o.get("priority_due"), dict) else {}
    pri_s = " ".join(f"{k}={v}" for k, v in pri.items() if v) or "none"
    return [
        "FEA",
        "──────",
        f"queue depth             {o.get('queue_depth', 0)}",
        f"due now                 {o.get('due_now', 0)}",
        f"backing off             {o.get('backing_off', 0)}",
        f"acquisitions/hour       {o.get('acquisitions_hour', 0)}",
        f"NSE success rate        {pct_s}",
        f"NSE unavailable         {o.get('nse_unavailable', 0)}",
        f"parse failures          {o.get('parse_failures', 0)}",
        f"validation conflicts    {o.get('validation_conflicts', 0)}",
        f"completed/hour          {o.get('completed_hour', 0)}",
        f"median acquisition time {med_s}",
        "Yahoo suppressed       YES",
        f"priority due            {pri_s}",
    ]
