"""LOOP0 L2 — unique-state decision consult (advice-only).

New decision state → retrieve Beliefs + WSO + Experiences → persist.
Same state / evidence / thesis → reuse. No LLM. Phase 5 stays frozen.

``mark_only`` / session-clock tags are not decision states.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

VERSION = "loop0.l2.decision_consult.v1"
STORE_REL = Path("market") / "decision_consults"
INFLUENCE = "advice_only"

_log = logging.getLogger("atlas.reasoning.decision_consult")

_SKIP_TAGS = (
    "mark_only",
    "session_closed",
    "yahoo_cooldown",
    "empty_live_feed",
    "empty_feed",
    "feed_error",
    "feed_exhausted",
)

_SKIP_ACTIONS = frozenset({"", "skip", "noop"})


def should_consult(*, action: str, strategy_tag: str | None = None) -> bool:
    a = str(action or "").strip().lower()
    t = str(strategy_tag or "").strip().lower()
    if a in _SKIP_ACTIONS or a not in {"buy", "sell", "hold", "reduce", "watch"}:
        return False
    return not any(noise in t for noise in _SKIP_TAGS)


def ranking_bucket(rank: Any) -> str:
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return "unranked"
    if r <= 5:
        return "top5"
    if r <= 15:
        return "mid"
    return "tail"


def cash_band(cash_pct: Any) -> str:
    try:
        p = float(cash_pct)
    except (TypeError, ValueError):
        return "na"
    if p > 1.0:
        p = p / 100.0
    band = int(max(0.0, min(1.0, p)) * 10)
    return f"c{band}"


def book_fingerprint(held_symbols: list[str] | None, cash_pct: Any = None) -> str:
    names = ",".join(sorted({str(s).strip().upper() for s in (held_symbols or []) if s}))
    return f"{names}|{cash_band(cash_pct)}"


def regime_bucket(
    indicators: dict[str, Any] | None = None,
    regime_tags: list[str] | None = None,
) -> str:
    tags = [str(t).strip().lower() for t in (regime_tags or []) if t]
    tag_s = ",".join(sorted(tags)[:4]) if tags else ""
    ind = indicators if isinstance(indicators, dict) else {}
    rsi = ind.get("rsi14")
    if rsi is None:
        rsi = ind.get("rsi")
    try:
        rv = float(rsi) if rsi is not None else None
    except (TypeError, ValueError):
        rv = None
    if rv is None:
        rsi_b = "rsi_na"
    elif rv >= 70:
        rsi_b = "rsi_ob"
    elif rv <= 30:
        rsi_b = "rsi_os"
    else:
        rsi_b = "rsi_mid"
    above = ind.get("above_sma20")
    if above is True:
        sma_b = "sma_above"
    elif above is False:
        sma_b = "sma_below"
    else:
        sma_b = "sma_na"
    return f"{sma_b}_{rsi_b}|{tag_s}"


def evidence_fingerprint(
    *,
    research_ok: Any = None,
    portfolio_ok: Any = None,
    pe_present: bool = False,
    plc_reason: str = "",
    er_completeness: Any = None,
) -> str:
    try:
        er_b = f"er{int(float(er_completeness) * 5)}"
    except (TypeError, ValueError):
        er_b = "er_na"
    plc = str(plc_reason or "").split(":")[0].strip().lower()[:40]
    return (
        f"rg{1 if research_ok else 0}"
        f"|pg{1 if portfolio_ok else 0}"
        f"|pe{1 if pe_present else 0}"
        f"|{plc or 'nopc'}|{er_b}"
    )


def decision_state_key(
    *,
    laboratory_id: str,
    symbol: str,
    ist_day: str,
    action_kind: str,
    strategy_tag: str = "",
    thesis_id: str = "",
    ranking_bucket_s: str = "unranked",
    book_fp: str = "",
    evidence_fp: str = "",
    regime: str = "",
) -> str:
    payload = {
        "lab": str(laboratory_id or "").strip().lower(),
        "symbol": str(symbol or "").strip().upper(),
        "day": str(ist_day or ""),
        "action": str(action_kind or "").strip().lower(),
        "tag": str(strategy_tag or "").strip().lower(),
        "thesis": str(thesis_id or "").strip(),
        "rank": str(ranking_bucket_s or "unranked"),
        "book": str(book_fp or ""),
        "evidence": str(evidence_fp or ""),
        "regime": str(regime or ""),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return digest


def _cache_path(data_dir: str | Path | None, laboratory_id: str, ist_day: str) -> Path | None:
    if not data_dir:
        return None
    lab = "".join(c if c.isalnum() or c in "-_" else "_" for c in (laboratory_id or "lab"))
    day = "".join(c if c.isalnum() or c in "-_" else "_" for c in (ist_day or "day"))
    return Path(data_dir) / STORE_REL / lab / f"{day}.json"


def load_day_cache(
    data_dir: str | Path | None, laboratory_id: str, ist_day: str
) -> dict[str, Any]:
    path = _cache_path(data_dir, laboratory_id, ist_day)
    if path is None or not path.is_file():
        return {"version": VERSION, "states": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": VERSION, "states": {}}
    if not isinstance(doc, dict):
        return {"version": VERSION, "states": {}}
    states = doc.get("states")
    if not isinstance(states, dict):
        doc["states"] = {}
    return doc


def save_day_cache(
    data_dir: str | Path | None,
    laboratory_id: str,
    ist_day: str,
    doc: dict[str, Any],
) -> None:
    path = _cache_path(data_dir, laboratory_id, ist_day)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        _log.debug("decision consult cache write failed: %s", path, exc_info=True)


def _belief_slice(beliefs: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in beliefs[:limit]:
        if not isinstance(b, dict):
            continue
        out.append(
            {
                "id": b.get("id"),
                "belief_key": b.get("belief_key"),
                "domain": b.get("domain"),
                "status": b.get("status"),
                "statement": str(b.get("statement") or "")[:240],
                "confidence": b.get("effective_confidence", b.get("confidence")),
            }
        )
    return out


def _wso_slice(wso: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(wso, dict):
        return None
    return {
        "symbol": wso.get("symbol"),
        "unknowns": list(wso.get("unknowns") or [])[:8],
        "uncertainty": dict(wso.get("uncertainty") or {}) if isinstance(wso.get("uncertainty"), dict) else {},
        "has_thesis": bool(wso.get("thesis") or wso.get("working_thesis")),
    }


def _experience_slice(rows: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in rows[:limit]:
        row = raw if isinstance(raw, dict) else {}
        journal = row.get("journal") if isinstance(row.get("journal"), dict) else {}
        lesson = str(journal.get("lesson") or row.get("lesson") or row.get("title") or "")[:200]
        out.append(
            {
                "id": row.get("id") or journal.get("id"),
                "lesson": lesson,
            }
        )
    return out


def empty_belief_context(
    *,
    state_key: str,
    query: str,
    note: str,
    reused: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = {
        "version": VERSION,
        "state_key": state_key,
        "reused": bool(reused),
        "purpose": "decide",
        "influence": INFLUENCE,
        "beliefs_found": 0,
        "note": note,
        "belief_ids": [],
        "beliefs": [],
        "wso": None,
        "experiences": [],
        "query": query,
    }
    if extra:
        ctx.update(extra)
    return ctx


def consult_unique_decision(
    reasoning: Any | None,
    *,
    symbol: str,
    laboratory_id: str,
    action_kind: str,
    strategy_tag: str = "",
    ist_day: str,
    cache: dict[str, Any] | None = None,
    data_dir: str | Path | None = None,
    experience_os: Any | None = None,
    thesis_id: str = "",
    rank: Any = None,
    book_fp: str = "",
    evidence_fp: str = "",
    regime: str = "",
    sector: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    """Retrieve worldview for one unique decision state. Advice-only. No LLM."""
    query = " ".join(
        p
        for p in (
            str(symbol or "").strip(),
            str(sector or "").strip(),
            "market",
            str(thesis_id or "").strip(),
            str(strategy_tag or "").replace("_", " "),
        )
        if p
    )
    if not should_consult(action=action_kind, strategy_tag=strategy_tag):
        return empty_belief_context(
            state_key="",
            query=query,
            note="Not a unique decision state (clock/feed noise).",
            extra={"skipped": True, "skip_reason": "not_decision_state"},
        )

    key = decision_state_key(
        laboratory_id=laboratory_id,
        symbol=symbol,
        ist_day=ist_day,
        action_kind=action_kind,
        strategy_tag=strategy_tag,
        thesis_id=thesis_id,
        ranking_bucket_s=ranking_bucket(rank),
        book_fp=book_fp,
        evidence_fp=evidence_fp,
        regime=regime,
    )
    doc = cache if isinstance(cache, dict) else None
    if doc is None:
        doc = load_day_cache(data_dir, laboratory_id, ist_day)
    states = doc.setdefault("states", {})
    if not isinstance(states, dict):
        states = {}
        doc["states"] = states
    prior = states.get(key)
    if isinstance(prior, dict) and prior.get("belief_context"):
        ctx = dict(prior["belief_context"])
        ctx["reused"] = True
        ctx["state_key"] = key
        prior["reuse_count"] = int(prior.get("reuse_count") or 0) + 1
        states[key] = prior
        return ctx

    if reasoning is None:
        return empty_belief_context(
            state_key=key,
            query=query,
            note="ReasoningService not bound — worldview not consulted.",
            extra={"skipped": True, "skip_reason": "no_reasoning"},
        )

    beliefs: list[dict[str, Any]] = []
    try:
        consulted = reasoning.consult(
            domain="market",
            query=query,
            limit=8,
            purpose="decide",
            record_mode="once",
        )
        beliefs = list(consulted.get("beliefs") or [])
    except TypeError:
        # Older façade without record_mode.
        try:
            consulted = reasoning.consult(
                domain="market", query=query, limit=8, purpose="decide"
            )
            beliefs = list(consulted.get("beliefs") or [])
        except Exception:  # noqa: BLE001
            _log.debug("decision consult beliefs failed", exc_info=True)
    except Exception:  # noqa: BLE001
        _log.debug("decision consult beliefs failed", exc_info=True)

    wso = None
    if data_dir:
        try:
            from atlas.investment.world_state import load_wso

            wso = load_wso(data_dir, laboratory_id, symbol)
        except Exception:  # noqa: BLE001
            _log.debug("WSO load failed", exc_info=True)

    experiences: list[Any] = []
    if experience_os is not None:
        try:
            experiences = list(experience_os.recall(query, limit=5) or [])
        except Exception:  # noqa: BLE001
            _log.debug("experience recall failed", exc_info=True)

    sliced = _belief_slice(beliefs)
    n = len(sliced)
    if n == 0:
        note = "No relevant belief found."
    else:
        note = f"{n} belief(s) consulted (advice-only; no size/side change)."
    ctx = {
        "version": VERSION,
        "state_key": key,
        "reused": False,
        "purpose": "decide",
        "influence": INFLUENCE,
        "beliefs_found": n,
        "note": note,
        "belief_ids": [b.get("id") for b in sliced if b.get("id")],
        "beliefs": sliced,
        "wso": _wso_slice(wso),
        "experiences": _experience_slice(experiences),
        "query": query,
    }
    states[key] = {"belief_context": ctx, "reuse_count": 0}
    if persist:
        save_day_cache(data_dir, laboratory_id, ist_day, doc)
    return ctx
