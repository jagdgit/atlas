"""Capability surface the kernel can plan against.

Investment evidence adapters (ladder) live here. Live toolbox entries
(``sql``, ``logs``, ``git``, ``code``, …) are merged from
``CapabilityRegistry`` / ``ToolRegistry`` via :func:`build_unified_catalog`
so Agent Kernel does not keep a parallel orphan tool list (J1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Escalation ladder. Cognitive Core is last and never a fact source.
LADDER: tuple[tuple[str, int], ...] = (
    ("local_market_store", 0),
    ("knowledge_search", 1),
    ("structured_provider", 2),
    ("web_search", 3),
    ("news_search", 3),
    ("research_scientist", 4),
    ("alternative_source", 5),
    ("cognitive_core", 6),
)

NEWS_REQUIREMENTS = frozenset({"company_news", "news", "headlines"})
DERIVED_REQUIREMENTS = {
    "relative_strength": ("price_history", "sector_benchmark"),
}

# Toolbox ids that must come from the live registry, never a hard-coded orphan list.
LIVE_TOOLBOX = frozenset({"sql", "logs", "git", "code", "python"})


@dataclass(frozen=True)
class KernelCapability:
    name: str
    description: str
    atlas_capability: str
    cost: str
    latency: str
    domains: tuple[str, ...]
    side_effect_level: str
    verification: str
    failure_modes: tuple[str, ...]
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


def _live_toolbox_specs() -> dict[str, KernelCapability]:
    """Descriptors for registry-backed toolbox capabilities (added only when live)."""
    evidence_out = {"ok": "bool", "outcome": "str", "error": "str"}
    return {
        "sql": KernelCapability(
            "sql",
            "Read-only SQL over Atlas Postgres / local DBs (sql.query / tables / schema).",
            "sql",
            "cheap",
            "low",
            ("general", "ops"),
            "read",
            "structured rows + outcome",
            ("blocked", "unavailable", "error"),
            {"sql": "str", "source": "str", "limit": "int"},
            evidence_out,
        ),
        "logs": KernelCapability(
            "logs",
            "List, tail, and search Atlas's own log files (secret-redacted).",
            "logs",
            "cheap",
            "low",
            ("general", "ops"),
            "read",
            "redacted log lines",
            ("blocked", "empty", "unavailable"),
            {"pattern": "str", "file": "str", "lines": "int"},
            evidence_out,
        ),
        "git": KernelCapability(
            "git",
            "Read-only local git status, log, diff, branches, file history.",
            "git",
            "cheap",
            "low",
            ("general", "engineering"),
            "read",
            "repo snapshot",
            ("unavailable", "not_a_repo"),
            {"repo": "str"},
            evidence_out,
        ),
        "code": KernelCapability(
            "code",
            "Parse and map the local codebase (symbols, graph, patterns).",
            "code",
            "cheap",
            "low",
            ("general", "engineering"),
            "read",
            "structured code facts",
            ("unavailable",),
            {"path": "str", "query": "str"},
            evidence_out,
        ),
        "python": KernelCapability(
            "python",
            "Deterministic Python execution for calculations on retrieved inputs.",
            "python",
            "cheap",
            "low",
            ("general", "investment"),
            "read",
            "value + provenance",
            ("inputs_missing", "error"),
            {"code": "str", "inputs": "list"},
            {"value": "number", "provenance": "list"},
        ),
    }


def _live_name_present(name: str, capabilities: Any, tools: Any) -> bool:
    if capabilities is not None and hasattr(capabilities, "has") and capabilities.has(name):
        return True
    if tools is None:
        return False
    names = list(tools.names()) if hasattr(tools, "names") else []
    prefix = f"{name}."
    return any(str(n).startswith(prefix) or str(n) == name for n in names)


def build_unified_catalog(
    capabilities: Any = None,
    tools: Any = None,
) -> dict[str, KernelCapability]:
    """Investment ladder + live toolbox entries that are actually registered (J1)."""
    catalog = dict(default_catalog())
    for name, spec in _live_toolbox_specs().items():
        if _live_name_present(name, capabilities, tools):
            catalog[name] = spec
    return catalog


def default_catalog() -> dict[str, KernelCapability]:
    """Investment evidence adapters (ladder). Live toolbox is layered by
    :func:`build_unified_catalog` — do not hard-code sql/logs/git/code here.
    """
    common_in = {"requirement": "str", "symbol": "str", "objective": "str"}
    evidence_out = {"ok": "bool", "evidence": "object", "citations": "list", "error": "str"}
    rows = [
        KernelCapability(
            "local_market_store",
            "Read durable local bars, completeness, and research files.",
            "memory",
            "cheap",
            "low",
            ("investment",),
            "read",
            "provenance path + no invented fields",
            ("missing_file", "null_fundamental"),
            common_in,
            evidence_out,
        ),
        KernelCapability(
            "knowledge_search",
            "Knowledge / RAG lookup. Insufficient context stays insufficient.",
            "knowledge",
            "cheap",
            "low",
            ("investment", "general"),
            "read",
            "citations or explicit insufficient",
            ("insufficient", "unavailable"),
            common_in,
            evidence_out,
        ),
        KernelCapability(
            "structured_provider",
            "Existing structured market or fundamental provider.",
            "market_reader",
            "moderate",
            "medium",
            ("investment",),
            "read",
            "provider payload + source",
            ("provider_missing", "series_unavailable"),
            common_in,
            evidence_out,
        ),
        KernelCapability(
            "web_search",
            "External web/search acquisition when local evidence is insufficient.",
            "search",
            "moderate",
            "medium",
            ("investment", "general"),
            "read",
            "at least one citation; otherwise unverified",
            ("no_reliable_series", "unavailable"),
            common_in,
            evidence_out,
        ),
        KernelCapability(
            "news_search",
            "News acquisition for company-event timing.",
            "search",
            "moderate",
            "medium",
            ("investment",),
            "read",
            "cited headlines",
            ("no_headlines",),
            common_in,
            evidence_out,
        ),
        KernelCapability(
            "research_scientist",
            "Existing research loop. Advice and evidence only.",
            "research",
            "expensive",
            "high",
            ("investment", "general"),
            "read",
            "answer + evidence + uncertainty",
            ("unavailable", "unverified"),
            common_in,
            evidence_out,
        ),
        KernelCapability(
            "alternative_source",
            "A different source for the same requirement after the primary path fails.",
            "web",
            "moderate",
            "medium",
            ("investment",),
            "read",
            "independent provenance",
            ("unavailable",),
            common_in,
            evidence_out,
        ),
        KernelCapability(
            "python_calculation",
            "Deterministic calculation from already retrieved inputs.",
            "python",
            "cheap",
            "low",
            ("investment", "general"),
            "read",
            "inputs present + sanity range",
            ("inputs_missing",),
            {"inputs": "list"},
            {"value": "number", "provenance": "list"},
        ),
        KernelCapability(
            "experience_lookup",
            "Prior episodes from kernel failure memory and Experience OS.",
            "learning",
            "cheap",
            "low",
            ("general",),
            "read",
            "retrieved record ids",
            ("none",),
            {"query": "str"},
            {"matches": "list"},
        ),
        KernelCapability(
            "cognitive_core",
            "Interpretation over a bounded evidence packet. Never orders.",
            "llm",
            "llm",
            "high",
            ("general", "investment"),
            "advice",
            "review_status set; orders stripped",
            ("unreviewed", "no_llm"),
            {"packet": "object"},
            {"review_status": "str", "conclusion": "str"},
        ),
        KernelCapability(
            "worker.lifecycle",
            "Resume a paper lab worker paused by Phase-5 accidental dedupe only.",
            "worker.lifecycle",
            "cheap",
            "low",
            ("ops",),
            "write",
            "resume receipt; never pause/stop/create",
            ("not_allowed", "pause_reason_not_phase5_stale", "unavailable"),
            {"action": "str", "laboratory_id": "str"},
            {"ok": "bool", "worker_id": "str", "status": "str", "error": "str"},
        ),
    ]
    return {row.name: row for row in rows}


class EvidenceBus:
    """What each capability can currently return. Tests and adapters fill slots."""

    def __init__(self, catalog: dict[str, KernelCapability] | None = None) -> None:
        self._catalog: dict[str, KernelCapability] = dict(catalog or default_catalog())
        self.available: dict[str, bool] = {name: True for name in self._catalog}
        self.slots: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[dict[str, Any]] = []
        self.generation: dict[str, int] = {name: 0 for name in self._catalog}
        self.forced: set[str] = set()
        self.status_reason: dict[str, str] = {}

    def catalog_names(self) -> list[str]:
        return list(self._catalog)

    def replace_catalog(self, catalog: dict[str, KernelCapability]) -> None:
        """J1 — swap in a unified catalog (ladder + live toolbox). Preserves slots."""
        self._catalog = dict(catalog)
        for name in self._catalog:
            self.available.setdefault(name, True)
            self.generation.setdefault(name, 0)

    def sync_from_registries(self, capabilities: Any = None, tools: Any = None) -> None:
        self.replace_catalog(build_unified_catalog(capabilities, tools))

    def catalog_view(self) -> list[dict[str, Any]]:
        out = []
        for name, spec in self._catalog.items():
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "atlas_capability": spec.atlas_capability,
                    "input_schema": dict(spec.input_schema),
                    "output_schema": dict(spec.output_schema),
                    "cost": spec.cost,
                    "latency": spec.latency,
                    "available": bool(self.available.get(name)),
                    "domains": list(spec.domains),
                    "side_effect_level": spec.side_effect_level,
                    "verification": spec.verification,
                    "failure_modes": list(spec.failure_modes),
                    "generation": int(self.generation.get(name) or 0),
                }
            )
        return out

    def put(self, capability: str, requirement: str, payload: dict[str, Any]) -> None:
        self.slots[(capability, requirement)] = dict(payload)
        self.available[capability] = True
        self.forced.add(capability)
        self.generation[capability] = int(self.generation.get(capability) or 0) + 1

    def set_available(self, capability: str, available: bool) -> None:
        self.available[capability] = bool(available)
        self.generation[capability] = int(self.generation.get(capability) or 0) + 1
        if available:
            self.forced.add(capability)

    def apply_external_policy(
        self,
        allow_external: bool,
        *,
        web_available: bool | None = None,
        web_reason: str | None = None,
    ) -> None:
        """Policy false disables external caps. True does not invent a client."""
        if not allow_external:
            self._set_external("web_search", False, "POLICY_DISABLED")
            self._set_external("news_search", False, "POLICY_DISABLED")
            if "research_scientist" not in self.forced:
                self.available["research_scientist"] = False
            return
        if web_available is None:
            return
        reason = web_reason or ("SUCCESS" if web_available else "CLIENT_NOT_CONFIGURED")
        self._set_external("web_search", bool(web_available), reason)
        # No separate production news-search provider. Do not alias web search.
        self._set_external("news_search", False, "CLIENT_NOT_CONFIGURED")

    def _set_external(self, name: str, available: bool, reason: str) -> None:
        self.status_reason[name] = reason
        if name in self.forced:
            return
        current = bool(self.available.get(name))
        self.available[name] = bool(available)
        if current != bool(available):
            self.generation[name] = int(self.generation.get(name) or 0) + 1

    def has_slot(self, capability: str, requirement: str) -> bool:
        return (capability, requirement) in self.slots or (capability, "*") in self.slots

    def query(self, capability: str, requirement: str) -> dict[str, Any]:
        self.calls.append({"capability": capability, "requirement": requirement})
        if not self.available.get(capability, False):
            return {
                "ok": False,
                "error": f"{capability}_unavailable",
                "missing": capability,
                "citations": [],
                "invented": False,
            }
        payload = self.slots.get((capability, requirement))
        if payload is None:
            payload = self.slots.get((capability, "*"))
        if not payload:
            return {
                "ok": False,
                "error": f"{requirement}_not_available",
                "missing": requirement,
                "citations": [],
                "invented": False,
            }
        if payload.get("invented"):
            return {
                "ok": False,
                "error": "manufactured_evidence_rejected",
                "missing": requirement,
                "citations": [],
                "invented": True,
            }
        if payload.get("insufficient") or payload.get("ok") is False:
            return {
                "ok": False,
                "error": str(payload.get("error") or "insufficient"),
                "missing": str(payload.get("missing") or requirement),
                "citations": list(payload.get("citations") or []),
                "invented": False,
            }
        evidence = payload.get("evidence", payload)
        return {
            "ok": True,
            "evidence": evidence,
            "citations": list(payload.get("citations") or []),
            "invented": False,
            "error": None,
            "missing": None,
        }

    def call_count(self, capability: str, requirement: str | None = None) -> int:
        n = 0
        for row in self.calls:
            if row.get("capability") != capability:
                continue
            if requirement is not None and row.get("requirement") != requirement:
                continue
            n += 1
        return n
