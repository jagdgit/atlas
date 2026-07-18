"""Load Stage 3B eval corpora from ``tests/fixtures/eval/`` (or an override root)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_ROOT = _REPO_ROOT / "tests" / "fixtures" / "eval"


def fixture_path(name: str, *, root: Path | None = None) -> Path:
    """Resolve a fixture file under the eval fixture root."""
    base = root or DEFAULT_FIXTURE_ROOT
    path = base / name
    if not path.exists():
        raise FileNotFoundError(f"eval fixture not found: {path}")
    return path


def load_json_fixture(name: str, *, root: Path | None = None) -> dict[str, Any]:
    """Load a JSON fixture object (must be a top-level object)."""
    raw = json.loads(fixture_path(name, root=root).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"fixture {name} must be a JSON object")
    return raw


def load_cases(name: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    """Load the ``cases`` list from a fixture file."""
    data = load_json_fixture(name, root=root)
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"fixture {name} missing cases list")
    return cases
