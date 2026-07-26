"""InvestmentResearchService — IRA Phase A orchestration."""

from __future__ import annotations

import logging
from typing import Any

from atlas.investment import quality_seed as qs
from atlas.investment import filings as fl
from atlas.investment.research.models import (
    CONF_LOW,
    CONF_MEDIUM,
    CONF_VERY_LOW,
    DEFAULT_PROGRAM,
    MVR_QUESTIONS,
    PHASE_BLOCKED,
    PHASE_MVR_READY,
    PHASE_QUEUED,
    PHASE_RESEARCHING,
    PHASE_THESIS_READY,
    VERSION,
    classify_questions,
    coverage_detail,
    coverage_pct,
    default_mvr_questions,
    default_research_plan,
    empty_dossier,
    mark_section,
    mark_stale_sections,
    mvr_status,
    normalize_symbol,
    overall_confidence,
    research_quality,
    stale_sections,
    utc_now_iso,
)
from atlas.investment.research.valuation import (
    MIN_MOS_BUY_PCT,
    build_valuation_case,
    thesis_stance_from_valuation,
)
from atlas.investment.research.store import ResearchStore
from atlas.investment.research import sector_packs as packs
from atlas.investment.research import timing as timing_pack
from atlas.investment.research import management_pack as mgmt_pack
from atlas.investment.research.evidence import (
    critical_flags_summary,
    evidence_sufficiency,
    level_for_filing,
    make_evidence,
    cap_confidence_without_evidence,
    prioritize_missing_inputs,
    schedule_research_questions,
    section_evidence_levels,
    sections_impacted_by_fields,
    sections_impacted_by_filings,
)


class InvestmentResearchService:
    """On-demand + watchlist research spine (Market Program)."""

    name = "investment_research"
    VERSION = VERSION

    def __init__(
        self,
        *,
        data_dir: str | None = None,
        company_data: Any | None = None,
        market_reader: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._store = ResearchStore(data_dir, logger=logger)
        self._companies = company_data
        self._market = market_reader
        self._logger = logger or logging.getLogger("atlas.investment.research")

    # --- public API -----------------------------------------------------

    def get_or_create(
        self,
        symbol: str,
        *,
        program_id: str = DEFAULT_PROGRAM,
    ) -> dict[str, Any]:
        sym = normalize_symbol(symbol)
        doc = self._store.get(sym, program_id=program_id)
        if doc is None:
            doc = empty_dossier(sym, program_id=program_id)
            doc["questions"] = default_mvr_questions(sym)
            doc["plan"] = default_research_plan(sym)
            doc["management_pack"] = mgmt_pack.empty_management_pack()
            self._ensure_management_questions(doc)
            doc = self._store.save(doc)
        else:
            # Backfill F3 pack / questions on older dossiers
            if not isinstance(doc.get("management_pack"), dict):
                doc["management_pack"] = mgmt_pack.empty_management_pack()
            if self._ensure_management_questions(doc):
                doc = self._store.save(doc)
        return doc

    def _ensure_management_questions(self, doc: dict[str, Any]) -> bool:
        """Append F3 management checklist questions once. Returns True if mutated."""
        qs = list(doc.get("questions") or [])
        have = {q.get("id") for q in qs if isinstance(q, dict)}
        added = False
        for q in mgmt_pack.management_questions_for_symbol(str(doc.get("symbol") or "")):
            if q["id"] not in have:
                qs.append(q)
                added = True
        if added:
            doc["questions"] = qs
        return added

    def awareness(self, symbol: str, *, program_id: str = DEFAULT_PROGRAM) -> dict[str, Any]:
        doc = self.get_or_create(symbol, program_id=program_id)
        mvr = mvr_status(doc)
        cov_detail = coverage_detail(doc)
        cov = float(cov_detail["coverage_pct"])
        conf = overall_confidence(doc)
        quality = research_quality(doc)
        q_class = classify_questions(doc)
        sections = doc.get("sections") if isinstance(doc.get("sections"), dict) else {}
        section_confidence = {
            k: (v or {}).get("confidence", CONF_VERY_LOW) for k, v in sections.items()
        }
        freshness = {
            k: {"as_of": (v or {}).get("as_of"), "status": (v or {}).get("status")}
            for k, v in sections.items()
        }
        open_q = q_class.get("open") or []
        gap_q = [
            q for q in (doc.get("questions") or [])
            if isinstance(q, dict) and q.get("status") in {"open", "blocked", "answered_gap"}
        ]
        # Flatten top gaps from sections for UI
        top_gaps: list[str] = []
        for name, sec in sections.items():
            if not isinstance(sec, dict):
                continue
            for g in sec.get("gaps") or []:
                top_gaps.append(str(g))
            if str(sec.get("confidence") or "") == CONF_VERY_LOW and name in (
                "management", "cash_flow", "valuation", "moat"
            ):
                top_gaps.append(f"{name}: confidence very_low")
        known_u = list(doc.get("known_unknowns") or [])
        if not known_u:
            known_u = top_gaps[:12]
        thesis = doc.get("thesis") if isinstance(doc.get("thesis"), dict) else {}
        valuation = doc.get("valuation") if isinstance(doc.get("valuation"), dict) else {}
        biz = (sections.get("business") or {}).get("fields") or {}
        risks = ((sections.get("risks") or {}).get("fields") or {}).get("top_risks") or []
        missing_pri = prioritize_missing_inputs(list(valuation.get("missing_inputs") or []))
        sufficiency = evidence_sufficiency(
            valuation=valuation,
            sections=sections,
            mvr_satisfied=bool(mvr.get("satisfied")),
            mos=valuation.get("margin_of_safety_pct"),
            critical_flags=list(doc.get("critical_flags") or []),
        )
        flags_sum = critical_flags_summary(list(doc.get("critical_flags") or []))
        next_work = schedule_research_questions(doc, limit=8)
        # Section evidence levels for UI (IRA.25)
        section_evidence = {
            k: {
                "levels": section_evidence_levels(v),
                "confidence": (v or {}).get("confidence"),
            }
            for k, v in sections.items()
            if isinstance(v, dict)
        }
        brief = {
            "summary": thesis.get("summary") or doc.get("doing_now"),
            "thesis": thesis.get("summary"),
            "stance": thesis.get("stance"),
            "business": " · ".join(
                str(x) for x in (biz.get("name"), biz.get("sector"), biz.get("summary")) if x
            ),
            "watch_items": list(doc.get("watch_items") or [])[:8],
            "honesty": (
                "Hermetic / hint-based MVR — not live NSE filings. "
                f"Coverage {cov}% (depth-weighted) · confidence {conf} · "
                f"research quality {quality.get('level')} — these are independent."
            ),
            "risks": list(risks)[:5],
        }
        caution = conf in {CONF_MEDIUM, "high", CONF_LOW} and cov < 40
        if conf in {"high", CONF_MEDIUM} and cov < 50:
            caution = True
        # warn: coverage looks "done enough" while confidence stays very_low
        caution_cov_conf = cov >= 35 and conf == CONF_VERY_LOW
        return {
            "version": VERSION,
            "symbol": doc.get("symbol"),
            "program_id": program_id,
            "phase": doc.get("phase"),
            "doing_now": doc.get("doing_now"),
            "completed": [
                s["id"] for s in ((doc.get("plan") or {}).get("steps") or [])
                if isinstance(s, dict) and s.get("status") == "done"
            ],
            "blocked_on": list(doc.get("blocked_on") or []),
            "open_questions": open_q,
            "gap_questions": gap_q,
            "questions_classified": q_class,
            "research_plan_step": ((doc.get("plan") or {}).get("steps") or [None])[
                min(int((doc.get("plan") or {}).get("cursor") or 0), max(0, len((doc.get("plan") or {}).get("steps") or []) - 1))
            ] if (doc.get("plan") or {}).get("steps") else None,
            "known_knowns": list(doc.get("known_knowns") or []),
            "known_unknowns": known_u[:20],
            "top_gaps": top_gaps[:12],
            "brief": brief,
            "pack": doc.get("pack"),
            "section_confidence": section_confidence,
            "coverage_by_section": cov_detail.get("by_section"),
            "coverage_by_evidence": cov_detail.get("by_evidence"),
            "coverage_by_reasoning": cov_detail.get("by_reasoning"),
            "freshness": freshness,
            "confidence": conf,
            "coverage": cov,
            "research_quality": quality,
            "evidence_sufficiency": sufficiency,
            "critical_flags": flags_sum,
            "next_work": next_work,
            "section_evidence": section_evidence,
            "missing_inputs": {
                "critical": missing_pri.get("critical") or [],
                "important": missing_pri.get("important") or [],
                "optional": missing_pri.get("optional") or [],
            },
            "mvr": mvr,
            "mvr_satisfied": bool(mvr.get("satisfied")),
            "caution_high_confidence_low_coverage": caution,
            "caution_high_coverage_low_confidence": caution_cov_conf,
            "next": doc.get("next"),
            "last_updated": doc.get("updated_at"),
            "trigger": doc.get("trigger"),
            "mode": doc.get("mode"),
            "thesis": thesis or None,
            "valuation": valuation or None,
            "timing": doc.get("timing"),
            "fundamentals_status": doc.get("fundamentals_status"),
            "memories_count": len(doc.get("memories") or []),
            "outcomes_count": len(doc.get("outcomes") or []),
            "management_pack": doc.get("management_pack"),
            "outcome_priors": doc.get("outcome_priors"),
            "thesis_drivers": (thesis.get("drivers") if thesis else None),
            "thesis_distinctiveness": (
                thesis.get("distinctiveness") if thesis else None
            ),
            "sector_pack": packs.pack_by_id(doc.get("pack")) if doc.get("pack") else None,
        }

    def start(
        self,
        symbol: str,
        *,
        program_id: str = DEFAULT_PROGRAM,
        mode: str = "mvr",
        force: bool = False,
        trigger: str = "on_demand",
    ) -> dict[str, Any]:
        """Run a bounded MVR research pass (hermetic seeds + gaps). Idempotent unless force."""
        sym = normalize_symbol(symbol)
        doc = self.get_or_create(sym, program_id=program_id)
        if not force and doc.get("phase") in {PHASE_MVR_READY, PHASE_THESIS_READY} and mode == "mvr":
            return {
                "started": False,
                "reason": "already_mvr_ready",
                "awareness": self.awareness(sym, program_id=program_id),
                "dossier": doc,
            }

        doc["phase"] = PHASE_RESEARCHING
        doc["doing_now"] = f"MVR research pass for {sym}"
        doc["trigger"] = trigger
        want_deep = str(mode).lower() == "deep"
        # IRA.30 — auto deep quality-gated; operator force always allowed
        if want_deep and not force:
            q = research_quality(doc)
            if str(q.get("level") or "basic") == "basic":
                return {
                    "started": False,
                    "ok": False,
                    "reason": "deep_quality_gated",
                    "detail": (
                        "Automatic deep mode requires research quality ≥ developing. "
                        "Pass force=true to override, or apply operator snapshots first."
                    ),
                    "research_quality": q,
                    "awareness": self.awareness(sym, program_id=program_id),
                    "dossier": doc,
                }
        doc["mode"] = "deep" if want_deep else "mvr"
        doc["blocked_on"] = []
        if not doc.get("questions"):
            doc["questions"] = default_mvr_questions(sym)
        if not isinstance(doc.get("management_pack"), dict):
            doc["management_pack"] = mgmt_pack.empty_management_pack()
        self._ensure_management_questions(doc)
        if not (doc.get("plan") or {}).get("steps"):
            doc["plan"] = default_research_plan(sym)
        self._store.save(doc)

        try:
            doc = self._run_mvr_pass(doc)
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("research pass failed for %s", sym)
            doc["phase"] = PHASE_BLOCKED
            doc["blocked_on"] = [f"error:{type(exc).__name__}"]
            doc["doing_now"] = "blocked"
            doc["next"] = "retry_research"
            self._store.save(doc)
            return {
                "started": True,
                "ok": False,
                "reason": str(exc),
                "awareness": self.awareness(sym, program_id=program_id),
                "dossier": doc,
            }

        return {
            "started": True,
            "ok": True,
            "reason": None,
            "awareness": self.awareness(sym, program_id=program_id),
            "dossier": doc,
        }

    def dossier(self, symbol: str, *, program_id: str = DEFAULT_PROGRAM) -> dict[str, Any]:
        return self.get_or_create(symbol, program_id=program_id)

    def list_researched(self, *, program_id: str = DEFAULT_PROGRAM) -> list[dict[str, Any]]:
        rows = []
        for sym in self._store.list_symbols(program_id=program_id):
            rows.append(self.awareness(sym, program_id=program_id))
        return rows

    def daily_digest(self, *, program_id: str = DEFAULT_PROGRAM, limit: int = 12) -> dict[str, Any]:
        """Studied / decided / learned rollup for investor emails."""
        rows = self.list_researched(program_id=program_id)
        studied: list[dict[str, Any]] = []
        lessons: list[str] = []
        open_gaps: list[str] = []
        for aw in rows[: max(1, limit * 2)]:
            thesis = aw.get("thesis") if isinstance(aw.get("thesis"), dict) else {}
            studied.append(
                {
                    "symbol": aw.get("symbol"),
                    "phase": aw.get("phase"),
                    "coverage": aw.get("coverage"),
                    "confidence": aw.get("confidence"),
                    "mvr_satisfied": aw.get("mvr_satisfied"),
                    "thesis": (thesis.get("summary") or "")[:160],
                    "stance": thesis.get("stance"),
                    "outcomes_count": aw.get("outcomes_count") or 0,
                }
            )
            for ku in (aw.get("known_unknowns") or [])[:2]:
                open_gaps.append(f"{aw.get('symbol')}: {ku}")
            doc = self._store.get(str(aw.get("symbol") or ""), program_id=program_id) or {}
            for out in list(doc.get("outcomes") or [])[-3:]:
                if isinstance(out, dict) and out.get("note"):
                    lessons.append(f"{aw.get('symbol')}: {out.get('result')} — {out.get('note')}")
        return {
            "studied": studied[:limit],
            "lessons": lessons[-limit:],
            "open_gaps": open_gaps[:limit],
            "count": len(rows),
        }

    def record_outcome(
        self,
        symbol: str,
        *,
        program_id: str = DEFAULT_PROGRAM,
        result: str,
        note: str = "",
        trade: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Daily/trade learning hook — ThesisOutcome stub."""
        doc = self.get_or_create(symbol, program_id=program_id)
        outcome = {
            "id": f"out-{len(doc.get('outcomes') or []) + 1}",
            "at": utc_now_iso(),
            "result": result,  # held | weakened | falsified | observed | fill
            "note": note,
            "trade": trade or {},
            "thesis_id": (doc.get("thesis") or {}).get("id"),
        }
        outs = list(doc.get("outcomes") or [])
        outs.append(outcome)
        doc["outcomes"] = outs[-50:]
        # Research memory trail
        mem = {
            "id": f"m-{len(doc.get('memories') or []) + 1}",
            "at": utc_now_iso(),
            "observation": note or f"Trading experience: {result}",
            "interpretation": f"Thesis outcome tagged {result}",
            "evidence": [trade] if trade else [],
            "confidence": CONF_LOW,
            "alternatives": [],
            "decision_note": "Update beliefs on next research refresh",
        }
        mems = list(doc.get("memories") or [])
        mems.append(mem)
        doc["memories"] = mems[-100:]
        known = list(doc.get("known_knowns") or [])
        bit = f"outcome:{result}"
        if bit not in known:
            known.append(bit)
        doc["known_knowns"] = known[-40:]
        doc["updated_at"] = utc_now_iso()
        # IRA.29 — outcome → section priors + question priority
        self._apply_outcome_priors(doc, result=result, note=note)
        self._store.save(doc)
        return outcome

    def _apply_outcome_priors(
        self,
        doc: dict[str, Any],
        *,
        result: str,
        note: str = "",
    ) -> None:
        """ThesisOutcome shapes next research — not price alone (IRA.29)."""
        res = str(result or "").lower()
        priors = dict(doc.get("outcome_priors") or {})
        priors["last_result"] = res
        priors["last_note"] = (note or "")[:200]
        priors["updated_at"] = utc_now_iso()
        counts = dict(priors.get("counts") or {})
        counts[res] = int(counts.get(res) or 0) + 1
        priors["counts"] = counts

        # Bump related open questions
        bump_ids: list[str] = []
        if res in {"weakened", "falsified"}:
            bump_ids = ["q2", "q3", "q4", "mgmt-q1", "mgmt-q3", "mgmt-q7"]  # mgmt/debt/fcf
            priors["ranking_penalty"] = round(
                float(priors.get("ranking_penalty") or 0) + (0.15 if res == "falsified" else 0.08),
                4,
            )
            # Re-open critical management questions
            for q in doc.get("questions") or []:
                if not isinstance(q, dict):
                    continue
                if q.get("id") in bump_ids or (
                    q.get("pack") == "management" and q.get("critical")
                ):
                    if q.get("status") == "answered":
                        q["status"] = "open"
                        q["answer_note"] = (
                            f"Reopened after thesis outcome={res}: {note[:80]}"
                        )
            # Section prior: management/cash_flow need attention
            for sec_name in ("management", "cash_flow", "valuation", "risks"):
                sec = ((doc.get("sections") or {}).get(sec_name)) or {}
                if isinstance(sec, dict):
                    gaps = list(sec.get("gaps") or [])
                    bit = f"outcome_prior:{res} — re-examine {sec_name}"
                    if bit not in gaps:
                        gaps.append(bit)
                    sec["gaps"] = gaps[-12:]
                    (doc.setdefault("sections", {}))[sec_name] = sec
        elif res == "held":
            priors["ranking_bonus"] = round(
                min(0.12, float(priors.get("ranking_bonus") or 0) + 0.04),
                4,
            )

        # Experience-cited line for next thesis
        cites = list(priors.get("citations") or [])
        cites.append(
            {
                "at": utc_now_iso(),
                "result": res,
                "note": (note or "")[:160],
            }
        )
        priors["citations"] = cites[-12:]
        doc["outcome_priors"] = priors
        if isinstance(doc.get("thesis"), dict) and cites:
            thesis = dict(doc["thesis"])
            last = cites[-1]
            line = (
                f"Prior outcome: {last.get('result')} — {last.get('note') or 'checkpoint'}."
            )
            if line not in (thesis.get("summary") or ""):
                thesis["summary"] = (thesis.get("summary") or "") + f" {line}"
            thesis["outcome_citations"] = cites[-4:]
            doc["thesis"] = thesis

    def list_symbols(self, *, program_id: str = DEFAULT_PROGRAM) -> list[str]:
        """Known researched symbols for cooperative worker batches (IRA.21)."""
        return list(self._store.list_symbols(program_id=program_id) or [])

    def symbols_needing_work(
        self,
        *,
        program_id: str = DEFAULT_PROGRAM,
        limit: int = 12,
    ) -> list[str]:
        """IRA.26 — symbols with open questions or critical missing inputs first."""
        scored: list[tuple[int, str]] = []
        for sym in self._store.list_symbols(program_id=program_id):
            doc = self._store.get(sym, program_id=program_id)
            if not isinstance(doc, dict):
                continue
            score = 0
            if doc.get("critical_flags"):
                score += 100
            work = schedule_research_questions(doc, limit=8)
            open_n = sum(1 for w in work if w.get("kind") in {"question", "missing_input"})
            score += open_n * 10
            if stale_sections(doc):
                score += 5
            if score:
                scored.append((score, sym))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [s for _, s in scored[: max(1, int(limit))]]

    def research_bias_map(
        self,
        symbols: list[str] | None = None,
        *,
        program_id: str = DEFAULT_PROGRAM,
    ) -> dict[str, float]:
        """Soft ranking nudge: researched/MVR-ready > thin/stale (IRA.16)."""
        out: dict[str, float] = {}
        want = [normalize_symbol(s) for s in (symbols or []) if str(s).strip()]
        if not want:
            want = self._store.list_symbols(program_id=program_id)
        for sym in want:
            doc = self._store.get(sym, program_id=program_id)
            if doc is None:
                continue
            aw_cov = coverage_pct(doc)
            mvr = mvr_status(doc)
            stale = stale_sections(doc)
            bias = 0.0
            if mvr.get("satisfied"):
                bias += 0.12
            bias += min(0.10, float(aw_cov) / 500.0)  # up to +0.1 at 50%+
            if len(stale) >= 3:
                bias -= 0.08
            # IRA.29 — ThesisOutcome priors
            priors = doc.get("outcome_priors") if isinstance(doc.get("outcome_priors"), dict) else {}
            bias -= float(priors.get("ranking_penalty") or 0)
            bias += float(priors.get("ranking_bonus") or 0)
            if doc.get("critical_flags"):
                bias -= 0.2
            if bias:
                out[sym] = round(bias, 4)
        return out

    def refresh_stale(
        self,
        symbol: str | None = None,
        *,
        program_id: str = DEFAULT_PROGRAM,
        max_symbols: int = 8,
        force_sections: list[str] | None = None,
    ) -> dict[str, Any]:
        """IRA.7 — incremental TTL refresh (no full rebuild unless MVR incomplete)."""
        if symbol:
            targets = [normalize_symbol(symbol)]
        else:
            targets = self._store.list_symbols(program_id=program_id)[: max(1, int(max_symbols))]
        refreshed: list[dict[str, Any]] = []
        for sym in targets:
            doc = self.get_or_create(sym, program_id=program_id)
            flipped = mark_stale_sections(doc)
            stale = list(force_sections or []) or stale_sections(doc)
            if not stale and not flipped and not force_sections:
                continue
            # Prefer incremental section rewrite; force_sections always incremental (F1).
            if force_sections:
                doc = self._incremental_refresh(doc, list(force_sections))
            elif doc.get("phase") in {PHASE_MVR_READY, PHASE_THESIS_READY}:
                doc = self._incremental_refresh(doc, stale)
            else:
                doc = self._run_mvr_pass(doc)
            refreshed.append(
                {
                    "symbol": sym,
                    "flipped_stale": flipped,
                    "refreshed": list(force_sections or stale),
                    "phase": doc.get("phase"),
                    "coverage": coverage_pct(doc),
                }
            )
        return {
            "ok": True,
            "program_id": program_id,
            "count": len(refreshed),
            "items": refreshed,
        }

    def apply_operator_snapshot(
        self,
        symbol: str,
        fields: dict[str, Any],
        *,
        program_id: str = DEFAULT_PROGRAM,
        as_of: str | None = None,
        note: str = "",
        evidence_confidence: str = "verified",
        auto_refresh: bool = True,
    ) -> dict[str, Any]:
        """IRA F1 — ladder layer 1: operator snapshot → memory → incremental sections."""
        from atlas.investment.screener_signals import publish_snapshot

        sym = normalize_symbol(symbol)
        conf = str(evidence_confidence or "verified").strip().lower()
        if conf not in {"verified", "estimated"}:
            conf = "verified"
        payload = {k: v for k, v in (fields or {}).items() if v is not None and v != ""}
        payload["evidence_confidence"] = conf
        payload["source"] = "operator_snapshot"
        payload["method"] = "operator_snapshot"
        if as_of:
            payload["as_of"] = as_of
        snap = publish_snapshot(
            {sym: payload},
            program_id=program_id,
            source="operator_snapshot",
            as_of=as_of,
            note=note or "Operator research snapshot (IRA F1)",
        )
        # Ensure dossier exists
        doc = self.get_or_create(sym, program_id=program_id)
        self._add_memory(
            doc,
            observation=f"Operator snapshot applied ({', '.join(sorted(payload)[:8])})",
            interpretation=(
                f"Ladder layer 1 evidence · confidence={conf}. "
                "Incremental section refresh only — no full rebuild."
            ),
            evidence={
                "level": "F",
                "source": "operator_snapshot",
                "as_of": as_of or payload.get("as_of"),
                "fields": {k: payload[k] for k in payload if k not in {"source", "method"}},
                "evidence_confidence": conf,
            },
            confidence=CONF_LOW if conf == "verified" else CONF_VERY_LOW,
        )
        self._store.save(doc)

        impacted = sections_impacted_by_fields(payload)
        refresh_result = None
        if auto_refresh:
            if not impacted:
                impacted = ["valuation", "cash_flow", "financial_health"]
            # Ensure MVR exists once so incremental path has sections
            if doc.get("phase") in {PHASE_QUEUED, None, ""} or not doc.get("thesis"):
                self.start(sym, program_id=program_id, mode="mvr", force=True, trigger="operator_snapshot")
            refresh_result = self.refresh_stale(
                sym,
                program_id=program_id,
                force_sections=impacted,
            )
            # Patch thesis summary lightly after valuation refresh
            doc = self.get_or_create(sym, program_id=program_id)
            val = doc.get("valuation") if isinstance(doc.get("valuation"), dict) else {}
            if isinstance(doc.get("thesis"), dict) and val:
                thesis = dict(doc["thesis"])
                stance = thesis_stance_from_valuation(val)
                thesis["stance"] = stance
                mos = val.get("margin_of_safety_pct")
                method_label = val.get("method_label") or val.get("method")
                thesis["summary"] = (
                    (thesis.get("summary") or "").split("Current conclusion:")[0].rstrip()
                    + f" Current conclusion: {str(stance).replace('_', ' ').upper()} — "
                    + (
                        f"MoS={mos}% via {method_label}."
                        if mos is not None
                        else f"MoS unknown ({method_label})."
                    )
                    + f" Evidence confidence={conf}."
                )
                thesis["as_of"] = utc_now_iso()
                thesis["valuation_id"] = val.get("id")
                doc["thesis"] = thesis
                self._store.save(doc)

        return {
            "ok": True,
            "symbol": sym,
            "snapshot": {"count": snap.get("count"), "as_of": snap.get("as_of")},
            "impacted_sections": impacted,
            "refresh": refresh_result,
            "awareness": self.awareness(sym, program_id=program_id),
        }

    def apply_filing_refs(
        self,
        symbol: str,
        filings: list[dict[str, Any]],
        *,
        program_id: str = DEFAULT_PROGRAM,
        as_of: str | None = None,
        note: str = "",
        auto_refresh: bool = True,
    ) -> dict[str, Any]:
        """IRA.24 — ladder layer 3: filing refs (no scrape) → memory → incremental sections."""
        from atlas.investment import filings as fl_mod

        sym = normalize_symbol(symbol)
        cleaned: list[dict[str, Any]] = []
        for raw in filings or []:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or raw.get("name") or "").strip()
            if not title:
                continue
            kind = str(raw.get("kind") or "filing").strip()
            level = level_for_filing(kind, source=str(raw.get("source") or "operator"))
            cleaned.append(
                {
                    "title": title,
                    "kind": kind,
                    "as_of": str(raw.get("as_of") or raw.get("date") or as_of or ""),
                    "url": str(raw.get("url") or ""),
                    "source": str(raw.get("source") or "operator_snapshot"),
                    "period": str(raw.get("period") or ""),
                    "evidence_level": level,
                }
            )
        if not cleaned:
            return {"ok": False, "reason": "no_filings", "symbol": sym}

        snap = fl_mod.publish_snapshot(
            {sym: cleaned},
            program_id=program_id,
            source="operator_snapshot",
            as_of=as_of,
            note=note or "Operator filing refs (IRA.24) — not a scrape",
        )
        doc = self.get_or_create(sym, program_id=program_id)
        levels = sorted({c["evidence_level"] for c in cleaned})
        self._add_memory(
            doc,
            observation=f"Filing refs attached ({len(cleaned)}): " + "; ".join(
                c["title"][:60] for c in cleaned[:3]
            ),
            interpretation=(
                f"Ladder layer 3 refs · evidence levels {','.join(levels)}. "
                "Titles/provenance only — line items not extracted."
            ),
            evidence={"level": levels[0] if len(levels) == 1 else "A" if "A" in levels else levels[0],
                      "filings": cleaned, "levels": levels},
            confidence=CONF_LOW,
        )
        # Enrich management evidence with filing refs
        mgmt = (doc.get("sections") or {}).get("management") or {}
        fields = dict((mgmt.get("fields") if isinstance(mgmt, dict) else {}) or {})
        ev_list = list(fields.get("evidence") or []) if isinstance(fields.get("evidence"), list) else []
        for c in cleaned:
            ev_list.append(
                make_evidence(
                    claim=f"Filing ref: {c['title'][:80]}",
                    level=c["evidence_level"],
                    status="ref_only",
                    source=c.get("source") or "operator_snapshot",
                    ref=c.get("url") or c.get("title"),
                    confidence=CONF_LOW,
                )
            )
        fields["evidence"] = ev_list[-12:]
        fields["filings_refs"] = cleaned[:6]
        mark_section(
            doc,
            "management",
            fields=fields,
            confidence=CONF_LOW if any(c["evidence_level"] in {"A", "B"} for c in cleaned) else CONF_VERY_LOW,
            gaps=["management: filing refs present — capital allocation still not scored"],
            sources=["filings", "operator_snapshot"],
            status="present",
        )
        self._store.save(doc)

        impacted = sections_impacted_by_filings(cleaned)
        refresh_result = None
        if auto_refresh:
            if doc.get("phase") in {PHASE_QUEUED, None, ""} or not doc.get("thesis"):
                self.start(sym, program_id=program_id, mode="mvr", force=True, trigger="filing_refs")
            refresh_result = self.refresh_stale(
                sym, program_id=program_id, force_sections=impacted
            )
            # Re-apply management evidence after refresh may overwrite — merge again lightly
            doc = self.get_or_create(sym, program_id=program_id)
            mgmt2 = (doc.get("sections") or {}).get("management") or {}
            f2 = dict((mgmt2.get("fields") if isinstance(mgmt2, dict) else {}) or {})
            f2["filings_refs"] = cleaned[:6]
            f2["evidence"] = ev_list[-12:]
            mark_section(
                doc,
                "management",
                fields=f2,
                confidence=CONF_LOW if any(c["evidence_level"] in {"A", "B"} for c in cleaned) else CONF_VERY_LOW,
                gaps=["management: filing refs present — capital allocation still not scored"],
                sources=["filings", "operator_snapshot"],
                status="present",
            )
            cap_confidence_without_evidence(doc)
            self._store.save(doc)

        return {
            "ok": True,
            "symbol": sym,
            "filings_count": len(cleaned),
            "evidence_levels": levels,
            "snapshot": {"count": snap.get("count"), "as_of": snap.get("as_of")},
            "impacted_sections": impacted,
            "refresh": refresh_result,
            "awareness": self.awareness(sym, program_id=program_id),
        }

    def raise_critical_flag(
        self,
        symbol: str,
        *,
        text: str,
        kind: str = "thesis_invalidating",
        program_id: str = DEFAULT_PROGRAM,
        affects: list[str] | None = None,
    ) -> dict[str, Any]:
        """IRA.26b — critical evidence that can outweigh checklist completion."""
        sym = normalize_symbol(symbol)
        doc = self.get_or_create(sym, program_id=program_id)
        kind_n = str(kind or "thesis_invalidating").strip().lower()
        if kind_n not in {
            "thesis_invalidating",
            "valuation_irrelevant",
            "governance",
            "covenant",
            "fraud",
        }:
            kind_n = "thesis_invalidating"
        flag = {
            "id": f"cf-{len(doc.get('critical_flags') or []) + 1}",
            "at": utc_now_iso(),
            "kind": kind_n,
            "text": str(text or "").strip() or "Critical evidence raised",
            "affects": list(affects or ["thesis", "risks"]),
            "source": "operator",
        }
        flags = list(doc.get("critical_flags") or [])
        flags.append(flag)
        doc["critical_flags"] = flags[-20:]
        self._add_memory(
            doc,
            observation=f"Critical flag ({kind_n}): {flag['text'][:160]}",
            interpretation=(
                "Critical evidence outweighs completed checklist fields. "
                "Paper buys blocked while flag is active."
            ),
            evidence={"level": "F", "critical_flag": flag},
            confidence=CONF_LOW,
        )
        # Risks section + thesis weaken
        risks_sec = (doc.get("sections") or {}).get("risks") or {}
        rfields = dict((risks_sec.get("fields") if isinstance(risks_sec, dict) else {}) or {})
        top = list(rfields.get("top_risks") or [])
        top.insert(0, f"CRITICAL ({kind_n}): {flag['text']}")
        rfields["top_risks"] = top[:10]
        mark_section(
            doc,
            "risks",
            fields=rfields,
            confidence=CONF_LOW,
            gaps=[],
            sources=["critical_flag", "operator"],
            status="present",
        )
        if isinstance(doc.get("thesis"), dict) and kind_n in {
            "thesis_invalidating",
            "fraud",
            "governance",
        }:
            thesis = dict(doc["thesis"])
            thesis["stance"] = "avoid"
            thesis["summary"] = (
                (thesis.get("summary") or "")
                + f" CRITICAL FLAG: {flag['text']} — thesis avoid until cleared."
            )
            thesis["as_of"] = utc_now_iso()
            doc["thesis"] = thesis
        doc["next"] = "resolve_critical_flag"
        self._store.save(doc)
        return {
            "ok": True,
            "symbol": sym,
            "flag": flag,
            "awareness": self.awareness(sym, program_id=program_id),
        }

    def apply_management_pack(
        self,
        symbol: str,
        answers: dict[str, Any] | list[dict[str, Any]],
        *,
        program_id: str = DEFAULT_PROGRAM,
        operator_note: str = "",
        evidence_level: str = "F",
        auto_refresh: bool = True,
    ) -> dict[str, Any]:
        """IRA F3 — management / capital-allocation checklist → section + questions."""
        sym = normalize_symbol(symbol)
        doc = self.get_or_create(sym, program_id=program_id)
        pack = mgmt_pack.apply_management_answers(
            doc.get("management_pack") if isinstance(doc.get("management_pack"), dict) else None,
            answers,
            evidence_level=evidence_level,
            operator_note=operator_note or None,
        )
        doc["management_pack"] = pack
        self._ensure_management_questions(doc)

        # Sync ResearchQuestions linked to checklist ids
        by_check = {
            str(i.get("id")): i
            for i in (pack.get("items") or [])
            if isinstance(i, dict) and i.get("id")
        }
        for q in doc.get("questions") or []:
            if not isinstance(q, dict) or q.get("pack") != "management":
                continue
            item = by_check.get(str(q.get("checklist_id") or ""))
            if not item or not item.get("answer"):
                continue
            st = str(item.get("status") or "answered")
            if st in {"answered", "weak"}:
                q["status"] = "answered" if st == "answered" else "answered_gap"
                q["answer_note"] = str(item.get("answer"))[:240]
                q["answered_at"] = item.get("updated_at") or utc_now_iso()
            elif st == "blocked":
                q["status"] = "blocked"
                q["answer_note"] = str(item.get("answer"))[:240]

        built = mgmt_pack.management_section_fields(pack)
        prev = (doc.get("sections") or {}).get("management") or {}
        prev_fields = dict((prev.get("fields") if isinstance(prev, dict) else {}) or {})
        fields = dict(built["fields"])
        if prev_fields.get("filings_refs"):
            fields["filings_refs"] = prev_fields["filings_refs"]
        filing_ev = [
            e
            for e in (prev_fields.get("evidence") or [])
            if isinstance(e, dict) and str(e.get("claim") or "").startswith("Filing ref:")
        ]
        if filing_ev:
            fields["evidence"] = list(fields.get("evidence") or []) + filing_ev
            fields["evidence"] = fields["evidence"][-16:]
        mark_section(
            doc,
            "management",
            fields=fields,
            confidence=built["confidence"],
            gaps=list(built.get("gaps") or []),
            sources=list(built.get("sources") or ["management_pack", "operator"]),
            status="present",
        )
        answered_n = sum(
            1
            for i in (pack.get("items") or [])
            if isinstance(i, dict) and i.get("status") in {"answered", "weak"} and i.get("answer")
        )
        self._add_memory(
            doc,
            observation=f"Management pack updated ({answered_n} answered items)",
            interpretation=(
                "F3 checklist — operator judgments on capital allocation / governance. "
                "Does not invent ROIC history; gaps remain explicit."
            ),
            evidence={"level": evidence_level, "pack_summary": fields.get("checklist_summary")},
            confidence=CONF_LOW if answered_n else CONF_VERY_LOW,
        )
        self._store.save(doc)

        refresh_result = None
        if auto_refresh:
            if doc.get("phase") in {PHASE_QUEUED, None, ""} or not doc.get("thesis"):
                self.start(
                    sym,
                    program_id=program_id,
                    mode="mvr",
                    force=True,
                    trigger="management_pack",
                )
                # start rebuilds from management_pack; re-sync answered question notes
                doc = self.get_or_create(sym, program_id=program_id)
                doc["management_pack"] = pack
                for q in doc.get("questions") or []:
                    if not isinstance(q, dict) or q.get("pack") != "management":
                        continue
                    item = by_check.get(str(q.get("checklist_id") or ""))
                    if not item or not item.get("answer"):
                        continue
                    st = str(item.get("status") or "answered")
                    if st in {"answered", "weak"}:
                        q["status"] = "answered" if st == "answered" else "answered_gap"
                        q["answer_note"] = str(item.get("answer"))[:240]
                built2 = mgmt_pack.management_section_fields(pack)
                mark_section(
                    doc,
                    "management",
                    fields=built2["fields"],
                    confidence=built2["confidence"],
                    gaps=list(built2.get("gaps") or []),
                    sources=list(built2.get("sources") or ["management_pack", "operator"]),
                    status="present",
                )
                self._store.save(doc)
                refresh_result = {"started": True, "sections": ["management"]}
            else:
                refresh_result = self.refresh_stale(
                    sym, program_id=program_id, force_sections=["management", "risks"]
                )

        return {
            "ok": True,
            "symbol": sym,
            "answered": answered_n,
            "management_pack": pack,
            "refresh": refresh_result,
            "awareness": self.awareness(sym, program_id=program_id),
        }

    def gate_buy(
        self,
        symbol: str,
        *,
        program_id: str = DEFAULT_PROGRAM,
        require_mvr: bool = True,
        require_thesis: bool = True,
        require_mos: bool | None = None,
        min_coverage: float = 0.0,
        min_mos_pct: float | None = None,
        mos_mode: str | None = None,
    ) -> dict[str, Any]:
        """Research-based gate for Decision Simulation / paper trading.

        ``mos_mode``:
        - ``off`` — ignore MoS
        - ``when_available`` — if MoS known, require >= min; if unknown, force Watch (block)
        - ``required`` — same as when_available but explicit
        - ``soft`` — if MoS known and negative, block; if unknown, allow
        """
        sym = normalize_symbol(symbol)
        aw = self.awareness(sym, program_id=program_id)
        reasons: list[str] = []
        if require_mvr and not aw.get("mvr_satisfied"):
            reasons.append(
                "mvr_incomplete:" + ",".join((aw.get("mvr") or {}).get("missing") or [])
            )
        thesis = aw.get("thesis")
        if require_thesis and not (isinstance(thesis, dict) and thesis.get("id")):
            reasons.append("thesis_missing")
        if min_coverage and float(aw.get("coverage") or 0) < float(min_coverage):
            reasons.append(f"coverage_below_{min_coverage}")

        val = aw.get("valuation") if isinstance(aw.get("valuation"), dict) else {}
        mode = (mos_mode or "").strip().lower()
        if not mode:
            if require_mos is True:
                mode = "required"
            elif require_mos is False:
                mode = "off"
            else:
                # IRA.12 default: MoS when valuation present → else Watch
                mode = "when_available" if val else "off"
        floor = float(min_mos_pct if min_mos_pct is not None else MIN_MOS_BUY_PCT)
        mos = val.get("margin_of_safety_pct") if val else None
        if mode in {"when_available", "required"}:
            if mos is None:
                reasons.append("mos_unknown")
            else:
                try:
                    if float(mos) < floor:
                        reasons.append(f"mos_below_{floor}")
                except (TypeError, ValueError):
                    reasons.append("mos_unknown")
        elif mode == "soft" and mos is not None:
            try:
                if float(mos) < 0:
                    reasons.append("mos_negative")
            except (TypeError, ValueError):
                pass

        stance = (thesis or {}).get("stance") if isinstance(thesis, dict) else None
        if stance == "avoid":
            reasons.append("thesis_avoid")

        # IRA.26b — critical evidence outweighs MVR checklist
        flags = (aw.get("critical_flags") or {}).get("active") or []
        for flg in flags:
            if not isinstance(flg, dict):
                continue
            kind = str(flg.get("kind") or "")
            if kind == "thesis_invalidating":
                reasons.append("critical_flag:thesis_invalidating")
            elif kind == "valuation_irrelevant":
                reasons.append("critical_flag:valuation_irrelevant")

        allowed = not reasons
        action = "buy_ok" if allowed else "hold_research"
        if not allowed and (
            "mos_unknown" in reasons
            or "mos_below_" in ",".join(reasons)
            or any("critical_flag" in r for r in reasons)
        ):
            action = "watch"
        if any("thesis_invalidating" in r for r in reasons):
            action = "avoid"
        return {
            "allowed": allowed,
            "action": action,
            "reasons": reasons,
            "symbol": sym,
            "mos_mode": mode,
            "mos": mos,
            "awareness": {
                "phase": aw.get("phase"),
                "coverage": aw.get("coverage"),
                "confidence": aw.get("confidence"),
                "mvr_satisfied": aw.get("mvr_satisfied"),
                "stance": stance,
            },
        }

    def evaluate_outcomes(
        self,
        *,
        program_id: str = DEFAULT_PROGRAM,
        max_symbols: int = 20,
        checkpoint_hours: float = 24.0,
        before_each: Any | None = None,
    ) -> dict[str, Any]:
        """IRA.14 — timed thesis checkpoints for open / recent dossiers."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        evaluated: list[dict[str, Any]] = []
        for sym in self._store.list_symbols(program_id=program_id)[: max(1, int(max_symbols))]:
            if callable(before_each):
                before_each(sym)
            doc = self._store.get(sym, program_id=program_id)
            if not isinstance(doc, dict) or not doc.get("thesis"):
                continue
            outs = list(doc.get("outcomes") or [])
            last = outs[-1] if outs else None
            last_at = None
            if isinstance(last, dict) and last.get("at"):
                try:
                    last_at = datetime.fromisoformat(str(last["at"]).replace("Z", "+00:00"))
                except Exception:  # noqa: BLE001
                    last_at = None
            need = last is None or (
                last_at is not None
                and (now - last_at) >= timedelta(hours=float(checkpoint_hours))
            )
            if not need:
                continue
            stance = (doc.get("thesis") or {}).get("stance") or "watch"
            note = f"Timed checkpoint — thesis stance={stance}; review falsifiers"
            outcome = self.record_outcome(
                sym,
                program_id=program_id,
                result="observed",
                note=note,
                trade={"kind": "checkpoint", "stance": stance},
            )
            evaluated.append({"symbol": sym, "outcome": outcome})
        return {
            "ok": True,
            "count": len(evaluated),
            "items": evaluated,
            "program_id": program_id,
        }

    def weekly_learning_digest(
        self,
        *,
        program_id: str = DEFAULT_PROGRAM,
        limit: int = 20,
    ) -> dict[str, Any]:
        """IRA.17 — belief changes / lessons rollup for weekly email."""
        dig = self.daily_digest(program_id=program_id, limit=limit)
        belief_changes: list[str] = []
        for aw in dig.get("studied") or []:
            sym = aw.get("symbol")
            doc = self._store.get(str(sym or ""), program_id=program_id) or {}
            thesis = doc.get("thesis") if isinstance(doc.get("thesis"), dict) else {}
            outs = [o for o in (doc.get("outcomes") or []) if isinstance(o, dict)]
            weakened = sum(1 for o in outs if o.get("result") == "weakened")
            held = sum(1 for o in outs if o.get("result") == "held")
            falsified = sum(1 for o in outs if o.get("result") == "falsified")
            if weakened or falsified or held:
                belief_changes.append(
                    f"{sym}: stance={thesis.get('stance')} · "
                    f"held={held} weakened={weakened} falsified={falsified}"
                )
            for mem in list(doc.get("memories") or [])[-2:]:
                if isinstance(mem, dict) and "outcome" in str(mem.get("interpretation") or "").lower():
                    belief_changes.append(
                        f"{sym}: {mem.get('observation') or mem.get('interpretation')}"
                    )
        return {
            **dig,
            "belief_changes": belief_changes[:limit],
            "kind": "weekly_research_learning",
        }

    def writeback_lessons_to_mentor(
        self,
        *,
        experience_os: Any,
        program_id: str = DEFAULT_PROGRAM,
        limit: int = 8,
        portfolio_key: str | None = None,
    ) -> dict[str, Any]:
        """IRA.15 — push recent ThesisOutcomes into Experience OS journals."""
        if experience_os is None or not hasattr(experience_os, "journal"):
            return {"ok": False, "reason": "experience_os_unavailable", "written": 0}
        written: list[dict[str, Any]] = []
        for aw in self.list_researched(program_id=program_id)[:40]:
            if len(written) >= limit:
                break
            sym = str(aw.get("symbol") or "")
            doc = self._store.get(sym, program_id=program_id) or {}
            for out in reversed(list(doc.get("outcomes") or [])):
                if len(written) >= limit:
                    break
                if not isinstance(out, dict):
                    continue
                if out.get("mentor_written"):
                    continue
                result = str(out.get("result") or "observed")
                if result not in {"held", "weakened", "falsified"}:
                    continue
                thesis = doc.get("thesis") if isinstance(doc.get("thesis"), dict) else {}
                title = f"Thesis outcome {sym}: {result}"
                try:
                    jr = experience_os.journal(
                        title=title,
                        observation=str(out.get("note") or f"{sym} outcome {result}"),
                        decision=f"Thesis {thesis.get('id')} stance={thesis.get('stance')}",
                        outcome=result,
                        reflection=(
                            f"Falsifiers: {', '.join(str(x) for x in (thesis.get('falsifiers') or [])[:3])}"
                            or "Review assumptions on next plan"
                        ),
                        lesson=(
                            f"Last time thesis on {sym} was tagged {result}; "
                            "cite this before sizing again."
                        ),
                        reasoning="IRA.15 ThesisOutcome → Mentor writeback",
                        domain="markets",
                        tags=[
                            "ira",
                            "thesis_outcome",
                            result,
                            sym.lower().replace(".ns", ""),
                            *(["portfolio:" + portfolio_key] if portfolio_key else []),
                        ],
                        recommendations=[
                            {
                                "kind": "research",
                                "text": f"Re-check falsifiers for {sym} before buy",
                            }
                        ],
                        metadata={
                            "symbol": sym,
                            "thesis_id": thesis.get("id"),
                            "outcome_id": out.get("id"),
                            "program_id": program_id,
                        },
                        strict=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("mentor writeback failed for %s: %s", sym, exc)
                    continue
                out["mentor_written"] = True
                out["mentor_at"] = utc_now_iso()
                written.append({"symbol": sym, "outcome_id": out.get("id"), "journal": jr})
            # persist mentor_written flags
            doc["outcomes"] = list(doc.get("outcomes") or [])
            self._store.save(doc)
        return {"ok": True, "written": len(written), "items": written}

    # --- internal MVR pass ----------------------------------------------

    def _run_mvr_pass(self, doc: dict[str, Any]) -> dict[str, Any]:
        sym = str(doc.get("symbol") or "")
        self._mark_plan(doc, "collect", "doing")
        doc["doing_now"] = "Collecting quality seeds + filing refs"

        ratios = {}
        try:
            ratios = qs.ratios_for_symbol(sym) or {}
        except Exception:  # noqa: BLE001
            ratios = {}
        filing_refs = []
        try:
            filing_refs = fl.filings_for_symbol(sym) or fl.hermetic_filings_for(sym)
        except Exception:  # noqa: BLE001
            try:
                filing_refs = fl.hermetic_filings_for(sym)
            except Exception:  # noqa: BLE001
                filing_refs = []

        # Optional company profile (config_seed → filings_seed → fundamentals gap)
        profile: dict[str, Any] = {}
        fund_status: dict[str, Any] = {"tried": [], "used": None}
        if self._companies is not None and hasattr(self._companies, "fetch"):
            for prov in ("config_seed", "filings_seed", "fundamentals"):
                try:
                    out = self._companies.fetch(sym, provider=prov)
                    fund_status["tried"].append({"provider": prov, "ok": True})
                    if isinstance(out, dict) and (out.get("profile") or {}).get("name"):
                        profile = out.get("profile") or {}
                        fund_status["used"] = prov
                        break
                    if isinstance(out, dict) and out.get("profile"):
                        profile = out.get("profile") or profile
                        fund_status["used"] = fund_status["used"] or prov
                except Exception as exc:  # noqa: BLE001 - CapabilityGap expected
                    fund_status["tried"].append(
                        {
                            "provider": prov,
                            "ok": False,
                            "gap": str(getattr(exc, "capability", None) or type(exc).__name__),
                            "detail": str(exc)[:200],
                        }
                    )
            if not fund_status["used"]:
                doc.setdefault("blocked_on", []).append("company_data:no_live_profile")
        doc["fundamentals_status"] = fund_status

        # IRA.19 — midcap hint + sector pack when config_seed empty
        hint_profile = packs.enrich_profile_from_hint(sym)
        if hint_profile and not profile.get("name"):
            profile = {**hint_profile, **{k: v for k, v in profile.items() if v}}
            doc.setdefault("known_knowns", []).append(
                f"hint:{hint_profile.get('source') or 'atlas_midcap_hint'}"
            )
        sector_pack = packs.pack_for(
            sym, sector=str(profile.get("sector") or ratios.get("sector") or "")
        )
        if sector_pack:
            doc["pack"] = sector_pack.get("id")
            # Append pack questions once
            existing_texts = {
                str(q.get("text") or "") for q in (doc.get("questions") or []) if isinstance(q, dict)
            }
            qs_list = list(doc.get("questions") or [])
            for i, text in enumerate(sector_pack.get("extra_questions") or []):
                if text in existing_texts:
                    continue
                qs_list.append(
                    {
                        "id": f"pack-q{i+1}",
                        "symbol": sym,
                        "text": text,
                        "status": "open",
                        "created_at": utc_now_iso(),
                        "answered_at": None,
                        "memory_ids": [],
                        "pack": sector_pack.get("id"),
                        "critical": i < 2,
                    }
                )
            doc["questions"] = qs_list
            doc["watch_items"] = list(
                dict.fromkeys(
                    list(hint_profile.get("watch_items") or [])
                    + list(sector_pack.get("risk_lenses") or [])
                    + list(sector_pack.get("primary_kpis") or [])[:4]
                )
            )[:12]

        self._mark_plan(doc, "collect", "done")
        self._add_memory(
            doc,
            observation=f"Collected seeds for {sym}",
            interpretation=(
                "Hermetic/operator/hint data only — not live filings scrape"
                + (f"; pack={sector_pack.get('id')}" if sector_pack else "")
            ),
            evidence={
                "ratios": ratios,
                "filings_count": len(filing_refs),
                "hint": bool(hint_profile),
                "pack": (sector_pack or {}).get("id"),
            },
            confidence=CONF_LOW,
        )

        # Business
        self._mark_plan(doc, "business", "doing")
        doc["doing_now"] = "Sketching business section"
        name = str(profile.get("name") or hint_profile.get("name") or sym)
        sector = str(
            profile.get("sector")
            or ratios.get("sector")
            or hint_profile.get("sector")
            or "unknown"
        )
        biz_gaps = []
        if sector == "unknown":
            biz_gaps.append(
                "sector unknown — business coverage capped at 10% until classified"
            )
        if not sector_pack and sector != "unknown":
            biz_gaps.append("no sector intelligence pack matched — thesis may stay generic")
        if not ratios:
            biz_gaps.append("no quality_seed ratios — PE/ROE/FCF unknown until operator snapshot")
        summary = (
            profile.get("knowledge_text")
            or " ".join(profile.get("facts") or [])
            or f"{name} ({sym}) — MVR stub from available seeds"
        )
        subsector = str(
            profile.get("subsector") or hint_profile.get("subsector") or ""
        ).strip()
        if subsector and subsector.lower() not in summary.lower():
            summary = f"{summary} Subsector hint: {subsector}."
        if sector_pack:
            kpis = list(sector_pack.get("primary_kpis") or [])[:4]
            if kpis:
                summary = f"{summary} Sector KPIs to verify: {'; '.join(kpis)}."
        mark_section(
            doc,
            "business",
            fields={
                "name": name,
                "sector": sector,
                "subsector": subsector or None,
                "summary": summary,
                "pack_id": (sector_pack or {}).get("id"),
                "primary_kpis": list((sector_pack or {}).get("primary_kpis") or [])[:8],
            },
            confidence=CONF_MEDIUM if sector != "unknown" and hint_profile else (
                CONF_MEDIUM if sector != "unknown" else CONF_LOW
            ),
            gaps=biz_gaps,
            sources=(
                ["quality_seed", "company_profile", "midcap_hint", "sector_pack"]
                if hint_profile or sector_pack
                else (["quality_seed", "company_profile"] if profile else ["quality_seed"])
            ),
            status="present",
        )
        if biz_gaps:
            self._answer_question(doc, 0, "Business sketch with gaps: " + "; ".join(biz_gaps), status="answered_gap")
        else:
            self._answer_question(doc, 0, "Business sketch formed from available seeds")
        self._mark_plan(doc, "business", "done")

        # Management — F3 pack (never invent capital-allocation history)
        # NOTE: keep sector_pack separate — do not overwrite with management_pack
        mgmt_doc = doc.get("management_pack")
        if not isinstance(mgmt_doc, dict):
            mgmt_doc = mgmt_pack.empty_management_pack()
            doc["management_pack"] = mgmt_doc
        # Preserve filing refs evidence if already attached
        prev_mgmt = (doc.get("sections") or {}).get("management") or {}
        prev_fields = dict((prev_mgmt.get("fields") if isinstance(prev_mgmt, dict) else {}) or {})
        mgmt_built = mgmt_pack.management_section_fields(mgmt_doc)
        fields = dict(mgmt_built["fields"])
        if prev_fields.get("filings_refs"):
            fields["filings_refs"] = prev_fields["filings_refs"]
        prev_ev = list(prev_fields.get("evidence") or [])
        filing_ev = [
            e for e in prev_ev
            if isinstance(e, dict) and str(e.get("claim") or "").startswith("Filing ref:")
        ]
        if filing_ev:
            fields["evidence"] = list(fields.get("evidence") or []) + filing_ev
            fields["evidence"] = fields["evidence"][-16:]
        # Sector-specific management behaviors as open evidence gaps
        if sector_pack:
            fields["sector_management_lenses"] = list(
                sector_pack.get("management_behaviors") or []
            )[:4]
        mark_section(
            doc,
            "management",
            fields=fields,
            confidence=mgmt_built["confidence"],
            gaps=list(mgmt_built.get("gaps") or [])
            or ["management: track record / capital allocation unknown"],
            sources=list(mgmt_built.get("sources") or ["management_pack"]),
            status="present",
        )
        answered_n = sum(
            1
            for i in (mgmt_doc.get("items") or [])
            if isinstance(i, dict) and i.get("status") in {"answered", "weak"} and i.get("answer")
        )
        self._answer_question(
            doc,
            1,
            (
                f"Management pack {answered_n} checklist items answered"
                if answered_n
                else "Management marked as known_unknown (explicit gap — use management pack)"
            ),
            status="answered" if answered_n >= 3 else "answered_gap",
        )

        # Financial health / cash flow from ratios
        self._mark_plan(doc, "cash_debt", "doing")
        de = ratios.get("debt_to_equity")
        roe = ratios.get("roe")
        roic = ratios.get("roic")
        fh_gaps = []
        if de is None:
            fh_gaps.append("debt_to_equity missing")
        fh_fields: dict[str, Any] = {
            "debt_to_equity": de,
            "roe": roe,
            "source": ratios.get("source") or "seed",
        }
        if roic is not None:
            fh_fields["roic"] = roic
        if ratios.get("operating_margin") is not None:
            fh_fields["operating_margin"] = ratios.get("operating_margin")
        if ratios.get("net_margin") is not None:
            fh_fields["net_margin"] = ratios.get("net_margin")
        mark_section(
            doc,
            "financial_health",
            fields=fh_fields,
            confidence=CONF_LOW if de is not None else CONF_VERY_LOW,
            gaps=fh_gaps or [],
            sources=["quality_seed"],
            status="present",
        )
        self._answer_question(doc, 2, f"Debt/equity seed={de}", status="answered_gap" if de is None else "answered")

        fcf = ratios.get("fcf")
        if fcf is not None:
            cf_gaps = []
            cf_fields = {"fcf": fcf, "note": "FCF from operator/screener seed"}
            cf_conf = CONF_LOW
            cf_sources = ["quality_seed"]
            self._answer_question(doc, 3, f"FCF seed={fcf}")
        else:
            cf_gaps = ["cash_flow: FCF history unknown — CapabilityGap until filings/fundamentals"]
            cf_fields = {"fcf": None, "note": "FCF unknown"}
            cf_conf = CONF_VERY_LOW
            cf_sources = ["gap"]
            self._answer_question(doc, 3, "FCF unknown — watch-only until data", status="answered_gap")
        mark_section(
            doc,
            "cash_flow",
            fields=cf_fields,
            confidence=cf_conf,
            gaps=cf_gaps,
            sources=cf_sources,
            status="present",
        )
        self._mark_plan(doc, "cash_debt", "done")

        # Profitability / growth when optional fields supplied (IRA.8)
        if any(ratios.get(k) is not None for k in ("roe", "roic", "operating_margin", "net_margin")):
            mark_section(
                doc,
                "profitability",
                fields={
                    k: ratios.get(k)
                    for k in ("roe", "roic", "operating_margin", "net_margin")
                    if ratios.get(k) is not None
                },
                confidence=CONF_LOW,
                gaps=[],
                sources=["quality_seed"],
                status="present",
            )
        rev_cagr = ratios.get("revenue_cagr")
        earn_cagr = ratios.get("earnings_cagr")

        # Valuation
        self._mark_plan(doc, "valuation", "doing")
        doc["doing_now"] = "Building valuation case"
        valuation = build_valuation_case(
            symbol=sym,
            ratios={
                **ratios,
                "roe": roe,
                "roic": roic,
                "debt_to_equity": de,
                "fcf": fcf,
                "pe": ratios.get("pe"),
                "sector": sector,
            },
            price=ratios.get("price"),
            shares=ratios.get("shares") or ratios.get("share_count"),
            valuation_id=f"val-{sym}",
        )
        doc["valuation"] = valuation
        val_fields = dict(valuation)
        if sector_pack and sector_pack.get("valuation_methods"):
            val_fields["sector_valuation_methods"] = list(
                sector_pack.get("valuation_methods") or []
            )[:4]
        mark_section(
            doc,
            "valuation",
            fields=val_fields,
            confidence=CONF_LOW
            if valuation.get("pe") is not None or valuation.get("fcf") is not None
            else CONF_VERY_LOW,
            gaps=list(valuation.get("gaps") or []),
            sources=["quality_seed", "screener_optional", "ira11"]
            + (["sector_pack"] if sector_pack else []),
            status="present",
        )
        mos = valuation.get("margin_of_safety_pct")
        self._answer_question(
            doc,
            4,
            f"Valuation {valuation.get('method')}; MoS="
            + (f"{mos}%" if mos is not None else "unknown"),
            status="answered" if mos is not None else "answered_gap",
        )
        self._mark_plan(doc, "valuation", "done")

        # Risks — sector lenses first (not generic data-risk twins)
        self._mark_plan(doc, "management_risks", "doing")
        risks: list[str] = []
        if sector_pack:
            for lens in (sector_pack.get("risk_lenses") or [])[:6]:
                risks.append(str(lens))
            for fm in (sector_pack.get("failure_modes") or [])[:2]:
                risks.append(f"Failure mode: {fm}")
        risks.append(
            "Data risk: hermetic/hint seeds may not reflect live fundamentals"
        )
        if de is not None and float(de) > 1.0:
            risks.append(f"Leverage: debt_to_equity seed={de}")
        mark_section(
            doc,
            "risks",
            fields={"top_risks": risks},
            confidence=CONF_LOW,
            gaps=[] if sector_pack else ["risks: no sector pack — lenses generic"],
            sources=["mvr", "sector_pack"] if sector_pack else ["mvr"],
            status="present",
        )
        self._answer_question(
            doc,
            5,
            (
                f"Sector risks from {(sector_pack or {}).get('id')} pack"
                if sector_pack
                else "Top impairment/data risks named (no sector pack)"
            ),
            status="answered" if sector_pack else "answered_gap",
        )
        self._mark_plan(doc, "management_risks", "done")

        # Moat lenses from pack (honest: lenses only, not scored moat)
        if sector_pack and sector_pack.get("moat_lenses"):
            mark_section(
                doc,
                "moat",
                fields={
                    "lenses": list(sector_pack.get("moat_lenses") or [])[:5],
                    "note": "Moat lenses from sector pack — not yet evidenced",
                },
                confidence=CONF_VERY_LOW,
                gaps=["moat: lenses named; evidence not verified"],
                sources=["sector_pack"],
                status="present",
            )
        # Leave pack questions open (honest) unless deep mode
        if doc.get("mode") != "deep":
            for q in doc.get("questions") or []:
                if isinstance(q, dict) and q.get("pack") and q.get("status") == "open":
                    q["status"] = "open"
                    q["answer_note"] = "Needs operator filings / deeper research mode"

        # Filing refs → ResearchMemory + growth (IRA.9)
        if filing_refs:
            doc.setdefault("known_knowns", []).append(f"filings_refs:{len(filing_refs)}")
            self._add_memory(
                doc,
                observation=f"Filing refs available ({len(filing_refs)})",
                interpretation="Provenance retained; line items not scraped",
                evidence={"filings": filing_refs[:6]},
                confidence=CONF_LOW,
            )
            growth_fields: dict[str, Any] = {"filings_refs": filing_refs[:4]}
            growth_gaps = ["growth CAGRs not computed from filings (refs only)"]
            if rev_cagr is not None:
                growth_fields["revenue_cagr"] = rev_cagr
                growth_gaps = []
            if earn_cagr is not None:
                growth_fields["earnings_cagr"] = earn_cagr
            mark_section(
                doc,
                "growth",
                fields=growth_fields,
                confidence=CONF_LOW if rev_cagr is not None else CONF_LOW,
                gaps=growth_gaps,
                sources=["filings", "quality_seed"] if rev_cagr is not None else ["filings"],
                status="present",
            )
        elif rev_cagr is not None or earn_cagr is not None:
            mark_section(
                doc,
                "growth",
                fields={
                    k: ratios.get(k)
                    for k in ("revenue_cagr", "earnings_cagr")
                    if ratios.get(k) is not None
                },
                confidence=CONF_LOW,
                gaps=[],
                sources=["quality_seed"],
                status="present",
            )

        # Thesis — sector-pack voice (IRA: distinctiveness without inventing facts)
        self._mark_plan(doc, "thesis", "doing")
        doc["doing_now"] = "Writing investment thesis"
        stance = thesis_stance_from_valuation(valuation)
        mos = valuation.get("margin_of_safety_pct")
        mos_bit = f"MoS={mos}% ({valuation.get('mos_method')})" if mos is not None else "MoS unknown"
        shallow: list[str] = []
        if valuation.get("method") == "insufficient" or mos is None:
            shallow.append("valuation / margin of safety")
        if fcf is None:
            shallow.append("free cash flow")
        if de is None:
            shallow.append("leverage")
        shallow.append("management capital allocation")
        if sector_pack:
            # Prefer pack-specific open gaps over generic WC line
            for kpi in list(sector_pack.get("primary_kpis") or [])[:2]:
                shallow.append(str(kpi).lower())
        else:
            shallow.append("working capital durability")
        drivers = packs.build_thesis_drivers(sector_pack, hint=hint_profile or None)
        thesis_bits = packs.thesis_fields_from_pack(
            sector_pack,
            name=name,
            sector=sector,
            subsector=subsector,
            stance=stance,
            mos_bit=mos_bit,
            method=str(valuation.get("method") or "insufficient"),
            shallow=shallow,
        )
        thesis = {
            "id": f"th-{sym}",
            "as_of": utc_now_iso(),
            "horizon": "12m",
            "stance": stance,
            "summary": thesis_bits["summary"],
            "bull": thesis_bits["bull"],
            "base": thesis_bits["base"],
            "bear": thesis_bits["bear"],
            "catalysts": thesis_bits["catalysts"],
            "falsifiers": thesis_bits["falsifiers"],
            "drivers": drivers,
            "interest": thesis_bits.get("interest"),
            "valuation_methods_note": thesis_bits.get("valuation_methods_note"),
            "moat_lenses": thesis_bits.get("moat_lenses"),
            "pack_id": (sector_pack or {}).get("id"),
            "linked_questions": [q.get("id") for q in doc.get("questions") or []],
            "valuation_id": valuation["id"],
        }
        thesis["distinctiveness"] = packs.thesis_distinctiveness(
            thesis, sector_pack, company_name=name
        )
        if (
            stance == "watch"
            and roe is not None
            and de is not None
            and float(de) < 0.8
            and float(roe) > 0.15
        ):
            thesis["stance"] = "watch_positive"
            thesis["summary"] += (
                f" Seed ROE={roe} and D/E={de} look reasonable on paper — "
                "still need MoS and management evidence before size."
            )
        doc["thesis"] = thesis
        self._mark_plan(doc, "thesis", "done")

        # IRA.20 — timing pack (outside MVR sections; never unlocks buys)
        doc["timing"] = self._timing_snapshot(sym)

        # IRA.25b — never allow medium+ confidence without evidence pointers
        cap_confidence_without_evidence(doc)

        # MVR gate
        self._mark_plan(doc, "mvr_gate", "doing")
        mvr = mvr_status(doc)
        doc["known_unknowns"] = [
            g
            for sec in (doc.get("sections") or {}).values()
            for g in (sec.get("gaps") or [])
        ][:20]
        if mvr.get("satisfied"):
            doc["phase"] = PHASE_THESIS_READY if doc.get("thesis") else PHASE_MVR_READY
            doc["next"] = "monitor_or_deepen"
            doc["doing_now"] = f"MVR satisfied — thesis {thesis.get('stance')}"
        else:
            doc["phase"] = PHASE_RESEARCHING
            doc["next"] = "complete_mvr:" + ",".join(mvr.get("missing") or [])
            doc["doing_now"] = "MVR incomplete"
        self._mark_plan(doc, "mvr_gate", "done")
        doc["updated_at"] = utc_now_iso()
        return self._store.save(doc)

    def _timing_snapshot(self, symbol: str) -> dict[str, Any]:
        """Labeled timing-only indicators; thesis_weight always 0."""
        if self._market is None or not hasattr(self._market, "bars_for"):
            return {
                "label": timing_pack.LABEL,
                "status": "no_market_reader",
                "honesty": timing_pack.HONESTY,
                "signals": {},
                "thesis_weight": 0,
                "note": "Market reader not bound — timing skipped",
            }
        try:
            out = self._market.bars_for(symbol, limit=120)
            bars = (out or {}).get("bars") if isinstance(out, dict) else None
            snap = timing_pack.timing_from_bars(bars if isinstance(bars, list) else [])
            if isinstance(out, dict):
                snap["provider"] = out.get("provider")
            return snap
        except Exception as exc:  # noqa: BLE001 - CapabilityGap / empty bars
            return {
                "label": timing_pack.LABEL,
                "status": "unavailable",
                "honesty": timing_pack.HONESTY,
                "signals": {},
                "thesis_weight": 0,
                "gap": str(getattr(exc, "capability", None) or type(exc).__name__),
                "detail": str(exc)[:200],
            }

    def _mark_plan(self, doc: dict[str, Any], step_id: str, status: str) -> None:
        plan = doc.setdefault("plan", default_research_plan(str(doc.get("symbol") or "")))
        steps = list(plan.get("steps") or [])
        for i, s in enumerate(steps):
            if isinstance(s, dict) and s.get("id") == step_id:
                s["status"] = status
                if status == "doing":
                    plan["cursor"] = i
                break
        plan["steps"] = steps
        plan["updated_at"] = utc_now_iso()
        doc["plan"] = plan

    def _answer_question(
        self,
        doc: dict[str, Any],
        index: int,
        note: str,
        *,
        status: str = "answered",
    ) -> None:
        qs_list = list(doc.get("questions") or [])
        if 0 <= index < len(qs_list) and isinstance(qs_list[index], dict):
            qs_list[index]["status"] = status
            qs_list[index]["answered_at"] = utc_now_iso()
            qs_list[index]["answer_note"] = note
        doc["questions"] = qs_list

    def _add_memory(
        self,
        doc: dict[str, Any],
        *,
        observation: str,
        interpretation: str,
        evidence: Any,
        confidence: str,
    ) -> None:
        mems = list(doc.get("memories") or [])
        mems.append(
            {
                "id": f"m-{len(mems) + 1}",
                "at": utc_now_iso(),
                "observation": observation,
                "interpretation": interpretation,
                "evidence": evidence,
                "confidence": confidence,
                "alternatives": [],
                "decision_note": "",
            }
        )
        doc["memories"] = mems[-100:]

    def _incremental_refresh(self, doc: dict[str, Any], sections: list[str]) -> dict[str, Any]:
        """Refresh selected sections from seeds/filings without resetting thesis id."""
        sym = str(doc.get("symbol") or "")
        doc["doing_now"] = f"Incremental refresh: {','.join(sections[:4])}"
        ratios: dict[str, Any] = {}
        try:
            ratios = qs.ratios_for_symbol(sym) or {}
        except Exception:  # noqa: BLE001
            ratios = {}
        filing_refs: list[Any] = []
        try:
            filing_refs = fl.filings_for_symbol(sym) or fl.hermetic_filings_for(sym)
        except Exception:  # noqa: BLE001
            filing_refs = []

        want = set(sections)
        de = ratios.get("debt_to_equity")
        if "financial_health" in want:
            mark_section(
                doc,
                "financial_health",
                fields={
                    "debt_to_equity": de,
                    "roe": ratios.get("roe"),
                    "roic": ratios.get("roic"),
                    "source": ratios.get("source") or "seed",
                },
                confidence=CONF_LOW if de is not None else CONF_VERY_LOW,
                gaps=[] if de is not None else ["debt_to_equity missing"],
                sources=["quality_seed", "ttl_refresh"],
                status="present",
            )
        if "cash_flow" in want:
            fcf = ratios.get("fcf")
            mark_section(
                doc,
                "cash_flow",
                fields={"fcf": fcf, "note": "refreshed"},
                confidence=CONF_LOW if fcf is not None else CONF_VERY_LOW,
                gaps=[] if fcf is not None else ["cash_flow: FCF unknown"],
                sources=["quality_seed", "ttl_refresh"],
                status="present",
            )
        if "valuation" in want:
            val = build_valuation_case(
                symbol=sym,
                ratios={
                    **ratios,
                    "debt_to_equity": de if de is not None else ratios.get("debt_to_equity"),
                },
                price=ratios.get("price"),
                shares=ratios.get("shares") or ratios.get("share_count"),
                valuation_id=(doc.get("valuation") or {}).get("id") or f"val-{sym}",
            )
            doc["valuation"] = val
            mark_section(
                doc,
                "valuation",
                fields=val,
                confidence=CONF_LOW if val.get("pe") is not None or val.get("fcf") is not None else CONF_VERY_LOW,
                gaps=list(val.get("gaps") or []),
                sources=["quality_seed", "ttl_refresh", "ira11"],
                status="present",
            )
            if isinstance(doc.get("thesis"), dict):
                doc["thesis"] = dict(doc["thesis"])
                doc["thesis"]["stance"] = thesis_stance_from_valuation(val)
                doc["thesis"]["valuation_id"] = val.get("id")
                doc["thesis"]["as_of"] = utc_now_iso()
        if "growth" in want and (filing_refs or ratios.get("revenue_cagr") is not None):
            fields: dict[str, Any] = {}
            if filing_refs:
                fields["filings_refs"] = filing_refs[:4]
            if ratios.get("revenue_cagr") is not None:
                fields["revenue_cagr"] = ratios.get("revenue_cagr")
            mark_section(
                doc,
                "growth",
                fields=fields,
                confidence=CONF_LOW,
                gaps=[],
                sources=["filings", "ttl_refresh"],
                status="present",
            )
        if "profitability" in want:
            mark_section(
                doc,
                "profitability",
                fields={
                    k: ratios.get(k)
                    for k in ("roe", "roic", "operating_margin", "net_margin")
                    if ratios.get(k) is not None
                },
                confidence=CONF_LOW,
                gaps=[],
                sources=["quality_seed", "ttl_refresh"],
                status="present",
            )
        if "risks" in want:
            prior = ((doc.get("sections") or {}).get("risks") or {}).get("fields") or {}
            mark_section(
                doc,
                "risks",
                fields={
                    "top_risks": prior.get("top_risks")
                    or ["Refresh: re-check impairment risks"]
                },
                confidence=CONF_LOW,
                gaps=[],
                sources=["ttl_refresh"],
                status="present",
            )
        if "management" in want:
            pack = doc.get("management_pack")
            built = mgmt_pack.management_section_fields(
                pack if isinstance(pack, dict) else None
            )
            prev = (doc.get("sections") or {}).get("management") or {}
            prev_fields = dict((prev.get("fields") if isinstance(prev, dict) else {}) or {})
            fields = dict(built["fields"])
            if prev_fields.get("filings_refs"):
                fields["filings_refs"] = prev_fields["filings_refs"]
            filing_ev = [
                e
                for e in (prev_fields.get("evidence") or [])
                if isinstance(e, dict) and str(e.get("claim") or "").startswith("Filing ref:")
            ]
            if filing_ev:
                fields["evidence"] = list(fields.get("evidence") or []) + filing_ev
                fields["evidence"] = fields["evidence"][-16:]
            mark_section(
                doc,
                "management",
                fields=fields,
                confidence=built["confidence"],
                gaps=list(built.get("gaps") or []),
                sources=list(built.get("sources") or ["management_pack", "ttl_refresh"]),
                status="present",
            )

        self._add_memory(
            doc,
            observation=f"Incremental TTL refresh for {sym}",
            interpretation=f"Sections refreshed: {', '.join(sorted(want))}",
            evidence={"sections": sorted(want), "ratios_keys": list(ratios.keys())},
            confidence=CONF_LOW,
        )
        mvr = mvr_status(doc)
        if mvr.get("satisfied"):
            doc["phase"] = PHASE_THESIS_READY if doc.get("thesis") else PHASE_MVR_READY
            doc["next"] = "monitor_or_deepen"
        doc["doing_now"] = "idle"
        doc["updated_at"] = utc_now_iso()
        return self._store.save(doc)
