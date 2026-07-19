"""Conversation Reader (Phase C · PHASE_C_PLAN §C.8, BB10/BB11 / constitution P11).

The second **non-code** reader: it turns a chat / Cursor / assistant **export Asset** (a `.json` or
`.jsonl` transcript) into a structured text **Artifact** — chats become a first-class knowledge
source, flowing through the *one* pipeline ``Asset → Reader → Artifact → Extraction → Knowledge``
(P11) exactly like documents and code. Each message becomes a **section** (role + text) and the
concatenated turns become the artifact `text` that RAG chunking + prose finding extraction consume.

Like :class:`~atlas.readers.document.DocumentReader` it owns no knowledge or state (P11): it reads
bytes and returns an artifact, cached in the Derived Artifact Store keyed by
``{asset_id, asset_version, reader, reader_version}`` (BB11) so re-reading an unchanged export is a
cheap cache hit. It is duck-typed against the Asset Store (``get_bytes``/``versions``) and the
artifact cache (``get``/``put``).

Export shapes are heterogeneous, so parsing is deliberately tolerant:
  * ``.jsonl`` — one JSON object per line (Cursor transcripts, OpenAI-style logs);
  * ``.json``  — a list of messages, or an object with a ``messages``/``conversation``/``turns`` list.
Each message's **role** is read from any of ``role``/``type``/``sender``/``author`` and its **text**
from any of ``content``/``text``/``message``/``body`` (content-parts lists are flattened). Malformed
lines/messages are skipped, never fatal (honesty over crashing).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atlas.assets.service import AssetStore

CONVERSATION_READER_ID = "conversation"
CONVERSATION_READER_VERSION = "1.0.0"

_SUPPORTED_EXTENSIONS = (".json", ".jsonl")
_ROLE_KEYS = ("role", "type", "sender", "author", "speaker")
_TEXT_KEYS = ("content", "text", "message", "body")
_MESSAGE_LIST_KEYS = ("messages", "conversation", "turns", "history", "items")


class ConversationReader:
    """Read a chat/Cursor export asset → cached transcript artifact (BB11); reuse when unchanged."""

    id = CONVERSATION_READER_ID
    VERSION = CONVERSATION_READER_VERSION

    def __init__(
        self,
        assets: "AssetStore",
        artifacts: Any,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._assets = assets
        self._artifacts = artifacts  # DerivedArtifactStore (duck-typed: get/put)
        self._logger = logger or logging.getLogger("atlas.readers.conversation")

    def supported_extensions(self) -> list[str]:
        return list(_SUPPORTED_EXTENSIONS)

    def read(
        self,
        asset_id: str,
        asset_version: int | None = None,
        *,
        filename: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        version = self._resolve_version(asset_id, asset_version)
        if not force:
            cached = self._artifacts.get(asset_id, version, self.id, self.VERSION)
            if cached is not None:
                return cached
        filename = filename or self._filename_from_metadata(asset_id, version)
        data = self._assets.get_bytes(asset_id, version)
        artifact = self._extract(data, filename, asset_id, version)
        self._artifacts.put(asset_id, version, self.id, self.VERSION, artifact)
        return artifact

    # --- internals ------------------------------------------------------
    def _extract(
        self, data: bytes, filename: str | None, asset_id: str, version: int
    ) -> dict[str, Any]:
        suffix = Path(filename).suffix.lower() if filename else ""
        base = {
            "reader": self.id,
            "reader_version": self.VERSION,
            "asset_id": asset_id,
            "asset_version": version,
            "content_type": "text/plain",
            "extension": suffix,
        }
        if suffix and suffix not in _SUPPORTED_EXTENSIONS:
            return {**base, "outcome": "unsupported", "text": "", "chars": 0,
                    "reason": f"unsupported conversation format: {suffix}", "sections": []}

        try:
            text_raw = data.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return {**base, "outcome": "error", "text": "", "chars": 0,
                    "reason": f"decode failed: {exc}", "sections": []}

        try:
            turns = self._parse(text_raw, suffix)
        except Exception as exc:  # noqa: BLE001 - a malformed export is reported, never fatal
            return {**base, "outcome": "error", "text": "", "chars": 0,
                    "reason": f"parse failed: {exc}", "sections": []}

        sections = [
            {"ordinal": i, "role": role, "text": body}
            for i, (role, body) in enumerate(turns)
            if body.strip()
        ]
        if not sections:
            return {**base, "outcome": "empty", "text": "", "chars": 0,
                    "reason": "no messages with text", "sections": []}

        text = "\n\n".join(f"{s['role']}: {s['text']}" for s in sections)
        return {
            **base,
            "outcome": "ok",
            "text": text,
            "chars": len(text),
            "reason": None,
            "messages": len(sections),
            "sections": sections,
        }

    def _parse(self, raw: str, suffix: str) -> list[tuple[str, str]]:
        """Return an ordered list of ``(role, text)`` turns from a JSON/JSONL export."""
        if suffix == ".jsonl":
            return self._parse_jsonl(raw)
        if suffix == ".json":
            return self._parse_json(raw)
        # No/unknown extension: try JSONL first (line-delimited), then a single JSON doc.
        turns = self._parse_jsonl(raw)
        return turns or self._parse_json(raw)

    def _parse_jsonl(self, raw: str) -> list[tuple[str, str]]:
        turns: list[tuple[str, str]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # skip a malformed line; keep the rest
            turns.extend(self._turns_from(obj))
        return turns

    def _parse_json(self, raw: str) -> list[tuple[str, str]]:
        raw = raw.strip()
        if not raw:
            return []
        doc = json.loads(raw)
        return self._turns_from(doc)

    def _turns_from(self, obj: Any) -> list[tuple[str, str]]:
        """Extract turns from a parsed value: a message, a list of messages, or a container dict."""
        if isinstance(obj, list):
            turns: list[tuple[str, str]] = []
            for item in obj:
                turns.extend(self._turns_from(item))
            return turns
        if isinstance(obj, dict):
            for key in _MESSAGE_LIST_KEYS:
                if isinstance(obj.get(key), list):
                    return self._turns_from(obj[key])
            role = self._first_str(obj, _ROLE_KEYS) or "message"
            text = self._extract_text(obj)
            if text.strip():
                return [(role, text)]
            return []
        if isinstance(obj, str) and obj.strip():
            return [("message", obj)]
        return []

    def _extract_text(self, obj: dict[str, Any]) -> str:
        for key in _TEXT_KEYS:
            if key not in obj:
                continue
            value = obj[key]
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                # content-parts: [{type:"text", text:"…"}, …] or a list of strings.
                parts: list[str] = []
                for part in value:
                    if isinstance(part, str):
                        parts.append(part)
                    elif isinstance(part, dict):
                        t = part.get("text") or part.get("content")
                        if isinstance(t, str):
                            parts.append(t)
                if parts:
                    return "\n".join(parts)
            elif isinstance(value, dict):
                inner = value.get("text") or value.get("content")
                if isinstance(inner, str):
                    return inner
        return ""

    @staticmethod
    def _first_str(obj: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return None

    def _resolve_version(self, asset_id: str, asset_version: int | None) -> int:
        if asset_version is not None:
            return int(asset_version)
        versions = self._assets.versions(asset_id)
        if not versions:
            raise ValueError(f"asset has no versions: {asset_id}")
        return int(versions[0]["version"])

    def _filename_from_metadata(self, asset_id: str, version: int) -> str | None:
        for row in self._assets.versions(asset_id):
            if int(row.get("version", -1)) == version:
                meta = row.get("metadata") or {}
                name = meta.get("filename")
                return str(name) if name else None
        return None
