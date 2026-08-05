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
    """Closed attributable exits per strategy_tag (never mixed)."""
    counts: dict[str, int] = defaultdict(int)
    for attr in attributions:
        if not isinstance(attr, dict):
            continue
        if str(attr.get("trigger") or "") not in CLOSED_TRIGGERS:
            continue
        did = str(attr.get("decision_id") or "")
        pkt = packets_by_id.get(did) if did else None
        tag = "unknown"
        if isinstance(pkt, dict) and pkt.get("strategy_tag"):
            tag = str(pkt["strategy_tag"])
        elif isinstance(attr.get("payload"), dict):
            extra = attr["payload"].get("extra") or {}
            if isinstance(extra, dict) and extra.get("strategy_tag"):
                tag = str(extra["strategy_tag"])
        counts[tag] += 1
    return dict(counts)


def gate_status(
    *,
    closed_by_strategy: dict[str, int],
    force_override: bool = False,
    override_note: str = "",
) -> dict[str, Any]:
    """Whether DI.7 export is allowed."""
    lanes = {
        tag: {
            "n_closed": n,
            "tier": sample_tier(n),
            "trusted": sample_tier(n) == "trusted",
        }
        for tag, n in sorted(closed_by_strategy.items())
    }
    trusted_tags = [t for t, row in lanes.items() if row["trusted"]]
    total_closed = sum(closed_by_strategy.values())
    # Gate: at least one strategy_tag reaches trusted (≥300), OR total ≥300
    # with no single trusted lane still blocked for mixed training claims.
    any_trusted = bool(trusted_tags)
    total_trusted_enough = total_closed >= TRUSTED_MIN
    allowed = any_trusted or (force_override and bool(str(override_note or "").strip()))
    reason = "ok"
    if not allowed:
        if force_override and not str(override_note or "").strip():
            reason = "force_override requires a non-empty override_note"
        else:
            reason = (
                f"need ≥{TRUSTED_MIN} closed attributable exits on at least one "
                f"strategy_tag (have total={total_closed}; "
                f"best={max(closed_by_strategy.values()) if closed_by_strategy else 0}). "
                f"Pass force_override=true with override_note to proceed early."
            )
    return {
        "allowed": allowed,
        "reason": reason,
        "trusted_min": TRUSTED_MIN,
        "total_closed": total_closed,
        "any_strategy_trusted": any_trusted,
        "trusted_strategy_tags": trusted_tags,
        "total_closed_ge_trusted_min": total_trusted_enough,
        "force_override": bool(force_override),
        "override_note": str(override_note or "")[:500] or None,
        "lanes": lanes,
        "live_nn_trading": False,
        "live_nn_note": (
            "Hard refuse: no live NN trading until walk-forward paper beats "
            "rules baseline (recorded on offline_eval)."
        ),
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

    return {
        "decision_id": pkt.get("decision_id") or attr.get("decision_id"),
        "attribution_id": attr.get("id"),
        "ts_ist": pkt.get("ts_ist") or attr.get("created_at"),
        "symbol": pkt.get("symbol") or attr.get("symbol"),
        "action": pkt.get("action"),
        "strategy_tag": pkt.get("strategy_tag") or "unknown",
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
        },
        "trigger": attr.get("trigger"),
    }


def build_export_dataset(
    *,
    packets: list[dict[str, Any]],
    attributions: list[dict[str, Any]],
    portfolio_key: str = "india_equity_learner",
) -> dict[str, Any]:
    packets_by_id = {
        str(p["decision_id"]): p
        for p in packets
        if isinstance(p, dict) and p.get("decision_id")
    }
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
        "portfolio_key": portfolio_key,
        "rows": rows,
        "row_count": len(rows),
        "closed_by_strategy": closed_by,
        "packets_indexed": len(packets_by_id),
    }


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
) -> dict[str, Any]:
    """Build gated export + offline eval; write JSONL mirror when allowed."""
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
    eval_doc = offline_eval_rules_baseline(built["rows"])

    out: dict[str, Any] = {
        "version": VERSION,
        "portfolio_key": portfolio_key,
        "as_of_ist": ist_now_iso(),
        "gate": gate,
        "exported": False,
        "row_count": built["row_count"],
        "closed_by_strategy": built["closed_by_strategy"],
        "offline_eval": eval_doc,
        "live_nn_trading": False,
        "honesty": (
            "DI.7 exports decide-time features + graded outcomes. "
            "Never trains or deploys live NN from this path. "
            "Never mixes strategy_tag sample gates."
        ),
    }
    if not gate["allowed"]:
        out["blocked"] = gate["reason"]
        return out

    # Write mirrors
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
    gate = gate_status(closed_by_strategy=closed)
    return {
        "version": VERSION,
        "portfolio_key": portfolio_key,
        "gate": gate,
        "closed_by_strategy": closed,
        "attributions_loaded": len(attributions),
        "live_nn_trading": False,
        "next_step": (
            "Accumulate closed attributable exits per strategy_tag until tier=trusted, "
            "or POST /v1/market/ml-export with force_override + override_note."
        ),
    }
