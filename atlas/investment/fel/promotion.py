"""Promotion is a status, never a live V1 mutation (FEL.3 / D6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ALLOWED = frozenset({"never", "candidate", "paper_challenger"})
LIVE_CONTROL = "live_control"


def promotion_for(*, result: str, operator_level10: bool = False) -> str:
    """FEL never writes live_control. Level 10 is an operator act outside this module."""
    del operator_level10
    if result == "improve":
        return "candidate"
    if result == "conditional":
        return "candidate"
    return "never"


def assert_not_live(promotion: str) -> None:
    if promotion == LIVE_CONTROL:
        raise ValueError("FEL must not promote to live_control")


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in (text or ""))[:80]


def enqueue_candidate_investigation(
    data_dir: str | Path | None,
    *,
    promotion: str,
    candidate_id: str,
    symbol: str,
    metric: str,
    laboratory_id: str = "india_equity_learner",
) -> dict[str, Any]:
    """Write one kernel inbox file for a candidate. Does not change the strategy.

    The file is a pointer. It is written only when the named fact is TRUSTED or
    an explicit UNKNOWN. The numeric value stays in the quality registry.
    """
    assert_not_live(promotion)
    if str(promotion or "") != "candidate":
        return {"ok": False, "written": False, "reason": "not_a_candidate"}
    cid = str(candidate_id or "").strip()
    if not cid or not data_dir or not str(symbol or "").strip() or not str(metric or "").strip():
        return {"ok": False, "written": False, "reason": "candidate_pointer_incomplete"}
    from atlas.investment.data_quality import Q_TRUSTED, Q_UNKNOWN, current_capability

    row = current_capability(data_dir, symbol, metric, laboratory_id=laboratory_id)
    quality = str((row or {}).get("quality_status") or "")
    reason = str((row or {}).get("reason") or "").strip()
    if quality == Q_TRUSTED:
        fact_state = "TRUSTED"
    elif quality == Q_UNKNOWN and reason:
        fact_state = "UNKNOWN"
    else:
        return {"ok": False, "written": False, "reason": "fact_not_trusted_or_unknown"}
    evidence_id = str((row or {}).get("evidence_id") or "") or None
    metric_name = str((row or {}).get("metric") or metric)
    objective = (
        f"Investigate FEL candidate {cid} for {symbol}. "
        f"The {metric_name} fact is {fact_state}. "
        f"Evidence {evidence_id or 'none'}."
    )
    inbox = Path(data_dir) / "agent_kernel" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / f"fel-{_safe(cid)}.json"
    if path.is_file():
        return {"ok": True, "written": False, "reason": "already_queued", "path": str(path), "objective": objective}
    doc = {
        "source": "fel_candidate",
        "domain": "investment",
        "symbol": str(symbol).strip().upper(),
        "objective": objective,
        "reason": f"fel promotion candidate {cid}",
        "required": [metric_name],
        "candidate_id": cid,
        "fact": {
            "symbol": str(symbol).strip().upper(),
            "metric": metric_name,
            "quality": fact_state,
            "evidence_id": evidence_id,
            "reason": reason or None,
        },
        "constraints": {"never_orders": True, "strategy_mutation": False},
        "decision_impact": False,
        "interpretive": False,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "written": True, "path": str(path), "objective": objective}
