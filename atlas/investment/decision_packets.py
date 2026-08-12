"""Decision Packets (DI.1) — freeze belief + evidence at decide-time.

Feature contributions heuristic (v1)
------------------------------------
Signed integer contributions in roughly ``[-20, +20]`` derived from existing
investment score axes and technical indicators. Missing research/fundamentals
contribute **0** and add an ``unknowns`` flag — never invent positive business
or valuation scores.

Mapping:
- business ← financial_health axis
- management ← (future; 0 for now)
- valuation ← valuation axis; MoS boosts; missing PE/FCF → unknown
- technical ← technical axis + SMA margin / RSI band
- macro ← macro_theme axis
- news ← 0 until observations cite news
- experience ← risk/experience bias when present
- research ← coverage / research confidence proxy
- portfolio_fit ← gate allowed (+); block (−)

Hybrid storage: Postgres (``DecisionPacketRepository``) authoritative when
available; JSON mirrors under ``investment/decisions/`` always attempted after
a successful primary write (or as sole store when repo is None — hermetic).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from atlas.repositories.decision_packet_repo import ALLOWED_ACTIONS

_log = logging.getLogger("atlas.investment.decision_packets")

PACKET_VERSION = "di.packet.1"
STORE_REL = Path("investment") / "decisions"
_IST = ZoneInfo("Asia/Kolkata")

STRATEGY_TAGS = frozenset(
    {
        "sma_cross_rsi",
        "next_alternative",
        "research_forced_hold",
        "portfolio_trim",
        "policy_block",
        "session_closed",
        "plan_watch",
        "plan_hold",
        "manual_operator",
        "pack_block",
        "capability_gap",
        "fill_rejected",
        "engine_hold",
    }
)

_CONTRIB_KEYS = (
    "business",
    "management",
    "valuation",
    "technical",
    "macro",
    "news",
    "experience",
    "research",
    "portfolio_fit",
)

# Completeness: fraction of these that are non-null / non-empty.
_CRITICAL = (
    ("action",),
    ("strategy_tag",),
    ("market_snapshot", "session"),
    ("market_snapshot", "sector"),
    ("prices", "mark"),
    ("reasons_for",),
    ("confidence_breakdown", "overall"),
    ("feature_contributions", "technical"),
)


def ist_today() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def mirror_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / STORE_REL


def mirror_by_id_path(data_dir: str | Path, decision_id: str) -> Path:
    return mirror_root(data_dir) / "by_id" / f"{decision_id}.json"


def mirror_day_path(data_dir: str | Path, portfolio_key: str, ts_ist: str) -> Path:
    safe = (portfolio_key or "unknown").replace("/", "_").strip() or "unknown"
    return mirror_root(data_dir) / "by_day" / safe / f"{ts_ist}.jsonl"


def _clamp_contrib(x: float) -> int:
    if not math.isfinite(x):
        return 0
    return int(max(-20, min(20, round(x))))


def _get_path(doc: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def completeness_score(payload: dict[str, Any]) -> float:
    if not payload:
        return 0.0
    hits = 0
    for path in _CRITICAL:
        val = _get_path(payload, path)
        if val is None:
            continue
        if isinstance(val, (list, dict, str)) and not val:
            continue
        hits += 1
    return round(hits / max(1, len(_CRITICAL)), 3)


def compute_unknowns(
    *,
    fundamentals: dict[str, Any] | None = None,
    investment_score: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
) -> list[str]:
    unknowns: list[str] = []
    fund = fundamentals if isinstance(fundamentals, dict) else {}
    if fund.get("pe") is None:
        unknowns.append("pe_missing")
    if fund.get("fcf") is None and fund.get("free_cash_flow") is None:
        unknowns.append("fcf_missing")
    # LI.2 — provider conflicts (never invent blended PE)
    for c in fund.get("evidence_conflicts") or []:
        tag = str(c)
        if tag and tag not in unknowns:
            unknowns.append(tag)
    score = investment_score if isinstance(investment_score, dict) else {}
    axes = score.get("axes") if isinstance(score.get("axes"), dict) else {}
    if not axes:
        unknowns.append("investment_axes_missing")
    val = valuation if isinstance(valuation, dict) else {}
    if val.get("margin_of_safety_pct") is None and fund.get("pe") is None:
        unknowns.append("mos_unknown")
    return unknowns


def feature_contributions_v1(
    *,
    investment_score: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    action: str = "hold",
    research_gate: dict[str, Any] | None = None,
    portfolio_gate: dict[str, Any] | None = None,
    research_coverage: float | None = None,
) -> dict[str, int]:
    """Heuristic v1 signed contributions — see module docstring."""
    score = investment_score if isinstance(investment_score, dict) else {}
    axes = score.get("axes") if isinstance(score.get("axes"), dict) else {}
    ind = indicators if isinstance(indicators, dict) else {}
    val = valuation if isinstance(valuation, dict) else {}
    sign = 1.0 if action in ("buy", "watch") else (-1.0 if action in ("sell", "reduce") else 0.5)

    def axis_contrib(name: str, weight: float = 12.0) -> int:
        raw = axes.get(name)
        if raw is None:
            return 0
        try:
            # axes are 0..1; center at 0.5 → signed
            centered = (float(raw) - 0.5) * 2.0 * weight * sign
            return _clamp_contrib(centered)
        except (TypeError, ValueError):
            return 0

    out = {k: 0 for k in _CONTRIB_KEYS}
    out["business"] = axis_contrib("financial_health", 10.0)
    out["valuation"] = axis_contrib("valuation", 14.0)
    out["technical"] = axis_contrib("technical", 12.0)
    out["macro"] = axis_contrib("macro_theme", 8.0)
    out["experience"] = axis_contrib("risk", 6.0)

    # Technical extras from indicators
    tech_extra = 0.0
    try:
        rsi = float(ind["rsi"]) if ind.get("rsi") is not None else None
        if rsi is not None:
            if rsi < 35:
                tech_extra += 4.0 * sign
            elif rsi > 65:
                tech_extra -= 4.0 * sign
    except (TypeError, ValueError):
        pass
    try:
        sma_f = ind.get("sma_fast")
        sma_s = ind.get("sma_slow")
        if sma_f is not None and sma_s is not None and float(sma_s) != 0:
            margin = (float(sma_f) - float(sma_s)) / abs(float(sma_s))
            tech_extra += max(-8.0, min(8.0, margin * 100.0)) * sign
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    out["technical"] = _clamp_contrib(out["technical"] + tech_extra)

    try:
        mos = val.get("margin_of_safety_pct")
        if mos is not None:
            out["valuation"] = _clamp_contrib(
                out["valuation"] + max(-8.0, min(8.0, float(mos) / 5.0)) * sign
            )
    except (TypeError, ValueError):
        pass

    if research_coverage is not None:
        try:
            out["research"] = _clamp_contrib((float(research_coverage) - 0.5) * 16.0 * sign)
        except (TypeError, ValueError):
            out["research"] = 0

    rg = research_gate if isinstance(research_gate, dict) else {}
    pg = portfolio_gate if isinstance(portfolio_gate, dict) else {}
    if rg.get("allowed") is False:
        out["research"] = _clamp_contrib(out["research"] - 8)
        out["portfolio_fit"] = _clamp_contrib(out["portfolio_fit"] - 2)
    if pg.get("allowed") is False:
        out["portfolio_fit"] = _clamp_contrib(out["portfolio_fit"] - 10)
    elif pg.get("allowed") is True and action == "buy":
        out["portfolio_fit"] = _clamp_contrib(out["portfolio_fit"] + 4)
    if pg.get("trimmed_from") or (pg.get("trim") or {}).get("binding"):
        out["portfolio_fit"] = _clamp_contrib(out["portfolio_fit"] - 2)

    return out


def confidence_breakdown_v1(
    *,
    investment_score: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    research_gate: dict[str, Any] | None = None,
    overall_hint: float | None = None,
) -> dict[str, Any]:
    score = investment_score if isinstance(investment_score, dict) else {}
    axes = score.get("axes") if isinstance(score.get("axes"), dict) else {}
    ind = indicators if isinstance(indicators, dict) else {}
    rg = research_gate if isinstance(research_gate, dict) else {}

    tech = None
    if axes.get("technical") is not None:
        try:
            tech = round(float(axes["technical"]), 3)
        except (TypeError, ValueError):
            tech = None
    elif ind.get("rsi") is not None:
        try:
            rsi = float(ind["rsi"])
            tech = round(max(0.0, min(1.0, 1.0 - abs(rsi - 50.0) / 50.0)), 3)
        except (TypeError, ValueError):
            tech = None

    inv_conf = score.get("confidence") or score.get("label")
    res_conf = rg.get("confidence") or rg.get("research_confidence")
    if isinstance(score.get("overall"), (int, float)):
        overall = round(float(score["overall"]), 3)
    elif overall_hint is not None:
        overall = round(float(overall_hint), 3)
    elif tech is not None:
        overall = tech
    else:
        overall = None

    return {
        "business": round(float(axes["financial_health"]), 3)
        if axes.get("financial_health") is not None
        else None,
        "management": None,
        "valuation": round(float(axes["valuation"]), 3)
        if axes.get("valuation") is not None
        else None,
        "technical": tech,
        "macro": round(float(axes["macro_theme"]), 3)
        if axes.get("macro_theme") is not None
        else None,
        "news": None,
        "experience": None,
        "research_confidence": res_conf,
        "investment_confidence": inv_conf,
        "overall": overall,
    }


def empty_market_snapshot(*, session: str | None = None, sector: str | None = None) -> dict[str, Any]:
    return {
        "session": session or "nse_equity",
        "regime_tags": [],
        "nifty_level": None,
        "india_vix": None,
        "usdinr": None,
        "sector": sector,
        "sector_day_return": None,
        "breadth_advance": None,
        "breadth_decline": None,
        "breadth_pct": None,
        "news_tone": None,
        "liquidity_band": None,
        "note": "nulls allowed; never invent",
    }


# LQ.6 / LI.0a.2 — locked regime vocabulary (unknown allowed; never invent)
REGIME_VOCAB: frozenset[str] = frozenset(
    {
        "bull",
        "bear",
        "sideways",
        "high_vol",
        "election",
        "geopolitical",
        "budget",
        "pandemic",
        "rate_cut",
        "rate_hike",
        "unknown",
    }
)

_REGIME_ALIASES: dict[str, str] = {
    "bullish": "bull",
    "bearish": "bear",
    "range": "sideways",
    "ranging": "sideways",
    "volatile": "high_vol",
    "highvol": "high_vol",
    "high-volatility": "high_vol",
    "ratecut": "rate_cut",
    "ratehike": "rate_hike",
    "geo": "geopolitical",
}


def normalize_regime_tags(tags: Any) -> list[str]:
    """Keep only locked vocab tags; map light aliases; never invent from P&L."""
    if tags is None:
        return []
    raw = tags if isinstance(tags, (list, tuple, set)) else [tags]
    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        s = str(t or "").strip().lower().replace(" ", "_").replace("-", "_")
        if not s:
            continue
        s = _REGIME_ALIASES.get(s, s)
        if s not in REGIME_VOCAB:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[:12]


def resolve_regime_tags(
    *,
    explicit: Any = None,
    macro_observations: list[dict[str, Any]] | None = None,
    default_unknown: bool = True,
) -> list[str]:
    """LQ.6 — evidence tags or ``["unknown"]``; never invent bull/bear from prices.

    Prefer concrete explicit → macro/policy payload.regime_tags → unknown.
    """
    tags = normalize_regime_tags(explicit)
    concrete = [t for t in tags if t != "unknown"]
    if concrete:
        return concrete[:12]
    for obs in macro_observations or []:
        if not isinstance(obs, dict):
            continue
        pl = obs.get("payload") if isinstance(obs.get("payload"), dict) else {}
        got = normalize_regime_tags(pl.get("regime_tags") or obs.get("regime_tags"))
        got_concrete = [t for t in got if t != "unknown"]
        if got_concrete:
            return got_concrete[:12]
    if tags:
        return ["unknown"]
    if default_unknown:
        return ["unknown"]
    return []


def stamp_regime_on_snapshot(
    snap: dict[str, Any] | None,
    *,
    explicit: Any = None,
    macro_observations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ensure market_snapshot.regime_tags is non-empty (unknown OK)."""
    out = dict(snap or empty_market_snapshot())
    existing = out.get("regime_tags")
    out["regime_tags"] = resolve_regime_tags(
        explicit=explicit if explicit is not None else existing,
        macro_observations=macro_observations,
        default_unknown=True,
    )
    return out


def regime_tags_for_closed_row(
    packet: dict[str, Any] | None = None,
    attr: dict[str, Any] | None = None,
) -> list[str]:
    """LQ.6 — regime labels for a closed training/export row (unknown OK)."""
    pkt = packet if isinstance(packet, dict) else {}
    a = attr if isinstance(attr, dict) else {}
    pl = a.get("payload") if isinstance(a.get("payload"), dict) else {}
    snap = pkt.get("market_snapshot") if isinstance(pkt.get("market_snapshot"), dict) else {}
    return resolve_regime_tags(
        explicit=pl.get("regime_tags") or snap.get("regime_tags"),
        default_unknown=True,
    )


def build_packet(
    *,
    action: str,
    symbol: str,
    portfolio_key: str,
    strategy_tag: str,
    ts_ist: str | None = None,
    decision_id: str | None = None,
    mission_id: str | None = None,
    setup_tag: str | None = None,
    parent_decision_id: str | None = None,
    derived_from_lesson_ids: list[str] | None = None,
    prior_thesis_id: str | None = None,
    engine_decision_id: str | None = None,
    fill_trade_id: str | None = None,
    experiment_id: str | None = None,
    hypothesis_id: str | None = None,
    market_snapshot: dict[str, Any] | None = None,
    prices: dict[str, Any] | None = None,
    investment_score: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    valuation: dict[str, Any] | None = None,
    fundamentals: dict[str, Any] | None = None,
    reasons_for: list[str] | None = None,
    reasons_against: list[str] | None = None,
    evidence_refs: list[Any] | None = None,
    observation_ids: list[str] | None = None,
    research_gate: dict[str, Any] | None = None,
    portfolio_gate: dict[str, Any] | None = None,
    research_coverage: float | None = None,
    plan_link: dict[str, Any] | None = None,
    gates_extra: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
    overall_confidence_hint: float | None = None,
    process_flags: list[dict[str, Any]] | None = None,
    process_context: dict[str, Any] | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an immutable ``di.packet.1`` payload (does not persist)."""
    act = str(action or "").strip().lower()
    if act not in ALLOWED_ACTIONS:
        raise ValueError(f"invalid action {action!r}")
    tag = str(strategy_tag or "").strip() or "manual_operator"
    did = str(decision_id or uuid4())
    day = ts_ist or ist_today()
    from atlas.investment.laboratory import normalize_experiment_id

    exp_id = normalize_experiment_id(experiment_id)
    snap = stamp_regime_on_snapshot(dict(market_snapshot or empty_market_snapshot()))
    contrib = feature_contributions_v1(
        investment_score=investment_score,
        indicators=indicators,
        valuation=valuation,
        action=act,
        research_gate=research_gate,
        portfolio_gate=portfolio_gate,
        research_coverage=research_coverage,
    )
    conf = confidence_breakdown_v1(
        investment_score=investment_score,
        indicators=indicators,
        research_gate=research_gate,
        overall_hint=overall_confidence_hint,
    )
    unknowns = compute_unknowns(
        fundamentals=fundamentals,
        investment_score=investment_score,
        valuation=valuation,
    )
    pg = portfolio_gate if isinstance(portfolio_gate, dict) else {}
    gates = {
        "research": dict(research_gate) if isinstance(research_gate, dict) else {},
        "portfolio": dict(pg) if pg else {},
        "trimmed_from": pg.get("trimmed_from"),
        "binding": (pg.get("trim") or {}).get("binding") if isinstance(pg.get("trim"), dict) else pg.get("binding"),
    }
    if gates_extra:
        gates.update(gates_extra)

    payload: dict[str, Any] = {
        "version": PACKET_VERSION,
        "decision_id": did,
        "ts_ist": day,
        "symbol": symbol,
        "action": act,
        "portfolio_key": portfolio_key or "unknown",
        # LI.1a — laboratory_id aliases portfolio_key (Laboratory ⊃ ledger)
        "laboratory_id": portfolio_key or "unknown",
        "mission_id": str(mission_id) if mission_id else None,
        "strategy_tag": tag,
        "setup_tag": setup_tag,
        # LI.4 — experiment lane (default keeps legacy packets gated together)
        "experiment_id": exp_id,
        # LI.5b — scientific hypothesis link (distinct from prior_thesis_id)
        "hypothesis_id": str(hypothesis_id) if hypothesis_id else None,
        "parent_decision_id": parent_decision_id,
        "derived_from_lesson_ids": list(derived_from_lesson_ids or []),
        "prior_thesis_id": prior_thesis_id,
        "engine_decision_id": str(engine_decision_id) if engine_decision_id else None,
        "fill_trade_id": str(fill_trade_id) if fill_trade_id else None,
        "market_snapshot": snap,
        "prices": dict(prices or {}),
        "feature_contributions": contrib,
        "confidence_breakdown": conf,
        "reasons_for": [str(r) for r in (reasons_for or []) if r],
        "reasons_against": [str(r) for r in (reasons_against or []) if r],
        "evidence_refs": list(evidence_refs or []),
        "observation_ids": list(observation_ids or []),
        "unknowns": unknowns,
        "expected": dict(expected)
        if isinstance(expected, dict)
        else {
            "holding_horizon": "position",
            "return_band": None,
            "thesis_id": prior_thesis_id,
            "falsifiers": [],
        },
        "plan_link": dict(plan_link)
        if isinstance(plan_link, dict)
        else {"rank": None, "suggested_notional": None, "in_daily_plan": False},
        "gates": gates,
    }
    meta: dict[str, Any] = {"completeness": completeness_score(payload)}
    flags = list(process_flags) if process_flags else None
    if flags is None and process_context is not None:
        try:
            from atlas.investment.process_proxies import detect_packet_flags

            # Attach score + meta so overconfidence / journal gates see real completeness
            tmp = dict(payload)
            tmp["meta"] = dict(meta)
            if isinstance(investment_score, dict):
                tmp["investment_score"] = investment_score
            flags = detect_packet_flags(tmp, **dict(process_context))
        except Exception:  # noqa: BLE001
            flags = []
    if flags:
        meta["process_flags"] = flags
    if isinstance(meta_extra, dict):
        for k, v in meta_extra.items():
            if v is not None and k not in meta:
                meta[k] = v
    payload["meta"] = meta
    return payload


def packet_row_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": payload["decision_id"],
        "ts_ist": payload["ts_ist"],
        "symbol": payload["symbol"],
        "action": payload["action"],
        "portfolio_key": payload["portfolio_key"],
        "mission_id": payload.get("mission_id"),
        "strategy_tag": payload["strategy_tag"],
        "setup_tag": payload.get("setup_tag"),
        "parent_decision_id": payload.get("parent_decision_id"),
        "prior_thesis_id": payload.get("prior_thesis_id"),
        "engine_decision_id": payload.get("engine_decision_id"),
        "fill_trade_id": payload.get("fill_trade_id"),
        "payload": payload,
        "payload_version": payload.get("version") or PACKET_VERSION,
    }


def summarize_packet(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": payload.get("decision_id"),
        "ts_ist": payload.get("ts_ist"),
        "symbol": payload.get("symbol"),
        "action": payload.get("action"),
        "strategy_tag": payload.get("strategy_tag"),
        "portfolio_key": payload.get("portfolio_key"),
        "completeness": (payload.get("meta") or {}).get("completeness"),
        "reasons_for": (payload.get("reasons_for") or [])[:3],
        "unknowns": payload.get("unknowns") or [],
        "mark": (payload.get("prices") or {}).get("mark"),
    }


def write_mirrors(data_dir: str | Path | None, payload: dict[str, Any]) -> dict[str, str]:
    """Best-effort JSON mirrors. Never raises to caller after logging."""
    if not data_dir:
        return {}
    paths: dict[str, str] = {}
    try:
        by_id = mirror_by_id_path(data_dir, str(payload["decision_id"]))
        by_id.parent.mkdir(parents=True, exist_ok=True)
        by_id.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        paths["by_id"] = str(by_id)
        day = mirror_day_path(
            data_dir, str(payload.get("portfolio_key") or "unknown"), str(payload["ts_ist"])
        )
        day.parent.mkdir(parents=True, exist_ok=True)
        with day.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
        paths["by_day"] = str(day)
    except Exception:  # noqa: BLE001
        _log.warning("decision packet mirror failed", exc_info=True)
    return paths


def _load_json_packet(data_dir: str | Path, decision_id: str) -> dict[str, Any] | None:
    path = mirror_by_id_path(data_dir, decision_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _load_day_jsonl(
    data_dir: str | Path, *, portfolio_key: str, ts_ist: str
) -> list[dict[str, Any]]:
    path = mirror_day_path(data_dir, portfolio_key, ts_ist)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
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
                out.append(doc)
    except Exception:  # noqa: BLE001
        _log.debug("day jsonl read failed: %s", path, exc_info=True)
    return out


class DecisionPacketStore:
    """Hybrid packet store: Postgres when available, JSON always mirrored."""

    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        repo: Any | None = None,
        timeline: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data_dir = str(data_dir) if data_dir else None
        self._repo = repo
        self._timeline = timeline
        self._logger = logger or _log

    @property
    def data_dir(self) -> str | None:
        return self._data_dir

    def bind_timeline(self, timeline: Any) -> None:
        self._timeline = timeline

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist packet. Primary = repo insert when present; else JSON-only."""
        if payload.get("version") != PACKET_VERSION:
            raise ValueError(f"unsupported packet version {payload.get('version')!r}")
        if payload.get("action") not in ALLOWED_ACTIONS:
            raise ValueError(f"invalid action {payload.get('action')!r}")
        row = packet_row_from_payload(payload)
        stored: dict[str, Any] | None = None
        if self._repo is not None:
            try:
                stored = self._repo.insert(row)
            except Exception:  # noqa: BLE001
                self._logger.warning(
                    "decision packet postgres insert failed; mirroring only",
                    exc_info=True,
                )
                stored = None
        mirrors = write_mirrors(self._data_dir, payload)
        if stored is None and not mirrors and not self._data_dir:
            # Last resort: return payload without durability (tests may still assert shape)
            self._logger.debug("decision packet saved without durable backend")
        timeline_meta: dict[str, Any] = {}
        if self._timeline is not None:
            try:
                timeline_meta = self._timeline.on_packet_saved(payload) or {}
            except Exception:  # noqa: BLE001
                self._logger.debug("DI.2 timeline hook failed", exc_info=True)
        return {
            "packet": payload,
            "row": stored,
            "mirrors": mirrors,
            "version": PACKET_VERSION,
            "mirror_path": mirrors.get("by_id"),
            "timeline": timeline_meta,
        }

    def record(self, **kwargs: Any) -> dict[str, Any]:
        return self.save(build_packet(**kwargs))

    def get(self, decision_id: str) -> dict[str, Any] | None:
        if self._repo is not None:
            try:
                row = self._repo.get(decision_id)
                if row and isinstance(row.get("payload"), dict):
                    return dict(row["payload"])
            except Exception:  # noqa: BLE001
                self._logger.debug("packet get via repo failed", exc_info=True)
        if self._data_dir:
            return _load_json_packet(self._data_dir, str(decision_id))
        return None

    def list_day(
        self,
        *,
        portfolio_key: str,
        ts_ist: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        day = ts_ist or ist_today()
        items: list[dict[str, Any]] = []
        if self._repo is not None:
            try:
                rows = self._repo.list_day(
                    portfolio_key=portfolio_key, ts_ist=day, limit=limit
                )
                for row in rows:
                    if isinstance(row.get("payload"), dict):
                        items.append(dict(row["payload"]))
                if items:
                    return items[:limit]
            except Exception:  # noqa: BLE001
                self._logger.debug("list_day via repo failed", exc_info=True)
        if self._data_dir:
            items = _load_day_jsonl(
                self._data_dir, portfolio_key=portfolio_key, ts_ist=day
            )
            # jsonl is append order; newest last → reverse
            items = list(reversed(items))
        return items[:limit]

    def list_symbol(
        self,
        *,
        symbol: str,
        limit: int = 20,
        portfolio_key: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._repo is not None:
            try:
                rows = self._repo.list_symbol(
                    symbol=symbol, limit=limit, portfolio_key=portfolio_key
                )
                out = [
                    dict(r["payload"])
                    for r in rows
                    if isinstance(r.get("payload"), dict)
                ]
                if out:
                    return out
            except Exception:  # noqa: BLE001
                self._logger.debug("list_symbol via repo failed", exc_info=True)
        # JSON fallback: scan by_id (bounded)
        if not self._data_dir:
            return []
        root = mirror_root(self._data_dir) / "by_id"
        if not root.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(doc, dict):
                continue
            if doc.get("symbol") != symbol:
                continue
            if portfolio_key and doc.get("portfolio_key") != portfolio_key:
                continue
            found.append(doc)
            if len(found) >= limit:
                break
        return found

    def symbols_with_strategy(
        self,
        *,
        portfolio_key: str,
        ts_ist: str,
        strategy_tag: str,
    ) -> set[str]:
        if self._repo is not None:
            try:
                return self._repo.list_day_strategy_symbols(
                    portfolio_key=portfolio_key,
                    ts_ist=ts_ist,
                    strategy_tag=strategy_tag,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("symbols_with_strategy repo failed", exc_info=True)
        day = self.list_day(portfolio_key=portfolio_key, ts_ist=ts_ist, limit=500)
        return {
            str(p["symbol"])
            for p in day
            if p.get("strategy_tag") == strategy_tag and p.get("symbol")
        }


def infer_strategy_tag(
    *,
    action_line: str | None = None,
    kind: str | None = None,
    as_alt: bool = False,
    research_blocked: bool = False,
    portfolio_blocked: bool = False,
    policy_blocked: bool = False,
    pack_blocked: bool = False,
    gap: bool = False,
) -> str:
    line = (action_line or "").lower()
    if as_alt or "[alt]" in line:
        return "next_alternative"
    if research_blocked or "research_hold" in line:
        return "research_forced_hold"
    if portfolio_blocked or "portfolio_hold" in line:
        return "portfolio_trim"
    if policy_blocked or "policy_block" in line:
        return "policy_block"
    if pack_blocked or "pack_block" in line:
        return "pack_block"
    if gap or "gap (" in line:
        return "capability_gap"
    if "fill_rejected" in line:
        return "fill_rejected"
    if kind in ("buy", "sell", "reduce"):
        return "sma_cross_rsi"
    return "engine_hold"


def emit_plan_watch_packets(
    store: DecisionPacketStore,
    *,
    daily_plan: dict[str, Any],
    portfolio_key: str,
    mission_id: str | None = None,
    ts_ist: str | None = None,
    session: str = "nse_equity",
) -> list[dict[str, Any]]:
    """Idempotent once-per-day plan_watch packets for daily plan candidates."""
    day = ts_ist or str(daily_plan.get("as_of") or ist_today())
    pk = portfolio_key or str(daily_plan.get("portfolio_key") or "india_equity_learner")
    already = store.symbols_with_strategy(
        portfolio_key=pk, ts_ist=day, strategy_tag="plan_watch"
    )
    already |= store.symbols_with_strategy(
        portfolio_key=pk, ts_ist=day, strategy_tag="plan_hold"
    )
    written: list[dict[str, Any]] = []
    for cand in daily_plan.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        symbol = str(cand.get("symbol") or "").strip()
        if not symbol or symbol in already:
            continue
        why = str(cand.get("why") or "").strip()
        reasons = [why] if why else [f"daily plan candidate rank={cand.get('rank')}"]
        for ex in (cand.get("explanations") or [])[:4]:
            if isinstance(ex, dict) and ex.get("text"):
                reasons.append(str(ex.get("text")))
            elif ex:
                reasons.append(str(ex))
        result = store.record(
            action="watch",
            symbol=symbol,
            portfolio_key=pk,
            strategy_tag="plan_watch",
            ts_ist=day,
            mission_id=mission_id,
            market_snapshot=stamp_regime_on_snapshot(
                empty_market_snapshot(
                    session=session, sector=str(cand.get("sector") or "") or None
                )
            ),
            prices={"mark": cand.get("mark") or cand.get("price")},
            reasons_for=reasons,
            plan_link={
                "rank": cand.get("rank"),
                "suggested_notional": cand.get("suggested_notional"),
                "in_daily_plan": True,
            },
            expected={
                "holding_horizon": "position",
                "return_band": None,
                "thesis_id": None,
                "falsifiers": [],
            },
        )
        written.append(result["packet"])
        already.add(symbol)
    return written


def format_decisions_section(packets: list[dict[str, Any]] | None) -> list[str]:
    """Evening-mail lines for Decisions today.

    OI-RLD0 / D3: collapse routine HOLD spam into a dominant-state summary;
    list buy/sell (and other material) packets individually.
    """
    packets = [p for p in (packets or []) if isinstance(p, dict)]
    lines = ["", f"Decisions today ({len(packets)} evaluations):"]
    if not packets:
        lines.append("  (no decision packets recorded)")
        return lines

    try:
        from atlas.investment.experience_integrity import (
            is_routine_hold,
            material_decision_state,
        )
    except Exception:  # noqa: BLE001
        is_routine_hold = None  # type: ignore[assignment]
        material_decision_state = None  # type: ignore[assignment]

    material: list[dict[str, Any]] = []
    routine: list[dict[str, Any]] = []
    for p in packets:
        act = str(p.get("action") or "").lower()
        tag = str(p.get("strategy_tag") or "")
        if act in {"buy", "sell"}:
            material.append(p)
        elif is_routine_hold is not None and is_routine_hold(
            action=act, strategy_tag=tag
        ):
            routine.append(p)
        else:
            material.append(p)

    if routine and material_decision_state is not None:
        from collections import Counter

        state_counts = Counter(material_decision_state(p) for p in routine)
        unique_states = len(state_counts)
        lines.append(
            f"  Unique routine states: {unique_states} · "
            f"routine evaluations: {len(routine)} · "
            f"material buy/sell listed: {len(material)}"
        )
        # Dominant state
        dominant, n_dom = state_counts.most_common(1)[0]
        parts = dominant.split("|")
        # hold|tag|reason
        if len(parts) >= 3:
            action_s, tag_s, reason_s = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            action_s, tag_s, reason_s = parts[0], parts[1], "—"
        else:
            action_s, tag_s, reason_s = dominant, "—", "—"
        lines.append("  Dominant state:")
        lines.append(
            f"    {(action_s or '?').upper()} / {tag_s or '—'} / {reason_s or '—'}"
        )
        lines.append(f"    Occurrences: {n_dom}")
        # Affected symbols (sample)
        by_state = [p for p in routine if material_decision_state(p) == dominant]
        syms: list[str] = []
        seen: set[str] = set()
        for p in by_state:
            s = str(p.get("symbol") or "").upper()
            if s and s not in seen:
                seen.add(s)
                syms.append(s)
            if len(syms) >= 8:
                break
        if syms:
            lines.append(f"    Affected (sample): {', '.join(syms)}")
        if unique_states > 1:
            lines.append("  Other routine states:")
            for st, n in state_counts.most_common(5)[1:]:
                lines.append(f"    · {st} ×{n}")
    elif routine:
        lines.append(f"  Routine HOLD/switch_blocked evaluations: {len(routine)}")

    show = material[:40]
    if show:
        lines.append("  Material decisions:")
    for p in show:
        reasons = p.get("reasons_for") or []
        why = f" — {reasons[0]}" if reasons else ""
        lines.append(
            f"  · {(p.get('action') or '?').upper()} {p.get('symbol')} "
            f"[{p.get('strategy_tag') or '—'}] "
            f"id={str(p.get('decision_id') or '')[:8]}…{why}"
        )
        unknowns = p.get("unknowns") or []
        if unknowns:
            lines.append(f"     unknowns: {', '.join(str(u) for u in unknowns[:6])}")
    if not material and not routine:
        lines.append("  (no classified packets)")
    elif not material and routine:
        lines.append("  (no buy/sell packets — routine checks only)")
    return lines
