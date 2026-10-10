"""Nine-line lab status contract for evening / ops mail (weekend P3).

Every laboratory block must report the same stages with an explicit scope.
Counts without a laboratory id are a bug. F&O planned symbols that look like
cash equities (``.NS`` / ``.BO``) with no option contracts are contamination.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VERSION = "lab.status.contract.v1"
FNO_LABS = frozenset({"india_fno_learner", "fno_learner"})
EQUITY_SUFFIX = re.compile(r"\.(NS|BO)$", re.I)
OPTION_HINT = re.compile(r"\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2,}", re.I)


def is_fno_laboratory(laboratory_id: str | None) -> bool:
    return str(laboratory_id or "").strip().lower() in FNO_LABS


def looks_like_cash_equity(symbol: str) -> bool:
    s = str(symbol or "").strip().upper()
    if not s:
        return False
    if OPTION_HINT.search(s):
        return False
    if EQUITY_SUFFIX.search(s):
        return True
    # Bare cash ticker without option month code (e.g. HFCL, IDEA)
    if s.isalpha() and 2 <= len(s) <= 12 and "CE" not in s[-2:] and "PE" not in s[-2:]:
        return True
    return False


def looks_like_option_contract(symbol: str) -> bool:
    s = str(symbol or "").strip().upper()
    if not s:
        return False
    if OPTION_HINT.search(s):
        return True
    if s.endswith("CE") or s.endswith("PE"):
        return True
    return False


def sanitize_fno_planned_symbols(
    planned: list[Any] | None,
    *,
    laboratory_id: str | None,
) -> dict[str, Any]:
    """Reject cash-watchlist contamination on an F&O KPI planned list.

    Returns ``{planned_symbols, planned_symbols_status, planned_symbols_note}``.
    """
    raw = [str(s).strip().upper() for s in (planned or []) if str(s).strip()]
    if not is_fno_laboratory(laboratory_id):
        return {
            "planned_symbols": raw,
            "planned_symbols_status": "ok",
            "planned_symbols_note": None,
        }
    if not raw:
        return {
            "planned_symbols": [],
            "planned_symbols_status": "not_evaluating",
            "planned_symbols_note": "F&O planned list empty — lab not evaluating contracts",
        }
    options = [s for s in raw if looks_like_option_contract(s)]
    cash = [s for s in raw if looks_like_cash_equity(s)]
    if cash and not options:
        return {
            "planned_symbols": [],
            "planned_symbols_status": "contaminated_cash_watchlist",
            "planned_symbols_note": (
                "Rejected cash equity names on F&O planned list: "
                + ", ".join(cash[:8])
                + ". F&O must list option contracts or not_evaluating."
            ),
            "rejected_symbols": cash,
        }
    return {
        "planned_symbols": options or raw,
        "planned_symbols_status": "ok" if options else "mixed",
        "planned_symbols_note": None,
    }


def assert_fno_planned_symbols_honest(
    planned: list[Any] | None,
    *,
    laboratory_id: str | None,
) -> None:
    """Raise AssertionError when F&O KPI planned list is cash-contaminated."""
    if not is_fno_laboratory(laboratory_id):
        return
    raw = [str(s).strip().upper() for s in (planned or []) if str(s).strip()]
    options = [s for s in raw if looks_like_option_contract(s)]
    cash = [s for s in raw if looks_like_cash_equity(s)]
    if cash and not options:
        raise AssertionError(
            "F&O planned_symbols contaminated with cash equities and no option contracts: "
            + ", ".join(cash[:8])
        )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def nightly_cognition_status(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str,
) -> dict[str, Any]:
    """Read durable nightly receipt — schedule existence is not completion."""
    if not data_dir:
        return {"status": "NOT_RUN_YET", "ran": False}
    path = (
        Path(data_dir)
        / "investment"
        / "nightly_cognition"
        / laboratory_id
        / f"{as_of_ist}.json"
    )
    doc = _read_json(path)
    if not doc:
        return {"status": "NOT_RUN_YET", "ran": False, "path": str(path)}
    if doc.get("ran") is True:
        return {
            "status": "COMPLETE",
            "ran": True,
            "stages_ran": list(doc.get("stages_ran") or []),
            "path": str(path),
        }
    if doc.get("skipped_reason"):
        return {
            "status": "PARTIAL",
            "ran": False,
            "skipped_reason": doc.get("skipped_reason"),
            "path": str(path),
        }
    return {"status": "NOT_RUN_YET", "ran": bool(doc.get("ran")), "path": str(path)}


def build_lab_status_contract(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    as_of_ist: str,
    worker: dict[str, Any] | None = None,
    kpis: dict[str, Any] | None = None,
    ops: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the nine-line contract for one laboratory."""
    lab = str(laboratory_id or "").strip()
    day = str(as_of_ist or "").strip()
    w = worker if isinstance(worker, dict) else {}
    k = kpis if isinstance(kpis, dict) else {}
    o = ops if isinstance(ops, dict) else {}

    if data_dir and not k:
        kpath = (
            Path(data_dir)
            / "market"
            / "trading_kpis"
            / lab
            / f"{day}.json"
        )
        loaded = _read_json(kpath)
        if loaded:
            k = loaded.get("kpis") if isinstance(loaded.get("kpis"), dict) else loaded

    if data_dir and not o:
        opath = Path(data_dir) / "investment" / "ops_health" / f"{day}.json"
        o = _read_json(opath) or {}

    planned_raw = list(k.get("planned_symbols") or [])
    planned = sanitize_fno_planned_symbols(planned_raw, laboratory_id=lab)

    # Cognitive / experiment receipts
    hyp = None
    if data_dir:
        qpath = (
            Path(data_dir)
            / "investment"
            / "cognitive"
            / "queue"
            / f"{lab}.jsonl"
        )
        if qpath.is_file():
            try:
                for line in qpath.read_text(encoding="utf-8").splitlines()[::-1]:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get("hypothesis_id"):
                        hyp = row
                        break
            except (OSError, json.JSONDecodeError):
                hyp = None

    cycle = None
    if data_dir:
        cpath = (
            Path(data_dir)
            / "investment"
            / "cognitive"
            / "cycles"
            / lab
            / f"{day}.json"
        )
        cycle = _read_json(cpath)

    nightly = nightly_cognition_status(
        data_dir, laboratory_id=lab, as_of_ist=day
    )

    open_inc = list(o.get("open_incidents") or [])
    incidents = o.get("incidents") if isinstance(o.get("incidents"), dict) else {}
    lab_incs = {
        key: val
        for key, val in incidents.items()
        if isinstance(val, dict)
        and (
            str(val.get("lab") or "") == lab
            or key.startswith("fno:")
            and is_fno_laboratory(lab)
        )
    }

    top_reason = None
    reasons = k.get("top_no_fill_reasons") or []
    if isinstance(reasons, list) and reasons:
        first = reasons[0]
        if isinstance(first, dict):
            top_reason = f"{first.get('reason')}×{first.get('count')}"
        else:
            top_reason = str(first)

    return {
        "version": VERSION,
        "laboratory_id": lab,
        "as_of_ist": day,
        "window": day,
        "lines": {
            "1_worker": {
                "status": w.get("status"),
                "schedule_enabled": w.get("schedule_enabled"),
                "last_tick_at": w.get("last_tick_at"),
                "pause_reason": w.get("pause_reason"),
            },
            "2_data": {
                "provider_status": o.get("provider_status")
                or (o.get("fno") or {}).get("provider_status"),
                "futures_master": (o.get("fno") or {}).get("futures_master"),
                "options_master": (o.get("fno") or {}).get("options_master"),
            },
            "3_decisions": {
                "candidates_planned": k.get("candidates_planned"),
                "planned_symbols": planned.get("planned_symbols"),
                "planned_symbols_status": planned.get("planned_symbols_status"),
                "planned_symbols_note": planned.get("planned_symbols_note"),
            },
            "4_gates": {
                "top_reason": top_reason,
                "portfolio_gate_blocks": k.get("portfolio_gate_blocks"),
            },
            "5_execution": {
                "buys_today": k.get("buys_today"),
                "sells_today": k.get("sells_today"),
                "fills_today": k.get("fills_today"),
                "open_positions": k.get("open_positions"),
                "filled_symbols": k.get("filled_symbols"),
            },
            "6_learning": {
                "episodes": (cycle or {}).get("episodes"),
                "patterns": (cycle or {}).get("patterns"),
                "learning_candidates": (cycle or {}).get("learning_candidates"),
                "nightly_cognition": nightly.get("status"),
            },
            "7_experiments": {
                "hypothesis_id": (hyp or {}).get("hypothesis_id"),
                "status": (hyp or {}).get("status"),
                "dimension": (hyp or {}).get("dimension"),
                "detail": (hyp or {}).get("detail"),
            },
            "8_beliefs": {
                "belief_proposals": (cycle or {}).get("belief_proposals"),
                "validated": (cycle or {}).get("validated"),
                "note": "ACCEPTED_OPS is not a market L5 lesson",
            },
            "9_health": {
                "open_incidents": open_inc,
                "lab_incidents": {
                    key: {
                        "status": val.get("status"),
                        "recovery": val.get("recovery"),
                        "resolution": val.get("resolution"),
                    }
                    for key, val in lab_incs.items()
                },
                "fno_category": (o.get("fno") or {}).get("category"),
            },
        },
    }


def format_lab_status_contract_lines(contract: dict[str, Any] | None) -> list[str]:
    if not isinstance(contract, dict):
        return []
    lab = contract.get("laboratory_id")
    day = contract.get("as_of_ist")
    lines = [
        "",
        f"══ Lab status contract · {lab} · window {day} ══",
    ]
    L = contract.get("lines") if isinstance(contract.get("lines"), dict) else {}
    order = [
        ("1_worker", "Worker"),
        ("2_data", "Data"),
        ("3_decisions", "Decisions"),
        ("4_gates", "Gates"),
        ("5_execution", "Execution"),
        ("6_learning", "Learning"),
        ("7_experiments", "Experiments"),
        ("8_beliefs", "Beliefs"),
        ("9_health", "Health"),
    ]
    for key, title in order:
        blob = L.get(key) if isinstance(L.get(key), dict) else {}
        bits = [f"{k}={v}" for k, v in blob.items() if v not in (None, "", [], {})]
        lines.append(f"  {title}: " + ("; ".join(bits) if bits else "—"))
    note = ((L.get("3_decisions") or {}).get("planned_symbols_note"))
    if note:
        lines.append(f"  Note: {note}")
    lines.append("Each count above is scoped to this laboratory and window.")
    return lines
