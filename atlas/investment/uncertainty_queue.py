"""OI-MDPH0 Phase 4 — Uncertainty → acquisition work queue.

unknown → importance → HIGH → acquisition task → packet update → re-evaluate

Turns material unknowns (fcf_missing, pe_missing, …) into durable work items
instead of infinite HOLD loops. Does not invent fundamentals or place orders.
"""

from __future__ import annotations

import json
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VERSION = "learn.uncertainty_queue.v1"
STORE_REL = Path("investment") / "uncertainty_queue"
_IST = ZoneInfo("Asia/Kolkata")
_log = logging.getLogger("atlas.investment.uncertainty_queue")

STATUS_PENDING = "PENDING"
STATUS_DONE = "DONE"
STATUS_NOT_WORTHWHILE = "NOT_WORTHWHILE"
STATUS_EXPIRED = "EXPIRED"

# Material unknowns that block or degrade fundamental confidence
MATERIAL_UNKNOWN_CODES = frozenset(
    {
        "fcf_missing",
        "pe_missing",
        "pb_missing",
        "pb_conflict",
        "mos_unknown",
        "roe_missing",
        "revenue_missing",
        "identity_unknown",
        "debt_missing",
        "sector_missing",
    }
)

IMPORTANCE_HIGH = {
    "fcf_missing": "FCF materially affects fundamental confidence and thesis gates.",
    "pe_missing": "PE missing blocks valuation-relative ranking.",
    "mos_unknown": "Margin of safety unknown — cannot size conviction.",
    "identity_unknown": "Company identity unresolved — thesis may be quarantined.",
    "debt_missing": "Debt/equity is required by PLC.A — missing D/E is a decision gap.",
    "roe_missing": "ROE missing blocks PLC.A completeness.",
    "sector_missing": "Sector missing blocks PLC.A completeness — not an XBRL P&L fact.",
}


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (s or ""))[:80]


def store_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    return Path(data_dir) / STORE_REL / _safe(laboratory_id)


def classify_importance(code: str) -> tuple[str, str]:
    code = str(code or "").strip().lower()
    if code in IMPORTANCE_HIGH:
        return "HIGH", IMPORTANCE_HIGH[code]
    if code in MATERIAL_UNKNOWN_CODES:
        return "MEDIUM", f"Material unknown '{code}' affects decision quality."
    return "LOW", f"Unknown '{code}' noted — may not block Next-₹1."


def make_acquisition_task(
    *,
    laboratory_id: str,
    symbol: str,
    unknown_code: str,
    owner: str = "research_pipeline",
    expiry_days: int = 7,
    why: str | None = None,
) -> dict[str, Any]:
    sym = str(symbol or "").upper()
    code = str(unknown_code or "").strip().lower()
    importance, default_why = classify_importance(code)
    tid = hashlib.sha1(f"{laboratory_id}:{sym}:{code}".encode()).hexdigest()[:12]
    exp = (datetime.now(_IST) + timedelta(days=int(expiry_days))).strftime("%Y-%m-%d")
    return {
        "version": VERSION,
        "id": f"UQ-{tid}",
        "laboratory_id": laboratory_id,
        "symbol": sym,
        "unknown": code,
        "importance": importance,
        "why": why or default_why,
        "action": f"Acquire evidence for {code} on {sym}",
        "owner": owner,
        "status": STATUS_PENDING,
        "expiry_ist": exp,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "packet_rebuild_required": True,
        "never_invents_fundamentals": True,
        "attempt_count": 0,
        "last_attempt_at": None,
        "last_error": None,
        "provider": None,
        "honesty": (
            "Task records the unknown — it does not fabricate FCF/PE. "
            "HOLD may continue until evidence arrives or task is marked not-worthwhile."
        ),
    }


def upsert_task(data_dir: str | Path, task: dict[str, Any]) -> dict[str, Any]:
    lab = str(task.get("laboratory_id") or "default")
    root = store_dir(data_dir, lab)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{task['id']}.json"
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    if existing.get("status") in {STATUS_DONE, STATUS_NOT_WORTHWHILE}:
        return existing
    merged = {**existing, **task, "updated_at": _now_iso()}
    if existing.get("created_at"):
        merged["created_at"] = existing["created_at"]
    # Preserve diagnostics unless the new task explicitly sets them
    for key in ("attempt_count", "last_attempt_at", "last_error", "provider"):
        if key in existing and task.get(key) in (None, 0, ""):
            merged[key] = existing.get(key)
    if existing.get("attempt_count") and not task.get("attempt_count"):
        merged["attempt_count"] = existing["attempt_count"]
    path.write_text(json.dumps(merged, indent=2, default=str) + "\n", encoding="utf-8")
    return merged


def mark_task(
    data_dir: str | Path,
    task_id: str,
    *,
    laboratory_id: str,
    status: str,
    note: str | None = None,
    last_error: str | None = None,
    provider: str | None = None,
    bump_attempt: bool = False,
) -> dict[str, Any]:
    path = store_dir(data_dir, laboratory_id) / f"{task_id}.json"
    if not path.is_file():
        return {"ok": False, "error": "not_found"}
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["status"] = status
    doc["updated_at"] = _now_iso()
    if note:
        doc["note"] = note
    if last_error is not None:
        doc["last_error"] = last_error
    if provider is not None:
        doc["provider"] = provider
    if bump_attempt:
        doc["attempt_count"] = int(doc.get("attempt_count") or 0) + 1
        doc["last_attempt_at"] = _now_iso()
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    return {"ok": True, "task": doc}


def note_attempt(
    data_dir: str | Path,
    task_id: str,
    *,
    laboratory_id: str,
    provider: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Record a drain attempt without changing PENDING/DONE."""
    path = store_dir(data_dir, laboratory_id) / f"{task_id}.json"
    if not path.is_file():
        return {"ok": False, "error": "not_found"}
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["attempt_count"] = int(doc.get("attempt_count") or 0) + 1
    doc["last_attempt_at"] = _now_iso()
    doc["updated_at"] = _now_iso()
    if provider is not None:
        doc["provider"] = provider
    if error is not None:
        doc["last_error"] = str(error)[:300]
    path.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
    return {"ok": True, "task": doc}


def list_tasks(
    data_dir: str | Path,
    laboratory_id: str,
    *,
    status: str | None = STATUS_PENDING,
) -> list[dict[str, Any]]:
    root = store_dir(data_dir, laboratory_id)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    today = ist_today()
    for p in root.glob("UQ-*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict):
            continue
        # Auto-expire
        if (
            doc.get("status") == STATUS_PENDING
            and doc.get("expiry_ist")
            and str(doc["expiry_ist"]) < today
        ):
            doc["status"] = STATUS_EXPIRED
            doc["updated_at"] = _now_iso()
            try:
                p.write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
            except OSError:
                pass
        if status and doc.get("status") != status:
            continue
        out.append(doc)
    out.sort(key=lambda d: (0 if d.get("importance") == "HIGH" else 1, d.get("symbol") or ""))
    return out


def enqueue_from_unknowns(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    symbol: str,
    unknowns: list[str] | None,
    only_material: bool = True,
) -> dict[str, Any]:
    """Create acquisition tasks for unknowns on a symbol."""
    codes = [str(u).strip().lower() for u in (unknowns or []) if u]
    created: list[str] = []
    skipped: list[str] = []
    for code in codes:
        if only_material and code not in MATERIAL_UNKNOWN_CODES:
            skipped.append(code)
            continue
        task = make_acquisition_task(
            laboratory_id=laboratory_id, symbol=symbol, unknown_code=code
        )
        upsert_task(data_dir, task)
        created.append(task["id"])
    return {
        "ok": True,
        "symbol": str(symbol or "").upper(),
        "created_ids": created,
        "skipped": skipped,
        "pending_n": len(list_tasks(data_dir, laboratory_id)),
    }


def enqueue_from_awareness(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    symbol: str,
    awareness: dict[str, Any] | None,
) -> dict[str, Any]:
    aw = awareness if isinstance(awareness, dict) else {}
    unknowns: list[str] = []

    def _norm(raw: Any) -> str | None:
        s = str(raw or "").strip().lower()
        if not s:
            return None
        if "." in s:
            s = s.rsplit(".", 1)[-1]
        for suffix in ("_missing", "_unknown", "_gap"):
            if s.endswith(suffix):
                base = s[: -len(suffix)]
                if base == "mos" or "margin" in base:
                    return "mos_unknown"
                if f"{base}_missing" in MATERIAL_UNKNOWN_CODES:
                    return f"{base}_missing"
                if base == "identity":
                    return "identity_unknown"
        if s in MATERIAL_UNKNOWN_CODES:
            return s
        if s in {"fcf", "free_cash_flow"}:
            return "fcf_missing"
        if s in {"pe", "pb", "roe", "revenue"}:
            return f"{s}_missing"
        if "mos" in s or "margin of safety" in s:
            return "mos_unknown"
        if "identity" in s:
            return "identity_unknown"
        return s

    for u in list(aw.get("unknowns") or []) + list(aw.get("known_unknowns") or []):
        n = _norm(u)
        if n:
            unknowns.append(n)
    # Also scan nested fundamental gaps
    fund = aw.get("fundamentals") if isinstance(aw.get("fundamentals"), dict) else {}
    for k, v in fund.items():
        if v in (None, "", "UNKNOWN", "missing") and f"{k}_missing" in MATERIAL_UNKNOWN_CODES:
            unknowns.append(f"{k}_missing")
    val = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {}
    for miss in list(val.get("missing_inputs") or []):
        n = _norm(miss)
        if n:
            unknowns.append(n)
    return enqueue_from_unknowns(
        data_dir, laboratory_id=laboratory_id, symbol=symbol, unknowns=unknowns
    )


def mark_not_worthwhile(
    data_dir: str | Path,
    task_id: str,
    *,
    laboratory_id: str,
    reason: str,
) -> dict[str, Any]:
    """Explicit not-worthwhile — closes the materiality gate without acquisition."""
    return mark_task(
        data_dir,
        task_id,
        laboratory_id=laboratory_id,
        status=STATUS_NOT_WORTHWHILE,
        note=reason,
    )


def prune_non_material_pending(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    material_symbols: set[str] | frozenset[str] | list[str],
    reason: str = "not_material_to_next_rupee",
) -> dict[str, Any]:
    """Mark pending tasks outside the lab-decision material set as NOT_WORTHWHILE.

    Material = Next-₹1 destination ∪ open holds ∪ SMA/plan/PLC.A-blocked names.
    Do not pass the full NIFTY50 watchlist.
    """
    mat = {str(s).upper() for s in (material_symbols or []) if s}
    closed: list[str] = []
    for t in list_tasks(data_dir, laboratory_id, status=STATUS_PENDING):
        sym = str(t.get("symbol") or "").upper()
        if sym and sym not in mat:
            tid = str(t.get("id") or "")
            if not tid:
                continue
            mark_not_worthwhile(
                data_dir, tid, laboratory_id=laboratory_id, reason=reason
            )
            closed.append(tid)
    return {"ok": True, "closed_n": len(closed), "ids": closed[:20]}


def format_queue_lines(
    data_dir: str | Path, laboratory_id: str, *, limit: int = 8
) -> list[str]:
    tasks = list_tasks(data_dir, laboratory_id, status=STATUS_PENDING)[:limit]
    if not tasks:
        return ["Uncertainty queue: empty (no pending material unknowns)."]
    lines = [f"Uncertainty queue ({len(tasks)} pending):"]
    for t in tasks:
        lines.append(
            f"  · {t.get('symbol')} {t.get('unknown')} "
            f"importance={t.get('importance')} owner={t.get('owner')} "
            f"expiry={t.get('expiry_ist')} [{t.get('id')}]"
        )
    return lines


def merge_decision_material(
    *,
    destination: str | None = None,
    holdings: list[dict[str, Any]] | None = None,
    extra: set[str] | frozenset[str] | list[str] | None = None,
) -> set[str]:
    """Next-₹1 ∪ open holds ∪ extra (plan / SMA BUY / PLC.A-blocked)."""
    out: set[str] = set()
    dest = str(destination or "").strip().upper()
    if dest and dest not in {"", "CASH"}:
        out.add(dest)
    for h in holdings or []:
        if not isinstance(h, dict):
            continue
        s = str(h.get("symbol") or "").strip().upper()
        if s:
            out.add(s)
    for s in extra or []:
        key = str(s or "").strip().upper()
        if key and key != "CASH":
            out.add(key)
    return out


def extra_material_from_lab(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    daily_plan: dict[str, Any] | None = None,
    plc_a_failed: list[str] | None = None,
) -> set[str]:
    """Plan names + today's BUY / fundamentals_incomplete packets + PLC.A fails."""
    extra: set[str] = set()
    if isinstance(daily_plan, dict):
        try:
            from atlas.investment.process_proxies import plan_index

            extra.update(plan_index(daily_plan).keys())
        except Exception:  # noqa: BLE001
            for c in daily_plan.get("candidates") or []:
                if isinstance(c, dict) and c.get("symbol"):
                    extra.add(str(c["symbol"]).strip().upper())
    for s in plc_a_failed or []:
        key = str(s or "").strip().upper()
        if key:
            extra.add(key)
    if not data_dir or not laboratory_id:
        return extra
    try:
        from atlas.investment.decision_packets import DecisionPacketStore, ist_today

        store = DecisionPacketStore(data_dir=str(data_dir))
        for pkt in store.list_day(portfolio_key=laboratory_id, ts_ist=ist_today(), limit=200):
            if not isinstance(pkt, dict):
                continue
            kind = str(pkt.get("kind") or pkt.get("action") or "").lower()
            tag = str(pkt.get("strategy_tag") or "").lower()
            reasons = " ".join(str(x) for x in (pkt.get("reasons_against") or [])).lower()
            if (
                kind in {"buy", "sell"}
                or "fundamentals_incomplete" in tag
                or "fundamentals_incomplete" in reasons
                or tag in {"sma_cross_rsi", "plan_watch"}
            ):
                sym = str(pkt.get("symbol") or "").strip().upper()
                if sym:
                    extra.add(sym)
    except Exception:  # noqa: BLE001
        _log.debug("packet material scan skipped", exc_info=True)
    return extra
