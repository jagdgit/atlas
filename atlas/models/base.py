"""Shared base for Atlas domain models (ADR-0036).

Models are typed, frozen dataclasses that replace raw ``dict`` rows once they
cross a module boundary. Repositories are the mapping layer (rows -> models),
which is where ADR-0027 (SQL only in repositories) meets ADR-0036 (typed models
only above them).

``Model.from_row`` maps a psycopg ``dict_row`` to the model: it pulls the fields
the model declares (ignoring extra columns), and normalizes ``UUID`` -> ``str``
so IDs are handled uniformly everywhere (matching the existing value types like
``SearchResult`` / ``Citation``). Timestamps stay as ``datetime``.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterable, Type, TypeVar
from uuid import UUID

T = TypeVar("T", bound="Model")


def _coerce(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    return value


class Model:
    """Marker base providing row <-> model mapping for frozen dataclasses."""

    @classmethod
    def from_row(cls: Type[T], row: dict[str, Any]) -> T:
        fields = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
        kwargs = {k: _coerce(v) for k, v in row.items() if k in fields}
        return cls(**kwargs)  # type: ignore[call-arg]

    @classmethod
    def from_rows(cls: Type[T], rows: Iterable[dict[str, Any]]) -> list[T]:
        return [cls.from_row(row) for row in rows]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)  # type: ignore[call-overload]
