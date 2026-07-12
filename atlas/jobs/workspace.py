"""Job Workspace — a per-job on-disk directory for durable artifacts (§5a, C3).

Stage 3, Step 1. Fixes §2.6 ("there is no job Workspace"): every job gets an isolated
directory under ``<data>/jobs/job_<id>/`` so work is durable, inspectable, and
reproducible. Debugging becomes *"open the workspace"*; a crash loses nothing; auditing
is trivial.

Layout (§5a)::

    <data>/jobs/job_<id>/
        plan.json         # the typed plan (a later step)
        search/           # raw search results per query
        downloads/        # acquired files (pdf/html/…)
        documents/        # normalized extracted text per source
        claims.json       # extracted structured claims
        evidence.json     # the serialized Evidence Graph
        notes.md          # loop trace / gap analysis (append-only)
        report.md         # final report
        manifest.json     # what was found/downloaded/read/extracted/verified

Retention (D3.5 / §13 A9): keep everything by default; nothing here deletes. Pure
filesystem + JSON, so it is fully unit-testable offline with a ``tmp_path``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_MANIFEST_STAGES = ("found", "downloaded", "read", "extracted", "verified")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value: str) -> str:
    """Make an id safe to embed in a path (defensive; job ids are uuids/ints)."""
    cleaned = _SAFE_ID_RE.sub("-", (value or "").strip())
    return cleaned.strip("-") or "unknown"


@dataclass
class JobWorkspace:
    """The on-disk working directory for one job.

    Construct via :meth:`for_job`. Directory creation is lazy on first write (or
    explicit :meth:`ensure`), so merely *referencing* a workspace touches no disk.
    """

    root: Path
    job_id: str
    _ensured: bool = field(default=False, repr=False)

    # --- construction ---------------------------------------------------
    @classmethod
    def for_job(cls, data_dir: str | Path, job_id: str) -> "JobWorkspace":
        base = Path(data_dir) / "jobs" / f"job_{_safe_component(job_id)}"
        return cls(root=base, job_id=str(job_id))

    # --- well-known paths ----------------------------------------------
    @property
    def search_dir(self) -> Path:
        return self.root / "search"

    @property
    def downloads_dir(self) -> Path:
        return self.root / "downloads"

    @property
    def documents_dir(self) -> Path:
        return self.root / "documents"

    @property
    def plan_path(self) -> Path:
        return self.root / "plan.json"

    @property
    def claims_path(self) -> Path:
        return self.root / "claims.json"

    @property
    def evidence_path(self) -> Path:
        return self.root / "evidence.json"

    @property
    def notes_path(self) -> Path:
        return self.root / "notes.md"

    @property
    def report_path(self) -> Path:
        return self.root / "report.md"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    # --- lifecycle ------------------------------------------------------
    def ensure(self) -> "JobWorkspace":
        """Create the directory tree (idempotent)."""
        for d in (self.root, self.search_dir, self.downloads_dir, self.documents_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._ensured = True
        return self

    def _ensure_once(self) -> None:
        if not self._ensured:
            self.ensure()

    # --- generic writers/readers ---------------------------------------
    def write_text(self, relative: str | Path, text: str) -> Path:
        path = self.root / relative
        self._ensure_once()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, relative: str | Path, obj: Any) -> Path:
        return self.write_text(relative, json.dumps(obj, indent=2, ensure_ascii=False))

    def read_json(self, relative: str | Path, default: Any = None) -> Any:
        path = self.root / relative
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return default

    def append_note(self, text: str) -> Path:
        """Append a timestamped line to ``notes.md`` (the loop trace)."""
        self._ensure_once()
        line = f"- `{_now()}` {text}\n"
        with self.notes_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return self.notes_path

    def download_path(self, filename: str) -> Path:
        """A path inside ``downloads/`` for an acquired file (name made safe)."""
        self._ensure_once()
        return self.downloads_dir / _safe_component(filename)

    def document_path(self, source_id: str, suffix: str = ".txt") -> Path:
        """A path inside ``documents/`` for a source's normalized text."""
        self._ensure_once()
        name = _safe_component(source_id)
        if suffix and not name.endswith(suffix):
            name = f"{name}{suffix}"
        return self.documents_dir / name

    # --- manifest (what was found/downloaded/read/extracted/verified) ---
    def load_manifest(self) -> dict[str, Any]:
        return self.read_json(self.manifest_path.name, default=None) or self._new_manifest()

    def _new_manifest(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "objective": "",
            "created_at": _now(),
            "updated_at": _now(),
            "counts": {stage: 0 for stage in _MANIFEST_STAGES},
            "sources": [],
        }

    def init_manifest(self, objective: str = "") -> dict[str, Any]:
        manifest = self._new_manifest()
        manifest["objective"] = objective
        self.write_json(self.manifest_path.name, manifest)
        return manifest

    def record_source(
        self,
        source_id: str,
        *,
        url: str = "",
        title: str = "",
        source_type: str = "",
        evidence_level: int | None = None,
        access_method: str = "",
        stage: str = "found",
        **extra: Any,
    ) -> dict[str, Any]:
        """Record (or update) a source in the manifest at a pipeline ``stage``.

        Stages are cumulative (``found`` → ``downloaded`` → ``read`` → ``extracted``
        → ``verified``); recording a later stage marks the source as having reached
        it and bumps the corresponding count once.
        """
        manifest = self.load_manifest()
        entry = next(
            (s for s in manifest["sources"] if s.get("id") == source_id), None
        )
        if entry is None:
            entry = {"id": source_id, "stages": []}
            manifest["sources"].append(entry)
        entry.update(
            {
                "url": url or entry.get("url", ""),
                "title": title or entry.get("title", ""),
                "source_type": source_type or entry.get("source_type", ""),
                "access_method": access_method or entry.get("access_method", ""),
            }
        )
        if evidence_level is not None:
            entry["evidence_level"] = evidence_level
        if extra:
            entry.update(extra)
        stages = entry.setdefault("stages", [])
        if stage in _MANIFEST_STAGES and stage not in stages:
            stages.append(stage)
            manifest["counts"][stage] = manifest["counts"].get(stage, 0) + 1
        manifest["updated_at"] = _now()
        self.write_json(self.manifest_path.name, manifest)
        return manifest

    def as_summary(self) -> dict[str, Any]:
        """A small, UI-friendly summary of the workspace state."""
        manifest = self.load_manifest()
        return {
            "job_id": self.job_id,
            "path": str(self.root),
            "objective": manifest.get("objective", ""),
            "counts": manifest.get("counts", {}),
            "source_count": len(manifest.get("sources", [])),
            "has_report": self.report_path.is_file(),
        }
