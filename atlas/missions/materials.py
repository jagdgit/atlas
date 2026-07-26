"""Program materials — one share path for Personal + Engineering (no double jobs).

Resume, notes, and past-work repos should be given **once**. Atlas routes them through
the Owner Knowledge pipeline:

- ``document`` / ``conversation`` → ingestion bridge → personal candidates/experiences
- ``code`` → ``learn_repository`` **once** → engineering findings **and** personal experiences

Roots are also registered on the Personal program's ``owner_knowledge`` mission so later
ticks stay in sync without a second Engineering ingest.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from atlas.missions.programs import get_program, program_label

KIND_CODE = "code"
KIND_DOCUMENT = "document"
KIND_CONVERSATION = "conversation"

_OWNER_PROGRAM = "personal_intelligence"
_OWNER_TEMPLATE = "owner_knowledge"
_SHARE_PROGRAMS = frozenset({"personal_intelligence", "engineering_intelligence"})

# Absolute / home paths mentioned in chat ("learn from /data/me/resume.pdf").
_PATH_RE = re.compile(
    r"(?P<path>(?:~|/data|/home|/Users|/var|/opt|/tmp|/[a-zA-Z0-9._-]+)[^\s\"'`]+)"
)
_SHARE_HINT = re.compile(
    r"\b(share|upload|ingest|learn|add|give|feed|read|from|resume|cv|portfolio|"
    r"past\s+work|project|repo|codebase|archive)\b",
    re.IGNORECASE,
)


def infer_kind(path: Path) -> str:
    """Guess archive root kind from a filesystem path."""
    if path.is_file():
        if path.suffix.lower() in {".json", ".jsonl"}:
            return KIND_CONVERSATION
        return KIND_DOCUMENT
    markers = (
        ".git",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "Makefile",
        "requirements.txt",
    )
    if any((path / m).exists() for m in markers):
        return KIND_CODE
    # Prefer code for directories that look like source trees; else document archive.
    code_ext = {".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".kt", ".c", ".cpp"}
    try:
        for child in path.rglob("*"):
            if child.is_file() and child.suffix.lower() in code_ext:
                return KIND_CODE
            if child.is_file() and child.suffix.lower() in {
                ".md",
                ".pdf",
                ".txt",
                ".html",
            }:
                # Keep scanning — code wins if found later in this walk budget.
                pass
    except OSError:
        pass
    return KIND_DOCUMENT


def extract_paths(message: str) -> list[str]:
    """Pull filesystem paths out of a chat message."""
    found: list[str] = []
    for match in _PATH_RE.finditer(message or ""):
        raw = match.group("path").rstrip(".,;:)")
        if raw not in found:
            found.append(raw)
    return found


def looks_like_share(message: str) -> bool:
    return bool(_SHARE_HINT.search(message or ""))


class ProgramMaterialsService:
    """Single entry point: share a path once → Personal + Engineering consume it."""

    name = "program_materials"
    VERSION = "mca.share.1"

    def __init__(
        self,
        *,
        missions: Any | None = None,
        templates: Any | None = None,
        configuration: Any | None = None,
        intelligence: Any | None = None,
        ingestion: Any | None = None,
        personal: Any | None = None,
        workers: Any | None = None,
        conversation: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._missions = missions
        self._templates = templates
        self._configuration = configuration
        self._intelligence = intelligence
        self._ingestion = ingestion
        self._personal = personal
        self._workers = workers
        self._conversation = conversation
        self._logger = logger or logging.getLogger("atlas.missions.materials")

    def share(
        self,
        path: str,
        *,
        program_id: str | None = None,
        kind: str | None = None,
        domain: str = "personal",
        process_now: bool = True,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Register + optionally process one material path (idempotent by path)."""
        del title  # reserved for future asset titles
        prog = (program_id or _OWNER_PROGRAM).strip()
        if get_program(prog) is None:
            raise LookupError(f"unknown program: {prog}")

        raw = (path or "").strip()
        if not raw:
            raise ValueError("path is required")
        resolved = Path(raw).expanduser()
        if not resolved.exists():
            raise FileNotFoundError(f"path not found: {resolved}")

        inferred = kind or infer_kind(resolved)
        if inferred not in {KIND_CODE, KIND_DOCUMENT, KIND_CONVERSATION}:
            raise ValueError(f"unsupported kind: {inferred}")

        # Market chat can still share owner materials (resume / past work) via the
        # same pipeline — never a second Engineering-only job.
        root = {
            "path": str(resolved.resolve()),
            "kind": inferred,
            "domain": domain or "personal",
        }
        archive = self._ensure_archive_root(root)
        processed: dict[str, Any] | None = None
        if process_now:
            processed = self._process_now(resolved, inferred, domain=root["domain"],
                                          mission_id=archive.get("mission_id"))

        profile: dict[str, Any] | None = None
        cv_learn: dict[str, Any] | None = None
        if process_now and self._personal is not None:
            try:
                if inferred == KIND_DOCUMENT and resolved.is_file():
                    cv_learn = self._personal.learn_from_cv_path(str(resolved))
                profile = self._personal.infer()
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("personal learn/infer after share failed: %s", exc)

        fed = ["personal_intelligence"]
        if inferred == KIND_CODE:
            fed.append("engineering_intelligence")

        return {
            "ok": True,
            "path": root["path"],
            "kind": inferred,
            "feeds": fed,
            "note": (
                "Shared once via Owner Knowledge — Personal learns you; "
                "Engineering learns the same repos without a second ingest."
                if inferred == KIND_CODE
                else "Shared once via Owner Knowledge — Personal will use this document "
                "(CV facts inferred when text is extractable)."
            ),
            "archive": archive,
            "processed": processed,
            "cv_learn": cv_learn,
            "profile": profile,
            "source_program": prog,
            "version": self.VERSION,
        }

    def chat(
        self,
        program_id: str,
        message: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Program-scoped chat: share paths when asked, else give program help."""
        if get_program(program_id) is None:
            raise LookupError(f"unknown program: {program_id}")
        text = (message or "").strip()
        if not text:
            raise ValueError("message is required")

        sid: str | None = None
        if self._conversation is not None:
            session = self._conversation.ensure_session(session_id)
            sid = str(session.id)
            self._conversation.add_user_message(sid, text)

        paths = extract_paths(text)
        shares: list[dict[str, Any]] = []
        errors: list[str] = []
        if paths and (looks_like_share(text) or len(paths) == 1):
            for p in paths:
                try:
                    shares.append(self.share(p, program_id=program_id, process_now=True))
                except FileNotFoundError as exc:
                    errors.append(str(exc))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{p}: {exc}")

        answer = self._compose_reply(program_id, text, shares=shares, errors=errors, paths=paths)
        tool_calls: list[dict[str, Any]] = []
        for s in shares:
            tool_calls.append(
                {
                    "action": "share_materials",
                    "path": s.get("path"),
                    "kind": s.get("kind"),
                    "feeds": s.get("feeds"),
                }
            )

        if self._conversation is not None and sid:
            self._conversation.add_assistant_message(
                sid, answer, tool_calls=tool_calls or None
            )

        return {
            "session_id": sid,
            "answer": answer,
            "shares": shares,
            "errors": errors,
            "program_id": program_id,
            "tool_calls": tool_calls,
        }

    # --- internals ------------------------------------------------------

    def _compose_reply(
        self,
        program_id: str,
        message: str,
        *,
        shares: list[dict[str, Any]],
        errors: list[str],
        paths: list[str],
    ) -> str:
        prog = get_program(program_id)
        title = prog.title if prog else program_id
        parts: list[str] = []

        if shares:
            for s in shares:
                kind = s.get("kind")
                path = s.get("path")
                feeds = ", ".join(s.get("feeds") or [])
                parts.append(
                    f"Shared `{path}` as **{kind}** → feeds {feeds} (one job, not two)."
                )
                proc = s.get("processed") or {}
                if proc.get("outcome") == "ok":
                    if kind == KIND_CODE:
                        parts.append(
                            f"Learned repo now: findings={proc.get('findings', 0)}, "
                            f"experiences={proc.get('experiences', 0)}."
                        )
                    else:
                        parts.append(
                            f"Ingested now: documents/chunks ok "
                            f"(candidates={proc.get('candidates', 0)})."
                        )
                elif proc:
                    parts.append(f"Process note: {proc.get('reason') or proc.get('outcome')}.")
                cv = s.get("cv_learn") or {}
                if cv.get("facts"):
                    parts.append(
                        f"CV → {cv.get('facts')} inferred fact(s) "
                        f"({cv.get('by_category')}). Confirm them under **Personal**."
                    )
                elif cv and cv.get("ok") is False:
                    parts.append(f"CV parse: {cv.get('reason') or 'no facts'}.")
            parts.append(
                "Open **Personal** to Confirm/Reject inferred facts; "
                "**Engineering** for repo findings. No need to upload again elsewhere."
            )

        if errors:
            parts.append("Could not share: " + "; ".join(errors))

        if shares or errors:
            return "\n".join(parts)

        if paths and not looks_like_share(message):
            return (
                f"I see path(s) {', '.join(paths)}. "
                "Say e.g. “share my resume at …” or “learn from …” and I’ll register "
                "them once for Personal + Engineering."
            )

        if program_id in _SHARE_PROGRAMS:
            return (
                f"**{title}** chat — give me materials as host paths (Atlas reads the disk).\n"
                "• Resume / CV / notes: `share /path/to/resume.pdf`\n"
                "• Past work (repos): `learn from /path/to/my-project`\n\n"
                "Repos and past-work repos are shared **once** via Owner Knowledge: "
                "Personal learns about you; Engineering learns the same code — "
                "you do not ingest twice."
            )

        return (
            f"**{title}** chat — ask about this program’s context, or share owner "
            "materials the same way (`share /path/to/resume.pdf`). "
            "Market data feeds stay on Missions / Assets; resume & past work still "
            "use the single Owner Knowledge path."
        )

    def _ensure_archive_root(self, root: dict[str, Any]) -> dict[str, Any]:
        """Add root to owner_knowledge config (deduped). Creates mission if needed."""
        mission_id = self._resolve_owner_mission_id()
        if mission_id is None or self._configuration is None:
            return {
                "mission_id": None,
                "registered": False,
                "reason": "owner_knowledge mission not available — processed in-memory only"
                if mission_id is None
                else "configuration service unavailable",
                "root": root,
            }

        active = self._configuration.get_active(mission_id)
        doc = dict(getattr(active, "document", None) or {})
        roots = [dict(r) for r in (doc.get("archive_roots") or [])]
        path_key = root["path"]
        existing = next((r for r in roots if str(r.get("path") or "") == path_key), None)
        if existing is not None:
            return {
                "mission_id": mission_id,
                "registered": True,
                "already_present": True,
                "root": existing,
                "config_version": getattr(active, "version", None),
            }

        roots.append(root)
        doc["archive_roots"] = roots
        cfg = self._configuration.update_config(
            mission_id,
            doc,
            change_note=f"program share: add {root['kind']} root {path_key}",
            activate=True,
        )
        # Nudge worker to pick up new root soon (best-effort).
        self._nudge_owner_worker(mission_id)
        return {
            "mission_id": mission_id,
            "registered": True,
            "already_present": False,
            "root": root,
            "config_version": getattr(cfg, "version", None),
        }

    def _resolve_owner_mission_id(self) -> str | None:
        if self._missions is None:
            return None
        label = program_label(_OWNER_PROGRAM)
        try:
            try:
                rows = self._missions.list_missions(label=label, limit=100)
            except TypeError:
                rows = self._missions.list_missions(limit=100)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("list missions for owner archive failed: %s", exc)
            return None

        for row in rows or []:
            data = row.to_dict() if hasattr(row, "to_dict") else dict(row)
            status = str(data.get("status") or "")
            if status in {"archived", "completed", "failed"}:
                continue
            labels = list(data.get("labels") or [])
            meta = data.get("metadata") or {}
            template = str(meta.get("template") or "")
            title = str(data.get("title") or "").lower()
            is_owner = (
                template == _OWNER_TEMPLATE
                or meta.get("role") == "Personal Observer"
                or "owner knowledge" in title
                or "personal observer" in title
            )
            if not is_owner:
                continue
            if label in labels or meta.get("program_id") == _OWNER_PROGRAM or is_owner:
                return str(data.get("id"))

        # Create Personal Observer if templates are wired.
        return self._start_owner_mission()

    def _start_owner_mission(self) -> str | None:
        if self._templates is None:
            return None
        try:
            result = self._templates.instantiate(
                _OWNER_TEMPLATE,
                title="Personal Intelligence · Personal Observer",
                labels=[program_label(_OWNER_PROGRAM), f"role:{_OWNER_TEMPLATE}"],
                metadata={
                    "program_id": _OWNER_PROGRAM,
                    "template": _OWNER_TEMPLATE,
                    "role": "Personal Observer",
                },
                activate=True,
            )
            mission = result.get("mission") if isinstance(result, dict) else result
            mid = getattr(mission, "id", None) or (mission or {}).get("id")
            return str(mid) if mid else None
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("auto-start owner_knowledge failed: %s", exc)
            return None

    def _nudge_owner_worker(self, mission_id: str) -> None:
        if self._workers is None:
            return
        try:
            # WorkerManager exposes workers for a mission; enqueue force if possible.
            listing = None
            if hasattr(self._workers, "list_for_mission"):
                listing = self._workers.list_for_mission(mission_id)
            elif hasattr(self._workers, "list_workers"):
                listing = [
                    w
                    for w in self._workers.list_workers()
                    if str(getattr(w, "mission_id", "") or "") == str(mission_id)
                    or (isinstance(w, dict) and str(w.get("mission_id") or "") == str(mission_id))
                ]
            for w in listing or []:
                wid = getattr(w, "id", None) or (w.get("id") if isinstance(w, dict) else None)
                wtype = getattr(w, "type", None) or (
                    w.get("type") if isinstance(w, dict) else None
                )
                if wid and (wtype == _OWNER_TEMPLATE or wtype is None):
                    if hasattr(self._workers, "enqueue_input"):
                        self._workers.enqueue_input(str(wid), {"force": True})
                    break
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("owner worker nudge skipped: %s", exc)

    def _process_now(
        self,
        path: Path,
        kind: str,
        *,
        domain: str,
        mission_id: str | None,
    ) -> dict[str, Any]:
        if kind == KIND_CODE:
            if self._intelligence is None:
                return {"outcome": "skipped", "reason": "intelligence unavailable"}
            out = self._intelligence.learn_repository(
                path=str(path),
                mission_id=mission_id,
                policy="project",
                embed=False,
            )
            return {
                "outcome": out.get("outcome"),
                "reason": out.get("reason"),
                "findings": out.get("findings"),
                "experiences": out.get("experiences"),
                "repo_uid": (out.get("repository") or {}).get("repo_uid")
                or out.get("repo_uid"),
            }

        if self._ingestion is None:
            return {"outcome": "skipped", "reason": "ingestion bridge unavailable"}

        totals = {"files": 0, "candidates": 0, "experiences": 0, "chunks": 0}
        files: list[Path]
        if path.is_file():
            files = [path]
        else:
            exts = (
                {".json", ".jsonl"}
                if kind == KIND_CONVERSATION
                else {".txt", ".md", ".pdf", ".html", ".htm", ".rst"}
            )
            files = [
                f
                for f in path.rglob("*")
                if f.is_file() and f.suffix.lower() in exts
            ][:100]

        last_reason = None
        for file in files:
            try:
                res = self._ingestion.ingest_file(
                    file,
                    kind="conversation" if kind == KIND_CONVERSATION else "document",
                    domain=domain,
                    embed=False,
                    extract_findings=True,
                    source="conversation" if kind == KIND_CONVERSATION else "document",
                )
                totals["files"] += 1
                totals["candidates"] += int(getattr(res, "candidates", 0) or 0)
                totals["experiences"] += int(getattr(res, "experiences", 0) or 0)
                totals["chunks"] += int(getattr(res, "chunks", 0) or 0)
            except Exception as exc:  # noqa: BLE001
                last_reason = str(exc)
                self._logger.warning("share ingest failed for %s: %s", file, exc)

        return {
            "outcome": "ok" if totals["files"] else "error",
            "reason": last_reason,
            "candidates": totals["candidates"],
            "experiences": totals["experiences"],
            "chunks": totals["chunks"],
            "files": totals["files"],
        }
