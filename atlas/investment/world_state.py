"""BRE.1 — World State Objects (Represent) + Uncertainty Ledger shells.

Deterministic store for persistent mental models. Semantic belief *text* is
authored later by the LLM (BRE.2 / §1.7); this slice creates shells, unknowns,
uncertainty dimensions, revision log, and evening honesty sections.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

VERSION = "bre1.wso.v1"
STORE_REL = Path("investment") / "world_state"

_log = logging.getLogger("atlas.investment.world_state")

UNCERTAINTY_KEYS = (
    "data",
    "model",
    "execution",
    "macro",
    "governance",
)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def store_root(data_dir: str | Path | None) -> Path | None:
    if not data_dir:
        return None
    return Path(data_dir) / STORE_REL


def lab_dir(data_dir: str | Path | None, laboratory_id: str) -> Path | None:
    root = store_root(data_dir)
    if root is None:
        return None
    lab = (laboratory_id or "market_intelligence").strip() or "market_intelligence"
    return root / lab


def symbol_path(
    data_dir: str | Path | None, laboratory_id: str, symbol: str
) -> Path | None:
    d = lab_dir(data_dir, laboratory_id)
    if d is None:
        return None
    from atlas.investment.symbol_aliases import resolve_yahoo_symbol

    canon = resolve_yahoo_symbol(symbol).canonical or symbol
    safe = canon.replace("/", "_").replace("\\", "_")
    return d / f"{safe}.json"


def empty_uncertainty() -> dict[str, str]:
    return {k: "unknown" for k in UNCERTAINTY_KEYS}


def empty_wso(
    *,
    symbol: str,
    laboratory_id: str,
    domain: str = "market",
) -> dict[str, Any]:
    from atlas.investment.symbol_aliases import resolve_yahoo_symbol

    res = resolve_yahoo_symbol(symbol)
    return {
        "version": VERSION,
        "domain": domain,
        "laboratory_id": laboratory_id,
        "symbol": res.canonical or symbol,
        "requested_symbol": symbol,
        "aliased_from": symbol if res.aliased else None,
        "business_model": [],
        "thesis_text": "",  # LLM-authored later (BRE.2)
        "thesis_strength": None,  # 0–10 when known
        "beliefs": {},  # name → {confidence, note} — semantic notes LLM-only later
        "falsifiers": [],
        "unknowns": [],
        "uncertainty": empty_uncertainty(),
        "evidence_ids": [],
        "decision_packet_ids": [],
        "revision_history": [],
        "last_revision_at": None,
        "status": "insufficient_evidence",
        "created_at": _utc(),
        "updated_at": _utc(),
    }


def load_wso(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbol: str,
) -> dict[str, Any] | None:
    path = symbol_path(data_dir, laboratory_id, symbol)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save_wso(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    lab = str(doc.get("laboratory_id") or "market_intelligence")
    sym = str(doc.get("symbol") or "")
    path = symbol_path(data_dir, lab, sym)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(doc)
    doc["updated_at"] = _utc()
    doc["version"] = VERSION
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ensure_wso(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbol: str,
    *,
    unknowns: list[str] | None = None,
    data_uncertainty: str | None = None,
) -> dict[str, Any]:
    """Load or create a WSO shell. Does not invent semantic thesis text."""
    existing = load_wso(data_dir, laboratory_id, symbol)
    if existing is None:
        doc = empty_wso(symbol=symbol, laboratory_id=laboratory_id)
    else:
        doc = dict(existing)
    if unknowns:
        cur = [str(u) for u in (doc.get("unknowns") or []) if u]
        for u in unknowns:
            u = str(u).strip()
            if u and u not in cur:
                cur.append(u)
        doc["unknowns"] = cur[:40]
    unc = dict(doc.get("uncertainty") or empty_uncertainty())
    for k in UNCERTAINTY_KEYS:
        unc.setdefault(k, "unknown")
    if data_uncertainty in {"high", "medium", "low", "unknown"}:
        unc["data"] = data_uncertainty
    doc["uncertainty"] = unc
    save_wso(data_dir, doc)
    return doc


def append_revision(
    doc: dict[str, Any],
    *,
    status: str,
    reason: str,
    evidence_delta: dict[str, Any] | None = None,
    llm: bool = False,
) -> dict[str, Any]:
    """Append-only revision record. llm=False ⇒ structural / no-evidence only."""
    hist = list(doc.get("revision_history") or [])
    rec = {
        "at": _utc(),
        "status": status,
        "reason": reason[:500],
        "evidence_delta": evidence_delta or {},
        "llm": bool(llm),
    }
    hist.append(rec)
    doc["revision_history"] = hist[-200:]
    doc["last_revision_at"] = rec["at"]
    doc["status"] = status
    return doc


def evidence_delta_counts(
    *,
    bars_n: int = 0,
    fundamentals_n: int = 0,
    news_n: int = 0,
    policy_n: int = 0,
    research_n: int = 0,
    seed_news_n: int = 0,
) -> dict[str, Any]:
    return {
        "bars": int(bars_n),
        "fundamentals": int(fundamentals_n),
        "news": int(news_n),
        "policy": int(policy_n),
        "research": int(research_n),
        "seed_news_ignored": int(seed_news_n),
        "material": bool(
            bars_n or fundamentals_n or news_n or policy_n or research_n
        ),
    }


def format_mind_change_section(
    wsos: list[dict[str, Any]] | None,
) -> list[str]:
    """Evening J3: belief changed? why? evidence? falsifier? (honest idle if none)."""
    lines = ["", "--- Belief / mind-change (WSO) ---"]
    lines.append(
        "J3 answers per open book: belief_changed · why · evidence · falsifier"
    )
    rows = [w for w in (wsos or []) if isinstance(w, dict)]
    if not rows:
        lines.append("No World State Objects for open books yet (BRE.1 shells pending).")
        lines.append("No beliefs changed today.")
        return lines
    changed = 0
    for w in rows:
        sym = str(w.get("symbol") or "?")
        status = str(w.get("status") or "unknown")
        hist = list(w.get("revision_history") or [])
        last = hist[-1] if hist else None
        last = last if isinstance(last, dict) else {}
        reason = str(last.get("reason") or "")
        material = status in {"strengthened", "weakened", "falsified"} and bool(last)
        unreviewed = status in {"unreviewed", "UNREVIEWED"} or "LLM_UNAVAILABLE" in reason
        if material:
            changed += 1
        evid = last.get("evidence_ids") or last.get("evidence_delta") or {}
        if isinstance(evid, dict):
            if evid.get("structural"):
                evid_s = "none — structural shell / idle"
            else:
                parts = [
                    f"{k}={v}"
                    for k, v in evid.items()
                    if v not in (None, "", [], {}, 0, False)
                ]
                evid_s = ", ".join(parts[:6]) if parts else "none — idle"
        elif isinstance(evid, list):
            evid_s = ", ".join(str(x) for x in evid[:6]) if evid else "none — idle"
        else:
            evid_s = str(evid)[:120] if evid else "none — idle"
        fals = list(w.get("falsifiers") or [])
        if not fals and isinstance(w.get("beliefs"), list):
            for b in w.get("beliefs") or []:
                if isinstance(b, dict) and b.get("falsifiers"):
                    fals.extend(list(b.get("falsifiers") or []))
        fals_s = "; ".join(str(x)[:80] for x in fals[:3]) if fals else "none recorded"
        why = reason[:160] if reason else (
            f"status={status}; no material revision"
            if not material
            else f"status={status}"
        )
        unk_n = len(w.get("unknowns") or [])
        lines.append(
            f"{sym}: belief_changed={'yes' if material else 'no'} "
            + ("UNREVIEWED " if unreviewed else "")
            + f"({status}"
            + (f"; {unk_n} unknowns" if unk_n and not material else "")
            + ")"
        )
        lines.append(f"  why: {why}")
        lines.append(f"  evidence: {evid_s}")
        lines.append(f"  falsifier: {fals_s}")
        if material and reason:
            # keep legacy one-liner for scanners that grep status —
            lines.append(f"  summary: {status} — {reason[:120]}")
    if changed == 0:
        lines.append("No beliefs changed today.")
    return lines


def format_evidence_delta_section(delta: dict[str, Any] | None) -> list[str]:
    """Evening: what new information entered Atlas today."""
    d = delta if isinstance(delta, dict) else {}
    lines = ["", "--- Evidence delta (today) ---"]
    lines.append(
        "bars={bars} · fundamentals={fundamentals} · news={news} · "
        "policy={policy} · research={research}".format(
            bars=int(d.get("bars") or 0),
            fundamentals=int(d.get("fundamentals") or 0),
            news=int(d.get("news") or 0),
            policy=int(d.get("policy") or 0),
            research=int(d.get("research") or 0),
        )
    )
    seed_n = int(d.get("seed_news_ignored") or 0)
    if seed_n:
        lines.append(
            f"seed_news_ignored={seed_n} (E0 — monitoring stubs are not evidence)"
        )
    if not d.get("material"):
        lines.append(
            "No material evidence delta — belief revision not expected (honest idle)."
        )
    return lines


def sync_open_book_wsos(
    data_dir: str | Path | None,
    laboratory_id: str,
    symbols: list[str],
    *,
    missing_fundamentals: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Ensure WSO shells for open-book symbols; set data uncertainty from gaps."""
    out: list[dict[str, Any]] = []
    miss = missing_fundamentals or {}
    for sym in symbols:
        gaps = list(miss.get(sym) or miss.get(str(sym).upper()) or [])
        unknowns = list(gaps)
        data_u = "high" if gaps else "unknown"
        if not gaps:
            # Still may lack news — curiosity fills later
            pass
        doc = ensure_wso(
            data_dir,
            laboratory_id,
            sym,
            unknowns=unknowns or None,
            data_uncertainty=data_u if gaps else None,
        )
        # Structural day stamp when no revision yet
        if not doc.get("revision_history"):
            append_revision(
                doc,
                status="insufficient_evidence" if gaps else "unchanged",
                reason=(
                    "WSO shell ensured; semantic beliefs await LLM (BRE.2)"
                    if not gaps
                    else f"data gaps: {', '.join(gaps[:6])}"
                ),
                evidence_delta={"structural": True},
                llm=False,
            )
            save_wso(data_dir, doc)
        out.append(doc)
    return out


# --- BRE.5 — lab-level global WSO (_GLOBAL.json; not a ticker) ---------------

GLOBAL_WSO_NAME = "_GLOBAL"


def global_wso_path(data_dir: str | Path | None, laboratory_id: str) -> Path | None:
    d = lab_dir(data_dir, laboratory_id)
    if d is None:
        return None
    return d / f"{GLOBAL_WSO_NAME}.json"


def empty_global_wso(
    *,
    laboratory_id: str,
    domain: str = "market",
) -> dict[str, Any]:
    """Lab-level World State — cross-symbol patterns (BRE.5)."""
    return {
        "version": VERSION,
        "kind": "global",
        "domain": domain,
        "laboratory_id": laboratory_id,
        "symbol": GLOBAL_WSO_NAME,
        "thesis_text": "",
        "beliefs": {},
        "patterns": [],
        "linked_symbols": [],
        "mentor_digest": None,
        "falsifiers": [],
        "unknowns": [],
        "uncertainty": empty_uncertainty(),
        "evidence_ids": [],
        "decision_packet_ids": [],
        "revision_history": [],
        "last_revision_at": None,
        "status": "insufficient_evidence",
        "created_at": _utc(),
        "updated_at": _utc(),
    }


def load_global_wso(
    data_dir: str | Path | None, laboratory_id: str
) -> dict[str, Any] | None:
    path = global_wso_path(data_dir, laboratory_id)
    if path is None or not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def save_global_wso(data_dir: str | Path | None, doc: dict[str, Any]) -> Path | None:
    lab = str(doc.get("laboratory_id") or "market_intelligence")
    path = global_wso_path(data_dir, lab)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(doc)
    out["updated_at"] = _utc()
    out["version"] = VERSION
    out["kind"] = "global"
    out["symbol"] = GLOBAL_WSO_NAME
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ensure_global_wso(
    data_dir: str | Path | None, laboratory_id: str, *, domain: str = "market"
) -> dict[str, Any]:
    existing = load_global_wso(data_dir, laboratory_id)
    if existing is not None:
        return dict(existing)
    doc = empty_global_wso(laboratory_id=laboratory_id, domain=domain)
    save_global_wso(data_dir, doc)
    return doc


def list_lab_wsos(
    data_dir: str | Path | None,
    laboratory_id: str,
    *,
    include_global: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Load per-symbol WSOs in a lab (skips _GLOBAL unless include_global)."""
    d = lab_dir(data_dir, laboratory_id)
    if d is None or not d.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        if p.name == f"{GLOBAL_WSO_NAME}.json" and not include_global:
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            rows.append(doc)
        if len(rows) >= limit:
            break
    return rows
