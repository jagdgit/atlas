"""CompanyIntelligenceWorker — Market Intelligence M2 (MI.5 / IL.4).

Loads company profiles (config_seed default; official filing adapters when keys
exist) → typed knowledge candidates → CandidateConsumer. No scraping.

IL.4: empty tickers/companies → ranked Investment Universe watchlist
(with minimal membership-based config_seed profiles).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from atlas.decision.rules import CapabilityGap
from atlas.investment import watchlists as wl
from atlas.knowledge.media_extraction import MediaKnowledgeExtractor
from atlas.trading.company import CompanyDataService
from atlas.workers.base import PersistentWorker, TickContext, TickResult


class CompanyIntelligenceWorker(PersistentWorker):
    type = "company_intelligence"
    VERSION = 2
    journal_ticks = True

    def __init__(
        self,
        *,
        company_data: Any | None = None,
        candidates: Any,
        extractor: Any | None = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._companies = company_data or CompanyDataService()
        self._candidates = candidates
        self._extractor = extractor or MediaKnowledgeExtractor(max_claims=10)
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.company_intelligence")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        tickers, companies, auto = wl.resolve_company_targets(cfg)
        state["auto_watchlist"] = auto

        # Operator inputs can add a ticker or inline profile
        for inp in ctx.inputs or []:
            if inp.get("company") and isinstance(inp["company"], dict):
                companies.append(inp["company"])
                sym = str(inp["company"].get("symbol") or "").strip()
                if sym and sym not in tickers:
                    tickers.append(sym)
            if inp.get("symbol"):
                sym = str(inp["symbol"]).strip()
                if sym and sym not in tickers:
                    tickers.append(sym)

        if not tickers:
            return TickResult(
                state=state,
                note=(
                    "idle: no tickers — set tickers=['RELIANCE.NS'] and/or "
                    "companies=[{symbol,name,sector,facts,filings}], or start M0 / "
                    "India learner so the ranked watchlist auto-loads"
                ),
            )

        if auto:
            state["auto_symbols"] = list(tickers)

        if companies:
            try:
                self._companies.load_config_profiles(companies)
            except Exception:  # noqa: BLE001
                pass

        provider = str(cfg.get("provider") or "").strip() or None
        seen = set(state.get("seen_hashes") or [])
        ok = 0
        gaps = 0
        emitted = 0
        notes: list[str] = []

        for symbol in tickers:
            try:
                result = self._companies.fetch(
                    symbol, provider=provider, companies=companies or None
                )
            except CapabilityGap as gap:
                gaps += 1
                notes.append(f"{symbol}: gap {gap.capability}")
                continue
            except Exception as exc:  # noqa: BLE001
                gaps += 1
                notes.append(f"{symbol}: error {exc}")
                self._logger.warning("company fetch failed for %s: %s", symbol, exc)
                continue

            text = str(result.get("knowledge_text") or "").strip()
            if not text:
                gaps += 1
                notes.append(f"{symbol}: empty profile")
                continue
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            if digest in seen and not cfg.get("force"):
                notes.append(f"{symbol}: unchanged")
                ok += 1
                continue

            profile = result.get("profile") or {}
            evidence = {
                "source": f"company:{result.get('provider')}",
                "symbol": symbol,
                "mission_id": ctx.mission_id,
                "company_name": profile.get("name"),
            }
            payloads = self._extractor.extract(
                text, evidence_ref=evidence, domain="markets"
            )
            # Ensure an entity candidate for the company name/symbol.
            name = str(profile.get("name") or symbol).strip()
            payloads.append(
                {
                    "statement": f"Entity: {name} (org)",
                    "claim_type": "entity",
                    "domain": "markets",
                    "evidence_ref": dict(evidence),
                    "value": {
                        "kind": "entity",
                        "name": name,
                        "entity_type": "org",
                        "symbol": symbol,
                        "sector": profile.get("sector"),
                        "epistemic": "entity",
                        "status": "UNVERIFIED",
                    },
                }
            )
            for payload in payloads:
                try:
                    self._candidates.emit(payload)
                    emitted += 1
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("candidate emit failed: %s", exc)

            seen.add(digest)
            ok += 1
            filings_n = len(profile.get("filings") or [])
            notes.append(
                f"{symbol}@{result.get('provider')}: facts={len(profile.get('facts') or [])} "
                f"filings={filings_n}"
            )

        if emitted and hasattr(self._candidates, "consume_pending"):
            try:
                self._candidates.consume_pending(limit=max(emitted, 20))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("candidate consolidate failed: %s", exc)

        state["seen_hashes"] = list(seen)[-200:]
        state["last_ok"] = ok
        state["last_gaps"] = gaps
        state["last_emitted"] = emitted

        if self._events is not None and emitted:
            try:
                self._events.emit(
                    "CompanyIntelligenceExtracted",
                    {
                        "mission_id": ctx.mission_id,
                        "emitted": emitted,
                        "tickers": tickers,
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        auto_note = f"auto watchlist ({len(tickers)}); " if auto else ""
        head = f"{auto_note}company: {ok} ok, {gaps} gap(s), emitted {emitted}"
        detail = "; ".join(notes[:6])
        return TickResult(state=state, note=f"{head} | {detail}" if detail else head)
