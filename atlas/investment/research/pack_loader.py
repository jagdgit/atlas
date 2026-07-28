"""SI.2 — load durable sector intelligence packs from YAML.

Builtin Python packs remain a hermetic fallback. YAML under
``atlas/investment/research/packs/`` overrides / extends them. Optional
operator overlay: ``{data_dir}/investment/sector_packs/*.yaml``.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("atlas.investment.research.packs")

_PACK_DIR = Path(__file__).resolve().parent / "packs"


def _read_yaml(path: Path) -> dict[str, Any] | None:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        logger.warning("PyYAML missing — cannot load sector pack %s", path)
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to read sector pack %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    pid = str(raw.get("id") or path.stem).strip()
    if not pid:
        return None
    raw["id"] = pid
    raw.setdefault("version", "si.2")
    return raw


def iter_pack_files(extra_dirs: list[Path] | None = None) -> list[Path]:
    paths: list[Path] = []
    if _PACK_DIR.is_dir():
        paths.extend(sorted(_PACK_DIR.glob("*.yaml")))
        paths.extend(sorted(_PACK_DIR.glob("*.yml")))
    for d in extra_dirs or []:
        if d and Path(d).is_dir():
            paths.extend(sorted(Path(d).glob("*.yaml")))
            paths.extend(sorted(Path(d).glob("*.yml")))
    return paths


def load_pack_files(
    *,
    data_dir: str | Path | None = None,
    builtins: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge builtins ← package YAML ← optional data_dir overlay."""
    out: dict[str, dict[str, Any]] = {}
    if builtins:
        for k, v in builtins.items():
            if isinstance(v, dict):
                out[str(k)] = dict(v)

    extra: list[Path] = []
    if data_dir:
        extra.append(Path(data_dir).expanduser() / "investment" / "sector_packs")

    for path in iter_pack_files(extra):
        row = _read_yaml(path)
        if not row:
            continue
        pid = str(row["id"])
        # Overlay merges on top of builtin / earlier file
        base = out.get(pid) or {}
        merged = {**base, **row}
        out[pid] = merged

    return out


@lru_cache(maxsize=4)
def cached_packs(data_dir: str | None = None) -> dict[str, dict[str, Any]]:
    """Cached merge; pass data_dir=None for package YAML + empty builtins call site."""
    return load_pack_files(data_dir=data_dir)


def clear_pack_cache() -> None:
    cached_packs.cache_clear()
