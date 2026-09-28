"""Why-own bundle — MKG + open-book fallbacks when theme edges are missing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _latest_scientist_note(
    data_dir: str | Path | None,
    symbol: str,
    *,
    laboratory_id: str,
) -> dict[str, Any] | None:
    if not data_dir:
        return None
    root = (
        Path(data_dir)
        / "investment"
        / "scientist_notes"
        / laboratory_id.replace("/", "_")
        / "by_id"
    )
    if not root.is_dir():
        root = Path(data_dir) / "investment" / "scientist_notes" / laboratory_id / "by_id"
    if not root.is_dir():
        return None
    sym = str(symbol or "").upper()
    best: tuple[float, dict[str, Any]] | None = None
    for p in root.glob("*.json"):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or str(doc.get("symbol") or "").upper() != sym:
            continue
        notes = doc.get("notes") if isinstance(doc.get("notes"), dict) else {}
        rank = 2 if notes.get("review_status") == "REVIEWED" else 1
        mtime = p.stat().st_mtime + rank * 1e9
        if best is None or mtime > best[0]:
            best = (mtime, doc)
    return best[1] if best else None


def why_own_bundle(
    data_dir: str | Path | None,
    symbol: str,
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    graph: dict[str, Any] | None = None,
    financial_cites: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """MKG why-own plus ACP / scientist / dossier fallbacks — advice-only."""
    from atlas.investment import mkg as mkg_mod
    from atlas.investment.mkg.service import why_own

    sym = str(symbol or "").strip().upper()
    if sym and not sym.endswith(".NS") and "." not in sym:
        sym = f"{sym}.NS"

    g = graph if graph is not None else mkg_mod.ensure_seeded(data_dir)
    fin = (
        list(financial_cites)
        if financial_cites is not None
        else mkg_mod.financial_cites_for(data_dir, sym, program_id=program_id)
    )
    mkg = why_own(g, sym, financial_cites=fin)

    fallback: dict[str, Any] = {}
    lines: list[str] = []

    # Allocation / ACP
    if data_dir:
        try:
            from atlas.investment.allocation_comparison import load_latest_acp_summary

            acp = load_latest_acp_summary(data_dir, laboratory_id, sym)
            if isinstance(acp, dict) and acp.get("decision"):
                fallback["acp"] = {
                    "decision": acp.get("decision"),
                    "reason_code": acp.get("reason_code"),
                    "operator_line": acp.get("operator_line"),
                    "expected_return": acp.get("expected_return"),
                }
                lines.append(
                    f"ACP: {acp.get('decision')} ({acp.get('reason_code') or '?'}) — "
                    f"{str(acp.get('operator_line') or '')[:140]}"
                )
        except Exception:  # noqa: BLE001
            pass

    # Scientist notes (ICR.5)
    sci_doc = _latest_scientist_note(data_dir, sym, laboratory_id=laboratory_id)
    if sci_doc:
        notes = sci_doc.get("notes") if isinstance(sci_doc.get("notes"), dict) else {}
        fallback["scientist"] = {
            "review_status": notes.get("review_status"),
            "llm_status": sci_doc.get("llm_status"),
            "summary": notes.get("summary") or notes.get("operator_line"),
        }
        if notes.get("summary") or notes.get("operator_line"):
            tag = notes.get("review_status") or sci_doc.get("llm_status") or "draft"
            lines.append(
                f"Scientist ({tag}): "
                f"{str(notes.get('summary') or notes.get('operator_line') or '')[:160]}"
            )

    # Research dossier snapshot
    if data_dir:
        dossier_path = (
            Path(data_dir)
            / "investment"
            / "research"
            / program_id
            / f"{sym}.json"
        )
        dossier = _safe_read_json(dossier_path) if dossier_path.is_file() else None
        if dossier:
            bi = dossier.get("business_identity") if isinstance(dossier.get("business_identity"), dict) else {}
            fallback["dossier"] = {
                "sector": bi.get("sector"),
                "industry": bi.get("industry"),
                "phase": dossier.get("phase"),
                "known_unknowns": (dossier.get("known_unknowns") or [])[:6],
            }
            sector = bi.get("sector") or bi.get("industry")
            if sector:
                lines.append(f"Dossier sector: {sector}")
            unknowns = list(dossier.get("known_unknowns") or [])[:4]
            if unknowns:
                lines.append("Still unknown: " + "; ".join(str(u) for u in unknowns))

    # World state
    if data_dir:
        wso_path = Path(data_dir) / "investment" / "world_state" / laboratory_id / f"{sym}.json"
        wso = _safe_read_json(wso_path) if wso_path.is_file() else None
        if wso:
            fallback["world_state"] = {
                "status": wso.get("status"),
                "unknowns": (wso.get("unknowns") or [])[:8],
            }
            if wso.get("status"):
                lines.append(f"World state: {wso.get('status')}")

    if fin:
        fin_bits = [
            f"{c.get('field')}={c.get('value')}"
            for c in fin[:4]
            if isinstance(c, dict) and c.get("field")
        ]
        if fin_bits:
            lines.append("Fundamentals (hermetic/import): " + ", ".join(fin_bits))

    mkg_ok = str(mkg.get("status") or "") == "ok"
    if mkg_ok:
        summary = str(mkg.get("summary") or "")
        display = summary
    else:
        head = str(mkg.get("summary") or f"No MKG theme edges for {sym} yet.")
        if lines:
            display = head + "\n\nOpen-book context:\n" + "\n".join(f"  · {ln}" for ln in lines)
        else:
            display = head
        summary = display

    return {
        **mkg,
        "mkg": mkg,
        "fallback": fallback,
        "financial_cites": fin,
        "summary": summary,
        "display_summary": display,
        "advice_only": True,
        "never_orders": True,
        "honesty": (
            "MKG cites catalog theme/policy edges only. When missing, Atlas shows "
            "ACP/scientist/dossier context — never invented supply chains."
        ),
    }
