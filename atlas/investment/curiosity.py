"""OI-CURIOSITY0 — Active Curiosity Engine.

WSO.unknowns[] → durable research queue when Cognitive Budget allows.
Does not invent evidence. Optional hermetic IRA.start for data-gap unknowns.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.cognitive_budget import (
    DEFAULT_CURIOSITY_TASKS,
    budget_for_wso,
)

_log = logging.getLogger("atlas.investment.curiosity")
_IST = ZoneInfo("Asia/Kolkata")

VERSION = "cur1.curiosity.v1"
STORE_REL = Path("investment") / "curiosity_queue"

# Unknowns that map cleanly to hermetic IRA / fundamentals refresh (J2/J4)
_DATA_GAP_UNKNOWNS = {
    "fcf",
    "free_cash_flow",
    "debt_equity",
    "debt_to_equity",
    "d_e",
    "debt",
    "pe",
    "pb",
    "roe",
    "roic",
    "promoter_holding",
    "promoter",
    "fundamentals",
    "sector",
    "earnings_proximity",
    "earnings_date",
}


def normalize_unknown(unknown: str) -> str:
    """Map ``fundamentals.fcf`` / ``fcf_missing`` → canonical gap key."""
    u = str(unknown or "").strip().lower()
    if not u:
        return ""
    if "." in u:
        u = u.rsplit(".", 1)[-1]
    for suffix in ("_missing", "_unknown", "_gap"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
    aliases = {
        "free_cash_flow": "fcf",
        "d_e": "debt_to_equity",
        "debt_equity": "debt_to_equity",
        "promoter": "promoter_holding",
        "earnings": "earnings_proximity",
    }
    return aliases.get(u, u)


def is_data_gap_unknown(unknown: str) -> bool:
    return normalize_unknown(unknown) in _DATA_GAP_UNKNOWNS


def queue_dir(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL


def queue_path(data_dir: str | Path | None, ist_date: str | None = None) -> Path | None:
    root = queue_dir(data_dir)
    if root is None:
        return None
    day = ist_date or datetime.now(_IST).strftime("%Y-%m-%d")
    return root / f"{day}.json"


def load_queue(
    data_dir: str | Path | None, ist_date: str | None = None
) -> dict[str, Any]:
    path = queue_path(data_dir, ist_date)
    if path is None or not path.is_file():
        return {
            "version": VERSION,
            "ist_date": ist_date or datetime.now(_IST).strftime("%Y-%m-%d"),
            "items": [],
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"items": []}
    except (OSError, json.JSONDecodeError):
        return {"items": []}


def save_queue(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    path = queue_path(data_dir, str(doc.get("ist_date") or None))
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _evidence_needed(unknown: str) -> list[str]:
    u = normalize_unknown(unknown)
    if u in {"fcf", "free_cash_flow"}:
        return ["cashflow statement", "screener FCF", "annual report"]
    if u in {"debt_to_equity", "debt_equity", "d_e", "debt"}:
        return ["balance sheet", "screener D/E"]
    if u in {"pe", "pb", "roe", "roic"}:
        return ["fundamentals store", "screener ratios"]
    if u in {"promoter_holding", "promoter"}:
        return ["shareholding pattern", "screener promoter %"]
    if u in {"earnings_proximity", "earnings_date"}:
        return ["earnings calendar", "results date"]
    if u in {"occupancy", "arpob"}:
        return ["quarterly presentation", "management commentary", "segment metrics"]
    if u in {"company", "sector", "macro", "gov", "news", "management_commentary"}:
        return ["real RSS/news", "filings", "not seed stubs"]
    return [f"evidence for unknown:{unknown}"]


def enqueue_from_wsos(
    data_dir: str | Path | None,
    laboratory_id: str,
    wsos: list[dict[str, Any]] | None,
    *,
    max_n: int = DEFAULT_CURIOSITY_TASKS,
    ist_date: str | None = None,
    open_symbols: set[str] | None = None,
) -> dict[str, Any]:
    """Build / merge nightly curiosity queue from WSO unknowns (deterministic)."""
    day = ist_date or datetime.now(_IST).strftime("%Y-%m-%d")
    prior = load_queue(data_dir, day)
    prior_keys = {
        (str(i.get("symbol") or ""), str(i.get("unknown") or ""))
        for i in (prior.get("items") or [])
        if isinstance(i, dict)
    }
    open_set = {str(s).upper() for s in (open_symbols or set())}
    candidates: list[dict[str, Any]] = []
    for w in wsos or []:
        if not isinstance(w, dict):
            continue
        sym = str(w.get("symbol") or "").strip()
        if not sym:
            continue
        is_open = (not open_set) or sym.upper() in open_set or any(
            sym.upper().startswith(o) for o in open_set
        )
        for unk in list(w.get("unknowns") or [])[:12]:
            unk_s = str(unk).strip()
            if not unk_s:
                continue
            key = (sym, unk_s)
            previously = key in prior_keys
            bud = budget_for_wso(
                w,
                is_open_position=is_open,
                previously_queued=previously,
            )
            if int(bud.get("llm_budget") or 0) <= 0 and not (
                is_open and is_data_gap_unknown(unk_s)
            ):
                # Still allow open-book data gaps at least once
                if previously:
                    continue
            candidates.append(
                {
                    "symbol": sym,
                    "laboratory_id": laboratory_id,
                    "unknown": unk_s,
                    "goal": f"resolve unknown: {unk_s}",
                    "evidence_needed": _evidence_needed(unk_s),
                    "priority": "high"
                    if is_open and is_data_gap_unknown(unk_s)
                    else ("medium" if is_open else "low"),
                    "status": "queued",
                    "llm_budget": int(bud.get("llm_budget") or 0),
                    "budget": bud,
                    "created_at": datetime.now(_IST).isoformat(),
                }
            )
    # Prefer new high-priority; dedupe
    seen: set[tuple[str, str]] = set(prior_keys)
    fresh: list[dict[str, Any]] = []
    for c in sorted(
        candidates,
        key=lambda x: (
            0 if x.get("priority") == "high" else 1,
            -int(x.get("llm_budget") or 0),
        ),
    ):
        key = (str(c["symbol"]), str(c["unknown"]))
        if key in seen:
            continue
        seen.add(key)
        fresh.append(c)
        if len(fresh) >= max(0, int(max_n)):
            break
    items = list(prior.get("items") or []) + fresh
    doc = {
        "version": VERSION,
        "ist_date": day,
        "laboratory_id": laboratory_id,
        "items": items[-200:],
        "enqueued_tonight": len(fresh),
        "max_n": int(max_n),
    }
    path = save_queue(data_dir, doc)
    doc["path"] = str(path) if path else None
    return doc


def maybe_start_ira_for_queue(
    queue_doc: dict[str, Any] | None,
    research: Any | None,
    *,
    max_starts: int = 2,
    trigger: str = "curiosity",
) -> list[dict[str, Any]]:
    """Optional hermetic IRA.start for data-gap unknowns (no LLM required)."""
    if research is None or not hasattr(research, "start"):
        return []
    started: list[dict[str, Any]] = []
    for item in list((queue_doc or {}).get("items") or []):
        if len(started) >= max_starts:
            break
        if not isinstance(item, dict) or item.get("status") != "queued":
            continue
        unk_raw = str(item.get("unknown") or "")
        unk = normalize_unknown(unk_raw)
        if unk not in _DATA_GAP_UNKNOWNS:
            continue
        sym = str(item.get("symbol") or "")
        if not sym:
            continue
        try:
            result = research.start(
                sym,
                trigger=trigger,
                mode="mvr",
            )
            item["status"] = "ira_started"
            item["work_at"] = datetime.now(_IST).isoformat()
            started.append(
                {
                    "symbol": sym,
                    "unknown": unk_raw,
                    "unknown_norm": unk,
                    "result_ok": bool(result) if not isinstance(result, dict) else True,
                    "status": "ira_started",
                }
            )
        except TypeError:
            try:
                research.start(sym)
                item["status"] = "ira_started"
                item["work_at"] = datetime.now(_IST).isoformat()
                started.append(
                    {
                        "symbol": sym,
                        "unknown": unk_raw,
                        "unknown_norm": unk,
                        "status": "ira_started",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                item["status"] = "ira_failed"
                item["error"] = type(exc).__name__
                _log.debug("curiosity IRA start failed for %s", sym, exc_info=True)
        except Exception as exc:  # noqa: BLE001
            item["status"] = "ira_failed"
            item["error"] = type(exc).__name__
            _log.debug("curiosity IRA start failed for %s", sym, exc_info=True)
    return started


def drain_queue_work(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    research: Any | None,
    wsos: list[dict[str, Any]] | None = None,
    open_symbols: set[str] | None = None,
    max_starts: int = 3,
    ist_date: str | None = None,
    trigger: str = "cws_j4",
) -> dict[str, Any]:
    """J4 — enqueue unknowns then start real IRA work; persist queue statuses.

    Only data-gap items become ``ira_started``. Non-data unknowns stay ``queued``
    (honest) and do **not** count as completed cognitive work.
    """
    day = ist_date or datetime.now(_IST).strftime("%Y-%m-%d")
    qdoc = enqueue_from_wsos(
        data_dir,
        laboratory_id,
        wsos,
        max_n=DEFAULT_CURIOSITY_TASKS,
        ist_date=day,
        open_symbols=open_symbols,
    )
    started = maybe_start_ira_for_queue(
        qdoc, research, max_starts=max(0, int(max_starts)), trigger=trigger
    )
    path = save_queue(data_dir, qdoc)
    qdoc["path"] = str(path) if path else None
    qdoc["work_started"] = started
    qdoc["work_started_n"] = len(started)
    return qdoc


def format_curiosity_section(queue_doc: dict[str, Any] | None) -> list[str]:
    """Evening/hourly: show curiosity queue with real work statuses."""
    q = queue_doc if isinstance(queue_doc, dict) else {}
    items = [i for i in (q.get("items") or []) if isinstance(i, dict)]
    lines = ["", "--- Curiosity / unknowns → work (J4) ---"]
    if not items:
        lines.append("No curiosity items queued tonight.")
        return lines
    by_status: dict[str, int] = {}
    for it in items:
        st = str(it.get("status") or "queued")
        by_status[st] = by_status.get(st, 0) + 1
    lines.append(
        "queue: "
        + " · ".join(f"{k}={v}" for k, v in sorted(by_status.items()))
        + f" · total={len(items)}"
    )
    for it in items[-6:]:
        lines.append(
            f"  · {it.get('symbol')}: {it.get('unknown')} "
            f"[{it.get('status')}] pri={it.get('priority')}"
        )
    n_work = int(q.get("work_started_n") or 0)
    if n_work:
        lines.append(f"work_started_tonight={n_work} (IRA MVR — hermetic)")
    else:
        lines.append(
            "Honesty: queued ≠ done. Data-gap items start IRA when research is available; "
            "news/commentary unknowns stay queued until real evidence exists."
        )
    return lines
