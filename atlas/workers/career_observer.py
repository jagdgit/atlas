"""CareerObserverWorker — CI.1.2 discover-only → career knowledge (never recommend).

Sensors (LinkedIn export paths, job JSON feeds, job_postings assets) → normalize →
CandidateConsumer ``domain=career``. May register snapshot / job assets for Advisor
consumption. Never calls DecisionEngine / never applies (L-SPLIT / P14).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atlas.career import observe as obs
from atlas.career import watchlist as wl
from atlas.career.feeds import load_postings_json
from atlas.personal.linkedin_export import load_linkedin_export_bundle
from atlas.workers.base import PersistentWorker, TickContext, TickResult

ASSET_PROFILE = "linkedin_profile_export"
ASSET_JOBS = "linkedin_export_jobs"


class CareerObserverWorker(PersistentWorker):
    type = "career_observer"
    VERSION = 1
    journal_ticks = True

    def __init__(
        self,
        *,
        candidates: Any,
        assets: Any | None = None,
        postings_reader: Any | None = None,
        configuration: Any | None = None,
        missions: Any | None = None,
        events: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._candidates = candidates
        self._assets = assets
        self._reader = postings_reader
        self._configuration = configuration
        self._missions = missions
        self._events = events
        self._logger = logger or logging.getLogger("atlas.workers.career_observer")

    def do_tick(self, ctx: TickContext) -> TickResult:
        cfg = ctx.config or {}
        state = dict(ctx.state or {})
        ticks = int(state.get("ticks", 0)) + 1
        state["ticks"] = ticks

        export_paths = [
            str(p).strip()
            for p in (cfg.get("linkedin_export_paths") or [])
            if str(p).strip()
        ]
        feed_paths = [
            str(p).strip() for p in (cfg.get("job_feed_paths") or []) if str(p).strip()
        ]
        source_names = [
            str(s).strip() for s in (cfg.get("job_feed_sources") or []) if str(s).strip()
        ]
        # Operator inputs can push a one-shot export path.
        for inp in ctx.inputs or []:
            if inp.get("linkedin_export_path"):
                export_paths.append(str(inp["linkedin_export_path"]).strip())
            if inp.get("job_feed_path"):
                feed_paths.append(str(inp["job_feed_path"]).strip())

        max_cands = max(1, int(cfg.get("max_candidates_per_tick") or 40))
        register_assets = bool(cfg.get("register_job_assets", True))
        seed_watchlist = bool(cfg.get("seed_watchlist", True))
        wire_advisor = bool(cfg.get("wire_advisor_sources", False))

        if not export_paths and not feed_paths and not source_names:
            return TickResult(
                state=state,
                note=(
                    "idle: set linkedin_export_paths=['/path/export.zip'] and/or "
                    "job_feed_paths / job_feed_sources — discover only, never recommends"
                ),
            )

        payloads: list[dict[str, Any]] = []
        postings_all: list[dict[str, Any]] = []
        companies: list[str] = []
        notes: list[str] = []
        fp_parts: list[str] = []

        for path in export_paths:
            bundle = load_linkedin_export_bundle(path)
            fp_parts.append(f"export:{bundle.get('path')}:{bundle.get('chars')}")
            if not bundle.get("ok"):
                notes.append(f"export fail {path}: {bundle.get('reason')}")
                continue
            payloads.extend(
                obs.candidates_from_bundle(
                    bundle, mission_id=ctx.mission_id, max_candidates=max_cands
                )
            )
            postings_all.extend(bundle.get("postings") or [])
            companies.extend(bundle.get("companies_followed") or [])
            for pos in bundle.get("positions") or []:
                if isinstance(pos, dict) and pos.get("company"):
                    companies.append(str(pos["company"]))
            if register_assets and self._assets is not None:
                try:
                    self._assets.register(
                        "linkedin_profile",
                        ASSET_PROFILE,
                        obs.profile_snapshot_bytes(bundle),
                        source_uri=str(bundle.get("path") or path),
                        content_type="application/json",
                        metadata={"ci": "CI.1.1", "policy": "suggestions_only"},
                    )
                    notes.append(f"profile asset={ASSET_PROFILE}")
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("profile asset register failed: %s", exc)

        for path in feed_paths:
            try:
                posts = load_postings_json(Path(path))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"feed fail {path}: {exc}")
                continue
            fp_parts.append(f"feed:{path}:{len(posts)}")
            postings_all.extend(posts)
            payloads.extend(
                obs.candidates_from_postings(
                    posts, mission_id=ctx.mission_id, max_candidates=max_cands
                )
            )

        for name in source_names:
            loaded, err = self._load_asset_postings(name)
            if err:
                notes.append(err)
                continue
            fp_parts.append(f"asset:{name}:{len(loaded)}")
            postings_all.extend(loaded)
            payloads.extend(
                obs.candidates_from_postings(
                    loaded, mission_id=ctx.mission_id, max_candidates=max_cands
                )
            )

        # Dedupe candidates by statement hash
        seen_stmt: set[str] = set(state.get("seen_statements") or [])
        fresh: list[dict[str, Any]] = []
        for payload in payloads:
            key = obs.fingerprint([str(payload.get("statement") or "")])
            if key in seen_stmt:
                continue
            seen_stmt.add(key)
            fresh.append(payload)
        fresh = fresh[:max_cands]

        fingerprint = obs.fingerprint(fp_parts + [str(len(fresh))])
        force = any(bool(item.get("force")) for item in (ctx.inputs or []))
        if not force and fingerprint == state.get("sources_fingerprint") and not fresh:
            state["ticks"] = ticks
            return TickResult(state=state, note="no change (career sensors unchanged)")

        emitted = 0
        for payload in fresh:
            try:
                self._candidates.emit(payload)
                emitted += 1
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("career candidate emit failed: %s", exc)

        if emitted and hasattr(self._candidates, "consume_pending"):
            try:
                self._candidates.consume_pending(limit=max(emitted, 20))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("career candidate consolidate failed: %s", exc)

        # Deduped postings → optional job_postings asset for Advisor (still no recommend here).
        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for p in postings_all:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("id") or "")
            if not pid:
                pid = obs.fingerprint(
                    [str(p.get("title") or ""), str(p.get("company") or ""), str(p.get("url") or "")]
                )
                p = dict(p)
                p["id"] = pid
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            deduped.append(p)

        if register_assets and deduped and self._assets is not None:
            try:
                self._assets.register(
                    "job_postings",
                    ASSET_JOBS,
                    obs.postings_asset_bytes(deduped),
                    source_uri="career_observer",
                    content_type="application/json",
                    metadata={
                        "posting_count": len(deduped),
                        "ci": "CI.1.2",
                        "policy": "discover_only",
                    },
                )
                notes.append(f"jobs asset={ASSET_JOBS} n={len(deduped)}")
                if wire_advisor and self._configuration is not None and self._missions is not None:
                    from atlas.career.feeds import wire_source_to_career_advisor

                    wired = wire_source_to_career_advisor(
                        missions=self._missions,
                        configuration=self._configuration,
                        source_name=ASSET_JOBS,
                    )
                    notes.append(f"advisor_wire={wired.get('ok')}")
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("jobs asset register failed: %s", exc)

        if seed_watchlist and companies:
            uniq = []
            for c in companies:
                c = (c or "").strip()
                if c and c not in uniq:
                    uniq.append(c)
            seeded = wl.seed_companies(uniq, source="career_observer", limit=40)
            notes.append(f"watchlist +{seeded.get('added', 0)}")

        # Seed applied jobs onto watchlist
        if seed_watchlist:
            for p in deduped:
                if str(p.get("operator_status") or "") != "applied":
                    continue
                try:
                    wl.upsert(
                        label=str(p.get("title") or p.get("id") or "job"),
                        kind="job",
                        operator_status="applied",
                        external_id=str(p.get("id") or "") or None,
                        url=str(p.get("url") or "") or None,
                        meta={"company": p.get("company"), "seeded_by": "career_observer"},
                    )
                except Exception:  # noqa: BLE001
                    pass

        state["seen_statements"] = list(seen_stmt)[-500:]
        state["sources_fingerprint"] = fingerprint
        state["last_emitted"] = emitted
        state["last_posting_count"] = len(deduped)

        if self._events is not None and emitted:
            try:
                self._events.emit(
                    "CareerObserverExtracted",
                    {
                        "mission_id": ctx.mission_id,
                        "emitted": emitted,
                        "postings": len(deduped),
                    },
                    source=self.type,
                )
            except Exception:  # noqa: BLE001
                pass

        extra = ("; ".join(notes)) if notes else ""
        return TickResult(
            state=state,
            note=(
                f"career observe: emitted {emitted} candidate(s), "
                f"{len(deduped)} posting(s)"
                + (f"; {extra}" if extra else "")
                + " (discover only — no recommend)"
            ),
        )

    def _load_asset_postings(self, name: str) -> tuple[list[dict[str, Any]], str | None]:
        if self._assets is None:
            return [], f"asset {name}: assets unavailable"
        try:
            asset = self._assets.get_by_name("job_postings", name)
            if asset is None:
                return [], f"asset {name}: not found"
            if self._reader is not None:
                artifact = self._reader.read(str(asset["id"]))
                if artifact.get("outcome") == "ok":
                    return [p for p in (artifact.get("postings") or []) if isinstance(p, dict)], None
                return [], f"asset {name}: {artifact.get('reason') or 'unreadable'}"
            raw = self._assets.get_bytes(str(asset["id"]))
            data = json.loads(raw)
            if isinstance(data, list):
                return [p for p in data if isinstance(p, dict)], None
            if isinstance(data, dict):
                for key in ("postings", "jobs", "items"):
                    chunk = data.get(key)
                    if isinstance(chunk, list):
                        return [p for p in chunk if isinstance(p, dict)], None
            return [], f"asset {name}: unexpected JSON shape"
        except Exception as exc:  # noqa: BLE001
            return [], f"asset {name}: {exc}"
