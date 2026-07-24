"""Capability Registry (ADR-0040; typed contracts added in S11).

Maps a capability *name* to the provider that offers it. Agents ask the kernel
"do I have X?" instead of importing modules, so plugins/services are truly
optional and swappable (ADR-0041) and an agent can degrade gracefully when a
capability is absent rather than failing at import time.

S11 makes capabilities **typed**: a registration may attach a ``contract`` (a
``runtime_checkable`` Protocol from ``atlas.capabilities``). The registry can then
*verify* that a provider actually implements its contract and report which required
capabilities are ``missing`` — the machinery behind honest Capability Gap Reports
(R2). Registration stays back-compatible: ``contract`` is optional.

This complements — it does not replace — the DI container (ADR-0043):

    container      = HOW to build a dependency (by key)
    capabilities   = WHAT is available to agents (by capability name)

Kept intentionally small to honour "the kernel is not a god object".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from atlas.exceptions import CapabilityMissingError


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    provider: Any
    contract: type | None = None
    # Phase 0 enrichment (ATLAS_OS_ROADMAP §5.10): self-inspection fields. ``version``
    # is the *real* build/version of the provider (source for artifact stamping, P2);
    # ``enabled`` lets a registered-but-off capability be advertised honestly;
    # ``dependencies`` are other capability names this one needs.
    version: str | None = None
    enabled: bool = True
    dependencies: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapabilityInfo:
    """Live snapshot of a capability (ATLAS_OS_ROADMAP §5.10 self-inspection).

    Produced by :meth:`CapabilityRegistry.inspect` on demand (pull model, R2/A3):
    the registry *probes* the provider for health/metrics rather than requiring it to
    push. ``healthy`` is ``None`` when the provider exposes no ``health_check``.
    """

    name: str
    kind: str | None
    version: str | None
    enabled: bool
    healthy: bool | None
    health_detail: str
    contract: str | None
    dependencies: tuple[str, ...]
    missing_dependencies: tuple[str, ...]
    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "version": self.version,
            "enabled": self.enabled,
            "healthy": self.healthy,
            "health_detail": self.health_detail,
            "contract": self.contract,
            "dependencies": list(self.dependencies),
            "missing_dependencies": list(self.missing_dependencies),
            "metrics": self.metrics,
        }


class CapabilityRegistry:
    def __init__(self, default_version: str | None = None) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._aliases: dict[str, str] = {}
        # Fallback version for capabilities that declare none and whose provider
        # exposes no version attribute — typically the Atlas package version, so
        # artifact stamping (P2) never records a hardcoded ``"v1"``.
        self._default_version = default_version

    def register(
        self,
        name: str,
        provider: Any,
        *,
        contract: type | None = None,
        version: str | None = None,
        enabled: bool = True,
        dependencies: Iterable[str] = (),
        **metadata: Any,
    ) -> None:
        """Advertise ``name`` as provided by ``provider`` (last registration wins).

        Optionally attach a ``contract`` (Protocol) the provider is expected to
        implement; use :meth:`verify` to check it. Phase 0 adds optional ``version``,
        ``enabled`` and ``dependencies`` for self-inspection (§5.10) — all
        back-compatible (callers that omit them are unchanged).
        """
        self._capabilities[name] = Capability(
            name,
            provider,
            contract,
            version=version,
            enabled=enabled,
            dependencies=tuple(dependencies),
            metadata=dict(metadata),
        )

    def alias(self, alias_name: str, target: str) -> None:
        """Map an operator/docs name onto a registered capability id (CAP.1)."""
        alias_name = (alias_name or "").strip()
        target = (target or "").strip()
        if not alias_name or not target:
            raise ValueError("alias_name and target are required")
        self._aliases[alias_name] = target
        # Case-insensitive convenience
        self._aliases[alias_name.lower()] = target

    def resolve_name(self, name: str) -> str:
        """Follow aliases to a canonical capability id."""
        from atlas.capabilities.needs import canonicalize

        raw = (name or "").strip()
        if not raw:
            return raw
        if raw in self._aliases:
            return self._aliases[raw]
        if raw.lower() in self._aliases:
            return self._aliases[raw.lower()]
        canon = canonicalize(raw)
        if canon in self._aliases:
            return self._aliases[canon]
        return canon

    def check_needs(
        self,
        needs: Iterable[str],
        *,
        require_healthy: bool = False,
    ) -> dict[str, Any]:
        """Resolve mission needs against the registry (satisfied / missing / disabled).

        Returns a NeedsReport dict suitable for journals and CapabilityGap payloads.
        """
        satisfied: list[dict[str, Any]] = []
        missing: list[str] = []
        disabled: list[str] = []
        unhealthy: list[str] = []
        seen: set[str] = set()
        for raw in needs:
            canon = self.resolve_name(str(raw))
            if not canon or canon in seen:
                continue
            seen.add(canon)
            cap = self._capabilities.get(canon)
            if cap is None:
                missing.append(canon)
                continue
            if not cap.enabled:
                disabled.append(canon)
                continue
            info = {
                "name": canon,
                "requested_as": str(raw),
                "version": self._resolve_version(cap),
                "kind": cap.metadata.get("kind"),
            }
            if require_healthy:
                healthy, detail, _ = self._probe_health(cap.provider)
                if healthy is False:
                    unhealthy.append(canon)
                    info["health_detail"] = detail
                    continue
            satisfied.append(info)
        ok = not missing and not disabled and not unhealthy
        return {
            "ok": ok,
            "satisfied": satisfied,
            "missing": missing,
            "disabled": disabled,
            "unhealthy": unhealthy,
            "version": "cap.1",
        }

    def provider_for(self, name: str) -> Any:
        """Resolve alias → capability → provider (raises if missing/disabled)."""
        canon = self.resolve_name(name)
        cap = self._capabilities.get(canon)
        if cap is None:
            raise CapabilityMissingError(
                f"no capability registered named '{canon}' (from '{name}')",
                capability=canon,
            )
        if not cap.enabled:
            raise CapabilityMissingError(
                f"capability '{canon}' is registered but disabled",
                capability=canon,
            )
        return cap.provider

    def has(self, name: str) -> bool:
        return self.resolve_name(name) in self._capabilities

    def get(self, name: str) -> Any:
        try:
            return self.provider_for(name)
        except CapabilityMissingError:
            # Preserve prior KeyError-style message for unknown names without alias noise
            canon = self.resolve_name(name)
            if canon not in self._capabilities:
                raise CapabilityMissingError(
                    f"no capability registered named '{name}'", capability=name
                ) from None
            raise

    def contract_of(self, name: str) -> type | None:
        cap = self._capabilities.get(name)
        return cap.contract if cap else None

    def verify(self, name: str) -> bool:
        """True if ``name`` is registered and its provider satisfies its contract.

        A capability with no declared contract is considered valid (nothing to
        check). Relies on ``runtime_checkable`` Protocols (method-presence check).
        """
        cap = self._capabilities.get(name)
        if cap is None:
            return False
        if cap.contract is None:
            return True
        try:
            return isinstance(cap.provider, cap.contract)
        except TypeError:
            # Non-runtime-checkable contract (e.g. a placeholder Protocol): treat
            # mere registration as sufficient.
            return True

    def missing(self, required: Iterable[str]) -> list[str]:
        """Return the required capability ids that are *not* registered.

        Order-preserving and de-duplicated — the input to a Gap Report (R2).
        Resolves aliases (CAP.1).
        """
        seen: dict[str, None] = {}
        for name in required:
            canon = self.resolve_name(str(name))
            if canon not in self._capabilities:
                seen.setdefault(canon, None)
        return list(seen)

    def names(self) -> list[str]:
        return sorted(self._capabilities)

    def describe(self) -> dict[str, dict[str, Any]]:
        """Return capability name -> metadata (+ contract) for introspection.

        Back-compatible: existing keys (``contract``, ``kind`` and any registration
        metadata) are preserved; Phase 0 adds ``version``/``enabled``/``dependencies``.
        """
        out: dict[str, dict[str, Any]] = {}
        for name, cap in sorted(self._capabilities.items()):
            meta = dict(cap.metadata)
            if cap.contract is not None:
                meta.setdefault("contract", cap.contract.__name__)
            meta.setdefault("version", self._resolve_version(cap))
            meta.setdefault("enabled", cap.enabled)
            meta.setdefault("dependencies", list(cap.dependencies))
            out[name] = meta
        return out

    def version_of(self, name: str) -> str | None:
        """Real version of a registered capability (source for artifact stamping, P2).

        Resolution order: explicit ``version=`` at registration, then a ``version`` /
        ``__version__`` attribute on the provider, else ``None``.
        """
        cap = self._capabilities.get(name)
        return self._resolve_version(cap) if cap is not None else None

    def inspect(self, name: str) -> CapabilityInfo:
        """Probe a capability for a live self-inspection snapshot (§5.10, pull model).

        Never raises for a *registered* capability: a provider whose ``health_check``
        or ``metrics`` blows up is reported as unhealthy / empty metrics rather than
        propagating. Raises :class:`CapabilityMissingError` only if ``name`` is unknown.
        """
        cap = self._capabilities.get(name)
        if cap is None:
            raise CapabilityMissingError(
                f"no capability registered named '{name}'", capability=name
            )
        healthy, detail, health_data = self._probe_health(cap.provider)
        metrics = self._probe_metrics(cap.provider)
        if health_data:
            # Fold health-check data under a namespace so it doesn't clobber metrics.
            metrics = {**metrics, "health": health_data}
        missing = tuple(d for d in cap.dependencies if d not in self._capabilities)
        return CapabilityInfo(
            name=cap.name,
            kind=cap.metadata.get("kind"),
            version=self._resolve_version(cap),
            enabled=cap.enabled,
            healthy=healthy,
            health_detail=detail,
            contract=cap.contract.__name__ if cap.contract is not None else None,
            dependencies=cap.dependencies,
            missing_dependencies=missing,
            metrics=metrics,
        )

    def inspect_all(self) -> dict[str, dict[str, Any]]:
        """Live self-inspection of every registered capability (name -> info dict)."""
        return {name: self.inspect(name).as_dict() for name in sorted(self._capabilities)}

    def self_report_gaps(self, *, include_missions: bool = True) -> dict[str, Any]:
        """First-class P15 gap self-report (OI-F5): what Atlas cannot do *right now*.

        Aggregates:
        - **catalog_gaps** — known capabilities in ``CAPABILITY_CATALOG`` that are not registered
        - **mission_gaps** — built-in mission need sets that are unsatisfied
        - **unhealthy** — registered providers whose health_check fails
        """
        from atlas.capabilities.contracts import describe_capabilities, gap_report
        from atlas.capabilities.needs import MISSION_NEEDS

        rows = describe_capabilities(self)
        catalog_missing = [str(r["id"]) for r in rows if not r.get("provided")]
        catalog_gaps = gap_report(catalog_missing)

        mission_gaps: list[dict[str, Any]] = []
        if include_missions:
            for mission, needs in sorted(MISSION_NEEDS.items()):
                report = self.check_needs(needs)
                if report.get("ok"):
                    continue
                mission_gaps.append(
                    {
                        "mission": mission,
                        "missing": list(report.get("missing") or []),
                        "disabled": list(report.get("disabled") or []),
                        "unhealthy": list(report.get("unhealthy") or []),
                    }
                )

        unhealthy: list[dict[str, Any]] = []
        for name in self.names():
            info = self.inspect(name)
            if info.healthy is False:
                unhealthy.append(
                    {
                        "name": name,
                        "detail": info.health_detail,
                        "version": info.version,
                    }
                )

        return {
            "version": "f5.1",
            "ok": not catalog_gaps and not mission_gaps and not unhealthy,
            "catalog_gaps": catalog_gaps,
            "mission_gaps": mission_gaps,
            "unhealthy": unhealthy,
            "summary": {
                "catalog_missing": len(catalog_gaps),
                "missions_blocked": len(mission_gaps),
                "unhealthy": len(unhealthy),
            },
            "principle": "P15 — never pretend a missing capability exists",
            "related": {
                "decision_gaps": "GET /v1/decision/gaps",
                "needs_check": "POST /v1/capabilities/needs",
            },
        }

    def _resolve_version(self, cap: Capability) -> str | None:
        if cap.version is not None:
            return cap.version
        for attr in ("version", "__version__"):
            value = getattr(cap.provider, attr, None)
            if isinstance(value, str) and value:
                return value
        return self._default_version

    @staticmethod
    def _probe_health(provider: Any) -> tuple[bool | None, str, dict[str, Any]]:
        check = getattr(provider, "health_check", None)
        if not callable(check):
            return None, "", {}
        try:
            status = check()
        except Exception as exc:  # noqa: BLE001 - probing must never crash inspection
            return False, f"health_check raised: {exc}", {}
        healthy = bool(getattr(status, "healthy", False))
        detail = str(getattr(status, "detail", "") or "")
        data = getattr(status, "data", None)
        return healthy, detail, dict(data) if isinstance(data, dict) else {}

    @staticmethod
    def _probe_metrics(provider: Any) -> dict[str, Any]:
        getter = getattr(provider, "metrics", None)
        if not callable(getter):
            return {}
        try:
            result = getter()
        except Exception:  # noqa: BLE001 - metrics are best-effort
            return {}
        return dict(result) if isinstance(result, dict) else {}
