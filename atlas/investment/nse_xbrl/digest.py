"""Hourly / evening FUNDAMENTAL INTELLIGENCE block (L23)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from atlas.investment.nse_xbrl.coverage import SLICE_FIELDS

OBS_REL = Path("investment") / "fundamental_intelligence" / "observation.json"
_OBS_LOCK = threading.Lock()


def load_observation(data_dir: str | Path | None) -> dict[str, Any]:
    if not data_dir:
        return {}
    p = Path(data_dir) / OBS_REL
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_observation(data_dir: str | Path | None, doc: dict[str, Any]) -> None:
    if not data_dir or not isinstance(doc, dict):
        return
    p = Path(data_dir) / OBS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with _OBS_LOCK:
        prev = load_observation(data_dir)
        merged = dict(prev)
        for k, v in doc.items():
            if k in {"nse_xbrl_success", "nse_parse_failures", "calculation_failures", "evidence_conflicts", "plc_a_reevaluated", "fea_acquired"}:
                try:
                    merged[k] = int(prev.get(k) or 0) + int(v or 0)
                except (TypeError, ValueError):
                    merged[k] = v
            else:
                merged[k] = v
        p.write_text(json.dumps(merged, indent=2, default=str) + "\n", encoding="utf-8")


def format_fundamental_intelligence_section(
    data_dir: str | Path | None = None,
    *,
    laboratory_id: str = "india_equity_learner",
    portfolio: dict[str, Any] | None = None,
) -> list[str]:
    """Always emit the block — zeros with names are honest; missing section is a fail."""
    from atlas.investment.fundamentals import get_symbol
    from atlas.investment.nse_xbrl.coverage import fundamentals_coverage
    from atlas.investment.nse_xbrl.identity import resolve_identity
    from atlas.investment.plc_buy_gates import evaluate_fundamental_sanity, sector_from_sources
    from atlas.investment.uncertainty_queue import STATUS_PENDING, list_tasks
    from atlas.investment.yahoo_fundamentals import get_yahoo_rate_gate

    root = data_dir
    if not root and isinstance(portfolio, dict):
        root = portfolio.get("data_dir")
    if not root:
        try:
            from atlas.config import get_config

            root = str(get_config().paths.data)
        except Exception:  # noqa: BLE001
            root = None

    obs = load_observation(root)
    pending = []
    try:
        pending = list_tasks(root, laboratory_id, status=STATUS_PENDING) if root else []
    except Exception:  # noqa: BLE001
        pending = []
    uq_codes = {
        "pe_missing",
        "roe_missing",
        "debt_missing",
        "fcf_missing",
        "sector_missing",
        "identity_unknown",
    }
    uq_n = sum(1 for t in pending if str(t.get("unknown") or "") in uq_codes)
    by_sym: dict[str, list[str]] = {}
    for t in pending:
        if not isinstance(t, dict):
            continue
        if str(t.get("unknown") or "") not in uq_codes:
            continue
        by_sym.setdefault(str(t.get("symbol") or "?").upper(), []).append(
            str(t.get("unknown"))
        )

    gate = {}
    try:
        if root:
            gate = get_yahoo_rate_gate(root).status()
    except Exception:  # noqa: BLE001
        gate = {}

    lines = [
        "",
        "━━━━━━━━ FUNDAMENTAL INTELLIGENCE ━━━━━━━━",
        f"Technical BUYs:          {obs.get('technical_buys', 'n/a')}",
        f"PLC.A incomplete:        {obs.get('plc_a_incomplete', 'n/a')}",
        f"UQ pending (pe/roe/d/e/fcf/sector/identity): {uq_n}",
        f"FEA acquired this window: {obs.get('fea_acquired', 0)}",
        f"NSE XBRL success:        {obs.get('nse_xbrl_success', 0)}",
        f"NSE parse failures:      {obs.get('nse_parse_failures', 0)}",
        f"Calculation failures:    {obs.get('calculation_failures', 0)}",
        f"Evidence conflicts:      {obs.get('evidence_conflicts', 0)}",
        f"PLC.A re-evaluated:      {obs.get('plc_a_reevaluated', 0)}",
        f"Still blocked:           {len(by_sym)}",
        "",
        "Coverage (material names only)",
    ]

    material = list(by_sym.keys())[:8]
    if "HBLPOWER" not in material and "HBLPOWER.NS" not in material:
        material = ["HBLPOWER"] + material
    ok_counts = {f: 0 for f in SLICE_FIELDS}
    tot = 0
    detail: list[str] = []
    for raw_sym in material[:8]:
        tot += 1
        row = get_symbol(root, raw_sym) if root else {}
        ident = resolve_identity(raw_sym, data_dir=str(root) if root else None, fundamentals=row)
        cov = fundamentals_coverage(fundamentals=row or {}, identity=ident)
        for item in cov.get("fields") or []:
            if item.get("ok"):
                ok_counts[item["field"]] = ok_counts.get(item["field"], 0) + 1
        marks = []
        missing = []
        for item in cov.get("fields") or []:
            mark = "✓" if item.get("ok") else "✗"
            marks.append(f"{item['field']} {mark}")
            if not item.get("ok"):
                missing.append(item["field"])
        sector = sector_from_sources(fundamentals=row) or ident.get("sector")
        plc = evaluate_fundamental_sanity(row or {}, sector=sector)
        uq = by_sym.get(raw_sym.upper()) or by_sym.get(
            raw_sym.upper().replace(".NS", "")
        ) or []
        if not uq:
            # try alt
            for k, v in by_sym.items():
                if k.replace(".NS", "") == raw_sym.upper().replace(".NS", ""):
                    uq = v
                    break
        reason = ",".join(missing) if missing else "complete"
        provider = (row or {}).get("source") or "none"
        detail.append(raw_sym.replace(".NS", ""))
        detail.append("  " + "   ".join(marks))
        detail.append(
            f"  provider={provider}   PLC.A={plc.get('code')}   missing: {reason}"
        )
        detail.append(
            f"  UQ: {'pending ' + ','.join(uq) if uq else 'none'}   "
            f"FEA: {obs.get('last_fea_reason') or '—'}   reason: {reason}"
        )

    if tot:
        lines.append(
            "  "
            + "  ".join(
                f"{f} {ok_counts.get(f, 0)}/{tot}" for f in SLICE_FIELDS
            )
        )
    else:
        lines.append("  PE ROE D/E FCF sector identity   0/0")

    lines.append("")
    lines.append(
        f"Yahoo fundamentals: suppressed on PE/ROE/D/E/FCF drain  "
        f"consecutive_429={gate.get('consecutive_blocks', 'n/a')}  "
        f"(secondary/cross-check only)"
    )
    lines.append("F&O resolved: NIFTY/BANK/FIN/MID  (see fno contracts; P1 stamp)")
    lines.append("")
    try:
        from atlas.investment.fundamental_evidence.ops import (
            format_fea_ops_lines,
            summarize_fea_ops,
        )

        ops = summarize_fea_ops(
            root, laboratory_id=laboratory_id, plan=obs.get("fea_last_plan")
        )
        lines.extend(format_fea_ops_lines(ops))
    except Exception:  # noqa: BLE001
        lines.extend(
            [
                "FEA",
                "──────",
                "(ops block failed to render)",
            ]
        )
    lines.append("")
    lines.extend(detail or ["(no material incompletes listed)"])
    return lines
