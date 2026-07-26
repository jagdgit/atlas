"""Durable store for IRA dossiers (data_dir/investment/research/)."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from atlas.investment.research.models import normalize_symbol

_LOCK = threading.RLock()
_MEM: dict[str, dict[str, Any]] = {}  # program_id → symbol → dossier


def _key(program_id: str, symbol: str, root: str | None = None) -> str:
    base = f"{program_id}:{normalize_symbol(symbol)}"
    if root:
        return f"{root}|{base}"
    return base


class ResearchStore:
    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._root = Path(data_dir).expanduser() if data_dir else None
        self._root_key = str(self._root) if self._root else "_mem_"
        self._logger = logger or logging.getLogger("atlas.investment.research.store")
        if self._root is not None:
            (self._root / "investment" / "research").mkdir(parents=True, exist_ok=True)

    def _path(self, program_id: str, symbol: str) -> Path | None:
        if self._root is None:
            return None
        sym = normalize_symbol(symbol).replace("/", "_")
        return self._root / "investment" / "research" / program_id / f"{sym}.json"

    def get(self, symbol: str, *, program_id: str = "market_intelligence") -> dict[str, Any] | None:
        sym = normalize_symbol(symbol)
        k = _key(program_id, sym, self._root_key)
        with _LOCK:
            if k in _MEM:
                return dict(_MEM[k])
        path = self._path(program_id, sym)
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                with _LOCK:
                    _MEM[k] = dict(data)
                return dict(data)
        except Exception:  # noqa: BLE001
            self._logger.debug("failed to load research dossier %s", path, exc_info=True)
        return None

    def save(self, dossier: dict[str, Any], *, program_id: str | None = None) -> dict[str, Any]:
        doc = dict(dossier)
        pid = str(program_id or doc.get("program_id") or "market_intelligence")
        sym = normalize_symbol(str(doc.get("symbol") or ""))
        doc["symbol"] = sym
        doc["program_id"] = pid
        k = _key(pid, sym, self._root_key)
        with _LOCK:
            _MEM[k] = dict(doc)
        path = self._path(pid, sym)
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
            except Exception:  # noqa: BLE001
                self._logger.debug("failed to persist research dossier %s", path, exc_info=True)
        return dict(doc)

    def list_symbols(self, *, program_id: str = "market_intelligence") -> list[str]:
        out: set[str] = set()
        prefix = f"{self._root_key}|{program_id}:"
        legacy_prefix = f"{program_id}:"
        with _LOCK:
            for k, doc in _MEM.items():
                if k.startswith(prefix) or (
                    self._root is None and k.startswith(legacy_prefix) and "|" not in k
                ):
                    if isinstance(doc, dict) and doc.get("symbol"):
                        out.add(str(doc["symbol"]))
        path_root = None if self._root is None else self._root / "investment" / "research" / program_id
        if path_root is not None and path_root.exists():
            for p in path_root.glob("*.json"):
                out.add(normalize_symbol(p.stem))
        return sorted(out)
