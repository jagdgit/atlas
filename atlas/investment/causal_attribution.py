"""DAV.1 — Decision Attribution densify: factors that helped / hurt / unknown.

Builds on DI.Attr / LQ.4. Never invents PE, FCF, sector-relative returns, or
news sentiment. Missing evidence → ``unknown`` with an honest note.

Operator narrative target (example)::

    valuation helped · momentum helped · sector unknown (no relative return) ·
    news unknown (no linked headlines) · thesis supported
"""

from __future__ import annotations

from typing import Any

VERSION = "dav.1.causal_factors"

FACTOR_IDS = (
    "valuation",
    "technical",
    "momentum",
    "business",
    "research",
    "macro",
    "experience",
    "sector",
    "news",
    "thesis",
    "timing",
    "policy",
)


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def decide_time_belief(packet: dict[str, Any] | None) -> dict[str, Any]:
    """Freeze-readable belief snapshot from an immutable Decision Packet."""
    pkt = packet if isinstance(packet, dict) else {}
    contrib = (
        pkt.get("feature_contributions")
        if isinstance(pkt.get("feature_contributions"), dict)
        else {}
    )
    drivers: dict[str, float] = {}
    for k, v in contrib.items():
        if k in {
            "version",
            "note",
            "sum",
            "total",
            "heuristic",
        } or str(k).startswith("_"):
            continue
        fv = _f(v)
        if fv is None or fv == 0:
            continue
        drivers[str(k)] = fv
    unknowns = list(pkt.get("unknowns") or [])
    fund = pkt.get("fundamentals") if isinstance(pkt.get("fundamentals"), dict) else {}
    val = pkt.get("valuation") if isinstance(pkt.get("valuation"), dict) else {}
    snap = (
        pkt.get("market_snapshot")
        if isinstance(pkt.get("market_snapshot"), dict)
        else {}
    )
    return {
        "version": VERSION,
        "symbol": pkt.get("symbol"),
        "strategy_tag": pkt.get("strategy_tag"),
        "drivers": drivers,
        "unknowns": unknowns,
        "has_pe": fund.get("pe") is not None or val.get("pe") is not None,
        "has_mos": val.get("margin_of_safety_pct") is not None,
        "has_fcf": fund.get("fcf") is not None or fund.get("free_cash_flow") is not None,
        "reasons_for": list(pkt.get("reasons_for") or [])[:6],
        "reasons_against": list(pkt.get("reasons_against") or [])[:6],
        "regime_tags": list(snap.get("regime_tags") or pkt.get("regime_tags") or []),
    }


def _role_from_alignment(
    decide_contrib: float,
    price_change_pct: float | None,
    *,
    threshold_pct: float = 2.0,
) -> str:
    """Align decide-time signed contrib with subsequent price path."""
    px = _f(price_change_pct)
    if px is None or abs(px) < float(threshold_pct):
        return "neutral"
    if decide_contrib > 0:
        return "helped" if px > 0 else "hurt"
    if decide_contrib < 0:
        return "helped" if px < 0 else "hurt"
    return "neutral"


def evaluate_causal_factors(
    packet: dict[str, Any] | None,
    *,
    price_change_pct: float | None = None,
    pnl: float | None = None,
    sector_rel_pct: float | None = None,
    news_count: int | None = None,
    news_sentiment: str | None = None,
    news_titles: list[str] | None = None,
    regime_tags: list[str] | None = None,
    thesis_correct: str | None = None,
    exit_reason_code: str | None = None,
    grades: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Outcome-time factor roles. Fail-closed unknowns when evidence missing."""
    belief = decide_time_belief(packet)
    px = _f(price_change_pct)
    if px is None and isinstance(grades, dict):
        px = _f(grades.get("price_change_pct"))
    factors: list[dict[str, Any]] = []
    missing: list[str] = []

    for name, contrib in (belief.get("drivers") or {}).items():
        if contrib is None:
            continue
        role = _role_from_alignment(float(contrib), px)
        factors.append(
            {
                "factor": name,
                "role": role,
                "decide_contrib": contrib,
                "evidence": "decide_time_contrib×price_path",
                "note": (
                    None
                    if role != "neutral"
                    else "price path too small / missing — no helped/hurt label"
                ),
            }
        )

    if sector_rel_pct is None:
        factors.append(
            {
                "factor": "sector",
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": "no sector-relative return supplied",
            }
        )
        missing.append("sector_rel_pct")
    else:
        rel = float(sector_rel_pct)
        if abs(rel) < 1.0:
            role = "neutral"
        else:
            role = "helped" if rel > 0 else "hurt"
        factors.append(
            {
                "factor": "sector",
                "role": role,
                "decide_contrib": None,
                "evidence": f"sector_rel_pct={rel:+.2f}",
                "note": None,
            }
        )

    titles = [str(t).strip() for t in (news_titles or []) if str(t).strip()]
    ncount = int(news_count or 0) or len(titles)
    if ncount <= 0:
        factors.append(
            {
                "factor": "news",
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": "no linked headlines on path",
            }
        )
        missing.append("news")
    else:
        sent = str(news_sentiment or "").strip().lower()
        if sent in {"positive", "pos", "+"} and px is not None and px > 0:
            role = "helped"
        elif sent in {"negative", "neg", "-"} and px is not None and px < 0:
            role = "hurt"  # long book: negative news with decline
        elif sent in {"positive", "pos", "+"} and px is not None and px < 0:
            role = "hurt"
        elif sent in {"negative", "neg", "-"} and px is not None and px > 0:
            role = "helped"
        else:
            role = "unknown"
        evidence = f"news_count={ncount}" + (f",sentiment={sent}" if sent else "")
        if titles:
            evidence += "; " + " | ".join(titles[:2])
        factors.append(
            {
                "factor": "news",
                "role": role,
                "decide_contrib": None,
                "evidence": evidence,
                "note": (
                    None
                    if role != "unknown"
                    else "headlines present but sentiment/direction not labeled"
                ),
            }
        )

    concrete_regime = [
        str(t)
        for t in (regime_tags or [])
        if str(t).strip() and str(t).strip().lower() != "unknown"
    ]
    if concrete_regime:
        role = "unknown"
        if px is not None:
            if "bull" in concrete_regime and px > 0:
                role = "helped"
            elif "bear" in concrete_regime and px < 0:
                role = "helped"
            elif "bull" in concrete_regime and px < 0:
                role = "hurt"
            elif "bear" in concrete_regime and px > 0:
                role = "hurt"
        factors.append(
            {
                "factor": "policy",
                "role": role,
                "decide_contrib": None,
                "evidence": "regime=" + ",".join(concrete_regime[:4]),
                "note": "bar-derived or macro-observed regime — not proven causation",
            }
        )
    else:
        factors.append(
            {
                "factor": "policy",
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": "no concrete regime tags",
            }
        )
        missing.append("regime")

    thesis = str(
        thesis_correct or (grades or {}).get("thesis_correct") or ""
    ).strip().lower()
    if thesis in {"yes", "supported", "true"}:
        factors.append(
            {
                "factor": "thesis",
                "role": "helped",
                "decide_contrib": None,
                "evidence": f"thesis_correct={thesis}",
                "note": None,
            }
        )
    elif thesis in {"no", "broken", "false"}:
        factors.append(
            {
                "factor": "thesis",
                "role": "hurt",
                "decide_contrib": None,
                "evidence": f"thesis_correct={thesis}",
                "note": None,
            }
        )
    else:
        factors.append(
            {
                "factor": "thesis",
                "role": "unknown",
                "decide_contrib": None,
                "evidence": None,
                "note": "thesis verdict not recorded yet",
            }
        )
        missing.append("thesis")

    code = str(exit_reason_code or "").strip().lower()
    if code in {"time_stop", "time-stop"}:
        factors.append(
            {
                "factor": "timing",
                "role": "hurt",
                "decide_contrib": None,
                "evidence": f"exit_reason={code}",
                "note": "time stop fired",
            }
        )
    elif code in {"stop_loss", "trailing_stop", "sma_crossunder"}:
        factors.append(
            {
                "factor": "timing",
                "role": "hurt" if (px is not None and px < 0) else "unknown",
                "decide_contrib": None,
                "evidence": f"exit_reason={code}",
                "note": None,
            }
        )

    if not belief.get("has_pe") and not belief.get("has_mos"):
        if not any(f.get("factor") == "valuation" for f in factors):
            factors.append(
                {
                    "factor": "valuation",
                    "role": "unknown",
                    "decide_contrib": None,
                    "evidence": None,
                    "note": "no PE/MoS at decide-time — cannot credit valuation",
                }
            )
            missing.append("valuation_inputs")

    helped = [f["factor"] for f in factors if f.get("role") == "helped"]
    hurt = [f["factor"] for f in factors if f.get("role") == "hurt"]
    unknown = [f["factor"] for f in factors if f.get("role") == "unknown"]

    bits: list[str] = []
    if helped:
        bits.append("helped: " + ", ".join(helped[:5]))
    if hurt:
        bits.append("hurt: " + ", ".join(hurt[:5]))
    if unknown:
        bits.append("unknown: " + ", ".join(unknown[:5]))
    if not bits:
        bits.append("no factor labels yet (need exit path + decide-time drivers)")

    return {
        "version": VERSION,
        "belief": belief,
        "factors": factors,
        "helped": helped,
        "hurt": hurt,
        "unknown": unknown,
        "missing_evidence": missing,
        "price_change_pct": px,
        "pnl": _f(pnl),
        "news_titles": titles[:4],
        "regime_tags": concrete_regime[:6],
        "narrative": "; ".join(bits),
        "honesty": (
            "Roles are path-alignment labels from durable evidence — "
            "not proven economic causation. Missing PE/FCF/sector/news stay unknown."
        ),
    }


def densify_attribution_for_display(
    attr: dict[str, Any],
    *,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach causal_factors for evening/mail when missing (display-only; no rewrite)."""
    if not isinstance(attr, dict):
        return attr
    out = dict(attr)
    payload = dict(out.get("payload") or {}) if isinstance(out.get("payload"), dict) else {}
    existing = payload.get("causal_factors")
    if isinstance(existing, dict) and existing.get("narrative"):
        return out
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    if isinstance(extra.get("causal_factors"), dict) and extra["causal_factors"].get(
        "narrative"
    ):
        payload["causal_factors"] = extra["causal_factors"]
        out["payload"] = payload
        return out
    pkt = packet if isinstance(packet, dict) else None
    grades = out.get("grades") if isinstance(out.get("grades"), dict) else {}
    wc = payload.get("what_changed") if isinstance(payload.get("what_changed"), dict) else {}
    nd = wc.get("news_delta") if isinstance(wc.get("news_delta"), dict) else {}
    try:
        causal = evaluate_causal_factors(
            pkt,
            price_change_pct=grades.get("price_change_pct"),
            pnl=payload.get("pnl"),
            sector_rel_pct=wc.get("sector_rel_pct") or wc.get("sector_relative_pct") or wc.get(
                "rs_vs_nifty"
            ),
            news_count=int(nd.get("count") or wc.get("news_count") or 0),
            news_sentiment=str(nd.get("sentiment") or wc.get("news_sentiment") or "")
            or None,
            news_titles=list(nd.get("titles") or [])[:4] if nd else None,
            regime_tags=list(wc.get("regime_tags") or [])[:6] if wc else None,
            thesis_correct=str(grades.get("thesis_correct") or "") or None,
            exit_reason_code=str(
                extra.get("exit_reason_code") or extra.get("exit_reason") or ""
            )
            or None,
            grades=grades,
        )
        payload["causal_factors"] = {
            "version": causal.get("version"),
            "narrative": causal.get("narrative"),
            "helped": causal.get("helped"),
            "hurt": causal.get("hurt"),
            "unknown": causal.get("unknown"),
            "missing_evidence": causal.get("missing_evidence"),
            "display_only": True,
        }
        out["payload"] = payload
    except Exception:  # noqa: BLE001
        pass
    return out


def enrich_attributions_for_evening(
    attributions: list[dict[str, Any]] | None,
    *,
    packet_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Best-effort causal densify for mail (does not mutate durable store)."""
    pkt_map = packet_by_id or {}
    out: list[dict[str, Any]] = []
    for a in attributions or []:
        if not isinstance(a, dict):
            continue
        did = str(a.get("decision_id") or "")
        pkt = pkt_map.get(did)
        out.append(densify_attribution_for_display(a, packet=pkt))
    return out


def format_causal_learning_lines(
    attributions: list[dict[str, Any]] | None,
    *,
    limit: int = 8,
) -> list[str]:
    """Evening / chat: evidence-backed learning vs undetermined gaps.

    Unknown ≠ learning. Only helped/hurt with evidence go under LEARNED.
    """
    lines: list[str] = []
    rows = [a for a in (attributions or []) if isinstance(a, dict)]
    learned: list[str] = []
    undetermined: list[str] = []
    data_needed: set[str] = set()
    news_bits: list[str] = []

    for a in rows:
        payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
        causal = payload.get("causal_factors")
        if not isinstance(causal, dict):
            extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
            causal = extra.get("causal_factors") if isinstance(extra, dict) else None
        if not isinstance(causal, dict):
            continue
        helped = [str(x) for x in (causal.get("helped") or []) if x]
        hurt = [str(x) for x in (causal.get("hurt") or []) if x]
        unknown = [str(x) for x in (causal.get("unknown") or []) if x]
        sym = a.get("symbol") or "?"
        trig = a.get("trigger") or "?"
        if helped or hurt:
            bits = []
            if helped:
                bits.append("helped=" + ",".join(helped[:4]))
            if hurt:
                bits.append("hurt=" + ",".join(hurt[:4]))
            learned.append(f"  · {sym} [{trig}]: {'; '.join(bits)}")
            narr = causal.get("narrative") or ""
            if narr and "unknown:" not in str(narr).lower():
                learned.append(f"      {narr}")
        if unknown and not helped and not hurt:
            undetermined.append(
                f"  · {sym} [{trig}]: could not determine — {', '.join(unknown[:6])}"
            )
            for u in unknown:
                data_needed.add(str(u).strip().lower())
        elif unknown:
            for u in unknown:
                data_needed.add(str(u).strip().lower())
        titles = causal.get("news_titles") or []
        if titles:
            news_bits.append(
                f"  · {sym}: {' | '.join(str(t)[:80] for t in titles[:2])}"
            )

    lines.append("")
    lines.append("WHAT ATLAS LEARNED (evidence-backed causes only):")
    if learned:
        lines.extend(learned[: max(1, limit * 2)])
    else:
        lines.append(
            "  (none yet — no helped/hurt causes with evidence; "
            "revisits alone are not lessons)"
        )

    lines.append("")
    lines.append("WHAT ATLAS COULD NOT DETERMINE:")
    if undetermined:
        lines.extend(undetermined[:limit])
    elif not rows:
        lines.append(
            "  (no attribution records — need exits/revisits with decide-time packets)"
        )
    else:
        lines.append("  (no all-unknown causal rows this window)")

    lines.append("")
    lines.append("DATA REQUIRED:")
    if data_needed:
        hint = {
            "news": "Company + sector news timeline",
            "sector": "Sector index / RS timeline",
            "policy": "Government / RBI / SEBI policy events",
            "thesis": "Thesis state vs falsifiers at decide-time",
            "market": "NIFTY / regime timeline",
            "fundamentals": "PE/FCF/ROE deltas on open books",
        }
        for key in sorted(data_needed):
            lines.append(f"  · {hint.get(key, key)}")
    else:
        lines.append("  · (none flagged from causal unknowns)")

    if news_bits:
        lines.append("")
        lines.append("Named headlines (context, not proven causes):")
        lines.extend(news_bits[:4])

    lines.append(
        "  Honesty: unknown ≠ learning. Helped/hurt require decide-time evidence."
    )
    return lines

