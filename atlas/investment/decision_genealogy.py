"""OI-GENE0 / GENE.1 — Decision genealogy assembler (honest gaps).

Chain (RLD §3.7):
  Decision → evidence → feature → strategy → experiment → outcome → lesson → next

Assembles from existing stores only — never invents missing links.
Optional write-path stamps ``parent_decision_id`` on follow-on material packets.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.decision_genealogy")
VERSION = "gene1.genealogy.v1"
STORE_REL = Path("investment") / "decisions" / "genealogy"

CHAIN_HOPS = (
    "decision",
    "evidence",
    "feature",
    "strategy",
    "experiment",
    "outcome",
    "lesson",
    "next",
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (s or ""))


def store_dir(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def by_id_path(data_dir: str | Path, decision_id: str) -> Path:
    d = store_dir(data_dir) / "by_id"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_safe(decision_id)}.json"


def find_parent_decision_id(
    packets_store: Any,
    *,
    symbol: str,
    portfolio_key: str,
    exclude_decision_id: str | None = None,
) -> str | None:
    """Most recent prior material (buy/sell) packet for symbol — honest parent link."""
    if packets_store is None or not symbol:
        return None
    try:
        rows = packets_store.list_symbol(
            symbol=symbol, limit=30, portfolio_key=portfolio_key
        ) or []
    except Exception:  # noqa: BLE001
        return None
    for p in rows:
        if not isinstance(p, dict):
            continue
        did = str(p.get("decision_id") or "")
        if exclude_decision_id and did == str(exclude_decision_id):
            continue
        act = str(p.get("action") or "").lower()
        if act not in {"buy", "sell"}:
            continue
        if did:
            return did
    return None


def _hop(name: str, *, present: bool, detail: Any = None, gap: str | None = None) -> dict[str, Any]:
    return {
        "hop": name,
        "present": bool(present),
        "detail": detail,
        "gap": gap if not present else None,
    }


def build_genealogy(
    decision_id: str,
    *,
    data_dir: str | Path | None = None,
    packet: dict[str, Any] | None = None,
    packets_store: Any | None = None,
    attributions_store: Any | None = None,
    laboratory_id: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Assemble genealogy for one decision. Honest nulls for missing hops."""
    did = str(decision_id or "").strip()
    pkt = packet
    if pkt is None and packets_store is not None:
        try:
            pkt = packets_store.get(did)
        except Exception:  # noqa: BLE001
            pkt = None
    if pkt is None and data_dir:
        try:
            from atlas.investment.decision_packets import _load_json_packet

            pkt = _load_json_packet(data_dir, did)
        except Exception:  # noqa: BLE001
            pkt = None

    hops: list[dict[str, Any]] = []
    gaps: list[str] = []

    if not isinstance(pkt, dict):
        hops.append(_hop("decision", present=False, gap="packet not found"))
        gaps.append("decision")
        doc = {
            "version": VERSION,
            "decision_id": did,
            "created_at": _now(),
            "hops": hops,
            "gaps": gaps,
            "completeness_pct": 0.0,
            "chain": list(CHAIN_HOPS),
        }
        return doc

    lab = str(
        laboratory_id
        or pkt.get("laboratory_id")
        or pkt.get("portfolio_key")
        or "india_equity_learner"
    )

    # 1 decision
    hops.append(
        _hop(
            "decision",
            present=True,
            detail={
                "decision_id": did,
                "symbol": pkt.get("symbol"),
                "action": pkt.get("action"),
                "strategy_tag": pkt.get("strategy_tag"),
                "parent_decision_id": pkt.get("parent_decision_id"),
                "ts_ist": pkt.get("ts_ist"),
            },
        )
    )

    # 2 evidence
    obs_ids = list(pkt.get("observation_ids") or [])
    evid_refs = list(pkt.get("evidence_refs") or [])
    evid_ok = bool(obs_ids or evid_refs)
    hops.append(
        _hop(
            "evidence",
            present=evid_ok,
            detail={"observation_ids": obs_ids[:20], "evidence_refs": evid_refs[:12]},
            gap=None if evid_ok else "no observation_ids or evidence_refs",
        )
    )
    if not evid_ok:
        gaps.append("evidence")

    # 3 feature
    feats = pkt.get("feature_contributions")
    feat_ok = isinstance(feats, dict) and bool(feats)
    hops.append(
        _hop(
            "feature",
            present=feat_ok,
            detail={"keys": list(feats.keys())[:12] if isinstance(feats, dict) else []},
            gap=None if feat_ok else "no feature_contributions",
        )
    )
    if not feat_ok:
        gaps.append("feature")

    # 4 strategy
    tag = pkt.get("strategy_tag")
    hops.append(
        _hop(
            "strategy",
            present=bool(tag),
            detail={"strategy_tag": tag, "setup_tag": pkt.get("setup_tag")},
            gap=None if tag else "no strategy_tag",
        )
    )
    if not tag:
        gaps.append("strategy")

    # 5 experiment (+ hypothesis)
    exp_id = pkt.get("experiment_id")
    hyp_id = pkt.get("hypothesis_id")
    exp_ok = bool(exp_id or hyp_id)
    hops.append(
        _hop(
            "experiment",
            present=exp_ok,
            detail={"experiment_id": exp_id, "hypothesis_id": hyp_id},
            gap=None if exp_ok else "no experiment_id or hypothesis_id",
        )
    )
    if not exp_ok:
        gaps.append("experiment")

    # 6 outcome (attributions + CF + rationale)
    attrs: list[dict[str, Any]] = []
    if attributions_store is not None and hasattr(attributions_store, "list_for_decision"):
        try:
            attrs = list(attributions_store.list_for_decision(did) or [])
        except Exception:  # noqa: BLE001
            attrs = []
    rationale = None
    if data_dir:
        try:
            from atlas.investment.decide_rationale import load_rationale

            rationale = load_rationale(data_dir, did, laboratory_id=lab)
        except Exception:  # noqa: BLE001
            rationale = None
    cf_rows: list[dict[str, Any]] = []
    if data_dir:
        try:
            from atlas.investment.counterfactual_learning import list_cfs

            for row in list_cfs(data_dir, laboratory_id=lab, limit=50):
                if str(row.get("decision_id") or "") == did:
                    cf_rows.append(
                        {
                            "cf_id": row.get("cf_id"),
                            "status": row.get("status"),
                            "alt_symbol": row.get("alt_symbol"),
                        }
                    )
        except Exception:  # noqa: BLE001
            cf_rows = []
    outcome_ok = bool(attrs or rationale or cf_rows)
    hops.append(
        _hop(
            "outcome",
            present=outcome_ok,
            detail={
                "attributions": len(attrs),
                "attribution_triggers": [
                    a.get("trigger") for a in attrs[:5] if isinstance(a, dict)
                ],
                "decide_rationale_status": (rationale or {}).get("status")
                if isinstance(rationale, dict)
                else None,
                "counterfactuals": cf_rows[:5],
            },
            gap=None
            if outcome_ok
            else "no attribution, decide_rationale, or counterfactual yet",
        )
    )
    if not outcome_ok:
        gaps.append("outcome")

    # 7 lesson
    lesson_ids = list(pkt.get("derived_from_lesson_ids") or [])
    lesson_ok = bool(lesson_ids)
    hops.append(
        _hop(
            "lesson",
            present=lesson_ok,
            detail={"derived_from_lesson_ids": lesson_ids[:12]},
            gap=None
            if lesson_ok
            else "no derived_from_lesson_ids (mentor→next not stamped yet)",
        )
    )
    if not lesson_ok:
        gaps.append("lesson")

    # 8 next (children with this as parent)
    children: list[str] = []
    if packets_store is not None:
        try:
            sym = str(pkt.get("symbol") or "")
            pk = str(pkt.get("portfolio_key") or lab)
            for p in packets_store.list_symbol(symbol=sym, limit=40, portfolio_key=pk) or []:
                if not isinstance(p, dict):
                    continue
                if str(p.get("parent_decision_id") or "") == did:
                    cid = p.get("decision_id")
                    if cid:
                        children.append(str(cid))
        except Exception:  # noqa: BLE001
            children = []
    next_ok = bool(children) or bool(pkt.get("parent_decision_id"))
    # "next" hop present if we are a parent OR we have a parent (chain continuity)
    hops.append(
        _hop(
            "next",
            present=bool(children),
            detail={
                "child_decision_ids": children[:12],
                "this_parent_decision_id": pkt.get("parent_decision_id"),
            },
            gap=None
            if children
            else "no child decisions with parent_decision_id pointing here",
        )
    )
    if not children:
        gaps.append("next")

    present_n = sum(1 for h in hops if h.get("present"))
    completeness = round(100.0 * present_n / max(1, len(CHAIN_HOPS)), 1)

    doc = {
        "version": VERSION,
        "decision_id": did,
        "laboratory_id": lab,
        "symbol": pkt.get("symbol"),
        "action": pkt.get("action"),
        "created_at": _now(),
        "hops": hops,
        "gaps": gaps,
        "completeness_pct": completeness,
        "chain": list(CHAIN_HOPS),
        "honesty": (
            "Gaps are real missing links — GENE.1 never invents parent/lesson/next ids."
        ),
    }
    if persist and data_dir:
        try:
            path = by_id_path(data_dir, did)
            path.write_text(
                json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            doc["path"] = str(path)
        except Exception:  # noqa: BLE001
            _log.debug("genealogy persist failed", exc_info=True)
    return doc


def completeness_summary(
    genealogies: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    rows = [g for g in (genealogies or []) if isinstance(g, dict)]
    if not rows:
        return {
            "n": 0,
            "mean_completeness_pct": None,
            "with_parent": 0,
            "sample_note": "No genealogies assembled yet.",
        }
    mean = round(
        sum(float(g.get("completeness_pct") or 0) for g in rows) / len(rows), 1
    )
    with_parent = 0
    for g in rows:
        for h in g.get("hops") or []:
            if isinstance(h, dict) and h.get("hop") == "decision":
                det = h.get("detail") if isinstance(h.get("detail"), dict) else {}
                if det.get("parent_decision_id"):
                    with_parent += 1
    return {
        "n": len(rows),
        "mean_completeness_pct": mean,
        "with_parent": with_parent,
        "sample_note": None,
    }


def format_genealogy_evening_lines(
    genealogies: list[dict[str, Any]] | None,
) -> list[str]:
    """Evening sample of decision genealogy completeness."""
    rows = [g for g in (genealogies or []) if isinstance(g, dict)]
    if not rows:
        return []
    lines = ["", "--- Decision genealogy (GENE.1) ---"]
    summary = completeness_summary(rows)
    lines.append(
        f"assembled={summary.get('n')} · mean_completeness="
        f"{summary.get('mean_completeness_pct')}% · "
        f"with_parent={summary.get('with_parent')}"
    )
    for g in rows[:5]:
        gaps = ", ".join(str(x) for x in (g.get("gaps") or [])[:4]) or "—"
        lines.append(
            f"  · {g.get('action')} {g.get('symbol')} "
            f"id={str(g.get('decision_id') or '')[:8]}… "
            f"{g.get('completeness_pct')}% gaps=[{gaps}]"
        )
    lines.append(
        "  Honesty: missing hops stay listed — required before AtlasNet (B21/D6)."
    )
    return lines
