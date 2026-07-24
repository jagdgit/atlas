"""World Models — platform framework for domain *structure* (WM.1 / V6.5).

Not a claim store: Knowledge OS holds statements; World Models hold exchange hours,
settlement rules, sector taxonomy, irradiance units, etc. Domain packs supply content;
this package owns the shape (solar-plant test).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class WorldFact:
    """One structural fact in a domain World Model (not a Knowledge claim)."""

    id: str
    kind: str  # exchange | session | sector | settlement | ...
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)
    pack_id: str = ""
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def matches(self, needle: str) -> bool:
        n = (needle or "").strip().lower()
        if not n:
            return True
        hay = " ".join(
            [
                self.id,
                self.kind,
                self.label,
                " ".join(self.tags),
                " ".join(f"{k} {v}" for k, v in self.attributes.items()),
            ]
        ).lower()
        return n in hay or any(tok in hay for tok in n.split() if len(tok) > 2)


@runtime_checkable
class WorldModelPack(Protocol):
    """Domain pack contract — Market, Solar, etc. implement this."""

    id: str
    name: str
    program_hint: str  # market | engineering | personal | solar | ...
    version: str

    def facts(self) -> list[WorldFact]:
        ...

    def describe(self) -> dict[str, Any]:
        ...


@dataclass
class StaticWorldModelPack:
    """Concrete pack built from an in-memory fact list (hermetic / seed)."""

    id: str
    name: str
    program_hint: str
    version: str
    _facts: list[WorldFact] = field(default_factory=list)
    description: str = ""

    def facts(self) -> list[WorldFact]:
        return [
            WorldFact(
                id=f.id,
                kind=f.kind,
                label=f.label,
                attributes=dict(f.attributes),
                pack_id=self.id,
                tags=f.tags,
            )
            for f in self._facts
        ]

    def describe(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for f in self._facts:
            kinds[f.kind] = kinds.get(f.kind, 0) + 1
        return {
            "id": self.id,
            "name": self.name,
            "program_hint": self.program_hint,
            "version": self.version,
            "description": self.description,
            "fact_count": len(self._facts),
            "kinds": kinds,
        }


class WorldModelRegistry:
    """Platform registry of World Model packs (framework, not domain content)."""

    VERSION = "wm.1"

    def __init__(self) -> None:
        self._packs: dict[str, WorldModelPack] = {}

    def register(self, pack: WorldModelPack) -> None:
        pid = str(getattr(pack, "id", "") or "").strip()
        if not pid:
            raise ValueError("WorldModelPack must have a non-empty id")
        self._packs[pid] = pack

    def list_packs(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for pack in self._packs.values():
            desc = pack.describe() if hasattr(pack, "describe") else {
                "id": pack.id,
                "name": pack.name,
                "program_hint": pack.program_hint,
                "version": pack.version,
            }
            out.append(desc)
        return sorted(out, key=lambda d: d.get("id") or "")

    def get(self, pack_id: str) -> WorldModelPack | None:
        return self._packs.get(str(pack_id or "").strip())

    def facts(
        self,
        *,
        pack_id: str | None = None,
        kind: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        packs: list[WorldModelPack]
        if pack_id:
            pack = self.get(pack_id)
            packs = [pack] if pack is not None else []
        else:
            packs = list(self._packs.values())
        kind_l = (kind or "").strip().lower() or None
        needle = (q or "").strip()
        rows: list[dict[str, Any]] = []
        for pack in packs:
            for fact in pack.facts():
                if kind_l and fact.kind.lower() != kind_l:
                    continue
                if needle and not fact.matches(needle):
                    continue
                rows.append(fact.as_dict())
                if len(rows) >= limit:
                    return rows
        return rows

    def context_for(
        self,
        topic: str,
        *,
        program_id: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Structural facts for Mission Context (MCA) — not Knowledge claims."""
        topic = (topic or "").strip()
        program_id = (program_id or "").strip().lower() or None
        # Prefer packs whose program_hint matches; else all packs.
        preferred = [
            p
            for p in self._packs.values()
            if program_id and program_id in str(p.program_hint).lower()
        ]
        search_ids = [p.id for p in (preferred or list(self._packs.values()))]
        rows: list[dict[str, Any]] = []
        for pid in search_ids:
            for fact in self.facts(pack_id=pid, q=topic or None, limit=limit):
                row = dict(fact)
                row["item_kind"] = "world_fact"  # distinguish from Knowledge chunk/finding
                rows.append(row)
                if len(rows) >= limit:
                    return rows
        return rows

    def as_dict(self) -> dict[str, Any]:
        return {
            "packs": self.list_packs(),
            "version": self.VERSION,
        }
