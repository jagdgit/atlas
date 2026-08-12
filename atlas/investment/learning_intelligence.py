"""LI.5b — Learning Intelligence (Atlas IQ skill axes + evolution + readiness).

Builds on LI.5a thin proxies: full skill-axis reports, failure histograms,
evolution narratives, and dataset quality readiness (NN still refused).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger("atlas.investment.learning_intelligence")

VERSION = "li.5b.learning_intelligence"
STORE_REL = Path("investment") / "learning_intelligence"

# LQ.5 — stated confidence vs outcome (hide vanity below sample)
CALIB_MIN_CURVE_N = 30  # whole curve hidden until this many scored exits
CALIB_MIN_BIN_N = 5
CALIB_BINS: tuple[tuple[float, float], ...] = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0001),
)

# Plan §LI.0a.10 — single primary root cause vocabulary
FAILURE_ROOT_CAUSES: tuple[str, ...] = (
    "research_failure",
    "evidence_failure",
    "execution_failure",
    "portfolio_failure",
    "market_regime_failure",
    "risk_failure",
    "psychological_policy_failure",
    "resource_limitation",
    "data_unavailable",
    "provider_conflict",
)

AXIS_NOTES = {
    "research": "Fundamentals / PE coverage depth",
    "decision": "Packet completeness and unknown honesty",
    "risk": "Process score / risk discipline",
    "execution": "Closed attributions and revisit completions",
    "learning": "Observation density + revisit drain rate",
    "calibration": "Stated confidence vs outcomes + failure-cause tagging",
    "evidence_quality": "Provider tier mix (filing/Screener > Yahoo)",
}


def normalize_failure_cause(raw: str | None) -> str | None:
    s = str(raw or "").strip().lower().replace(" ", "_")
    if not s:
        return None
    if s in FAILURE_ROOT_CAUSES:
        return s
    aliases = {
        "evidence": "evidence_failure",
        "research": "research_failure",
        "execution": "execution_failure",
        "portfolio": "portfolio_failure",
        "regime": "market_regime_failure",
        "risk": "risk_failure",
        "process": "psychological_policy_failure",
        "host_guard": "resource_limitation",
        "feed": "data_unavailable",
        "conflict": "provider_conflict",
    }
    return aliases.get(s)


def _store_dir(data_dir: str | Path, laboratory_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in laboratory_id)
    return Path(data_dir) / STORE_REL / safe


def evolution_path(data_dir: str | Path, laboratory_id: str) -> Path:
    return _store_dir(data_dir, laboratory_id) / "evolution_events.jsonl"


def iq_snapshot_path(data_dir: str | Path, laboratory_id: str) -> Path:
    return _store_dir(data_dir, laboratory_id) / "iq_latest.json"


def append_evolution_event(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    axis: str,
    from_score: float | None,
    to_score: float | None,
    reason: str,
    phase_id: str | None = None,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    event = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "laboratory_id": laboratory_id,
        "axis": str(axis),
        "from": from_score,
        "to": to_score,
        "reason": (reason or "")[:300],
        "phase_id": phase_id or "LI.5b",
        "version": VERSION,
    }
    try:
        path = evolution_path(data_dir, laboratory_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
        return event
    except Exception:  # noqa: BLE001
        _log.debug("evolution event append failed", exc_info=True)
        return None


def list_evolution_events(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    limit: int = 40,
) -> list[dict[str, Any]]:
    if not data_dir:
        return []
    path = evolution_path(data_dir, laboratory_id)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                rows.append(doc)
    except Exception:  # noqa: BLE001
        return []
    return rows[-limit:]


def _clamp_score(n: float) -> float:
    return round(max(0.0, min(100.0, float(n))), 1)


def _extract_failure_cause(attr: dict[str, Any]) -> str | None:
    if not isinstance(attr, dict):
        return None
    payload = attr.get("payload") if isinstance(attr.get("payload"), dict) else {}
    raw = payload.get("failure_cause")
    if not raw and isinstance(payload.get("extra"), dict):
        raw = payload["extra"].get("failure_cause")
    return normalize_failure_cause(str(raw) if raw else None)


def _extract_feature_drivers(attr: dict[str, Any]) -> list[dict[str, Any]]:
    """LQ.4 — top decide-time feature drivers on an attribution."""
    if not isinstance(attr, dict):
        return []
    payload = attr.get("payload") if isinstance(attr.get("payload"), dict) else {}
    drivers = payload.get("feature_drivers")
    if isinstance(drivers, list):
        return [d for d in drivers if isinstance(d, dict) and d.get("feature")]
    return []


def failure_cause_histogram(attributions: list[dict[str, Any]] | None) -> dict[str, int]:
    hist: dict[str, int] = {}
    for a in attributions or []:
        cause = _extract_failure_cause(a) if isinstance(a, dict) else None
        if cause:
            hist[cause] = hist.get(cause, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def feature_driver_histogram(attributions: list[dict[str, Any]] | None) -> dict[str, int]:
    """LQ.4 — how often each decide-time feature ranks among top drivers."""
    hist: dict[str, int] = {}
    for a in attributions or []:
        if not isinstance(a, dict):
            continue
        for d in _extract_feature_drivers(a)[:3]:
            feat = str(d.get("feature") or "").strip()
            if not feat:
                continue
            hist[feat] = hist.get(feat, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def _stated_confidence(packet: dict[str, Any] | None) -> float | None:
    """Decide-time frozen overall confidence (0–1); never invent."""
    if not isinstance(packet, dict):
        return None
    cb = packet.get("confidence_breakdown")
    if not isinstance(cb, dict):
        return None
    raw = cb.get("overall")
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v > 1.0 and v <= 100.0:
        v = v / 100.0
    if v < 0.0 or v > 1.0:
        return None
    return v


def build_confidence_calibration_curve(
    packets: list[dict[str, Any]] | None,
    attributions: list[dict[str, Any]] | None,
    *,
    min_curve_n: int = CALIB_MIN_CURVE_N,
    min_bin_n: int = CALIB_MIN_BIN_N,
) -> dict[str, Any]:
    """LQ.5 — per-lab reliability curve: stated confidence vs thesis hit rate.

    Hides the whole curve below ``min_curve_n`` scored exits; bins with
    ``n < min_bin_n`` stay honest nulls. Does not rewrite packet confidence.
    """
    pkts = [p for p in (packets or []) if isinstance(p, dict)]
    attrs = [a for a in (attributions or []) if isinstance(a, dict)]
    by_id = {
        str(p.get("decision_id")): p
        for p in pkts
        if p.get("decision_id")
    }
    scored: list[dict[str, Any]] = []
    for a in attrs:
        trig = str(a.get("trigger") or "exit")
        if trig not in {"exit", "manual"}:
            continue
        did = a.get("decision_id")
        pkt = by_id.get(str(did or ""))
        conf = _stated_confidence(pkt)
        grades = a.get("grades") if isinstance(a.get("grades"), dict) else {}
        thesis = str(grades.get("thesis_correct") or "").lower()
        if conf is None or thesis not in {"yes", "no"}:
            continue
        scored.append(
            {
                "decision_id": did,
                "confidence": conf,
                "hit": thesis == "yes",
                "pnl": grades.get("pnl")
                if grades.get("pnl") is not None
                else (a.get("payload") or {}).get("pnl"),
            }
        )

    n = len(scored)
    if n < max(1, int(min_curve_n)):
        return {
            "version": "lq.5",
            "visible": False,
            "n": n,
            "min_n": int(min_curve_n),
            "bins": [],
            "ece": None,
            "sample_note": (
                f"Confidence calibration hidden until ≥{min_curve_n} "
                f"scored exits with thesis yes/no (have {n})."
            ),
            "outcome": "thesis_correct",
        }

    bins: list[dict[str, Any]] = []
    ece_num = 0.0
    ece_den = 0
    for lo, hi in CALIB_BINS:
        rows = [s for s in scored if lo <= float(s["confidence"]) < hi]
        bn = len(rows)
        mid = round((lo + hi) / 2.0, 3)
        band = f"{lo:.1f}–{min(hi, 1.0):.1f}"
        if bn < max(1, int(min_bin_n)):
            bins.append(
                {
                    "band": band,
                    "stated_mid": mid,
                    "n": bn,
                    "hit_rate": None,
                    "gap": None,
                    "visible": False,
                }
            )
            continue
        hits = sum(1 for r in rows if r["hit"])
        hit_rate = round(hits / bn, 3)
        gap = round(mid - hit_rate, 3)
        bins.append(
            {
                "band": band,
                "stated_mid": mid,
                "n": bn,
                "hit_rate": hit_rate,
                "gap": gap,
                "visible": True,
            }
        )
        ece_num += bn * abs(mid - hit_rate)
        ece_den += bn

    ece = round(ece_num / ece_den, 4) if ece_den else None
    return {
        "version": "lq.5",
        "visible": True,
        "n": n,
        "min_n": int(min_curve_n),
        "bins": bins,
        "ece": ece,
        "sample_note": None,
        "outcome": "thesis_correct",
        "honesty": (
            "Stated confidence is decide-time freeze; hit_rate uses thesis_correct "
            "yes/(yes+no) only — partial/unknown excluded."
        ),
    }


def build_revision_calibration(
    wsos: list[dict[str, Any]] | None,
    *,
    min_n: int = 5,
) -> dict[str, Any]:
    """IQ.1 — WSO revision status mix + flip rate (deterministic).

    Flip = later material revision on same symbol that contradicts prior
    strengthen/weaken (e.g. strengthened then weakened/falsified).
    """
    material = {"strengthened", "weakened", "falsified"}
    status_counts: dict[str, int] = {}
    flips = 0
    sequences = 0
    linked: list[str] = []
    for w in wsos or []:
        if not isinstance(w, dict) or w.get("kind") == "global":
            continue
        sym = str(w.get("symbol") or "").strip()
        if not sym or sym == "_GLOBAL":
            continue
        hist = [
            r
            for r in (w.get("revision_history") or [])
            if isinstance(r, dict)
            and str(r.get("status") or "").lower() in material
        ]
        if not hist:
            continue
        linked.append(sym)
        sequences += 1
        for r in hist:
            st = str(r.get("status") or "").lower()
            status_counts[st] = int(status_counts.get(st) or 0) + 1
        prior = None
        for r in hist:
            st = str(r.get("status") or "").lower()
            if prior == "strengthened" and st in {"weakened", "falsified"}:
                flips += 1
            if prior in {"weakened", "falsified"} and st == "strengthened":
                flips += 1
            prior = st

    n = sum(status_counts.values())
    flip_rate = round(flips / sequences, 3) if sequences else None
    visible = n >= max(1, int(min_n))
    return {
        "version": "iq.1.revision_calibration",
        "visible": visible,
        "n": n,
        "min_n": int(min_n),
        "symbols": len(set(linked)),
        "status_counts": status_counts,
        "flip_events": flips,
        "sequences": sequences,
        "flip_rate": flip_rate if visible else None,
        "sample_note": None
        if visible
        else (
            f"Revision calibration hidden until ≥{min_n} material WSO "
            f"revisions (have {n})."
        ),
        "honesty": (
            "Flip rate = mind-changes that later reversed; not trading PnL. "
            "Confidence-vs-outcome remains LQ.5."
        ),
    }


def format_calibration_section(
    *,
    confidence_curve: dict[str, Any] | None = None,
    revision_calibration: dict[str, Any] | None = None,
) -> list[str]:
    """IQ.1 evening — dedicated calibration slice (always prints honesty)."""
    lines = ["", "--- Calibration (IQ.1) ---"]
    curve = confidence_curve if isinstance(confidence_curve, dict) else {}
    rev = revision_calibration if isinstance(revision_calibration, dict) else {}

    if curve:
        if curve.get("visible"):
            lines.append(
                f"  Confidence vs thesis (LQ.5): n={curve.get('n')} "
                f"ECE={curve.get('ece')}"
            )
        else:
            lines.append(
                f"  Confidence vs thesis: "
                f"{curve.get('sample_note') or 'hidden until sample'}"
            )
    else:
        lines.append("  Confidence vs thesis: (no scored exits yet)")

    if rev:
        if rev.get("visible"):
            lines.append(
                f"  Revision mind-change: n={rev.get('n')} "
                f"symbols={rev.get('symbols')} flip_rate={rev.get('flip_rate')}"
            )
            sc = rev.get("status_counts") or {}
            if sc:
                bits = ", ".join(f"{k}={v}" for k, v in list(sc.items())[:5])
                lines.append(f"    statuses: {bits}")
        else:
            lines.append(
                f"  Revision mind-change: "
                f"{rev.get('sample_note') or 'hidden until sample'}"
            )
        if rev.get("honesty"):
            lines.append(f"  Honesty: {rev.get('honesty')}")
    else:
        lines.append("  Revision mind-change: (no WSO revisions yet)")
    return lines


def format_evolution_narrative(
    events: list[dict[str, Any]] | None,
    *,
    limit: int = 8,
) -> list[str]:
    """Human lines: how Atlas-the-product got smarter (not trade P&L)."""
    rows = list(events or [])[-limit:]
    if not rows:
        return ["(no evolution events yet — IQ deltas will append here)"]
    lines: list[str] = []
    for e in rows:
        axis = e.get("axis") or "?"
        fr = e.get("from")
        to = e.get("to")
        reason = e.get("reason") or ""
        at = str(e.get("at") or "")[:10]
        delta = None
        try:
            if fr is not None and to is not None:
                delta = round(float(to) - float(fr), 1)
        except (TypeError, ValueError):
            delta = None
        d_s = f" ({delta:+})" if delta is not None else ""
        lines.append(
            f"{at}: {axis} {fr}→{to}{d_s} — {reason}"[:200]
        )
    return lines


def build_atlas_iq_proxies(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    packets: list[dict[str, Any]] | None = None,
    process_score: float | None = None,
    pending_revisits: int = 0,
    done_revisits: int = 0,
    observation_count: int = 0,
    attributions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Skill-axis Atlas IQ (0–100) with notes + failure histogram (lab-scoped)."""
    from atlas.investment.fundamentals import fundamentals_view
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    pkts = list(packets or [])
    attrs = list(attributions or [])
    n_packets = len(pkts)
    n_attr = len(attrs)

    fund = fundamentals_view(data_dir, program_id=program_id, limit=5) if data_dir else {}
    cov = (fund.get("coverage") or {}) if isinstance(fund, dict) else {}
    pe_pct = float(cov.get("pe_coverage_pct") or 0)
    research = _clamp_score(pe_pct)

    with_unknowns = sum(1 for p in pkts if (p.get("unknowns") or []))
    # OI-EXP0 — do not treat routine HOLD spam as decision skill
    try:
        from atlas.investment.experience_integrity import (
            build_experience_metrics,
            experience_quality_score,
            is_routine_hold,
        )

        material_pkts = [
            p
            for p in pkts
            if not is_routine_hold(
                action=p.get("action"), strategy_tag=str(p.get("strategy_tag") or "")
            )
        ]
        exp_m = build_experience_metrics(
            packets=pkts,
            attributions=attrs,
            evolution={
                "done_revisits": done_revisits,
                "pending_revisits": pending_revisits,
            },
        )
        exp_q = experience_quality_score(exp_m)
    except Exception:  # noqa: BLE001
        material_pkts = pkts
        exp_m = {}
        exp_q = None

    n_material = len(material_pkts)
    decision = _clamp_score(
        55.0
        + (10.0 if n_material else 0)
        - min(25.0, with_unknowns * 2.0)
        + min(10.0, observation_count)  # capped — obs alone ≠ intelligence
        + (min(15.0, float(exp_q) * 0.15) if exp_q is not None else 0)
    )

    risk = _clamp_score(float(process_score) * 10.0 if process_score is not None else 40.0)

    execution = _clamp_score(
        40.0 + min(40.0, n_attr * 8.0) + (10.0 if done_revisits else 0)
    )

    rev_total = pending_revisits + done_revisits
    rev_rate = (100.0 * done_revisits / rev_total) if rev_total else 0.0
    # Learning axis: revisits + attributed causes; observation spam capped hard
    learning = _clamp_score(
        0.55 * rev_rate
        + min(25.0, observation_count * 2.0)
        + min(25.0, n_attr * 5.0)
        + (float(exp_q) * 0.2 if exp_q is not None else 0)
    )

    with_cause = sum(1 for a in attrs if _extract_failure_cause(a))
    curve = build_confidence_calibration_curve(pkts, attrs)
    # LQ.5 — densify calibration: failure tags + reliability when curve visible
    cause_score = 35.0 + min(40.0, with_cause * 10.0) + (10.0 if n_attr >= 3 else 0)
    if curve.get("visible") and curve.get("ece") is not None:
        # Lower ECE → better calibration (cap contribution)
        ece = float(curve["ece"])
        curve_score = _clamp_score(100.0 - min(100.0, ece * 200.0))
        calibration = _clamp_score(0.45 * cause_score + 0.55 * curve_score)
    else:
        calibration = _clamp_score(cause_score)

    by_prov = (cov.get("by_provider") or {}).get("pe_by_provider") or {}
    yahoo = int(by_prov.get("yahoo_fundamentals") or 0)
    high = int(by_prov.get("screener_export") or 0) + int(by_prov.get("filing") or 0)
    evidence_quality = _clamp_score(
        20.0 + min(50.0, high * 15.0) + min(30.0, yahoo * 5.0)
    )

    axes = {
        "research": research,
        "decision": decision,
        "risk": risk,
        "execution": execution,
        "learning": learning,
        "calibration": calibration,
        "evidence_quality": evidence_quality,
    }
    overall = _clamp_score(sum(axes.values()) / max(1, len(axes)))
    hist = failure_cause_histogram(attrs)
    driver_hist = feature_driver_histogram(attrs)

    sample_note = None
    axis_hidden: list[str] = []
    if n_packets < 5 and n_attr < 1:
        sample_note = "Thin sample — treat Atlas IQ as directional only."
        axis_hidden = list(axes.keys())
    elif n_attr < 5:
        # Hide vanity on calibration/execution until enough closed rows
        for ax in ("calibration", "execution"):
            if ax not in axis_hidden:
                axis_hidden.append(ax)
    elif not curve.get("visible"):
        # Curve not ready — keep calibration axis visible as proxy-only note
        pass

    axis_report = {
        name: {
            "score": score,
            "note": AXIS_NOTES.get(name, ""),
            "visible": name not in axis_hidden or sample_note is None,
        }
        for name, score in axes.items()
    }
    if "calibration" in axis_report and not curve.get("visible"):
        axis_report["calibration"]["note"] = (
            AXIS_NOTES["calibration"]
            + f" — curve hidden (n={curve.get('n')}/{curve.get('min_n')})"
        )

    snap = {
        "version": VERSION,
        "laboratory_id": lab,
        "experience_metrics": exp_m if isinstance(exp_m, dict) else None,
        "experience_quality_score": exp_q,
        "material_packets": n_material,
        "packets_raw": n_packets,
        "program_id": program_id,
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "axes": axes,
        "axis_report": axis_report,
        "overall": overall,
        "failure_cause_histogram": hist,
        "feature_driver_histogram": driver_hist,
        "confidence_calibration": curve,
        "counts": {
            "packets": n_packets,
            "attributions": n_attr,
            "observations": observation_count,
            "revisits_pending": pending_revisits,
            "revisits_done": done_revisits,
            "failure_causes_tagged": with_cause,
            "exits_with_drivers": sum(
                1 for a in attrs if _extract_feature_drivers(a)
            ),
            "calibration_scored_exits": curve.get("n"),
        },
        "sample_note": sample_note,
        "axis_hidden_until_sample": axis_hidden,
        "failure_root_causes": list(FAILURE_ROOT_CAUSES),
    }
    try:
        from atlas.investment.experience_integrity import build_maturity_split

        ready_grade = None
        durable_ok = None
        if data_dir:
            try:
                from pathlib import Path
                import json as _json

                wl = Path(str(data_dir)) / "market" / "watchlists" / f"{program_id}.json"
                if wl.is_file():
                    extra = (
                        _json.loads(wl.read_text(encoding="utf-8")).get("extra") or {}
                    )
                    dur = extra.get("durable_bars") or extra.get("readiness") or {}
                    if isinstance(dur, dict):
                        ready_grade = dur.get("readiness_grade")
                        durable_ok = dur.get("durable_bars_ok")
            except Exception:  # noqa: BLE001
                pass
        snap["maturity_split"] = build_maturity_split(
            experience_metrics=exp_m if isinstance(exp_m, dict) else None,
            system_score=overall,
            readiness_grade=str(ready_grade) if ready_grade else None,
            durable_bars_ok=bool(durable_ok) if durable_ok is not None else None,
        )
    except Exception:  # noqa: BLE001
        snap["maturity_split"] = None
    if data_dir:
        try:
            path = iq_snapshot_path(data_dir, lab)
            path.parent.mkdir(parents=True, exist_ok=True)
            prev = None
            if path.is_file():
                try:
                    prev = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    prev = None
            path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
            if isinstance(prev, dict) and prev.get("overall") is not None:
                if abs(float(prev["overall"]) - overall) >= 1.0:
                    append_evolution_event(
                        data_dir,
                        laboratory_id=lab,
                        axis="overall",
                        from_score=float(prev["overall"]),
                        to_score=overall,
                        reason="atlas_iq_skill_axis_refresh",
                        phase_id="LI.5b",
                    )
            # Per-axis material moves
            prev_axes = (prev or {}).get("axes") if isinstance(prev, dict) else {}
            if isinstance(prev_axes, dict):
                for ax, score in axes.items():
                    try:
                        old = float(prev_axes.get(ax)) if prev_axes.get(ax) is not None else None
                    except (TypeError, ValueError):
                        old = None
                    if old is not None and abs(old - score) >= 5.0:
                        append_evolution_event(
                            data_dir,
                            laboratory_id=lab,
                            axis=ax,
                            from_score=old,
                            to_score=score,
                            reason=f"skill_axis_{ax}_delta",
                            phase_id="LI.5b",
                        )
        except Exception:  # noqa: BLE001
            _log.debug("iq snapshot persist failed", exc_info=True)
    return snap


def build_learning_intelligence_report(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    packets: list[dict[str, Any]] | None = None,
    attributions: list[dict[str, Any]] | None = None,
    process_score: float | None = None,
    pending_revisits: int = 0,
    done_revisits: int = 0,
    observation_count: int = 0,
    evolution_limit: int = 40,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full LI.5b payload: IQ + narratives + hypotheses summary + readiness."""
    from atlas.investment.hypothesis_learning import list_hypotheses
    from atlas.investment.laboratory import normalize_laboratory_id

    lab = normalize_laboratory_id(laboratory_id=laboratory_id)
    iq = build_atlas_iq_proxies(
        data_dir,
        laboratory_id=lab,
        program_id=program_id,
        packets=packets,
        process_score=process_score,
        pending_revisits=pending_revisits,
        done_revisits=done_revisits,
        observation_count=observation_count,
        attributions=attributions,
    )
    events = list_evolution_events(data_dir, laboratory_id=lab, limit=evolution_limit)
    narrative = format_evolution_narrative(events)
    hyps = list_hypotheses(data_dir, laboratory_id=lab, include_world=True, limit=30)
    readiness = None
    if isinstance(quality, dict):
        readiness = quality.get("readiness")
    return {
        "ok": True,
        "version": VERSION,
        "laboratory_id": lab,
        "atlas_iq": iq,
        "evolution_events": events,
        "evolution_narrative": narrative,
        "hypotheses": {
            "count": len(hyps),
            "open": sum(1 for h in hyps if h.get("status") == "open"),
            "verdicted": sum(1 for h in hyps if h.get("status") not in {None, "open"}),
            "items": hyps[:10],
        },
        "failure_cause_histogram": iq.get("failure_cause_histogram") or {},
        "feature_driver_histogram": iq.get("feature_driver_histogram") or {},
        "confidence_calibration": iq.get("confidence_calibration") or {},
        "readiness": readiness,
        "live_nn_trading": False,
    }


def format_atlas_iq_section(snap: dict[str, Any] | None) -> list[str]:
    if not isinstance(snap, dict) or not snap.get("axes"):
        return []
    lines = [
        "",
        "Atlas IQ skill axes (LI.5b — Learning Intelligence):",
        f"  Laboratory: {snap.get('laboratory_id')} · overall={snap.get('overall')}",
    ]
    mat = snap.get("maturity_split") if isinstance(snap.get("maturity_split"), dict) else None
    if mat:
        lines.append(
            f"  System Maturity: {mat.get('system_maturity')} · "
            f"Trading Evidence Maturity: {mat.get('trading_evidence_maturity')} · "
            f"Data Readiness: {mat.get('data_readiness')}"
        )
        lines.append(
            f"  Strategy Evidence: {mat.get('strategy_evidence')} · "
            f"Attribution Maturity: {mat.get('attribution_maturity')}"
        )
        if mat.get("honesty"):
            lines.append(f"  Honesty: {mat.get('honesty')}")
    report = snap.get("axis_report") or {}
    if report:
        for name, row in report.items():
            if not isinstance(row, dict):
                continue
            vis = "" if row.get("visible", True) else " [hidden until sample]"
            lines.append(
                f"  · {name}={row.get('score')} — {row.get('note') or ''}{vis}"
            )
    else:
        axes = snap.get("axes") or {}
        parts = [f"{k}={v}" for k, v in axes.items()]
        lines.append(f"  Axes: {', '.join(parts)}")
    hist = snap.get("failure_cause_histogram") or {}
    if hist:
        top = ", ".join(f"{k}={v}" for k, v in list(hist.items())[:5])
        lines.append(f"  Failure causes: {top}")
    drivers = snap.get("feature_driver_histogram") or {}
    if drivers:
        top_d = ", ".join(f"{k}={v}" for k, v in list(drivers.items())[:5])
        lines.append(f"  Top decide-time drivers: {top_d}")
    calib = snap.get("confidence_calibration") if isinstance(snap.get("confidence_calibration"), dict) else {}
    if calib:
        if calib.get("visible"):
            ece = calib.get("ece")
            lines.append(
                f"  Confidence calibration (LQ.5): n={calib.get('n')} ECE={ece}"
            )
            for b in (calib.get("bins") or [])[:5]:
                if not isinstance(b, dict):
                    continue
                if not b.get("visible"):
                    lines.append(
                        f"    · band {b.get('band')}: n={b.get('n')} (hidden)"
                    )
                    continue
                lines.append(
                    f"    · band {b.get('band')}: stated≈{b.get('stated_mid')} "
                    f"hit={b.get('hit_rate')} n={b.get('n')}"
                )
        else:
            lines.append(
                f"  Confidence calibration: {calib.get('sample_note') or 'hidden until sample'}"
            )
    counts = snap.get("counts") or {}
    lines.append(
        f"  n: packets={counts.get('packets')} attr={counts.get('attributions')} "
        f"obs={counts.get('observations')} revisits_done={counts.get('revisits_done')}"
    )
    if snap.get("sample_note"):
        lines.append(f"  Note: {snap.get('sample_note')}")
    return lines


def format_evolution_narrative_section(
    events: list[dict[str, Any]] | None = None,
    narrative: list[str] | None = None,
) -> list[str]:
    lines = ["", "Evolution memory (how Atlas got smarter):"]
    rows = narrative if narrative is not None else format_evolution_narrative(events)
    for ln in rows[:10]:
        lines.append(f"  · {ln}")
    return lines
