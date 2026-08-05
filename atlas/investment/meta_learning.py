"""DI.6 — Meta-learning weekly digest + Intelligence Dashboard enrichment.

Answers Appendix B / §5.9 questions from Decision Packets + attributions +
process proxies. **Never silently rewrites strategy** — only proposes playbook
change-log rows for operator review.

D6 measures Atlas-the-product (decision system quality), not portfolio vanity.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_log = logging.getLogger("atlas.investment.meta_learning")

VERSION = "di.meta.1"
STORE_REL = Path("investment") / "decisions" / "meta_learning"
_IST = ZoneInfo("Asia/Kolkata")

GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1, "F": 0}


def ist_now() -> datetime:
    return datetime.now(_IST)


def week_key(dt: datetime | None = None) -> str:
    """ISO week key e.g. 2026-W32."""
    d = dt or ist_now()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _grade_rank(g: Any) -> int | None:
    s = str(g or "").upper()
    return GRADE_RANK.get(s)


def mirror_path(
    data_dir: str | Path, *, portfolio_key: str, week: str
) -> Path:
    safe = (portfolio_key or "india_equity_learner").replace("/", "_")
    return Path(data_dir) / STORE_REL / safe / f"{week}.json"


def build_meta_learning_digest(
    *,
    portfolio_key: str = "india_equity_learner",
    packets: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    process_proxies: dict[str, Any] | None = None,
    evolution: dict[str, Any] | None = None,
    fundamentals_gaps: dict[str, Any] | None = None,
    week: str | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Hermetic weekly intelligence digest (proposals only — no auto strategy edits)."""
    pkt_list = [p for p in (packets or []) if isinstance(p, dict)]
    attr_list = [a for a in (attributions or []) if isinstance(a, dict)]
    prox = process_proxies if isinstance(process_proxies, dict) else {}
    evo = evolution if isinstance(evolution, dict) else {}
    gaps = fundamentals_gaps if isinstance(fundamentals_gaps, dict) else {}
    wk = week or week_key()

    packets_by_id = {
        str(p["decision_id"]): p for p in pkt_list if p.get("decision_id")
    }

    # --- Completeness / genealogy / evidence ---
    comps = [
        float((p.get("meta") or {}).get("completeness") or 0)
        for p in pkt_list
        if isinstance(p.get("meta"), dict)
    ]
    avg_comp = round(sum(comps) / len(comps), 3) if comps else None
    incomplete_pct = (
        round(100.0 * sum(1 for c in comps if c < 0.55) / len(comps), 1)
        if comps
        else None
    )
    with_parent = sum(1 for p in pkt_list if p.get("parent_decision_id"))
    genealogy_pct = (
        round(100.0 * with_parent / len(pkt_list), 1) if pkt_list else None
    )
    with_obs = sum(1 for p in pkt_list if p.get("observation_ids"))
    obs_cite_pct = (
        round(100.0 * with_obs / len(pkt_list), 1) if pkt_list else None
    )
    avg_unknowns = None
    if pkt_list:
        avg_unknowns = round(
            sum(len(p.get("unknowns") or []) for p in pkt_list) / len(pkt_list),
            2,
        )

    # --- Feature contributions vs decision_quality ---
    axis_sums: dict[str, list[float]] = defaultdict(list)
    axis_high_dq: dict[str, list[float]] = defaultdict(list)
    missing_before_poor: Counter[str] = Counter()
    dq_counts: Counter[str] = Counter()
    strategy_dq: dict[str, list[int]] = defaultdict(list)

    for attr in attr_list:
        grades = attr.get("grades") if isinstance(attr.get("grades"), dict) else {}
        dq = str(grades.get("decision_quality") or "").upper()
        if dq:
            dq_counts[dq] += 1
        did = str(attr.get("decision_id") or "")
        pkt = packets_by_id.get(did) or {}
        tag = str(pkt.get("strategy_tag") or "unknown")
        rank = _grade_rank(dq)
        if rank is not None:
            strategy_dq[tag].append(rank)
        contrib = (
            pkt.get("feature_contributions")
            if isinstance(pkt.get("feature_contributions"), dict)
            else {}
        )
        for axis, raw in contrib.items():
            v = _f(raw)
            if v is None:
                continue
            axis_sums[str(axis)].append(v)
            if rank is not None and rank >= 4:  # A/B
                axis_high_dq[str(axis)].append(v)
        if rank is not None and rank <= 2:  # D/E/F
            for u in pkt.get("unknowns") or []:
                missing_before_poor[str(u)] += 1

    feature_insights: list[dict[str, Any]] = []
    for axis, vals in sorted(axis_sums.items()):
        mean_all = round(sum(vals) / len(vals), 3) if vals else None
        hi = axis_high_dq.get(axis) or []
        mean_hi = round(sum(hi) / len(hi), 3) if hi else None
        feature_insights.append(
            {
                "axis": axis,
                "n": len(vals),
                "mean_contribution": mean_all,
                "mean_when_dq_ab": mean_hi,
                "n_dq_ab": len(hi),
                "never_mattered_hint": bool(
                    vals and all(abs(v) < 0.05 for v in vals)
                ),
            }
        )
    feature_insights.sort(
        key=lambda r: (
            -(r.get("mean_when_dq_ab") or 0),
            -(r.get("n") or 0),
        )
    )

    # Indicators / axes that never mattered
    never_mattered = [
        r["axis"]
        for r in feature_insights
        if r.get("never_mattered_hint") and (r.get("n") or 0) >= 3
    ]

    # Strategy tag quality (never mix for edge — this is DQ only)
    strategy_quality = []
    for tag, ranks in sorted(strategy_dq.items()):
        if not ranks:
            continue
        strategy_quality.append(
            {
                "strategy_tag": tag,
                "n": len(ranks),
                "avg_dq_rank": round(sum(ranks) / len(ranks), 2),
                "note": "decision_quality ranks only — not P&L edge",
            }
        )
    strategy_quality.sort(key=lambda r: (-(r["avg_dq_rank"]), -r["n"]))

    # Calibration: confidence vs DQ (Stage 2 thin)
    calib_n = 0
    overconfident = 0
    underconfident = 0
    for attr in attr_list:
        grades = attr.get("grades") if isinstance(attr.get("grades"), dict) else {}
        dq_r = _grade_rank(grades.get("decision_quality"))
        did = str(attr.get("decision_id") or "")
        pkt = packets_by_id.get(did) or {}
        conf = (
            pkt.get("confidence_breakdown")
            if isinstance(pkt.get("confidence_breakdown"), dict)
            else {}
        )
        overall = _f(conf.get("overall") or conf.get("total"))
        if dq_r is None or overall is None:
            continue
        calib_n += 1
        # overall often 0–1
        if overall > 1.5:
            overall = overall / 100.0
        # high confidence + poor DQ → overconfident
        if overall >= 0.7 and dq_r <= 2:
            overconfident += 1
        if overall <= 0.35 and dq_r >= 4:
            underconfident += 1
    calibration = {
        "n": calib_n,
        "overconfident": overconfident,
        "underconfident": underconfident,
        "overconfidence_rate": (
            round(overconfident / calib_n, 4) if calib_n else None
        ),
        "note": (
            "Thin Stage-2 heuristic: overall confidence vs decision_quality grade. "
            "Not market P&L."
        ),
    }

    # Process
    prox_counts = prox.get("counts") if isinstance(prox.get("counts"), dict) else {}
    process_score = prox.get("process_score")
    pending = evo.get("pending_revisits")
    done = evo.get("done_revisits")
    revisit_done_pct = None
    if isinstance(pending, (int, float)) and isinstance(done, (int, float)):
        tot = pending + done
        revisit_done_pct = round(100.0 * done / tot, 1) if tot else None

    # Intelligence score 0–100 (Atlas-the-product)
    parts: list[float] = []
    if avg_comp is not None:
        parts.append(100.0 * avg_comp)
    if obs_cite_pct is not None:
        parts.append(obs_cite_pct)
    if genealogy_pct is not None:
        parts.append(genealogy_pct)
    if revisit_done_pct is not None:
        parts.append(revisit_done_pct)
    if process_score is not None:
        parts.append(10.0 * float(process_score))
    if calib_n and calibration.get("overconfidence_rate") is not None:
        parts.append(100.0 * (1.0 - float(calibration["overconfidence_rate"])))
    intelligence_score = round(sum(parts) / len(parts), 1) if parts else None

    # Appendix B answers
    answers = {
        "markets": {
            "most_common_process_flag": (
                max(prox_counts, key=lambda k: prox_counts[k])
                if prox_counts and any(prox_counts.values())
                else None
            ),
            "best_strategy_tag_by_dq": (
                strategy_quality[0]["strategy_tag"] if strategy_quality else None
            ),
            "worst_strategy_tag_by_dq": (
                strategy_quality[-1]["strategy_tag"]
                if len(strategy_quality) > 1
                else None
            ),
            "stop_or_repeat": (
                "repeat"
                if strategy_quality
                and strategy_quality[0].get("avg_dq_rank", 0) >= 3.5
                else "gather_more_sample"
            ),
        },
        "atlas": {
            "incomplete_packets_pct": incomplete_pct,
            "overdue_revisits": pending,
            "revisit_done_pct": revisit_done_pct,
            "observation_citation_pct": obs_cite_pct,
            "genealogy_coverage_pct": genealogy_pct,
            "overconfidence_rate": calibration.get("overconfidence_rate"),
            "fundamentals_holes": gaps.get("symbols_with_gaps"),
            "avg_unknowns": avg_unknowns,
        },
    }

    # Playbook proposals (never auto-apply)
    proposals: list[dict[str, Any]] = []
    if never_mattered:
        proposals.append(
            {
                "kind": "feature_weight_review",
                "priority": "low",
                "text": (
                    f"Axes with near-zero contribution across ≥3 packets: "
                    f"{', '.join(never_mattered[:6])} — consider demoting in "
                    f"feature_contributions heuristics (playbook change-log)."
                ),
            }
        )
    if missing_before_poor:
        top_miss = missing_before_poor.most_common(3)
        proposals.append(
            {
                "kind": "evidence_gap",
                "priority": "medium",
                "text": (
                    "Missing fields preceding poor decision_quality: "
                    + ", ".join(f"{k}×{v}" for k, v in top_miss)
                    + " — prioritize operator import / research before sizing."
                ),
            }
        )
    if prox_counts.get("plan_violation") or prox_counts.get("fomo"):
        proposals.append(
            {
                "kind": "process_discipline",
                "priority": "medium",
                "text": (
                    f"Process flags this window: fomo={prox_counts.get('fomo', 0)} "
                    f"plan_violation={prox_counts.get('plan_violation', 0)} "
                    f"revenge={prox_counts.get('revenge', 0)} — review plan "
                    f"adherence before changing SMA knobs."
                ),
            }
        )
    if gaps.get("symbols_with_gaps"):
        proposals.append(
            {
                "kind": "fundamentals_coverage",
                "priority": "high",
                "text": (
                    f"{gaps.get('symbols_with_gaps')} watchlist names still missing "
                    f"PE/FCF — use learner-template import (never invent)."
                ),
            }
        )
    if not proposals:
        proposals.append(
            {
                "kind": "hold_course",
                "priority": "info",
                "text": (
                    "Insufficient attributable history for strong proposals — "
                    "keep logging packets; no strategy change recommended."
                ),
            }
        )

    doc: dict[str, Any] = {
        "version": VERSION,
        "portfolio_key": portfolio_key,
        "week": wk,
        "as_of_ist": ist_now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sample": {
            "packets": len(pkt_list),
            "attributions": len(attr_list),
            "dq_grade_counts": dict(dq_counts),
        },
        "intelligence_score": intelligence_score,
        "families": {
            "completeness": {
                "avg_packet_completeness": avg_comp,
                "incomplete_packets_pct": incomplete_pct,
                "avg_unknowns": avg_unknowns,
            },
            "evidence": {
                "observation_citation_pct": obs_cite_pct,
                "fundamentals_holes": gaps.get("symbols_with_gaps"),
            },
            "process": {
                "process_score": process_score,
                "proxy_counts": prox_counts,
                "revisit_done_pct": revisit_done_pct,
                "pending_revisits": pending,
                "done_revisits": done,
            },
            "learning": {
                "feature_insights": feature_insights[:12],
                "never_mattered_axes": never_mattered,
                "missing_before_poor_dq": dict(missing_before_poor.most_common(8)),
                "strategy_quality_by_dq": strategy_quality[:10],
            },
            "calibration": calibration,
            "genealogy": {"parent_link_pct": genealogy_pct},
        },
        "answers": answers,
        "proposals": proposals,
        "honesty": (
            "Proposals are operator review only — never silent strategy rewrites. "
            "decision_quality ≠ market P&L. Never mix strategy_tag edge stats here."
        ),
    }
    if data_dir:
        try:
            path = mirror_path(data_dir, portfolio_key=portfolio_key, week=wk)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8"
            )
            doc["mirror_path"] = str(path)
        except Exception:  # noqa: BLE001
            _log.debug("meta learning mirror failed", exc_info=True)
    return doc


def format_meta_learning_section(doc: dict[str, Any] | None) -> list[str]:
    if not isinstance(doc, dict) or not doc.get("version"):
        return []
    lines = ["", "Meta-learning (DI.6 — Atlas intelligence, not vanity P&L):"]
    lines.append(
        f"  Week {doc.get('week')} · intelligence_score={doc.get('intelligence_score')} "
        f"· packets={((doc.get('sample') or {}).get('packets'))} "
        f"· attributions={((doc.get('sample') or {}).get('attributions'))}"
    )
    ans = (doc.get("answers") or {}).get("atlas") or {}
    lines.append(
        f"  Incomplete packets={ans.get('incomplete_packets_pct')}% · "
        f"obs_cite={ans.get('observation_citation_pct')}% · "
        f"genealogy={ans.get('genealogy_coverage_pct')}% · "
        f"revisits done={ans.get('revisit_done_pct')}%"
    )
    mkt = (doc.get("answers") or {}).get("markets") or {}
    if mkt.get("best_strategy_tag_by_dq"):
        lines.append(
            f"  Best tag by DQ: {mkt.get('best_strategy_tag_by_dq')} · "
            f"common process flag: {mkt.get('most_common_process_flag') or '—'}"
        )
    for p in (doc.get("proposals") or [])[:4]:
        if isinstance(p, dict):
            lines.append(
                f"  → [{p.get('priority')}] {p.get('kind')}: "
                f"{(p.get('text') or '')[:120]}"
            )
    lines.append("  (Proposals only — playbook change-log accepts strategy edits.)")
    return lines


def collect_meta_learning_inputs(
    *,
    data_dir: str | Path | None,
    portfolio_key: str = "india_equity_learner",
    portfolio: dict[str, Any] | None = None,
    lookback_days: int = 14,
) -> dict[str, Any]:
    """Load recent DI stores and build weekly digest."""
    from atlas.investment.decision_attribution import DecisionAttributionStore
    from atlas.investment.decision_packets import DecisionPacketStore, ist_today
    from atlas.investment.decision_timeline import DecisionTimelineStore
    from atlas.investment.process_proxies import collect_process_scorecard

    port = portfolio if isinstance(portfolio, dict) else {}
    packets: list[dict[str, Any]] = []
    try:
        pstore = DecisionPacketStore(data_dir=data_dir)
        # recent days
        today = ist_today()
        base = datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=_IST)
        for i in range(max(1, int(lookback_days))):
            day = (base - timedelta(days=i)).strftime("%Y-%m-%d")
            packets.extend(
                pstore.list_day(portfolio_key=portfolio_key, ts_ist=day, limit=100)
            )
    except Exception:  # noqa: BLE001
        _log.debug("meta packets load failed", exc_info=True)

    # de-dupe by decision_id
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for p in packets:
        did = str(p.get("decision_id") or "")
        if did and did not in seen:
            seen.add(did)
            uniq.append(p)
    packets = uniq

    attributions: list[dict[str, Any]] = []
    try:
        astore = DecisionAttributionStore(data_dir=data_dir)
        attributions = astore.list_portfolio(portfolio_key=portfolio_key, limit=200)
    except Exception:  # noqa: BLE001
        pass

    evolution: dict[str, Any] = dict(port.get("evolution") or {})
    try:
        tstore = DecisionTimelineStore(data_dir=data_dir)
        evolution = tstore.learning_counts(portfolio_key=portfolio_key) or evolution
    except Exception:  # noqa: BLE001
        pass

    prox = port.get("process_proxies") if isinstance(port.get("process_proxies"), dict) else {}
    if not prox and data_dir:
        try:
            prox = collect_process_scorecard(
                data_dir=data_dir,
                portfolio_key=portfolio_key,
                portfolio=port,
            )
        except Exception:  # noqa: BLE001
            prox = {}

    fund_gaps = {}
    cov = port.get("fundamentals_coverage")
    if isinstance(cov, dict):
        fund_gaps = cov.get("learner_gaps") or {}

    return build_meta_learning_digest(
        portfolio_key=portfolio_key,
        packets=packets,
        attributions=attributions,
        process_proxies=prox,
        evolution=evolution,
        fundamentals_gaps=fund_gaps if isinstance(fund_gaps, dict) else {},
        data_dir=data_dir,
    )


def enrich_d6_metrics(
    base: dict[str, Any],
    *,
    meta: dict[str, Any] | None = None,
    process_proxies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge Stage-2 Intelligence Dashboard fields into D6 metrics dict."""
    out = dict(base or {})
    meta = meta if isinstance(meta, dict) else {}
    prox = process_proxies if isinstance(process_proxies, dict) else {}
    fam = meta.get("families") if isinstance(meta.get("families"), dict) else {}
    comp = fam.get("completeness") if isinstance(fam.get("completeness"), dict) else {}
    evid = fam.get("evidence") if isinstance(fam.get("evidence"), dict) else {}
    proc = fam.get("process") if isinstance(fam.get("process"), dict) else {}
    calib = fam.get("calibration") if isinstance(fam.get("calibration"), dict) else {}
    gene = fam.get("genealogy") if isinstance(fam.get("genealogy"), dict) else {}
    ans = (meta.get("answers") or {}).get("atlas") or {}

    out.update(
        {
            "intelligence_score": meta.get("intelligence_score"),
            "incomplete_packets_pct": comp.get("incomplete_packets_pct")
            or ans.get("incomplete_packets_pct"),
            "avg_unknowns": comp.get("avg_unknowns") or ans.get("avg_unknowns"),
            "observation_citation_pct": evid.get("observation_citation_pct")
            or ans.get("observation_citation_pct"),
            "revisit_done_pct": proc.get("revisit_done_pct")
            or ans.get("revisit_done_pct"),
            "process_score": proc.get("process_score") or prox.get("process_score"),
            "overconfidence_rate": calib.get("overconfidence_rate"),
            "genealogy_parent_pct": gene.get("parent_link_pct")
            or ans.get("genealogy_coverage_pct"),
            "meta_week": meta.get("week"),
            "proposal_count": len(meta.get("proposals") or []),
            "stage": 2 if meta.get("intelligence_score") is not None else out.get("stage", 1),
        }
    )
    return out
