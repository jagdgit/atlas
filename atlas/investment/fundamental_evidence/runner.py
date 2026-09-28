"""Run acquisition: plan → NSE/XBRL → optional Yahoo cross-check → UQ DONE."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from atlas.investment.fundamental_evidence.planner import plan_symbol_acquisition
from atlas.investment.fundamental_evidence.policy import (
    ACQUIRABLE_FIELDS,
    CODE_TO_FIELD,
    FIELD_TO_UQ_CODE,
)

VERSION = "fea.runner.v1"
_log = logging.getLogger("atlas.investment.fundamental_evidence")


def _field_present(row: dict[str, Any], field: str) -> bool:
    if field == "fcf":
        return row.get("fcf") is not None or row.get("free_cash_flow") is not None
    if field == "debt_to_equity":
        return row.get("debt_to_equity") is not None or row.get("debt_equity") is not None
    if field == "sector":
        s = str(row.get("sector") or "").strip()
        return bool(s) and s.lower() not in {"unknown", "n/a", "none"}
    if field == "identity":
        return bool(row.get("name") or row.get("legal_name"))
    return row.get(field) is not None


def _validate_candidate(
    field: str,
    value: Any,
    *,
    value_type: str | None = None,
    raw_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Light validation — refuse nonsense; never invent."""
    if value is None or value == "":
        return {"ok": False, "reason": "empty"}
    try:
        num = float(value)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "non_numeric"}
    if field == "pe" and (num <= 0 or num > 5000):
        return {"ok": False, "reason": "pe_out_of_range", "value": num}
    if field == "roe" and abs(num) > 500:
        return {"ok": False, "reason": "roe_out_of_range", "value": num}
    # FCF can be large INR absolute or crore-scale — allow negatives
    ref = raw_ref if isinstance(raw_ref, dict) else {}
    return {
        "ok": True,
        "field": field,
        "value": num,
        "value_type": value_type or ref.get("value_type") or "reported",
        "formula": ref.get("formula"),
        "inputs": ref.get("inputs"),
        "period": ref.get("period"),
        "provider": "yahoo_fundamentals",
    }


def acquire_for_symbol(
    data_dir: str | Path | None,
    symbol: str,
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    required_fields: list[str] | None = None,
    purpose: str = "swing_thesis",
    enabled: bool = True,
    opener: Any | None = None,
    push_to_ira: bool = True,
    research: Any | None = None,
    technical: str | None = None,
    nse_enabled: bool = True,
    nse_xml_text: str | list[str] | tuple[str, ...] | None = None,
    nse_price: float | None = None,
    evidence_as_of: str | None = None,
    nse_available_at: str | None = None,
    yahoo_secondary: bool = False,
) -> dict[str, Any]:
    """Acquire missing fundamentals: NSE/XBRL first. Yahoo only if yahoo_secondary."""
    from atlas.investment.data_plane_contract import build_symbol_evidence_view
    from atlas.investment.evidence_completeness import (
        apply_completeness_to_uncertainty,
        evaluate_evidence_completeness,
        persist_completeness,
    )
    from atlas.investment.fundamentals import (
        SOURCE_NSE_XBRL,
        SOURCE_YAHOO,
        enrich_from_yahoo,
        get_symbol,
        normalize_symbol,
        upsert_rows,
    )
    from atlas.investment.nse_xbrl.digest import save_observation
    from atlas.investment.nse_xbrl.identity import resolve_identity
    from atlas.investment.nse_xbrl.provider import acquire_from_nse
    from atlas.investment.uncertainty_queue import (
        STATUS_DONE,
        list_tasks,
        mark_task,
    )
    from atlas.investment.yahoo_fundamentals import (
        YAHOO_PRIORITY_OPEN_BOOK_ENRICH,
        get_yahoo_rate_gate,
    )
    from atlas.investment.fundamental_evidence.dispatch import schedule_nse_retry
    from atlas.investment.fundamental_evidence.ops import record_fea_event

    sym = normalize_symbol(symbol)
    plan = plan_symbol_acquisition(
        data_dir,
        sym,
        required_fields=required_fields,
        program_id=program_id,
        purpose=purpose,
    )
    out: dict[str, Any] = {
        "version": VERSION,
        "kind": "EVIDENCE_ACQUISITION_RESULT",
        "symbol": sym,
        "laboratory_id": laboratory_id,
        "plan": plan,
        "acquired": [],
        "still_missing": list(plan.get("missing") or []),
        "attempts": [],
        "uq_closed": [],
        "ira": None,
        "completeness": None,
        "evidence_view": None,
        "ok": True,
        "nse": None,
    }
    if plan.get("complete"):
        out["reason"] = "already_complete"
        out["evidence_view"] = build_symbol_evidence_view(
            data_dir, sym, laboratory_id=laboratory_id, program_id=program_id,
            technical=technical,
        )
        return out

    acquired: list[dict[str, Any]] = []
    t0 = time.monotonic()

    if nse_enabled:
        nse = acquire_from_nse(
            data_dir,
            sym,
            program_id=program_id,
            price=nse_price,
            evidence_as_of=evidence_as_of,
            xml_text=nse_xml_text,
            opener=opener if nse_xml_text is None else None,
            push_store=True,
            available_at=nse_available_at,
        )
        out["nse"] = {
            "ok": nse.get("ok"),
            "reason": nse.get("reason"),
            "parse": nse.get("parse"),
            "coverage": nse.get("coverage"),
            "conflicts": nse.get("conflicts") or [],
        }
        out["attempts"].append(
            {
                "provider": "nse_xbrl",
                "status": "ran" if nse.get("ok") else "miss",
                "reason": nse.get("reason"),
            }
        )
        acquired.extend(nse.get("acquired") or [])
        obs = {
            "fea_acquired": len(nse.get("acquired") or []),
            "last_fea_reason": nse.get("reason"),
        }
        if nse.get("ok") and (nse.get("parse") or {}).get("ok"):
            obs["nse_xbrl_success"] = 1
        elif (nse.get("parse") or {}).get("status") == "RETRY" or nse.get("reason") in {
            "malformed_xbrl",
            "no_mapped_facts",
            "parse_failure",
        }:
            obs["nse_parse_failures"] = 1
        if nse.get("reason") == "calc_unknown":
            obs["calculation_failures"] = 1
        if nse.get("conflicts"):
            obs["evidence_conflicts"] = len(nse.get("conflicts") or [])
        save_observation(data_dir, obs)

    # Identity/sector catalog even when XBRL missed. Do not overwrite nse_xbrl source.
    ident = resolve_identity(sym, data_dir=str(data_dir) if data_dir else None)
    if ident.get("sector_ok") or ident.get("identity_ok"):
        existing = get_symbol(data_dir, sym, program_id=program_id) or {}
        patch: dict[str, Any] = {"symbol": sym}
        if ident.get("sector_ok"):
            patch["sector"] = ident.get("sector")
        if ident.get("identity_ok"):
            patch["name"] = ident.get("name")
        if str(existing.get("source") or "") == SOURCE_NSE_XBRL:
            patch["source"] = SOURCE_NSE_XBRL
        else:
            patch["source"] = ident.get("source") or "universe_catalog"
        try:
            upsert_rows(
                data_dir,
                [patch],
                program_id=program_id,
                source=str(patch.get("source") or "universe_catalog"),
                note="identity/sector catalog (not XBRL)",
                merge_screener=True,
            )
        except Exception:  # noqa: BLE001
            _log.debug("identity catalog upsert skipped", exc_info=True)
        have = {a.get("field") for a in acquired}
        if ident.get("sector_ok") and "sector" not in have:
            acquired.append(
                {
                    "field": "sector",
                    "value": ident.get("sector"),
                    "provider": ident.get("source"),
                    "value_type": "reported",
                }
            )
        if ident.get("identity_ok") and "identity" not in have:
            acquired.append(
                {
                    "field": "identity",
                    "value": ident.get("name"),
                    "provider": ident.get("source"),
                    "value_type": "reported",
                }
            )

    row = get_symbol(data_dir, sym, program_id=program_id) or {}
    still = [f for f in (plan.get("missing") or []) if not _field_present(row, f)]
    yahoo_needed = [f for f in still if f in {"pe", "fcf", "roe", "debt_to_equity", "pb"}]
    allow_yahoo = bool(yahoo_secondary) and bool(enabled)

    gate = get_yahoo_rate_gate(data_dir)
    st = gate.status()
    cooling = float(st.get("cooldown_remaining_s") or 0) > 0

    if yahoo_needed and not allow_yahoo:
        out["attempts"].append(
            {
                "provider": "yahoo_fundamentals",
                "status": "skipped",
                "reason": "yahoo_suppressed",
            }
        )
    elif yahoo_needed and not enabled:
        out["attempts"].append(
            {"provider": "yahoo_fundamentals", "status": "skipped", "reason": "yahoo_disabled"}
        )
    elif yahoo_needed and cooling:
        out["attempts"].append(
            {
                "provider": "yahoo_fundamentals",
                "status": "skipped",
                "reason": "cooldown",
                "cooldown_remaining_s": st.get("cooldown_remaining_s"),
            }
        )
        out["rate_gate"] = st
    elif yahoo_needed:
        yahoo = enrich_from_yahoo(
            data_dir,
            [sym],
            program_id=program_id,
            enabled=True,
            opener=opener,
            only_gaps=True,
            batch_size=1,
            critical_fields=tuple(yahoo_needed),
            yahoo_priority=YAHOO_PRIORITY_OPEN_BOOK_ENRICH,
        )
        out["attempts"].append(
            {
                "provider": "yahoo_fundamentals",
                "status": "ran",
                "fetched": yahoo.get("fetched"),
                "reason": yahoo.get("reason"),
                "paused": yahoo.get("paused"),
                "errors": (yahoo.get("errors") or [])[:3],
            }
        )
        row = get_symbol(data_dir, sym, program_id=program_id) or {}
        for field in yahoo_needed:
            if not _field_present(row, field):
                continue
            bag = (row.get("evidence") or {}).get(field) or []
            latest = bag[-1] if isinstance(bag, list) and bag else {}
            raw_ref = latest.get("raw_ref") if isinstance(latest, dict) else {}
            val = row.get("fcf") if field == "fcf" else row.get(field)
            if field == "fcf" and val is None:
                val = row.get("free_cash_flow")
            checked = _validate_candidate(
                field,
                val,
                value_type=(raw_ref or {}).get("value_type"),
                raw_ref=raw_ref if isinstance(raw_ref, dict) else None,
            )
            if not checked.get("ok"):
                out["attempts"].append(
                    {"field": field, "status": "reject", "reason": checked.get("reason")}
                )
                continue
            if any(a.get("field") == field for a in acquired):
                continue
            acquired.append(
                {
                    "field": field,
                    "value": checked.get("value"),
                    "provider": SOURCE_YAHOO,
                    "value_type": checked.get("value_type"),
                    "formula": checked.get("formula"),
                    "inputs": checked.get("inputs"),
                    "period": checked.get("period"),
                    "source": row.get("source") or SOURCE_YAHOO,
                }
            )

    row = get_symbol(data_dir, sym, program_id=program_id) or {}
    still = [f for f in (plan.get("missing") or []) if not _field_present(row, f)]
    out["acquired"] = acquired
    out["still_missing"] = still

    try:
        for task in list_tasks(data_dir, laboratory_id) or []:
            if not isinstance(task, dict):
                continue
            if str(task.get("symbol") or "").upper() not in {sym, sym.replace(".NS", "")}:
                # HBLPOWER vs HBLPOWER.NS
                tsym = str(task.get("symbol") or "").upper().replace(".NS", "")
                if tsym != sym.replace(".NS", ""):
                    continue
            code = str(task.get("unknown") or "")
            field = CODE_TO_FIELD.get(code)
            if field and field not in still and (
                any(a.get("field") == field for a in acquired) or _field_present(row, field)
            ):
                mark_task(
                    data_dir,
                    str(task.get("id")),
                    laboratory_id=laboratory_id,
                    status=STATUS_DONE,
                    note=f"fea acquired {field}",
                    provider=str((acquired[0] or {}).get("provider") or "nse_xbrl")
                    if acquired
                    else "nse_xbrl",
                )
                out["uq_closed"].append(task.get("id"))
    except Exception:  # noqa: BLE001
        _log.debug("UQ close skipped", exc_info=True)

    val_fields = {
        a["field"]: a["value"]
        for a in acquired
        if a.get("field") in {"pe", "fcf", "roe", "debt_to_equity"}
    }
    if push_to_ira and val_fields and research is not None:
        try:
            for k in ("price", "shares", "pe", "fcf", "roe", "debt_to_equity"):
                if row.get(k) is not None and k not in val_fields:
                    val_fields[k] = row[k]
            out["ira"] = research.apply_operator_snapshot(
                sym,
                val_fields,
                program_id=program_id,
                note="FEA NSE/Yahoo acquisition → IRA refresh",
                evidence_confidence="estimated",
                auto_refresh=True,
            )
        except Exception as exc:  # noqa: BLE001
            out["ira"] = {"ok": False, "error": type(exc).__name__}

    try:
        aw = None
        if research is not None:
            try:
                aw = research.awareness(sym, program_id=program_id)
            except Exception:  # noqa: BLE001
                aw = None
        comp = evaluate_evidence_completeness(
            symbol=sym,
            laboratory_id=laboratory_id,
            awareness=aw if isinstance(aw, dict) else None,
            data_dir=data_dir,
            program_id=program_id,
        )
        persist_completeness(data_dir, comp)
        apply_completeness_to_uncertainty(data_dir, comp)
        out["completeness"] = {
            "decision": comp.get("decision"),
            "required_missing": comp.get("required_missing"),
            "usable_evidence_pct": comp.get("usable_evidence_pct"),
        }
        out["evidence_view"] = build_symbol_evidence_view(
            data_dir,
            sym,
            laboratory_id=laboratory_id,
            program_id=program_id,
            awareness=aw if isinstance(aw, dict) else None,
            technical=technical,
        )
    except Exception:  # noqa: BLE001
        _log.debug("completeness after acquire skipped", exc_info=True)

    if still:
        nse_blob = out.get("nse") if isinstance(out.get("nse"), dict) else {}
        nse_reason = nse_blob.get("reason")
        parse_blob = nse_blob.get("parse") if isinstance(nse_blob.get("parse"), dict) else {}
        parse_ok = bool(parse_blob.get("ok"))
        if nse_reason == "nse_unavailable":
            out["reason"] = "nse_unavailable"
            try:
                schedule_nse_retry(
                    data_dir,
                    laboratory_id=laboratory_id,
                    symbol=sym,
                    reason="nse_unavailable",
                )
            except Exception:  # noqa: BLE001
                _log.debug("NSE backoff stamp skipped", exc_info=True)
            out["honesty"] = (
                "NSE unavailable — explicit backoff. Yahoo is not the normal "
                "PE/ROE/D/E/FCF path."
            )
        elif parse_ok and nse_reason in {"partial", "calc_unknown"}:
            out["reason"] = "instance_incomplete"
            try:
                schedule_nse_retry(
                    data_dir,
                    laboratory_id=laboratory_id,
                    symbol=sym,
                    reason="instance_incomplete",
                )
            except Exception:  # noqa: BLE001
                _log.debug("instance_incomplete backoff skipped", exc_info=True)
            out["honesty"] = (
                "NSE filing parsed; remaining PE/ROE/D/E/FCF are UNKNOWN on this "
                "instance (need prior-year FY, more quarters, or definitional "
                "UNKNOWN such as non_positive_eps). Backing off — do not re-fetch "
                "the same Q1 every tick."
            )
        elif cooling and yahoo_needed and allow_yahoo:
            out["reason"] = "yahoo_cooldown"
            out["honesty"] = (
                "Yahoo cooling down after 429 — NSE tried first. "
                "Operator Screener import remains available."
            )
        elif not allow_yahoo and yahoo_needed and nse_reason in {None, "nse_unavailable", "partial", "calc_unknown"}:
            out["reason"] = nse_reason or "nse_unavailable"
        elif not enabled and yahoo_needed and nse_reason in {None, "nse_unavailable"}:
            out["reason"] = "yahoo_disabled"
        else:
            out["reason"] = "partial" if acquired else (nse_reason or "exhausted_network")
        out["next"] = {
            "operator_import": [FIELD_TO_UQ_CODE.get(f, f) for f in still],
            "hint": (
                "Remaining gaps — NSE miss. Retry on backoff. "
                "Use Screener CSV/xlsx import (no scrape) if still incomplete. "
                "Yahoo is not retried on this path."
            ),
        }
    else:
        out["reason"] = "complete"
    try:
        nse_blob = out.get("nse") if isinstance(out.get("nse"), dict) else {}
        record_fea_event(
            data_dir,
            {
                "symbol": sym,
                "reason": out.get("reason"),
                "nse_ok": bool(nse_blob.get("ok")),
                "nse_reason": nse_blob.get("reason"),
                "acquired_n": len(acquired),
                "ms": round((time.monotonic() - t0) * 1000.0, 1),
                "parse_failure": str(nse_blob.get("reason") or "")
                in {"malformed_xbrl", "no_mapped_facts", "parse_failure"},
                "conflicts": len(nse_blob.get("conflicts") or []),
            },
        )
    except Exception:  # noqa: BLE001
        _log.debug("FEA event skipped", exc_info=True)
    return out


def reconcile_non_network_uq(
    data_dir: str | Path | None,
    *,
    laboratory_id: str,
    research: Any | None = None,
    program_id: str = "market_intelligence",
) -> dict[str, Any]:
    """Close identity/mos UQ that must not go to Yahoo; stamp last_error otherwise."""
    from atlas.investment.uncertainty_queue import (
        STATUS_DONE,
        list_tasks,
        mark_task,
        note_attempt,
    )

    closed: list[str] = []
    noted: list[str] = []
    tasks = list_tasks(data_dir, laboratory_id) or []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        code = str(t.get("unknown") or "")
        tid = str(t.get("id") or "")
        sym = str(t.get("symbol") or "").upper()
        if not tid:
            continue
        if code == "mos_unknown":
            note_attempt(
                data_dir,
                tid,
                laboratory_id=laboratory_id,
                provider="ira_valuation",
                error="mos is IRA-computed, not a Yahoo fetch",
            )
            noted.append(tid)
            continue
        if code != "identity_unknown":
            continue
        identity_ok = False
        if research is not None and sym:
            try:
                aw = research.awareness(sym, program_id=program_id)
                ident = (aw or {}).get("identity") if isinstance(aw, dict) else None
                if ident in {"AVAILABLE", "available", True}:
                    identity_ok = True
                elif isinstance(ident, dict) and ident.get("status") in {
                    "AVAILABLE",
                    "available",
                    "ok",
                }:
                    identity_ok = True
            except Exception:  # noqa: BLE001
                identity_ok = False
        if not identity_ok and data_dir and sym:
            try:
                from atlas.investment.company_profiles import load_profile

                prof = load_profile(data_dir, sym)
                if isinstance(prof, dict) and (
                    prof.get("name") or prof.get("legal_name") or prof.get("sector")
                ):
                    identity_ok = True
            except Exception:  # noqa: BLE001
                pass
        if identity_ok:
            mark_task(
                data_dir,
                tid,
                laboratory_id=laboratory_id,
                status=STATUS_DONE,
                note="identity AVAILABLE — closed without Yahoo",
                provider="identity",
            )
            closed.append(tid)
        else:
            note_attempt(
                data_dir,
                tid,
                laboratory_id=laboratory_id,
                provider="identity",
                error="identity still unknown",
            )
            noted.append(tid)
    return {"closed_ids": closed, "noted_ids": noted}


def drain_uncertainty_queue(
    data_dir: str | Path | None,
    *,
    laboratory_id: str = "india_equity_learner",
    program_id: str = "market_intelligence",
    limit: int = 6,
    enabled: bool = True,
    opener: Any | None = None,
    push_to_ira: bool = True,
    research: Any | None = None,
    yahoo_secondary: bool = False,
    nse_concurrency: int = 3,
) -> dict[str, Any]:
    """Drain due UQ tasks: planner → priority batch → shared NSE pool."""
    from atlas.investment.fundamental_evidence.dispatch import plan_batch_acquisition
    from atlas.investment.nse_xbrl.digest import save_observation
    from atlas.investment.nse_xbrl.provider import configure_nse_pool
    from atlas.investment.uncertainty_queue import note_attempt

    reconcile_non_network_uq(
        data_dir,
        laboratory_id=laboratory_id,
        research=research,
        program_id=program_id,
    )
    try:
        configure_nse_pool(concurrency=nse_concurrency)
    except Exception:  # noqa: BLE001
        pass

    plan = plan_batch_acquisition(
        data_dir, laboratory_id=laboratory_id, limit=limit
    )
    work = list(plan.get("due") or [])
    try:
        save_observation(data_dir, {"fea_last_plan": plan})
    except Exception:  # noqa: BLE001
        pass

    for item in work:
        for tid in item.get("task_ids") or []:
            note_attempt(
                data_dir,
                str(tid),
                laboratory_id=laboratory_id,
                provider="nse_xbrl",
            )

    results: list[dict[str, Any]] = []
    workers = max(1, min(int(nse_concurrency or 1), max(1, len(work)), 4))

    def _one(item: dict[str, Any]) -> dict[str, Any]:
        return acquire_for_symbol(
            data_dir,
            item["symbol"],
            laboratory_id=laboratory_id,
            program_id=program_id,
            required_fields=item.get("fields"),
            enabled=enabled,
            opener=opener,
            push_to_ira=push_to_ira,
            research=research,
            purpose="uncertainty_queue",
            yahoo_secondary=yahoo_secondary,
        )

    if len(work) <= 1 or workers <= 1 or opener is not None:
        results = [_one(item) for item in work]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_one, item): item for item in work}
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as exc:  # noqa: BLE001
                    item = futs[fut]
                    results.append(
                        {
                            "symbol": item.get("symbol"),
                            "ok": False,
                            "reason": type(exc).__name__,
                            "acquired": [],
                        }
                    )

    return {
        "version": VERSION,
        "kind": "EVIDENCE_ACQUISITION_DRAIN",
        "laboratory_id": laboratory_id,
        "queued": len(work),
        "plan": {
            "queue_depth": plan.get("queue_depth"),
            "backing_off_n": plan.get("backing_off_n"),
            "priority_due": plan.get("priority_due"),
        },
        "results": results,
        "acquired_n": sum(len(r.get("acquired") or []) for r in results),
        "honesty": (
            "UQ drain — priority batch, shared NSE pool, Yahoo suppressed unless "
            "yahoo_secondary. Catalog-only names are not acquired. PLC.A unchanged."
        ),
    }
