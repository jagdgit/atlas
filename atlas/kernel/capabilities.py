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
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(
        self,
        name: str,
        provider: Any,
        *,
        contract: type | None = None,
        **metadata: Any,
    ) -> None:
        """Advertise ``name`` as provided by ``provider`` (last registration wins).

        Optionally attach a ``contract`` (Protocol) the provider is expected to
        implement; use :meth:`verify` to check it.
        """
        self._capabilities[name] = Capability(name, provider, contract, dict(metadata))

    def has(self, name: str) -> bool:
        return name in self._capabilities

    def get(self, name: str) -> Any:
        try:
            return self._capabilities[name].provider
        except KeyError:
            raise CapabilityMissingError(
                f"no capability registered named '{name}'", capability=name
            ) from None

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
        """
        seen: dict[str, None] = {}
        for name in required:
            if name not in self._capabilities:
                seen.setdefault(name, None)
        return list(seen)

    def names(self) -> list[str]:
        return sorted(self._capabilities)

    def describe(self) -> dict[str, dict[str, Any]]:
        """Return capability name -> metadata (+ contract) for introspection."""
        out: dict[str, dict[str, Any]] = {}
        for name, cap in sorted(self._capabilities.items()):
            meta = dict(cap.metadata)
            if cap.contract is not None:
                meta.setdefault("contract", cap.contract.__name__)
            out[name] = meta
        return out
