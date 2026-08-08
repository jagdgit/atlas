"""DI.7 — ML-ready export (gated) + offline eval stub.

Locked rules:
- Export only after ≥300 **trusted closed attributable** decisions, or explicit
  ``force_override`` with operator note.
- Never mix ``strategy_tag`` lanes when judging sample readiness.
- Offline eval before any online learned policy.
- **No live NN trading** — this module never places orders / never registers
  a trading policy. Walk-forward must beat rules baseline first (recorded here).

Labels prefer ``decision_quality`` / thesis correctness — not raw P&L alone
(respect may_update_priors hard rule).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.di_dashboards import GATE_USABLE_MAX, sample_tier

_log = logging.getLogger("atlas.investment.ml_export")

VERSION = "di.ml.1"
STORE_REL = Path("investment") / "decisions" / "ml_export"
_IST = ZoneInfo("Asia/Kolkata")

# Trusted gate = same as Stage-3 edge (n ≥ 300). GATE_USABLE_MAX is 299.
TRUSTED_MIN = GATE_USABLE_MAX + 1  # 300
CLOSED_TRIGGERS = frozenset({"exit", "manual"})


def ist_now_iso() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _f(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def count_closed_by_strategy(
    attributions: list[dict[str, Any]],
    packets_by_id: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Closed attributable exits per lane (LI.4: lab|strategy|experiment).

    Keys are full ``lane_key`` strings. Legacy callers that pass simple
    strategy→n maps into ``gate_status`` still work.
    """
    from atlas.investment.laboratory import (
        refuse_pooled_edge_metrics,
        resolve_lane_from_rows,
    )

    check_rows: list[dict[str, Any]] = []
    for attr in attributions:
        if isinstance(attr, dict):
            check_rows.append(attr)
            did = str(attr.get("decision_id") or "")
            pkt = packets_by_id.get(did) if did else None
            if isinstance(pkt, dict):
                check_rows.append(pkt)
    refuse_pooled_edge_metrics(check_rows, context="count_closed_by_strategy")

    counts: dict[str, int] = defaultdict(int)
    for attr in attributions:
        if not isinstance(attr, dict):
            continue
        if str(attr.get("trigger") or "") not in CLOSED_TRIGGERS:
            continue
        did = str(attr.get("decision_id") or "")
        pkt = packets_by_id.get(did) if did else None
        lane = resolve_lane_from_rows(attr, pkt if isinstance(pkt, dict) else None)
        counts[lane["lane_key"]] += 1
    return dict(counts)


# Alias for LI.4 naming
count_closed_by_lane = count_closed_by_strategy


def gate_status(
    *,
    closed_by_strategy: dict[str, int] | None = None,
    closed_by_lane: dict[str, int] | None = None,
    force_override: bool = False,
    override_note: str = "",
) -> dict[str, Any]:
    """Whether DI.7 / LI.4 export is allowed — gates per lane, never pooled."""
    from atlas.investment.laboratory import parse_lane_key

    closed = dict(closed_by_lane or closed_by_strategy or {})
    lanes = {
        key: {
            "n_closed": n,
            "tier": sample_tier(n),
            "trusted": sample_tier(n) == "trusted",
            **parse_lane_key(key),
        }
        for key, n in sorted(closed.items())
    }
    trusted_keys = [t for t, row in lanes.items() if row["trusted"]]
    trusted_tags = sorted(
        {
            (lanes[t].get("strategy_tag") or t)
            for t in trusted_keys
        }
    )
    total_closed = sum(closed.values())
    any_trusted = bool(trusted_keys)
    total_trusted_enough = total_closed >= TRUSTED_MIN
    allowed = any_trusted or (force_override and bool(str(override_note or "").strip()))
    reason = "ok"
    if not allowed:
        if force_override and not str(override_note or "").strip():
            reason = "force_override requires a non-empty override_note"
        else:
            reason = (
                f"need ≥{TRUSTED_MIN} closed attributable exits on at least one "
                f"(laboratory_id, strategy_tag, experiment_id) lane "
                f"(have total={total_closed}; "
                f"best={max(closed.values()) if closed else 0}). "
                f"Pass force_override=true with override_note to proceed early."
            )
    return {
        "allowed": allowed,
        "reason": reason,
        "trusted_min": TRUSTED_MIN,
        "total_closed": total_closed,
        "any_strategy_trusted": any_trusted,
        "any_lane_trusted": any_trusted,
        "trusted_strategy_tags": trusted_tags,
        "trusted_lanes": trusted_keys,
        "total_closed_ge_trusted_min": total_trusted_enough,
        "force_override": bool(force_override),
        "override_note": str(override_note or "")[:500] or None,
        "lanes": lanes,
        "live_nn_trading": False,
        "live_nn_note": (
            "Hard refuse: no live NN trading until walk-forward paper beats "
            "rules baseline (recorded on offline_eval)."
        ),
        "gate_scope": "(laboratory_id, strategy_tag, experiment_id)",
    }


def row_from_packet_attr(
    packet: dict[str, Any],
    attr: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One training row: decide-time features + outcome labels (not OHLCV alone)."""
    pkt = packet if isinstance(packet, dict) else {}
    attr = attr if isinstance(attr, dict) else {}
    grades = attr.get("grades") if isinstance(attr.get("grades"), dict) else {}
    contrib = (
        pkt.get("feature_contributions")
        if isinstance(pkt.get("feature_contributions"), dict)
        else {}
    )
    conf = (
        pkt.get("confidence_breakdown")
        if isinstance(pkt.get("confidence_breakdown"), dict)
        else {}
    )
    snap = (
        pkt.get("market_snapshot")
        if isinstance(pkt.get("market_snapshot"), dict)
        else {}
    )
    prices = pkt.get("prices") if isinstance(pkt.get("prices"), dict) else {}
    flags = list((pkt.get("meta") or {}).get("process_flags") or [])

    # Label: prefer decision_quality A/B as positive process label; thesis_correct;
    # only use pnl if may_update_priors is True.
    dq = str(grades.get("decision_quality") or "").upper()
    mq = str(grades.get("market_quality") or "").upper()
    may_update = grades.get("may_update_priors")
    if may_update is None:
        from atlas.investment.decision_attribution import may_update_priors

        may_update = may_update_priors(grades)
    thesis = str(grades.get("thesis_correct") or "unknown")
    pnl = _f(grades.get("pnl"))
    if pnl is None and isinstance(attr.get("payload"), dict):
        pnl = _f(attr["payload"].get("pnl"))

    label_dq_ab = 1 if dq in {"A", "B"} else (0 if dq else None)
    label_thesis = (
        1 if thesis == "yes" else (0 if thesis == "no" else None)
    )
    label_pnl_pos = None
    if may_update and pnl is not None:
        label_pnl_pos = 1 if pnl > 0 else 0

    from atlas.investment.laboratory import (
        DEFAULT_EXPERIMENT_ID,
        normalize_experiment_id,
        normalize_laboratory_id,
        resolve_lane_from_rows,
    )
    from atlas.investment.decision_packets import regime_tags_for_closed_row

    lane = resolve_lane_from_rows(attr, pkt)
    lab = lane["laboratory_id"] or normalize_laboratory_id(
        portfolio_key=pkt.get("portfolio_key")
    )
    exp = lane["experiment_id"] or DEFAULT_EXPERIMENT_ID

    closed = str(attr.get("trigger") or "") in CLOSED_TRIGGERS
    if closed:
        regime = regime_tags_for_closed_row(pkt, attr)
    else:
        from atlas.investment.decision_packets import normalize_regime_tags

        regime = normalize_regime_tags(snap.get("regime_tags"))

    return {
        "decision_id": pkt.get("decision_id") or attr.get("decision_id"),
        "attribution_id": attr.get("id"),
        "ts_ist": pkt.get("ts_ist") or attr.get("created_at"),
        "symbol": pkt.get("symbol") or attr.get("symbol"),
        "action": pkt.get("action"),
        "strategy_tag": pkt.get("strategy_tag") or lane["strategy_tag"] or "unknown",
        "laboratory_id": lab,
        "portfolio_key": lab,
        "experiment_id": normalize_experiment_id(exp),
        "lane_key": lane["lane_key"],
        "features": {
            "contributions": {k: _f(v) for k, v in contrib.items()},
            "confidence": {k: _f(v) for k, v in conf.items()},
            "completeness": _f((pkt.get("meta") or {}).get("completeness")),
            "unknowns_n": len(pkt.get("unknowns") or []),
            "observation_ids_n": len(pkt.get("observation_ids") or []),
            "has_parent": bool(pkt.get("parent_decision_id")),
            "in_daily_plan": bool((pkt.get("plan_link") or {}).get("in_daily_plan")),
            "plan_rank": (pkt.get("plan_link") or {}).get("rank"),
            "gap_pct": _f(prices.get("gap_pct")),
            "process_flag_proxies": [
                f.get("proxy") for f in flags if isinstance(f, dict)
            ],
            "market_snapshot_keys_present": [
                k for k, v in snap.items() if v is not None and k != "note"
            ],
            "regime_tags": regime,
            "evidence_refs_n": len(pkt.get("evidence_refs") or []),
            "prior_thesis_id": pkt.get("prior_thesis_id")
            or (pkt.get("expected") or {}).get("thesis_id"),
        },
        "labels": {
            "decision_quality": dq or None,
            "market_quality": mq or None,
            "execution_quality": grades.get("execution_quality"),
            "portfolio_quality": grades.get("portfolio_quality"),
            "thesis_correct": thesis,
            "may_update_priors": bool(may_update),
            "label_dq_ab": label_dq_ab,
            "label_thesis_yes": label_thesis,
            "label_pnl_pos_if_allowed": label_pnl_pos,
            "pnl": pnl if may_update else None,
            "pnl_hidden_reason": None
            if may_update
            else "blocked: market F + decision A/B (or may_update_priors false)",
            "failure_cause": (
                (attr.get("payload") or {}).get("failure_cause")
                if isinstance(attr.get("payload"), dict)
                else None
            ),
            "regime_tags": regime if closed else None,
        },
        "trigger": attr.get("trigger"),
    }


def build_export_dataset(
    *,
    packets: list[dict[str, Any]],
    attributions: list[dict[str, Any]],
    portfolio_key: str = "india_equity_learner",
) -> dict[str, Any]:
    from atlas.investment.laboratory import (
        normalize_laboratory_id,
        refuse_pooled_edge_metrics,
    )

    lab = normalize_laboratory_id(portfolio_key=portfolio_key)
    packets_by_id = {
        str(p["decision_id"]): p
        for p in packets
        if isinstance(p, dict) and p.get("decision_id")
    }
    # Hermeticity — refuse cross-lab packet/attr pools before labeling
    refuse_pooled_edge_metrics(
        list(packets_by_id.values()) + list(attributions),
        context="build_export_dataset",
    )
    rows: list[dict[str, Any]] = []
    for attr in attributions:
        if not isinstance(attr, dict):
            continue
        if str(attr.get("trigger") or "") not in CLOSED_TRIGGERS:
            continue
        did = str(attr.get("decision_id") or "")
        pkt = packets_by_id.get(did) or {
            "decision_id": did,
            "symbol": attr.get("symbol"),
            "strategy_tag": "unknown",
            "laboratory_id": lab,
            "portfolio_key": lab,
            "experiment_id": "default",
            "action": None,
            "meta": {},
            "feature_contributions": {},
            "confidence_breakdown": {},
            "plan_link": {},
            "prices": {},
            "market_snapshot": {},
            "unknowns": [],
            "observation_ids": [],
        }
        rows.append(row_from_packet_attr(pkt, attr))
    closed_by = count_closed_by_strategy(attributions, packets_by_id)
    return {
        "portfolio_key": lab,
        "laboratory_id": lab,
        "rows": rows,
        "row_count": len(rows),
        "closed_by_strategy": closed_by,
        "closed_by_lane": closed_by,
        "packets_indexed": len(packets_by_id),
    }


def build_export_quality_report(
    *,
    packets: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    laboratory_id: str = "india_equity_learner",
    portfolio_key: str | None = None,
) -> dict[str, Any]:
    """LI.4 — thin export quality report (regimes, provenance, hypothesis links).

    Never pools across laboratories. Rates are honest zeros when fields are empty —
    we do not invent regimes or thesis links.
    """
    from atlas.investment.di_dashboards import sample_tier
    from atlas.investment.laboratory import (
        extract_laboratory_id,
        normalize_laboratory_id,
        parse_lane_key,
        refuse_pooled_edge_metrics,
    )

    lab = normalize_laboratory_id(
        laboratory_id=laboratory_id, portfolio_key=portfolio_key
    )
    pkts = [p for p in (packets or []) if isinstance(p, dict)]
    attrs = [a for a in (attributions or []) if isinstance(a, dict)]
    refuse_pooled_edge_metrics(pkts + attrs, context="export_quality_report")

    # Filter to this lab only (ignore unscoped legacy rows without lab stamp)
    def _in_lab(row: dict[str, Any]) -> bool:
        got = extract_laboratory_id(row)
        return got is None or got == lab

    pkts = [p for p in pkts if _in_lab(p)]
    attrs = [a for a in attrs if _in_lab(a)]
    packets_by_id = {
        str(p["decision_id"]): p for p in pkts if p.get("decision_id")
    }

    n_packets = len(pkts)
    with_regime = 0
    with_evidence = 0
    with_hypothesis = 0
    with_li_hypothesis = 0
    with_obs = 0
    from atlas.investment.decision_packets import normalize_regime_tags, regime_tags_for_closed_row

    for p in pkts:
        snap = p.get("market_snapshot") if isinstance(p.get("market_snapshot"), dict) else {}
        tags = normalize_regime_tags(snap.get("regime_tags"))
        if tags:
            with_regime += 1
        if p.get("evidence_refs"):
            with_evidence += 1
        if p.get("prior_thesis_id") or (p.get("expected") or {}).get("thesis_id"):
            with_hypothesis += 1
        if p.get("hypothesis_id"):
            with_li_hypothesis += 1
        if p.get("observation_ids"):
            with_obs += 1

    closed = [
        a
        for a in attrs
        if str(a.get("trigger") or "") in CLOSED_TRIGGERS
    ]
    n_closed = len(closed)
    with_failure_cause = sum(
        1
        for a in closed
        if isinstance(a.get("payload"), dict)
        and (
            a["payload"].get("failure_cause")
            or (a["payload"].get("extra") or {}).get("failure_cause")
        )
    )
    # LQ.6 — closed rows always resolve to ≥1 tag (unknown allowed)
    closed_with_regime = 0
    closed_unknown_only = 0
    for a in closed:
        pkt = packets_by_id.get(str(a.get("decision_id") or "")) or {}
        tags = regime_tags_for_closed_row(pkt, a)
        if tags:
            closed_with_regime += 1
            if tags == ["unknown"]:
                closed_unknown_only += 1

    closed_by = count_closed_by_lane(attrs, packets_by_id)
    lane_rows = {
        key: {
            "n_closed": n,
            "tier": sample_tier(n),
            **parse_lane_key(key),
        }
        for key, n in sorted(closed_by.items())
    }

    def _rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return round(num / den, 4)

    any_trusted = any(
        (row.get("tier") == "trusted") for row in lane_rows.values()
    )
    regime_rate = _rate(with_regime, n_packets)
    closed_regime_rate = _rate(closed_with_regime, n_closed)
    provenance_rate = _rate(with_evidence, n_packets)
    failure_rate = _rate(with_failure_cause, n_closed)
    hyp_rate = _rate(with_hypothesis + with_li_hypothesis, n_packets)

    # LI.5b readiness gauge — measurable gates; NN still refused
    gates = [
        {
            "id": "closed_sample",
            "ok": any_trusted or n_closed >= TRUSTED_MIN,
            "detail": f"closed={n_closed}; any_lane_trusted={any_trusted}",
        },
        {
            "id": "failure_taxonomy",
            "ok": bool(failure_rate is not None and failure_rate >= 0.3) or n_closed == 0,
            "detail": f"failure_cause_tag_rate={failure_rate}",
        },
        {
            "id": "provenance",
            "ok": bool(provenance_rate is not None and provenance_rate >= 0.2)
            or n_packets == 0,
            "detail": f"provenance_cite_rate={provenance_rate}",
        },
        {
            "id": "regime_or_hypothesis_signal",
            "ok": bool(
                (closed_regime_rate or regime_rate or 0) >= 0.1
                or (hyp_rate or 0) >= 0.1
                or with_li_hypothesis > 0
            )
            or n_packets == 0,
            "detail": (
                f"closed_regime_rate={closed_regime_rate}; regime_rate={regime_rate}; "
                f"hypothesis_link_rate={hyp_rate}; li_hypothesis_ids={with_li_hypothesis}"
            ),
        },
    ]
    blocking = [g["id"] for g in gates if not g["ok"]]
    ready = len(blocking) == 0 and n_closed > 0
    readiness = {
        "ready": ready,
        "gates": gates,
        "blocking": blocking,
        "live_nn_trading": False,
        "live_nn_note": (
            "Readiness gauge is Learning Intelligence quality — not permission "
            "to train/deploy NN (that is LI.6 + walk-forward)."
        ),
        "version": "li.5b.readiness",
    }

    return {
        "version": "li.5b.export_quality",
        "laboratory_id": lab,
        "portfolio_key": lab,
        "n_packets": n_packets,
        "n_closed_attributions": n_closed,
        "regime_tag_fill_rate": regime_rate,
        "regime_tags_present": with_regime,
        "closed_regime_tag_fill_rate": closed_regime_rate,
        "closed_regime_tags_present": closed_with_regime,
        "closed_regime_unknown_only": closed_unknown_only,
        "provenance_cite_rate": provenance_rate,
        "evidence_refs_present": with_evidence,
        "observation_cite_rate": _rate(with_obs, n_packets),
        "hypothesis_link_rate": hyp_rate,
        "hypothesis_or_prior_thesis_linked": with_hypothesis,
        "li_hypothesis_ids_present": with_li_hypothesis,
        "failure_cause_tag_rate": failure_rate,
        "failure_causes_tagged": with_failure_cause,
        "closed_by_lane": closed_by,
        "lanes": lane_rows,
        "readiness": readiness,
        "honesty": (
            "LQ.6: closed rows resolve regime_tags (unknown allowed). "
            "Never invent bull/bear from P&L. Rates are within one laboratory only."
        ),
        "next_step": (
            "Clear readiness.blocking gates, then LI.6 quality-gated export "
            "(still no live NN)."
            if blocking
            else "Quality gates clear for this lab sample — LI.6 may export offline (NN still off)."
        ),
    }


def collect_export_quality_report(
    *,
    data_dir: str | Path | None,
    laboratory_id: str = "india_equity_learner",
    lookback_limit: int = 500,
) -> dict[str, Any]:
    """Load lab-scoped packets/attributions and build the LI.4 quality report."""
    from atlas.investment.decision_attribution import DecisionAttributionStore
    from atlas.investment.decision_packets import DecisionPacketStore, ist_today
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    attributions: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    try:
        astore = DecisionAttributionStore(data_dir=data_dir)
        attributions = astore.list_portfolio(
            portfolio_key=lab, limit=max(50, int(lookback_limit))
        )
    except Exception:  # noqa: BLE001
        _log.debug("quality report attributions load failed", exc_info=True)
    try:
        pstore = DecisionPacketStore(data_dir=data_dir)
        want = {
            str(a.get("decision_id"))
            for a in attributions
            if isinstance(a, dict) and a.get("decision_id")
        }
        for did in list(want)[: max(50, int(lookback_limit))]:
            try:
                doc = pstore.get(did)
                if isinstance(doc, dict):
                    packets.append(doc)
            except Exception:  # noqa: BLE001
                continue
        if len(packets) < 20:
            packets.extend(
                pstore.list_day(portfolio_key=lab, ts_ist=ist_today(), limit=100)
            )
    except Exception:  # noqa: BLE001
        _log.debug("quality report packets load failed", exc_info=True)
    return build_export_quality_report(
        packets=packets,
        attributions=attributions,
        laboratory_id=lab,
    )


def offline_eval_rules_baseline(
    rows: list[dict[str, Any]],
    *,
    train_frac: float = 0.7,
) -> dict[str, Any]:
    """Chronological walk-forward stub: rules baseline vs no-learned-policy.

    Rules baseline: predict positive DQ label when technical contribution > 0
    (or completeness ≥ 0.6 if no technical). Learned policy is **not** trained —
    ``learned_beats_rules`` stays False until a real offline model is plugged in.
    """
    labeled = [
        r
        for r in rows
        if isinstance(r, dict) and r.get("labels", {}).get("label_dq_ab") is not None
    ]
    labeled.sort(key=lambda r: str(r.get("ts_ist") or ""))
    n = len(labeled)
    if n < 10:
        return {
            "ok": False,
            "reason": f"need ≥10 labeled rows for offline eval (have {n})",
            "n": n,
            "learned_beats_rules": False,
            "live_nn_allowed": False,
        }
    split = max(1, min(n - 1, int(n * float(train_frac))))
    test = labeled[split:]
    correct = 0
    for r in test:
        feats = (r.get("features") or {}).get("contributions") or {}
        tech = _f(feats.get("technical"))
        comp = _f((r.get("features") or {}).get("completeness"))
        if tech is not None:
            pred = 1 if tech > 0 else 0
        else:
            pred = 1 if (comp or 0) >= 0.6 else 0
        gold = int(r["labels"]["label_dq_ab"])
        if pred == gold:
            correct += 1
    rules_acc = round(correct / len(test), 4) if test else None
    # No learned model in DI.7 scaffold
    learned_acc = None
    learned_beats = False
    return {
        "ok": True,
        "n_labeled": n,
        "n_train": split,
        "n_test": len(test),
        "rules_baseline_accuracy": rules_acc,
        "learned_accuracy": learned_acc,
        "learned_beats_rules": learned_beats,
        "live_nn_allowed": False,
        "note": (
            "Rules baseline only. Plug offline model later; live NN remains "
            "forbidden until learned_beats_rules is True on paper walk-forward."
        ),
    }


def export_ml_dataset(
    *,
    data_dir: str | Path | None,
    portfolio_key: str = "india_equity_learner",
    force_override: bool = False,
    override_note: str = "",
    lookback_limit: int = 500,
    atlasnet_partition: bool = True,
) -> dict[str, Any]:
    """Build gated export + offline eval; write JSONL mirror when allowed.

    LI.6: when ``atlasnet_partition`` is True (default), also write lab-partitioned
    AtlasNet prep layout + walk-forward contract (still no NN).
    """
    from atlas.investment.decision_attribution import DecisionAttributionStore
    from atlas.investment.decision_packets import DecisionPacketStore

    attributions: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    try:
        astore = DecisionAttributionStore(data_dir=data_dir)
        attributions = astore.list_portfolio(
            portfolio_key=portfolio_key, limit=max(50, int(lookback_limit))
        )
    except Exception:  # noqa: BLE001
        _log.debug("ml export attributions load failed", exc_info=True)
    try:
        pstore = DecisionPacketStore(data_dir=data_dir)
        # pull packets referenced by attributions
        want = {
            str(a.get("decision_id"))
            for a in attributions
            if isinstance(a, dict) and a.get("decision_id")
        }
        for did in list(want)[: max(50, int(lookback_limit))]:
            try:
                doc = pstore.get(did) if hasattr(pstore, "get") else None
                if isinstance(doc, dict):
                    packets.append(doc)
            except Exception:  # noqa: BLE001
                continue
        # also recent day scan if sparse
        if len(packets) < 20 and hasattr(pstore, "list_day"):
            from atlas.investment.decision_packets import ist_today

            packets.extend(
                pstore.list_day(
                    portfolio_key=portfolio_key, ts_ist=ist_today(), limit=100
                )
            )
    except Exception:  # noqa: BLE001
        _log.debug("ml export packets load failed", exc_info=True)

    built = build_export_dataset(
        packets=packets,
        attributions=attributions,
        portfolio_key=portfolio_key,
    )
    gate = gate_status(
        closed_by_strategy=built["closed_by_strategy"],
        force_override=force_override,
        override_note=override_note,
    )
    quality = build_export_quality_report(
        packets=packets,
        attributions=attributions,
        laboratory_id=portfolio_key,
    )
    eval_doc = offline_eval_rules_baseline(built["rows"])

    out: dict[str, Any] = {
        "version": VERSION,
        "portfolio_key": portfolio_key,
        "laboratory_id": portfolio_key,
        "as_of_ist": ist_now_iso(),
        "gate": gate,
        "exported": False,
        "row_count": built["row_count"],
        "closed_by_strategy": built["closed_by_strategy"],
        "closed_by_lane": built.get("closed_by_lane") or built["closed_by_strategy"],
        "quality": quality,
        "offline_eval": eval_doc,
        "live_nn_trading": False,
        "honesty": (
            "DI.7/LI.6 exports decide-time features + graded outcomes. "
            "Never trains or deploys live NN from this path. "
            "Never mixes laboratory / strategy_tag / experiment_id sample gates."
        ),
    }
    if not gate["allowed"]:
        out["blocked"] = gate["reason"]
        return out

    # Write mirrors (legacy flat + optional LI.6 partitioned)
    if data_dir:
        try:
            day = datetime.now(_IST).strftime("%Y-%m-%d")
            root = (
                Path(data_dir)
                / STORE_REL
                / portfolio_key.replace("/", "_")
                / day
            )
            root.mkdir(parents=True, exist_ok=True)
            meta_path = root / "manifest.json"
            jsonl_path = root / "rows.jsonl"
            with jsonl_path.open("w", encoding="utf-8") as fh:
                for row in built["rows"]:
                    fh.write(json.dumps(row, default=str) + "\n")
            manifest = {
                **{k: v for k, v in out.items() if k != "rows"},
                "row_count": built["row_count"],
                "jsonl_path": str(jsonl_path),
                "force_override": force_override,
                "override_note": override_note[:500] if override_note else None,
            }
            # include sample of rows only in manifest-adjacent preview
            preview_path = root / "preview.json"
            preview_path.write_text(
                json.dumps(
                    {"rows_preview": built["rows"][:20], "gate": gate, "offline_eval": eval_doc},
                    indent=2,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
            meta_path.write_text(
                json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
            )
            out["exported"] = True
            out["jsonl_path"] = str(jsonl_path)
            out["manifest_path"] = str(meta_path)
            out["preview_path"] = str(preview_path)
            if atlasnet_partition:
                try:
                    from atlas.investment.atlasnet_prep import (
                        build_walk_forward_contract,
                        write_lab_partitioned_export,
                    )

                    contract = build_walk_forward_contract(
                        built["rows"], laboratory_id=portfolio_key
                    )
                    written = write_lab_partitioned_export(
                        data_dir,
                        laboratory_id=portfolio_key,
                        rows=built["rows"],
                        manifest_body={
                            "gate": gate,
                            "quality": quality,
                            "offline_eval": eval_doc,
                            "force_override": force_override,
                        },
                        contract=contract,
                    )
                    out["atlasnet_prep"] = {
                        "version": "li.6.atlasnet_prep",
                        "live_nn_trading": False,
                        **written,
                    }
                    out["walk_forward_contract"] = contract
                except Exception:  # noqa: BLE001
                    _log.debug("atlasnet partition side-write failed", exc_info=True)
        except Exception:  # noqa: BLE001
            _log.debug("ml export write failed", exc_info=True)
            out["exported"] = False
            out["write_error"] = "mirror_write_failed"
    else:
        out["exported"] = True
        out["rows_preview"] = built["rows"][:20]
    return out


def ml_export_status(
    *,
    data_dir: str | Path | None,
    portfolio_key: str = "india_equity_learner",
    lookback_limit: int = 500,
) -> dict[str, Any]:
    """Gate check without writing files."""
    from atlas.investment.decision_attribution import DecisionAttributionStore
    from atlas.investment.decision_packets import DecisionPacketStore

    attributions: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    try:
        astore = DecisionAttributionStore(data_dir=data_dir)
        attributions = astore.list_portfolio(
            portfolio_key=portfolio_key, limit=max(50, int(lookback_limit))
        )
    except Exception:  # noqa: BLE001
        pass
    packets_by_id: dict[str, dict[str, Any]] = {}
    try:
        pstore = DecisionPacketStore(data_dir=data_dir)
        for a in attributions:
            did = str(a.get("decision_id") or "")
            if not did or did in packets_by_id:
                continue
            if hasattr(pstore, "get"):
                try:
                    doc = pstore.get(did)
                    if isinstance(doc, dict):
                        packets_by_id[did] = doc
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    closed = count_closed_by_strategy(attributions, packets_by_id)
    gate = gate_status(closed_by_lane=closed)
    quality = build_export_quality_report(
        packets=list(packets_by_id.values()),
        attributions=attributions,
        laboratory_id=portfolio_key,
    )
    return {
        "version": VERSION,
        "portfolio_key": portfolio_key,
        "laboratory_id": portfolio_key,
        "gate": gate,
        "closed_by_strategy": closed,
        "closed_by_lane": closed,
        "quality": quality,
        "attributions_loaded": len(attributions),
        "live_nn_trading": False,
        "next_step": (
            "Accumulate closed attributable exits per "
            "(laboratory_id, strategy_tag, experiment_id) until tier=trusted, "
            "or POST /v1/market/ml-export with force_override + override_note."
        ),
    }
