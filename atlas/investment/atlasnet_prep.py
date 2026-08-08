"""LI.6 — AtlasNet prep only (quality-gated lab-partitioned export + harness stub).

Design shape (not implemented here): shared world encoder → lab heads → meta.
This module **never** trains or deploys a neural net. ``live_nn_trading`` stays False.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from atlas.investment.ml_export import (
    VERSION as ML_EXPORT_VERSION,
    build_export_dataset,
    build_export_quality_report,
    gate_status,
    ist_now_iso,
    offline_eval_rules_baseline,
)

_log = logging.getLogger("atlas.investment.atlasnet_prep")

VERSION = "li.6.atlasnet_prep"
STORE_REL = Path("investment") / "decisions" / "atlasnet_prep"
_IST = ZoneInfo("Asia/Kolkata")

ATLASNET_SHAPE = {
    "shared_world_encoder": "design_only",
    "laboratory_heads": "design_only",
    "meta_controller": "design_only",
    "note": (
        "AtlasNet architecture is frozen in the locked LI plan (§7). "
        "LI.6 only prepares quality-gated lab-partitioned datasets + walk-forward contract."
    ),
}

# LQ.9 / plan §8.2 — harder than LI.6 prep export gates
HARD_GATE_MIN_CLOSED = 500
HARD_GATE_MIN_REGIMES = 10
HARD_GATE_MAX_MISSING_CRIT_PCT = 0.05
HARD_GATE_MIN_TIMELINE_COVERAGE = 0.70
HARD_GATE_MIN_THESIS_OR_HYP = 0.70
HARD_GATE_MIN_HISTORY_DAYS = 365
HARD_GATE_MIN_FAILURE_TAXONOMY = 0.30
CRITICAL_FEATURE_KEYS = (
    "completeness",
    "regime_tags",
    "contributions",
    "confidence",
)


class AtlasNetTrainBlocked(RuntimeError):
    """LQ.9 — raised when any train / paper-NN / live-NN path runs before §8.2."""

    def __init__(self, message: str, *, gate: dict[str, Any] | None = None):
        super().__init__(message)
        self.gate = gate or {}


def _safe_seg(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\-]+", "_", str(s or "unknown"))[:120]


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    try:
        s = str(raw).replace("Z", "+00:00")
        # date-only
        if len(s) <= 10 and "T" not in s:
            return datetime.fromisoformat(s)
        return datetime.fromisoformat(s)
    except Exception:  # noqa: BLE001
        return None


def evaluate_atlasnet_hard_gate(
    *,
    rows: list[dict[str, Any]] | None = None,
    packets: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    learned_beats_rules: bool = False,
    continuous_history_days: float | None = None,
) -> dict[str, Any]:
    """LQ.9 — plan §8.2 hard gate object (prep export stays separate / allowed).

    All criteria must pass before train / paper-NN / live-NN. Missing evidence
    fails closed — never invent regimes, timelines, or walk-forward wins.
    """
    from atlas.investment.decision_packets import normalize_regime_tags
    from atlas.investment.ml_export import CLOSED_TRIGGERS

    row_list = [r for r in (rows or []) if isinstance(r, dict)]
    pkt_list = [p for p in (packets or []) if isinstance(p, dict)]
    attr_list = [a for a in (attributions or []) if isinstance(a, dict)]
    closed = [
        a for a in attr_list if str(a.get("trigger") or "") in CLOSED_TRIGGERS
    ]
    n_closed = len(closed) if closed else sum(
        1 for r in row_list if str(r.get("trigger") or "") in CLOSED_TRIGGERS
    )
    if n_closed == 0 and row_list:
        # export rows are closed-labeled by construction in build_export_dataset
        n_closed = len(row_list)

    # Regimes across closed set
    regimes: set[str] = set()
    for r in row_list:
        feats = r.get("features") if isinstance(r.get("features"), dict) else {}
        labels = r.get("labels") if isinstance(r.get("labels"), dict) else {}
        for t in normalize_regime_tags(
            labels.get("regime_tags") or feats.get("regime_tags")
        ):
            if t != "unknown":
                regimes.add(t)
    for a in closed:
        pl = a.get("payload") if isinstance(a.get("payload"), dict) else {}
        for t in normalize_regime_tags(
            pl.get("regime_tags") or (pl.get("extra") or {}).get("regime_tags")
        ):
            if t != "unknown":
                regimes.add(t)
    for p in pkt_list:
        snap = p.get("market_snapshot") if isinstance(p.get("market_snapshot"), dict) else {}
        for t in normalize_regime_tags(snap.get("regime_tags")):
            if t != "unknown":
                regimes.add(t)

    # Critical decide-time field fill on export rows
    n_rows = len(row_list)
    missing_crit = 0
    for r in row_list:
        feats = r.get("features") if isinstance(r.get("features"), dict) else {}
        bad = False
        if feats.get("completeness") is None:
            bad = True
        tags = feats.get("regime_tags")
        if not tags:
            bad = True
        contrib = feats.get("contributions")
        if not isinstance(contrib, dict) or not contrib:
            bad = True
        conf = feats.get("confidence")
        if not isinstance(conf, dict) or not conf:
            bad = True
        if bad:
            missing_crit += 1
    missing_pct = (missing_crit / n_rows) if n_rows else 1.0

    # Timeline coverage — packet has observation cites or parent/checkpoints proxy
    timeline_ok = 0
    timeline_den = max(n_closed, len(pkt_list), 1)
    if pkt_list:
        timeline_den = len(pkt_list)
        for p in pkt_list:
            meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
            has = bool(p.get("observation_ids")) or bool(p.get("evidence_refs"))
            has = has or bool(meta.get("timeline_coverage")) or bool(
                meta.get("checkpoints_done")
            )
            # LQ.2 densify: evolution/open-book stamps
            if p.get("open_book") or meta.get("evolution_cadence"):
                has = True
            if has:
                timeline_ok += 1
    elif row_list:
        timeline_den = len(row_list)
        for r in row_list:
            feats = r.get("features") if isinstance(r.get("features"), dict) else {}
            if int(feats.get("observation_ids_n") or 0) > 0 or int(
                feats.get("evidence_refs_n") or 0
            ) > 0:
                timeline_ok += 1
    timeline_rate = timeline_ok / timeline_den if timeline_den else 0.0

    # Thesis or hypothesis outcomes on closed
    outcome_ok = 0
    outcome_den = max(n_closed, len(row_list), 1)
    if closed:
        outcome_den = len(closed)
        for a in closed:
            grades = a.get("grades") if isinstance(a.get("grades"), dict) else {}
            thesis = str(grades.get("thesis_correct") or "").lower()
            pl = a.get("payload") if isinstance(a.get("payload"), dict) else {}
            hyp = a.get("hypothesis_id") or pl.get("hypothesis_id") or (
                pl.get("extra") or {}
            ).get("hypothesis_id")
            if thesis in {"yes", "no", "partial"} or hyp:
                outcome_ok += 1
    elif row_list:
        outcome_den = len(row_list)
        for r in row_list:
            labels = r.get("labels") if isinstance(r.get("labels"), dict) else {}
            thesis = str(labels.get("thesis_correct") or "").lower()
            if thesis in {"yes", "no", "partial"} or labels.get("label_thesis_yes") is not None:
                outcome_ok += 1
    thesis_rate = outcome_ok / outcome_den if outcome_den else 0.0

    # Continuous history span
    stamps: list[datetime] = []
    for src in (row_list, pkt_list, closed):
        for item in src:
            ts = _parse_ts(item.get("ts_ist") or item.get("created_at"))
            if ts:
                stamps.append(ts)
    if continuous_history_days is not None:
        history_days = float(continuous_history_days)
    elif len(stamps) >= 2:
        history_days = (max(stamps) - min(stamps)).total_seconds() / 86400.0
    else:
        history_days = 0.0

    # Failure taxonomy on material losses
    losses = []
    for a in closed:
        grades = a.get("grades") if isinstance(a.get("grades"), dict) else {}
        pl = a.get("payload") if isinstance(a.get("payload"), dict) else {}
        pnl = grades.get("pnl")
        if pnl is None:
            pnl = pl.get("pnl")
        try:
            if pnl is not None and float(pnl) < 0:
                losses.append(a)
        except (TypeError, ValueError):
            continue
    tagged_losses = 0
    for a in losses:
        pl = a.get("payload") if isinstance(a.get("payload"), dict) else {}
        cause = pl.get("failure_cause") or (pl.get("extra") or {}).get("failure_cause")
        if cause:
            tagged_losses += 1
    loss_den = len(losses)
    failure_rate = (tagged_losses / loss_den) if loss_den else (
        1.0 if n_closed == 0 else 0.0
    )

    checks = [
        {
            "id": "closed_500",
            "ok": n_closed >= HARD_GATE_MIN_CLOSED,
            "detail": f"closed={n_closed} need>={HARD_GATE_MIN_CLOSED}",
        },
        {
            "id": "regimes_10",
            "ok": len(regimes) >= HARD_GATE_MIN_REGIMES,
            "detail": f"regimes={sorted(regimes)[:20]} n={len(regimes)} need>={HARD_GATE_MIN_REGIMES}",
        },
        {
            "id": "missing_critical_lt_5pct",
            "ok": n_rows > 0 and missing_pct < HARD_GATE_MAX_MISSING_CRIT_PCT,
            "detail": f"missing_pct={round(missing_pct, 4)} n_rows={n_rows}",
        },
        {
            "id": "timeline_coverage_70",
            "ok": timeline_rate >= HARD_GATE_MIN_TIMELINE_COVERAGE,
            "detail": f"timeline_rate={round(timeline_rate, 4)}",
        },
        {
            "id": "thesis_or_hypothesis_70",
            "ok": thesis_rate >= HARD_GATE_MIN_THESIS_OR_HYP,
            "detail": f"thesis_or_hyp_rate={round(thesis_rate, 4)}",
        },
        {
            "id": "history_12m",
            "ok": history_days >= HARD_GATE_MIN_HISTORY_DAYS,
            "detail": f"history_days={round(history_days, 1)} need>={HARD_GATE_MIN_HISTORY_DAYS}",
        },
        {
            "id": "failure_taxonomy",
            "ok": (loss_den == 0 and n_closed == 0)
            or (loss_den > 0 and failure_rate >= HARD_GATE_MIN_FAILURE_TAXONOMY)
            or (loss_den == 0 and n_closed > 0),
            "detail": (
                f"loss_tagged_rate={round(failure_rate, 4) if loss_den else None} "
                f"losses={loss_den}"
            ),
        },
        {
            "id": "learned_beats_rules",
            "ok": bool(learned_beats_rules),
            "detail": f"learned_beats_rules={bool(learned_beats_rules)}",
        },
    ]
    blocking = [c["id"] for c in checks if not c["ok"]]
    cleared = len(blocking) == 0
    status = "train_eligible" if cleared else "prep_only"
    return {
        "version": "lq.9.hard_gate",
        "atlasnet_status": status,
        "train_allowed": cleared,
        "paper_nn_allowed": cleared,
        "live_nn_trading": False,
        "live_nn_note": (
            "Even when §8.2 clears, live NN stays operator-gated; "
            "this object only unlocks train/paper-NN paths."
            if cleared
            else "Blocked: §8.2 hard gate not clear — prep export only."
        ),
        "checks": checks,
        "blocking": blocking,
        "metrics": {
            "n_closed": n_closed,
            "n_regimes": len(regimes),
            "regimes": sorted(regimes),
            "missing_critical_pct": round(missing_pct, 4),
            "timeline_coverage": round(timeline_rate, 4),
            "thesis_or_hypothesis_rate": round(thesis_rate, 4),
            "history_days": round(history_days, 1),
            "failure_taxonomy_rate": round(failure_rate, 4) if loss_den else None,
            "n_rows": n_rows,
            "learned_beats_rules": bool(learned_beats_rules),
        },
        "honesty": (
            "LQ.9: missing evidence fails closed. Prep export (LI.6) may still run. "
            "Never invent regimes, Sharpe, or walk-forward wins to clear this gate."
        ),
        "force_override_bypasses_train": False,
    }


def assert_atlasnet_train_allowed(
    hard_gate: dict[str, Any] | None,
    *,
    intent: str = "train",
) -> dict[str, Any]:
    """LQ.9 — raise unless §8.2 clears. Prep export must not call this."""
    gate = hard_gate if isinstance(hard_gate, dict) else {}
    if gate.get("train_allowed"):
        return gate
    blocking = gate.get("blocking") or ["hard_gate_unevaluated"]
    raise AtlasNetTrainBlocked(
        f"AtlasNet {intent} blocked by LQ.9 §8.2 hard gate — "
        f"blocking={blocking}. atlasnet_status=prep_only.",
        gate=gate,
    )


def refuse_atlasnet_beyond_prep(
    *,
    intent: str = "train",
    rows: list[dict[str, Any]] | None = None,
    packets: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    learned_beats_rules: bool = False,
) -> dict[str, Any]:
    """Evaluate §8.2 and refuse train/paper-NN unless cleared."""
    gate = evaluate_atlasnet_hard_gate(
        rows=rows,
        packets=packets,
        attributions=attributions,
        learned_beats_rules=learned_beats_rules,
    )
    assert_atlasnet_train_allowed(gate, intent=intent)
    return gate


def lane_partition_key(row: dict[str, Any]) -> str:
    """Filesystem-safe lane segment from a training row."""
    raw = str(row.get("lane_key") or "")
    if raw:
        return _safe_seg(raw.replace("|", "__"))
    lab = _safe_seg(row.get("laboratory_id") or row.get("portfolio_key") or "lab")
    tag = _safe_seg(row.get("strategy_tag") or "unknown")
    exp = _safe_seg(row.get("experiment_id") or "default")
    return f"{lab}__{tag}__{exp}"


def build_walk_forward_contract(
    rows: list[dict[str, Any]],
    *,
    laboratory_id: str,
    train_frac: float = 0.7,
) -> dict[str, Any]:
    """Persistable walk-forward contract — rules baseline only; no model training.

    Records fold boundaries and honesty flags so a future offline trainer can
    plug in without changing the Learning Intelligence contract.
    """
    from atlas.investment.laboratory import normalize_laboratory_id, refuse_pooled_edge_metrics

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    refuse_pooled_edge_metrics(rows, context="walk_forward_contract")
    labeled = [
        r
        for r in rows
        if isinstance(r, dict) and (r.get("labels") or {}).get("label_dq_ab") is not None
    ]
    labeled.sort(key=lambda r: str(r.get("ts_ist") or ""))
    n = len(labeled)
    eval_doc = offline_eval_rules_baseline(rows, train_frac=train_frac)
    split = int(eval_doc.get("n_train") or 0) if eval_doc.get("ok") else 0
    train_ids = [r.get("decision_id") for r in labeled[:split] if r.get("decision_id")]
    test_ids = [r.get("decision_id") for r in labeled[split:] if r.get("decision_id")]
    return {
        "version": VERSION,
        "contract": "walk_forward_v1",
        "laboratory_id": lab,
        "as_of_ist": ist_now_iso(),
        "train_frac": float(train_frac),
        "n_rows": len(rows),
        "n_labeled": n,
        "n_train": split,
        "n_test": max(0, n - split),
        "train_decision_ids_preview": train_ids[:20],
        "test_decision_ids_preview": test_ids[:20],
        "rules_baseline": eval_doc,
        "learned_model": None,
        "learned_beats_rules": False,
        "live_nn_allowed": False,
        "live_nn_trading": False,
        "atlasnet_status": "prep_only",
        "atlasnet_shape": ATLASNET_SHAPE,
        "hard_gate": None,  # filled by callers via evaluate_atlasnet_hard_gate
        "honesty": (
            "Contract records fold boundaries + rules baseline only. "
            "No NN weights are trained or loaded here. LQ.9 train paths must "
            "pass evaluate_atlasnet_hard_gate separately."
        ),
    }


def _export_allowed(
    *,
    gate: dict[str, Any],
    quality: dict[str, Any],
    force_override: bool,
    override_note: str,
) -> tuple[bool, str]:
    """Sample gate AND readiness (or force+note)."""
    if not gate.get("allowed"):
        return False, str(gate.get("reason") or "sample gate blocked")
    readiness = quality.get("readiness") if isinstance(quality, dict) else None
    ready = bool(isinstance(readiness, dict) and readiness.get("ready"))
    if ready:
        return True, "ok: sample gate + readiness"
    if force_override and str(override_note or "").strip():
        return True, "ok: force_override (readiness not clear)"
    blocking = (readiness or {}).get("blocking") if isinstance(readiness, dict) else []
    return False, (
        "readiness not clear — blocking="
        f"{blocking or ['unknown']}. Pass force_override + override_note, "
        "or clear LI.5b readiness gates first."
    )


def write_lab_partitioned_export(
    data_dir: str | Path,
    *,
    laboratory_id: str,
    rows: list[dict[str, Any]],
    manifest_body: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Write lab-scoped day export with by_lane partitions."""
    from atlas.investment.laboratory import normalize_laboratory_id, refuse_pooled_edge_metrics

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    refuse_pooled_edge_metrics(rows, context="write_lab_partitioned_export")
    day = datetime.now(_IST).strftime("%Y-%m-%d")
    root = Path(data_dir) / STORE_REL / f"lab_{_safe_seg(lab)}" / day
    root.mkdir(parents=True, exist_ok=True)
    by_lane = root / "by_lane"
    by_lane.mkdir(parents=True, exist_ok=True)

    partitions: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = lane_partition_key(row)
        partitions.setdefault(key, []).append(row)

    lane_paths: dict[str, str] = {}
    for key, lane_rows in sorted(partitions.items()):
        path = by_lane / key / "rows.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for row in lane_rows:
                fh.write(json.dumps(row, default=str) + "\n")
        lane_paths[key] = str(path)

    all_path = root / "all_rows.jsonl"
    with all_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            if isinstance(row, dict):
                fh.write(json.dumps(row, default=str) + "\n")

    contract_path = root / "walk_forward_contract.json"
    contract_path.write_text(
        json.dumps(contract, indent=2, default=str) + "\n", encoding="utf-8"
    )

    manifest = {
        **manifest_body,
        "version": VERSION,
        "ml_export_version": ML_EXPORT_VERSION,
        "laboratory_id": lab,
        "day": day,
        "row_count": len(rows),
        "lanes_written": sorted(lane_paths.keys()),
        "lane_paths": lane_paths,
        "all_rows_path": str(all_path),
        "contract_path": str(contract_path),
        "live_nn_trading": False,
        "atlasnet_status": "prep_only",
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )
    preview_path = root / "preview.json"
    preview_path.write_text(
        json.dumps(
            {
                "rows_preview": rows[:20],
                "lanes": {k: len(v) for k, v in partitions.items()},
                "contract_summary": {
                    "n_train": contract.get("n_train"),
                    "n_test": contract.get("n_test"),
                    "learned_beats_rules": False,
                    "live_nn_trading": False,
                },
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "root": str(root),
        "manifest_path": str(manifest_path),
        "contract_path": str(contract_path),
        "all_rows_path": str(all_path),
        "preview_path": str(preview_path),
        "lane_paths": lane_paths,
        "lanes_written": sorted(lane_paths.keys()),
    }


def _load_lab_packets_attrs(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    lookback_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
        _log.debug("atlasnet attributions load failed", exc_info=True)
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
            packets.extend(pstore.list_day(portfolio_key=lab, ts_ist=ist_today(), limit=100))
    except Exception:  # noqa: BLE001
        _log.debug("atlasnet packets load failed", exc_info=True)
    return packets, attributions


def export_atlasnet_prep(
    *,
    data_dir: str | Path | None,
    laboratory_id: str = "india_equity_learner",
    force_override: bool = False,
    override_note: str = "",
    lookback_limit: int = 500,
    train_frac: float = 0.7,
) -> dict[str, Any]:
    """LI.6 — quality-gated lab-partitioned export + walk-forward contract stub."""
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    packets, attributions = _load_lab_packets_attrs(
        data_dir, laboratory_id=lab, lookback_limit=lookback_limit
    )
    built = build_export_dataset(
        packets=packets, attributions=attributions, portfolio_key=lab
    )
    gate = gate_status(
        closed_by_lane=built.get("closed_by_lane") or built["closed_by_strategy"],
        force_override=force_override,
        override_note=override_note,
    )
    quality = build_export_quality_report(
        packets=packets, attributions=attributions, laboratory_id=lab
    )
    allowed, reason = _export_allowed(
        gate=gate,
        quality=quality,
        force_override=force_override,
        override_note=override_note,
    )
    contract = build_walk_forward_contract(
        built["rows"], laboratory_id=lab, train_frac=train_frac
    )
    hard_gate = evaluate_atlasnet_hard_gate(
        rows=built["rows"],
        packets=packets,
        attributions=attributions,
        learned_beats_rules=bool(contract.get("learned_beats_rules")),
    )
    out: dict[str, Any] = {
        "version": VERSION,
        "laboratory_id": lab,
        "portfolio_key": lab,
        "as_of_ist": ist_now_iso(),
        "gate": gate,
        "quality": quality,
        "hard_gate": hard_gate,
        "train_allowed": bool(hard_gate.get("train_allowed")),
        "export_allowed": allowed,
        "export_reason": reason,
        "exported": False,
        "row_count": built["row_count"],
        "closed_by_lane": built.get("closed_by_lane") or built["closed_by_strategy"],
        "walk_forward_contract": contract,
        "live_nn_trading": False,
        "atlasnet_status": hard_gate.get("atlasnet_status") or "prep_only",
        "atlasnet_shape": ATLASNET_SHAPE,
        "lq": "lq.9",
        "honesty": (
            "LI.6/LQ.9 AtlasNet prep: lab-partitioned export + walk-forward contract. "
            "Prep export may clear while train/paper-NN stay blocked by §8.2 hard_gate. "
            "Never trains or deploys NN. Never mixes laboratories."
        ),
    }
    if not allowed:
        out["blocked"] = reason
        return out

    if data_dir:
        try:
            written = write_lab_partitioned_export(
                data_dir,
                laboratory_id=lab,
                rows=built["rows"],
                manifest_body={
                    k: v
                    for k, v in out.items()
                    if k not in {"walk_forward_contract"}
                },
                contract=contract,
            )
            out["exported"] = True
            out.update(written)
        except Exception:  # noqa: BLE001
            _log.debug("atlasnet partitioned write failed", exc_info=True)
            out["exported"] = False
            out["write_error"] = "partitioned_write_failed"
    else:
        out["exported"] = True
        out["rows_preview"] = built["rows"][:20]
    return out


def atlasnet_prep_status(
    *,
    data_dir: str | Path | None,
    laboratory_id: str = "india_equity_learner",
    lookback_limit: int = 500,
) -> dict[str, Any]:
    """Status without writing — sample gate + readiness + prep honesty."""
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    packets, attributions = _load_lab_packets_attrs(
        data_dir, laboratory_id=lab, lookback_limit=lookback_limit
    )
    built = build_export_dataset(
        packets=packets, attributions=attributions, portfolio_key=lab
    )
    gate = gate_status(
        closed_by_lane=built.get("closed_by_lane") or built["closed_by_strategy"]
    )
    quality = build_export_quality_report(
        packets=packets, attributions=attributions, laboratory_id=lab
    )
    allowed, reason = _export_allowed(
        gate=gate, quality=quality, force_override=False, override_note=""
    )
    hard_gate = evaluate_atlasnet_hard_gate(
        rows=built["rows"],
        packets=packets,
        attributions=attributions,
        learned_beats_rules=False,
    )
    return {
        "version": VERSION,
        "laboratory_id": lab,
        "gate": gate,
        "quality": quality,
        "hard_gate": hard_gate,
        "train_allowed": bool(hard_gate.get("train_allowed")),
        "export_allowed": allowed,
        "export_reason": reason,
        "row_count": built["row_count"],
        "live_nn_trading": False,
        "atlasnet_status": hard_gate.get("atlasnet_status") or "prep_only",
        "atlasnet_shape": ATLASNET_SHAPE,
        "lq": "lq.9",
        "next_step": (
            "Clear LI.5b readiness + sample gates for prep export; "
            f"§8.2 hard_gate blocking={hard_gate.get('blocking')}. "
            "NN training remains forbidden until hard_gate.train_allowed."
            if not hard_gate.get("train_allowed")
            else (
                "§8.2 cleared for train/paper-NN eligibility — live NN still operator-gated. "
                if allowed
                else "Hard gate clear but prep export sample/readiness still blocked."
            )
        ),
    }


def request_atlasnet_train(
    *,
    data_dir: str | Path | None = None,
    laboratory_id: str = "india_equity_learner",
    intent: str = "train",
    lookback_limit: int = 800,
    learned_beats_rules: bool = False,
    force_override: bool = False,
    override_note: str = "",
) -> dict[str, Any]:
    """LQ.9 — sole entry for train/paper-NN. Force override cannot bypass §8.2."""
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    packets, attributions = _load_lab_packets_attrs(
        data_dir, laboratory_id=lab, lookback_limit=lookback_limit
    )
    built = build_export_dataset(
        packets=packets, attributions=attributions, portfolio_key=lab
    )
    hard_gate = evaluate_atlasnet_hard_gate(
        rows=built["rows"],
        packets=packets,
        attributions=attributions,
        learned_beats_rules=learned_beats_rules,
    )
    out: dict[str, Any] = {
        "version": "lq.9.train_request",
        "laboratory_id": lab,
        "intent": str(intent or "train"),
        "hard_gate": hard_gate,
        "train_allowed": bool(hard_gate.get("train_allowed")),
        "started": False,
        "live_nn_trading": False,
        "atlasnet_status": hard_gate.get("atlasnet_status") or "prep_only",
        "force_override_ignored": bool(force_override),
        "override_note": str(override_note or "")[:200] or None,
        "honesty": (
            "LQ.9: force_override cannot unlock train/paper-NN. "
            "Use LI.6 /atlasnet-prep for prep export only."
        ),
    }
    if force_override:
        out["blocked"] = (
            "force_override does not bypass §8.2 hard gate "
            f"(blocking={hard_gate.get('blocking')})"
        )
        return out
    try:
        assert_atlasnet_train_allowed(hard_gate, intent=intent)
    except AtlasNetTrainBlocked as exc:
        out["blocked"] = str(exc)
        return out
    # Cleared — still do not train weights in-process (ops/offline harness later)
    out["started"] = False
    out["note"] = (
        "§8.2 cleared; in-repo trainer not wired — record eligibility only. "
        "live_nn_trading remains False."
    )
    return out
