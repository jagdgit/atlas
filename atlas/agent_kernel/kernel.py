"""Agent Kernel operating loop.

Observe → work → prioritize → plan → route capabilities → execute → verify →
record → schedule the next tick. One investigation at a time. No silent pending.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from atlas.agent_kernel.bus import DERIVED_REQUIREMENTS, EvidenceBus, default_catalog
from atlas.agent_kernel.local_evidence import lookup_local
from atlas.agent_kernel.models import (
    DIAGNOSTIC_FIELDS,
    NON_SUCCESS,
    PRIORITY_RANK,
    STATUS_ACTIVE,
    STATUS_CAPABILITY_GAP,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_PLANNING_FAILED,
    STATUS_RETRY,
    STATUS_SUCCESS,
    STATUS_UNVERIFIED,
    STATUS_WAITING,
    VERSION,
    blank_diagnostics,
    empty_state,
    fingerprint,
    lineage,
    new_id,
    now_iso,
)
from atlas.agent_kernel.planner import plan_investigation
from atlas.agent_kernel.safety import capability_allowed, strip_orders
from atlas.agent_kernel.web_search import (
    CLIENT_NOT_CONFIGURED,
    NUMERIC_REQUIREMENTS,
    POLICY_DISABLED,
    PROVIDER_UNAVAILABLE,
    SUCCESS,
    WebSearchCapability,
)

_log = logging.getLogger("atlas.agent_kernel")

_RS_MIN = 0.01
_RS_MAX = 100.0


def _close(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, dict):
        return None
    for key in ("last_close", "close", "value", "relative_strength"):
        raw = value.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
    bars = value.get("bars")
    if isinstance(bars, list) and bars and isinstance(bars[-1], dict):
        return _close(bars[-1])
    return None


def _priority_class(obs: dict[str, Any]) -> str:
    hint = str(obs.get("priority_class") or "").upper()
    if hint in PRIORITY_RANK:
        return hint
    if obs.get("integrity") or obs.get("safety") or obs.get("data_corruption"):
        return "P0"
    if obs.get("decision_impact") or str(obs.get("importance") or "").upper() == "HIGH":
        return "P1"
    if obs.get("stale") or str(obs.get("importance") or "").upper() == "MEDIUM":
        return "P2"
    return "P3"


def _score(obs: dict[str, Any], klass: str) -> float:
    impact = 1.0 if obs.get("decision_impact") or klass in {"P0", "P1"} else 0.25
    uncertainty = 1.0 if obs.get("required") else 0.3
    urgency = float(obs.get("urgency") or (0.9 if klass == "P0" else 0.5))
    availability = float(obs.get("evidence_availability") or 0.6)
    cost = float(obs.get("cost") or 1.0)
    return PRIORITY_RANK[klass] + (100.0 * impact * uncertainty * urgency * availability / max(cost, 0.1))


class AgentKernel:
    def __init__(
        self,
        data_dir: str | Path,
        *,
        experience_os: Any = None,
        activity_journal: Any = None,
        job_planner: Any = None,
        llm: Any = None,
        cognitive_fn: Any = None,
        laboratory_id: str = "india_equity_learner",
        bus: EvidenceBus | None = None,
        web_search: Any = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.experience_os = experience_os
        self.activity_journal = activity_journal
        self.job_planner = job_planner
        self.llm = llm
        self.cognitive_fn = cognitive_fn
        self.laboratory_id = laboratory_id
        self.bus = bus or EvidenceBus()
        self._logger = logger or _log
        self._allow_external = True
        self._web: WebSearchCapability | None = None
        self.bind_web_search(web_search)
        self.state = self.load()

    @property
    def state_path(self) -> Path:
        return self.data_dir / "agent_kernel" / "state.json"

    def load(self) -> dict[str, Any]:
        path = self.state_path
        if not path.is_file():
            return empty_state()
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return empty_state()
        if not isinstance(doc, dict):
            return empty_state()
        base = empty_state()
        base.update(doc)
        base["tasks"] = doc.get("tasks") if isinstance(doc.get("tasks"), dict) else {}
        base["failure_memory"] = (
            doc.get("failure_memory") if isinstance(doc.get("failure_memory"), dict) else {}
        )
        if not isinstance(base.get("external_searches"), list):
            base["external_searches"] = []
        return base

    def save(self) -> None:
        self.state["version"] = VERSION
        self.state["updated_at"] = now_iso()
        self._refresh_indexes()
        path = self.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)

    def catalog(self) -> list[dict[str, Any]]:
        return self.bus.catalog_view()

    def bind_web_search(self, client: Any) -> None:
        """Attach the production search client. None leaves web_search unconfigured."""
        if client is None:
            self._web = None
            return
        wrapped = client if isinstance(client, WebSearchCapability) else WebSearchCapability(client)
        changed = self._web is None or self._web._client is not wrapped._client
        self._web = wrapped
        if changed and "web_search" not in self.bus.forced:
            self.bus.generation["web_search"] = int(self.bus.generation.get("web_search") or 0) + 1
            if self._allow_external and self._web.available():
                self.bus.available["web_search"] = True

    def resolve(self, name: str) -> dict[str, Any]:
        """Resolve a capability name to an executable implementation, if one exists."""
        cap = str(name or "").strip()
        if not capability_allowed(cap):
            return {
                "name": cap,
                "executable": False,
                "available": False,
                "status": "FORBIDDEN",
                "capability": None,
            }
        if cap == "news_search":
            status = POLICY_DISABLED if not self._allow_external else CLIENT_NOT_CONFIGURED
            return {
                "name": cap,
                "executable": False,
                "available": False,
                "status": status,
                "reason": "no separate news search provider is registered",
                "capability": None,
            }
        if cap == "web_search":
            if not self._allow_external:
                return {
                    "name": cap,
                    "executable": False,
                    "available": False,
                    "status": POLICY_DISABLED,
                    "capability": None,
                }
            if self._web is None:
                return {
                    "name": cap,
                    "executable": False,
                    "available": False,
                    "status": CLIENT_NOT_CONFIGURED,
                    "capability": None,
                }
            if not self._web.available():
                return {
                    "name": cap,
                    "executable": False,
                    "available": False,
                    "status": self._web.unavailable_reason() or PROVIDER_UNAVAILABLE,
                    "capability": None,
                }
            return {
                "name": cap,
                "executable": True,
                "available": True,
                "status": SUCCESS,
                "capability": self._web,
            }
        return {
            "name": cap,
            "executable": False,
            "available": bool(self.bus.available.get(cap)),
            "status": "DESCRIPTOR_ONLY",
            "capability": None,
        }

    def cycle(
        self,
        *,
        mode: str = "tick",
        observations: list[dict[str, Any]] | None = None,
        laboratory_id: str | None = None,
        allow_external: bool = True,
        max_investigations: int | None = None,
    ) -> dict[str, Any]:
        if laboratory_id:
            self.laboratory_id = laboratory_id
        self._allow_external = bool(allow_external)
        ready = self.resolve("web_search")
        self.bus.apply_external_policy(
            allow_external,
            web_available=bool(ready.get("executable")),
            web_reason=str(ready.get("status") or ""),
        )
        mode = (mode or "tick").strip().lower()
        created = self.observe(observations or [])
        resumed = self._resume_ready()
        limit = max_investigations
        if limit is None:
            limit = {"deep": 2, "event": 1, "tick": 1, "wait": 1}.get(mode, 1)
        selected = self._select(mode, limit=limit)
        reports = []
        for task_id in selected:
            reports.append(self._execute(self.state["tasks"][task_id]))
        if not selected and mode == "wait":
            note = "waiting: no evidence, schedule, capability change, or retry is due"
        elif not selected:
            note = "no runnable work"
        else:
            note = f"ran {len(selected)} investigation(s) mode={mode}"
        self.state["current_goal"] = (
            self.state["tasks"][selected[0]]["objective"] if selected else self.state.get("current_goal")
        )
        self.save()
        out = {
            "ok": True,
            "mode": mode,
            "note": note,
            "created": [c["id"] for c in created],
            "resumed": resumed,
            "ran": selected,
            "reports": reports,
            "version": VERSION,
        }
        self._journal(note, out)
        return out

    def observe(self, extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        payloads.extend(self._inbox_payloads())
        payloads.extend(self._uncertainty_payloads())
        payloads.extend(extra)
        created = []
        for payload in payloads:
            task = self._upsert(payload)
            if task is not None:
                created.append(task)
        return created

    def task(self, task_id: str) -> dict[str, Any] | None:
        row = self.state["tasks"].get(task_id)
        return dict(row) if isinstance(row, dict) else None

    def tasks(self) -> list[dict[str, Any]]:
        return list(self.state["tasks"].values())

    # --- observation ----------------------------------------------------
    def _inbox_payloads(self) -> list[dict[str, Any]]:
        inbox = self.data_dir / "agent_kernel" / "inbox"
        if not inbox.is_dir():
            return []
        out = []
        done = inbox.parent / "inbox_done"
        done.mkdir(parents=True, exist_ok=True)
        for path in sorted(inbox.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict):
                doc.setdefault("source", "inbox")
                out.append(doc)
            path.replace(done / path.name)
        return out

    def _uncertainty_payloads(self) -> list[dict[str, Any]]:
        try:
            from atlas.investment.uncertainty_queue import list_tasks
        except Exception:  # noqa: BLE001
            return []
        try:
            rows = list_tasks(self.data_dir, self.laboratory_id, status="PENDING")
        except Exception:  # noqa: BLE001
            return []
        out = []
        for row in rows:
            if str(row.get("importance") or "").upper() != "HIGH":
                continue
            symbol = str(row.get("symbol") or "")
            unknown = str(row.get("unknown") or "unknown")
            requirement = unknown.replace("_missing", "").replace("_unknown", "")
            out.append(
                {
                    "source": "uncertainty_queue",
                    "domain": "investment",
                    "symbol": symbol,
                    "objective": str(row.get("action") or f"Resolve {unknown} for {symbol}"),
                    "reason": str(row.get("why") or unknown),
                    "decision_impact": True,
                    "importance": "HIGH",
                    "urgency": 0.8,
                    "required": [requirement] if requirement else [unknown],
                    "uncertainty_refs": [row.get("id")],
                    "decision_id": None,
                    "priority_class": "P1",
                    "interpretive": False,
                }
            )
            if len(out) >= 1:
                break
        return out

    def _upsert(self, obs: dict[str, Any]) -> dict[str, Any] | None:
        objective = str(obs.get("objective") or "").strip()
        if not objective:
            return None
        required = [str(r) for r in (obs.get("required") or []) if r]
        symbol = str(obs.get("symbol") or "").upper()
        domain = str(obs.get("domain") or "general")
        fp = fingerprint(symbol=symbol, objective=objective, required=required, domain=domain)
        for existing in self.state["tasks"].values():
            if existing.get("fingerprint") == fp:
                return None
        klass = _priority_class(obs)
        episode_id = new_id("EP")
        work_id = new_id("AK")
        diag = blank_diagnostics()
        diag["reason"] = str(obs.get("reason") or "observed work")
        task = {
            "id": work_id,
            "fingerprint": fp,
            "episode_id": episode_id,
            "source": obs.get("source") or "observation",
            "domain": domain,
            "symbol": symbol,
            "objective": objective,
            "priority_class": klass,
            "score": _score(obs, klass),
            "status": STATUS_RETRY,
            "required": required,
            "evidence": {},
            "evidence_refs": list(obs.get("evidence_refs") or []),
            "uncertainty_refs": [str(x) for x in (obs.get("uncertainty_refs") or []) if x],
            "failed": [],
            "plan": None,
            "interpretive": bool(
                obs.get("interpretive")
                if "interpretive" in obs
                else _looks_interpretive(objective)
            ),
            "deterministic_only": bool(obs.get("deterministic_only") or _looks_deterministic(objective)),
            "needs_relative_strength": "relative_strength" in required or bool(obs.get("needs_relative_strength")),
            "constraints": dict(obs.get("constraints") or {}),
            "decision_impact": bool(obs.get("decision_impact")),
            "impact": obs.get("impact") or (
                "blocks_next_rupee_comparison" if obs.get("decision_impact") else "knowledge"
            ),
            "lineage": lineage(episode_id, work_id, obs.get("decision_id")),
            "cognitive": None,
            "blocked_generations": {},
            "created_at": now_iso(),
            "updated_at": now_iso(),
            **diag,
        }
        if task["deterministic_only"]:
            task["interpretive"] = False
        self.state["tasks"][work_id] = task
        return task

    # --- scheduling -----------------------------------------------------
    def _resume_ready(self) -> list[str]:
        resumed = []
        for task in self.state["tasks"].values():
            if task.get("status") != STATUS_CAPABILITY_GAP:
                continue
            if not self._capability_changed(task):
                continue
            task["status"] = STATUS_RETRY
            task["next_action"] = "resume_after_capability_change"
            task["reason"] = "missing capability became available; resuming the same task"
            task["plan"] = None
            task["updated_at"] = now_iso()
            resumed.append(task["id"])
        return resumed

    def _capability_changed(self, task: dict[str, Any]) -> bool:
        snap = task.get("blocked_generations") or {}
        if not isinstance(snap, dict) or not snap:
            return False
        for name, seen in snap.items():
            if int(self.bus.generation.get(name) or 0) > int(seen or 0):
                return True
        return False

    def _select(self, mode: str, *, limit: int) -> list[str]:
        due = []
        for task in self.state["tasks"].values():
            if not self._is_due(task, mode):
                continue
            due.append(task)
        if any(t.get("priority_class") in {"P0", "P1", "P2"} for t in due):
            due = [t for t in due if t.get("priority_class") != "P3"]
        due.sort(key=lambda t: (-int(PRIORITY_RANK.get(t.get("priority_class"), 0)), -float(t.get("score") or 0)))
        chosen = [t["id"] for t in due[: max(0, limit)]]
        chosen_set = set(chosen)
        for task in due:
            if task["id"] in chosen_set:
                continue
            if task.get("status") in {STATUS_SUCCESS, STATUS_CAPABILITY_GAP, STATUS_WAITING}:
                continue
            task["status"] = STATUS_RETRY
            task["reason"] = task.get("reason") or "higher priority work selected"
            task["next_action"] = "execute_on_next_tick"
            task["last_error"] = task.get("last_error")
            task["missing_requirement"] = task.get("missing_requirement")
            task["attempted_capabilities"] = list(task.get("attempted_capabilities") or [])
        return chosen

    def _is_due(self, task: dict[str, Any], mode: str) -> bool:
        status = task.get("status")
        if status == STATUS_ACTIVE:
            return True
        if status == STATUS_RETRY:
            when = task.get("next_retry_at")
            if mode == "wait" and when and str(when) > now_iso():
                return False
            return True
        if status == STATUS_CAPABILITY_GAP and mode == "event":
            return self._capability_changed(task)
        return False

    # --- execution ------------------------------------------------------
    def _execute(self, task: dict[str, Any]) -> dict[str, Any]:
        task["status"] = STATUS_ACTIVE
        task["updated_at"] = now_iso()
        self.state["current_work"] = task["id"]
        self.state["current_goal"] = task["objective"]
        self.save()
        if not task.get("plan"):
            planned = plan_investigation(
                task,
                catalog_names=list(default_catalog()),
                availability=dict(self.bus.available),
                generations=dict(self.bus.generation),
                failure_memory=self.state.get("failure_memory") or {},
                job_planner=self.job_planner,
            )
            task["plan"] = planned
            task["planner_source"] = planned.get("source")
            if not planned.get("ok"):
                return self._finish(
                    task,
                    STATUS_PLANNING_FAILED,
                    reason=str(planned.get("reason") or "planning failed"),
                    next_action="revise_objective_or_provide_planner",
                    retry_policy="manual",
                )
            for skip in planned.get("skipped_known_failures") or []:
                cap = str(skip.get("capability") or "")
                if not cap:
                    continue
                task["attempted_capabilities"] = _append(task.get("attempted_capabilities"), cap)
                task["failed"] = _append(task.get("failed"), f"{cap}:known_failure")
                task["last_error"] = str(skip.get("reason") or task.get("last_error") or "")
                if cap in {"web_search", "news_search"}:
                    status = str(self.bus.status_reason.get(cap) or skip.get("reason") or "unavailable")
                    self._record_search(
                        task,
                        capability=cap,
                        query="",
                        provider=None,
                        started_at=now_iso(),
                        completed_at=now_iso(),
                        result_count=0,
                        status=status,
                        error=status,
                        evidence_ids=[],
                    )
        for step in list(task["plan"].get("steps") or []):
            if step.get("done"):
                continue
            result = self._run_step(task, step)
            step["done"] = True
            step["result_ok"] = bool(result.get("ok"))
            step["error"] = result.get("error")
            task["updated_at"] = now_iso()
            self.save()
            if result.get("refused"):
                return self._finish(
                    task,
                    STATUS_FAILED,
                    reason=str(result.get("error") or "forbidden capability refused"),
                    next_action="do_not_retry_forbidden_side_effect",
                    retry_policy="never",
                    last_error=result.get("error"),
                )
        return self._conclude(task)

    def _run_step(self, task: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
        capability = str(step.get("capability") or "")
        if not capability_allowed(capability):
            task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
            task["last_error"] = f"forbidden capability {capability}"
            return {"ok": False, "refused": True, "error": task["last_error"]}
        kind = step.get("kind")
        if kind == "verify":
            return {"ok": True}
        if kind == "lookup_experience":
            return self._lookup_experience(task)
        if kind == "calculate":
            return self._calculate(task)
        if kind == "interpret":
            return self._interpret(task)
        if kind == "job_step":
            task["attempted_capabilities"] = _append(task.get("attempted_capabilities"), capability)
            task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
            return {
                "ok": False,
                "error": "job_step_recorded_not_executed_as_order",
            }
        requirement = str(step.get("requirement") or "")
        return self._acquire(task, capability, requirement)

    def _acquire(self, task: dict[str, Any], capability: str, requirement: str) -> dict[str, Any]:
        task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
        task["attempted_capabilities"] = _append(task.get("attempted_capabilities"), capability)
        memory = self.state.setdefault("failure_memory", {})
        key = f"{requirement}|{capability}"
        prior = memory.get(key)
        generation = int(self.bus.generation.get(capability) or 0)
        if isinstance(prior, dict) and generation <= int(prior.get("generation") or 0):
            task["failed"] = _append(
                task.get("failed"),
                f"{capability}:skipped_known_failure:{prior.get('error')}",
            )
            task["last_error"] = (
                f"previously failed because {prior.get('error') or 'the same approach failed'}"
            )
            return {"ok": False, "error": task["last_error"], "skipped": True}
        if capability == "web_search" and not self.bus.has_slot(capability, requirement):
            result = self._run_web_search(task, requirement)
        else:
            result = self.bus.query(capability, requirement)
        if (
            not result.get("ok")
            and capability in {"local_market_store", "knowledge_search"}
            and str(result.get("error") or "").endswith(("_not_available", "_unavailable"))
        ):
            disk = lookup_local(
                self.data_dir,
                symbol=str(task.get("symbol") or ""),
                requirement=requirement,
                laboratory_id=self.laboratory_id,
            )
            if disk.get("ok"):
                result = disk
            elif disk.get("error") and not str(disk.get("error")).endswith("_not_available"):
                result = disk
        if result.get("invented"):
            task["failed"] = _append(task.get("failed"), "manufactured_evidence_rejected")
            task["last_error"] = "manufactured_evidence_rejected"
            return result
        if result.get("ok"):
            task["evidence"][requirement] = result.get("evidence")
            for cite in result.get("citations") or []:
                task["evidence_refs"] = _append(task.get("evidence_refs"), str(cite))
            return result
        error = str(result.get("error") or "failed")
        task["failed"] = _append(task.get("failed"), f"{capability}:{error}")
        task["last_error"] = error
        task["missing_requirement"] = str(result.get("missing") or requirement)
        memory[key] = {
            "error": error,
            "generation": generation,
            "at": now_iso(),
            "episode_id": task.get("episode_id"),
            "requirement": requirement,
            "capability": capability,
        }
        return result

    def _run_web_search(self, task: dict[str, Any], requirement: str) -> dict[str, Any]:
        query = _search_query(task, requirement)
        started = now_iso()
        resolved = self.resolve("web_search")
        if not resolved.get("executable"):
            status = str(resolved.get("status") or CLIENT_NOT_CONFIGURED)
            self._record_search(
                task,
                capability="web_search",
                query=query,
                provider=None,
                started_at=started,
                completed_at=now_iso(),
                result_count=0,
                status=status,
                error=status,
                evidence_ids=[],
            )
            return {
                "ok": False,
                "error": status,
                "missing": "web_search",
                "citations": [],
                "invented": False,
            }
        outcome = resolved["capability"].execute(
            query,
            context={
                "work_id": task.get("id"),
                "symbol": task.get("symbol"),
                "requirement": requirement,
            },
        )
        self._record_search(
            task,
            capability="web_search",
            query=outcome.get("query") or query,
            provider=outcome.get("provider"),
            started_at=str(outcome.get("started_at") or started),
            completed_at=str(outcome.get("completed_at") or now_iso()),
            result_count=int(outcome.get("result_count") or 0),
            status=str(outcome.get("status") or "SEARCH_ERROR"),
            error=outcome.get("error"),
            evidence_ids=list(outcome.get("evidence_ids") or []),
        )
        evidence = list(outcome.get("evidence") or [])
        citations = list(outcome.get("citations") or [])
        for url in citations:
            task["evidence_refs"] = _append(task.get("evidence_refs"), str(url))
        if evidence:
            task["web_evidence"] = evidence
        if outcome.get("status") != SUCCESS:
            return {
                "ok": False,
                "error": str(outcome.get("error") or outcome.get("status")),
                "missing": requirement,
                "citations": citations,
                "invented": False,
                "status": outcome.get("status"),
            }
        if requirement in NUMERIC_REQUIREMENTS:
            return {
                "ok": False,
                "error": "web_snippets_are_not_a_structured_value",
                "missing": requirement,
                "citations": citations,
                "invented": False,
            }
        self.bus.slots[("web_search", requirement)] = {
            "evidence": evidence,
            "citations": citations,
        }
        return {
            "ok": True,
            "evidence": evidence,
            "citations": citations,
            "invented": False,
            "error": None,
            "missing": None,
        }

    def _record_search(
        self,
        task: dict[str, Any],
        *,
        capability: str,
        query: str,
        provider: str | None,
        started_at: str,
        completed_at: str,
        result_count: int,
        status: str,
        error: str | None,
        evidence_ids: list[str],
    ) -> None:
        row = {
            "work_id": task.get("id"),
            "attempt": int(task.get("attempt_count") or 0),
            "capability": capability,
            "query": query,
            "provider": provider,
            "started_at": started_at,
            "completed_at": completed_at,
            "result_count": result_count,
            "status": status,
            "error": error,
            "evidence_ids": list(evidence_ids),
        }
        task.setdefault("external_searches", [])
        task["external_searches"].append(row)
        self.state.setdefault("external_searches", [])
        self.state["external_searches"] = _prepend(self.state.get("external_searches"), row, 80)
        if self.activity_journal is not None and hasattr(self.activity_journal, "record"):
            try:
                self.activity_journal.record(
                    domain="agent_kernel",
                    worker="agent_kernel",
                    action=capability,
                    target=task.get("symbol") or None,
                    summary=f"{status} query={query[:160]} results={result_count}",
                    result="completed" if status == SUCCESS else "failed",
                    evidence=row,
                )
            except Exception:  # noqa: BLE001
                self._logger.debug("search journal failed", exc_info=True)

    def _calculate(self, task: dict[str, Any]) -> dict[str, Any]:
        task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
        task["attempted_capabilities"] = _append(task.get("attempted_capabilities"), "python_calculation")
        price = _close(task["evidence"].get("price_history"))
        sector = _close(task["evidence"].get("sector_benchmark"))
        if price is None or sector is None or sector == 0:
            task["failed"] = _append(task.get("failed"), "python_calculation:inputs_missing")
            task["last_error"] = "sector_or_price_missing"
            task["missing_requirement"] = "sector_benchmark" if sector is None else "price_history"
            return {"ok": False, "error": "sector_or_price_missing", "invented": False}
        ratio = price / sector
        if ratio < _RS_MIN or ratio > _RS_MAX:
            task["last_error"] = "relative_strength_outside_sanity_range"
            return {"ok": False, "error": task["last_error"], "invented": False}
        task["evidence"]["relative_strength"] = {
            "relative_strength": ratio,
            "method": "last_close_ratio",
            "provenance": ["price_history", "sector_benchmark"],
            "invented": False,
        }
        return {"ok": True, "evidence": task["evidence"]["relative_strength"], "invented": False}

    def _lookup_experience(self, task: dict[str, Any]) -> dict[str, Any]:
        task["attempted_capabilities"] = _append(task.get("attempted_capabilities"), "experience_lookup")
        matches = []
        for key, row in (self.state.get("failure_memory") or {}).items():
            if not isinstance(row, dict):
                continue
            blob = f"{key} {row.get('error') or ''}".lower()
            if task.get("symbol") and task["symbol"].lower() in blob:
                matches.append(row)
            elif any(req.lower() in blob for req in task.get("required") or []):
                matches.append(row)
        task["prior_failures"] = matches[:8]
        return {"ok": True, "evidence": matches}

    def _interpret(self, task: dict[str, Any]) -> dict[str, Any]:
        task["attempt_count"] = int(task.get("attempt_count") or 0) + 1
        task["attempted_capabilities"] = _append(task.get("attempted_capabilities"), "cognitive_core")
        if not self.bus.available.get("cognitive_core", True):
            task["cognitive"] = {"review_status": "UNREVIEWED", "reason": "cognitive_core_unavailable"}
            task["last_error"] = "cognitive_core_unavailable"
            return {"ok": False, "error": "cognitive_core_unavailable"}
        try:
            from atlas.reasoning.cognitive_core import build_evidence_packet, reason_as_scientist
        except Exception as exc:  # noqa: BLE001
            task["cognitive"] = {"review_status": "UNREVIEWED", "reason": str(exc)}
            return {"ok": False, "error": str(exc)}
        known = [f"{k}: {_clip(v)}" for k, v in (task.get("evidence") or {}).items()]
        missing = self._missing(task)
        packet = build_evidence_packet(
            question=task.get("objective") or "",
            laboratory_id=self.laboratory_id,
            decision_id=(task.get("lineage") or {}).get("decision_id"),
            symbol=task.get("symbol"),
            evidence=known,
            known=known,
            unknowns=missing,
            experiences=list(task.get("prior_failures") or []),
        )
        try:
            if self.cognitive_fn is not None:
                advice = self.cognitive_fn(packet)
            else:
                advice = reason_as_scientist(packet=packet, llm=self.llm)
        except Exception as exc:  # noqa: BLE001
            advice = {"review_status": "UNREVIEWED", "reason": str(exc)}
        if not isinstance(advice, dict):
            advice = {"review_status": "UNREVIEWED", "reason": "non_dict_advice"}
        advice = strip_orders(advice)
        advice.setdefault("review_status", "UNREVIEWED")
        cog_id = new_id("COG")
        advice["id"] = cog_id
        task["cognitive"] = advice
        task["lineage"]["cognitive_result_id"] = cog_id
        if str(advice.get("review_status")) != "REVIEWED":
            task["last_error"] = str(advice.get("reason") or advice.get("skip_reason") or "unreviewed")
            return {"ok": False, "error": task["last_error"], "evidence": advice}
        return {"ok": True, "evidence": advice}

    def _conclude(self, task: dict[str, Any]) -> dict[str, Any]:
        if any("manufactured_evidence_rejected" in str(item) for item in task.get("failed") or []):
            return self._finish(
                task,
                STATUS_FAILED,
                reason="refused manufactured evidence",
                next_action="do_not_invent_missing_evidence",
                retry_policy="on_new_source",
                last_error="manufactured_evidence_rejected",
            )
        steps = (task.get("plan") or {}).get("steps") or []
        if any(s.get("kind") == "job_step" and not s.get("result_ok") for s in steps):
            if not self._missing(task):
                return self._finish(
                    task,
                    STATUS_PARTIAL,
                    reason="job steps were recorded and not executed as side effects",
                    next_action="route_safe_steps_only",
                    retry_policy="manual",
                )
        missing = self._missing(task)
        if missing:
            primary = missing[0]
            gap_name = _gap_name(str(task.get("missing_requirement") or primary))
            return self._finish(
                task,
                STATUS_CAPABILITY_GAP,
                reason=_gap_reason(task, primary),
                next_action=f"register_or_acquire:{gap_name}",
                retry_policy="on_capability_change",
                last_error=task.get("last_error") or f"{primary}_unavailable",
                missing=gap_name,
            )
        review = str((task.get("cognitive") or {}).get("review_status") or "")
        cog = task.get("cognitive") or {}
        if task.get("interpretive") and review != "REVIEWED":
            return self._finish(
                task,
                STATUS_UNVERIFIED,
                reason="evidence collected but interpretation is UNREVIEWED",
                next_action="retry_cognitive_core_when_available",
                retry_policy="on_capability_change",
                last_error=task.get("last_error") or "unreviewed",
            )
        if task.get("interpretive") and (
            not cog.get("conclusion") or not cog.get("uncertainty")
        ):
            return self._finish(
                task,
                STATUS_PARTIAL,
                reason="interpretation missing conclusion or uncertainty",
                next_action="request_conclusion_with_uncertainty",
                retry_policy="on_tick",
            )
        if task.get("deterministic_only"):
            rs = task["evidence"].get("relative_strength")
            if not isinstance(rs, dict) or "provenance" not in rs:
                return self._finish(
                    task,
                    STATUS_UNVERIFIED,
                    reason="calculation missing provenance",
                    next_action="rerun_calculation_with_inputs",
                    retry_policy="on_tick",
                    last_error="missing_provenance",
                )
        return self._finish(
            task,
            STATUS_SUCCESS,
            reason="verification passed",
            next_action="observe_outcome",
            retry_policy="on_event",
        )

    def _missing(self, task: dict[str, Any]) -> list[str]:
        missing = []
        evidence = task.get("evidence") or {}
        for req in task.get("required") or []:
            if req in DERIVED_REQUIREMENTS:
                deps = DERIVED_REQUIREMENTS[req]
                if any(dep not in evidence for dep in deps):
                    missing.append(req)
                    continue
                if req not in evidence:
                    missing.append(req)
                continue
            if req not in evidence or evidence.get(req) in (None, "", [], {}):
                missing.append(req)
        return missing

    def _finish(
        self,
        task: dict[str, Any],
        status: str,
        *,
        reason: str,
        next_action: str,
        retry_policy: str,
        last_error: str | None = None,
        missing: str | None = None,
    ) -> dict[str, Any]:
        task["status"] = status
        task["reason"] = reason
        task["next_action"] = next_action
        task["retry_policy"] = retry_policy
        task["last_error"] = last_error if last_error is not None else task.get("last_error")
        task["missing_requirement"] = missing
        task["updated_at"] = now_iso()
        task["attempted_capabilities"] = list(task.get("attempted_capabilities") or [])
        task["attempt_count"] = int(task.get("attempt_count") or 0)
        if status == STATUS_CAPABILITY_GAP:
            task["blocked_generations"] = dict(self.bus.generation)
            task["next_retry_at"] = None
            gap = {
                "task_id": task["id"],
                "episode_id": task.get("episode_id"),
                "status": status,
                "objective": task.get("objective"),
                "symbol": task.get("symbol"),
                "attempted": list(task.get("attempted_capabilities") or []),
                "failed": list(task.get("failed") or []),
                "missing": missing,
                "impact": task.get("impact"),
                "next_action": next_action,
                "retry": retry_policy,
                "reason": reason,
                "last_error": task.get("last_error"),
                "at": task["updated_at"],
            }
            self.state["capability_gaps"] = _prepend(self.state.get("capability_gaps"), gap, 40)
            self.state["recent_failures"] = _prepend(self.state.get("recent_failures"), gap, 40)
        elif status == STATUS_SUCCESS:
            task["next_retry_at"] = None
            task["missing_requirement"] = None
            self.state["recent_successes"] = _prepend(
                self.state.get("recent_successes"),
                {"task_id": task["id"], "objective": task.get("objective"), "at": task["updated_at"]},
                40,
            )
            self._schedule_followup(task)
        else:
            task["next_retry_at"] = None if retry_policy in {"manual", "never", "on_capability_change"} else now_iso()
        self._write_experience(task)
        self._note_uncertainty(task)
        episode = {
            "episode_id": task.get("episode_id"),
            "work_id": task["id"],
            "lineage": dict(task.get("lineage") or {}),
            "status": status,
            "objective": task.get("objective"),
            "symbol": task.get("symbol"),
            "at": task["updated_at"],
        }
        self.state["episodes"] = _prepend(self.state.get("episodes"), episode, 80)
        self._ensure_diagnostics(task)
        self.state["current_work"] = None
        self.save()
        return {
            "task_id": task["id"],
            "status": status,
            "reason": reason,
            "next_action": next_action,
            "missing": missing,
        }

    def _schedule_followup(self, task: dict[str, Any]) -> None:
        follow_id = new_id("AK")
        episode_id = new_id("EP")
        diag = blank_diagnostics()
        diag["reason"] = f"outcome observation for {task['id']}"
        diag["next_action"] = "observe_outcome_when_event_arrives"
        diag["retry_policy"] = "on_event"
        follow = {
            "id": follow_id,
            "fingerprint": f"follow:{task['id']}",
            "episode_id": episode_id,
            "source": "follow_up",
            "domain": task.get("domain"),
            "symbol": task.get("symbol"),
            "objective": f"Observe outcome of: {task.get('objective')}",
            "priority_class": "P2",
            "score": 50,
            "status": STATUS_WAITING,
            "required": [],
            "evidence": {},
            "evidence_refs": [],
            "uncertainty_refs": [],
            "failed": [],
            "plan": None,
            "interpretive": False,
            "deterministic_only": False,
            "needs_relative_strength": False,
            "constraints": {},
            "decision_impact": False,
            "impact": "outcome_check",
            "lineage": lineage(episode_id, follow_id, (task.get("lineage") or {}).get("decision_id")),
            "cognitive": None,
            "blocked_generations": {},
            "parent_work_id": task["id"],
            "created_at": now_iso(),
            "updated_at": now_iso(),
            **diag,
        }
        follow["lineage"]["prediction_id"] = task["lineage"].get("prediction_id")
        self.state["tasks"][follow_id] = follow

    def _write_experience(self, task: dict[str, Any]) -> None:
        status = task.get("status")
        lesson = _lesson(task)
        summary = {
            "episode_id": task.get("episode_id"),
            "work_id": task["id"],
            "status": status,
            "objective": task.get("objective"),
            "lesson": lesson,
            "provisional": True,
            "validated_lesson": False,
            "at": now_iso(),
        }
        payload = {
            "title": f"Agent kernel {status}: {task.get('symbol') or task.get('objective')}"[:180],
            "observation": task.get("reason") or task.get("objective") or "",
            "reasoning": "Escalation ladder over registered capabilities. Orders were not considered.",
            "decision": f"status={status}; next={task.get('next_action')}",
            "outcome": json.dumps(
                {
                    "attempted": task.get("attempted_capabilities"),
                    "failed": task.get("failed"),
                    "missing": task.get("missing_requirement"),
                },
                default=str,
            )[:2000],
            "reflection": task.get("reason") or "",
            "lesson": lesson,
            "domain": task.get("domain") or "investment",
            "tags": ["agent_kernel", "provisional", str(status).lower()],
            "metadata": {
                "validated_lesson": False,
                "promotion": "withheld",
                "lineage": task.get("lineage"),
                "never_orders": True,
            },
            "no_belief_link_reason": "agent_kernel episode has no belief id yet",
            "strict": True,
        }
        exp_id = None
        if self.experience_os is not None and hasattr(self.experience_os, "journal"):
            try:
                written = self.experience_os.journal(**payload)
            except Exception as exc:  # noqa: BLE001
                written = {"ok": False, "error": str(exc)}
            summary["experience_os"] = written if isinstance(written, dict) else {"ok": False}
            if isinstance(written, dict) and written.get("ok"):
                result = written.get("result") if isinstance(written.get("result"), dict) else {}
                exp_id = str(result.get("id") or result.get("experience_id") or new_id("EXP"))
        if exp_id is None:
            exp_id = new_id("EXP")
            summary["experience_os"] = summary.get("experience_os") or {
                "ok": False,
                "error": "experience_os_unavailable",
                "stored_in": "agent_kernel_state",
            }
        task["lineage"]["experience_id"] = exp_id
        task["lineage"]["lesson_id"] = None
        summary["experience_id"] = exp_id
        self.state["experiences"] = _prepend(self.state.get("experiences"), summary, 80)

    def _note_uncertainty(self, task: dict[str, Any]) -> None:
        refs = task.get("uncertainty_refs") or []
        if not refs:
            return
        try:
            from atlas.investment.uncertainty_queue import mark_task, note_attempt
        except Exception:  # noqa: BLE001
            return
        for ref in refs:
            try:
                if task.get("status") == STATUS_SUCCESS:
                    mark_task(
                        self.data_dir,
                        str(ref),
                        laboratory_id=self.laboratory_id,
                        status="DONE",
                        note="agent_kernel resolved with cited evidence",
                        provider="agent_kernel",
                    )
                else:
                    note_attempt(
                        self.data_dir,
                        str(ref),
                        laboratory_id=self.laboratory_id,
                        provider="agent_kernel",
                        error=str(task.get("last_error") or task.get("status"))[:300],
                    )
            except Exception:  # noqa: BLE001
                self._logger.debug("uncertainty note failed", exc_info=True)

    def _journal(self, note: str, report: dict[str, Any]) -> None:
        if self.activity_journal is None or not hasattr(self.activity_journal, "record"):
            return
        try:
            self.activity_journal.record(
                domain="agent_kernel",
                worker="agent_kernel",
                action="cycle",
                summary=note[:500],
                result="completed",
                evidence={
                    "ran": report.get("ran"),
                    "created": report.get("created"),
                    "mode": report.get("mode"),
                },
            )
        except Exception:  # noqa: BLE001
            self._logger.debug("activity journal failed", exc_info=True)

    def _refresh_indexes(self) -> None:
        raw = self.state.get("tasks") or {}
        tasks = [t for t in raw.values() if isinstance(t, dict)]
        self.state["open_questions"] = [
            {
                "task_id": t.get("id"),
                "missing": t.get("missing_requirement"),
                "objective": t.get("objective"),
            }
            for t in tasks
            if t.get("status") in NON_SUCCESS and t.get("missing_requirement")
        ][:40]
        self.state["next_actions"] = [
            {
                "task_id": t.get("id"),
                "status": t.get("status"),
                "next_action": t.get("next_action"),
                "priority_class": t.get("priority_class"),
            }
            for t in tasks
            if t.get("status") != STATUS_SUCCESS
        ][:40]
        self.state["active_hypotheses"] = [
            (t.get("cognitive") or {}).get("conclusion") or (t.get("cognitive") or {}).get("hypothesis")
            for t in tasks
            if isinstance(t.get("cognitive"), dict)
        ][:20]
        self.state["pending_verifications"] = [
            t.get("id") for t in tasks if t.get("status") in {STATUS_UNVERIFIED, STATUS_PARTIAL, STATUS_WAITING}
        ][:40]

    def _ensure_diagnostics(self, task: dict[str, Any]) -> None:
        for key in DIAGNOSTIC_FIELDS:
            task.setdefault(key, None if key in {"last_error", "missing_requirement", "next_retry_at"} else [])
        if task.get("status") in NON_SUCCESS:
            if not task.get("reason"):
                task["reason"] = "unspecified"
            if not task.get("next_action"):
                task["next_action"] = "review"


def _search_query(task: dict[str, Any], requirement: str) -> str:
    parts = [
        str(task.get("symbol") or "").strip(),
        str(requirement or "").replace("_", " ").strip(),
        str(task.get("objective") or "").strip(),
    ]
    return " ".join(part for part in parts if part)[:400]


def _looks_interpretive(objective: str) -> bool:
    text = objective.lower()
    return any(token in text for token in ("should ", "whether ", "well supported", "explain "))


def _looks_deterministic(objective: str) -> bool:
    text = objective.lower()
    return text.startswith("determine historical") or "calculate" in text


def _gap_name(requirement: str) -> str:
    if requirement in {"sector_benchmark", "sector_history", "sector_ohlcv"}:
        return "durable_sector_OHLCV_provider"
    return requirement


def _gap_reason(task: dict[str, Any], requirement: str) -> str:
    episode = task.get("episode_id")
    priors = [
        row
        for row in (task.get("prior_failures") or [])
        if isinstance(row, dict) and row.get("episode_id") not in {None, episode}
    ]
    if priors:
        err = priors[0].get("error") or "the same approach failed"
        return f"previously failed because {err}; {requirement} still unavailable"
    if requirement in {"sector_benchmark", "sector_history", "sector_ohlcv", "durable_sector_OHLCV_provider"}:
        return "historical sector series unavailable"
    if "sector" in requirement:
        return "historical sector series unavailable"
    return f"{requirement} unavailable after the escalation ladder"


def _lesson(task: dict[str, Any]) -> str:
    if task.get("status") == STATUS_CAPABILITY_GAP:
        return (
            f"Atlas currently lacks {task.get('missing_requirement') or 'a required source'}. "
            "Retry only when that capability changes. Provisional — not a validated lesson."
        )
    if task.get("status") == STATUS_SUCCESS:
        return (
            "When a similar question appears, retrieve the cited evidence before interpreting it. "
            "Provisional — not a validated lesson."
        )
    return (
        f"Episode ended {task.get('status')}: {task.get('reason') or ''}. "
        "Provisional — not a validated lesson."
    )


def _clip(value: Any) -> str:
    return str(value)[:180]


def _append(values: Any, item: str) -> list[str]:
    out = [str(v) for v in (values or [])]
    if item not in out:
        out.append(item)
    return out


def _prepend(values: Any, item: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    rows = [item]
    for row in values or []:
        if isinstance(row, dict):
            rows.append(row)
    return rows[:limit]
