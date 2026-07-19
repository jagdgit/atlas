"""Design reasoning — advice-only LLM design review (Phase B · §B.5, BB6/Q-B3/P9/P10).

A bounded ``code``-role LLM pass over the **architecture graph + mined patterns** that produces
explainable **design findings** (`design` / `risk` claim types) with confidence, evidence
(which modules), a rationale, and **rejected alternatives** (P9). It **never edits code** (P10) —
it only advises. It is **structural-change-triggered** (BB6/Q-B3): the review runs only when the
B.3 graph diff shows a real structural change (new/removed module, dependency-graph change, entry
-point/call change); doc-/comment-/whitespace-only re-ingests **skip** the LLM entirely, so token
cost tracks architectural change, not ingest frequency. It **skips cleanly** when the LLM is
unavailable (structural findings from B.2 still land). Per P11 it owns no state.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from atlas.knowledge.domains import DOMAIN_CODE
from atlas.llm.provider import ChatMessage

if TYPE_CHECKING:
    from atlas.llm.service import LLMService

# Design-reviewer version (P2/BB8): bump when the review's finding *shape* changes.
DESIGN_REVIEWER_VERSION = "1.0.0"

CLAIM_DESIGN = "design"
CLAIM_RISK = "risk"

_CONFIDENCE = {
    "high": ("HIGH", 0.85),
    "medium": ("MEDIUM", 0.6),
    "low": ("LOW", 0.35),
}

_SYSTEM = (
    "You are Atlas's engineering design reviewer. You produce ADVICE-ONLY design findings "
    "about a codebase's architecture from the structural summary you are given. "
    "You NEVER write, modify, or suggest edits to code — you only reason about design. "
    "Ground every finding in the provided modules/edges/patterns; if the evidence is weak, "
    "omit the finding rather than speculate. "
    "Return ONLY a JSON array (no prose) of at most {max} items. Each item is an object: "
    '{"title": short stable name, "type": "design" | "risk", '
    '"confidence": "high" | "medium" | "low", '
    '"statement": one-sentence finding, '
    '"evidence": [module paths or names that justify it], '
    '"rationale": why this matters, '
    '"rejected_alternatives": [other designs you considered and why you did not pick them]}.'
)

_slug_re = re.compile(r"[^a-z0-9]+")


def _slug(title: str) -> str:
    return _slug_re.sub("-", (title or "").strip().lower()).strip("-")[:80]


def should_review(graph_info: dict[str, Any] | None) -> bool:
    """Structural-change gate (BB6/Q-B3) over a B.3 persist result ``{reused, diff}``.

    Review when a **new** graph version was cut (first version, or a changed structure);
    **skip** when the graph was reused unchanged (doc-/comment-/whitespace-only edits).
    With no graph info at all, default to reviewing (best-effort, no gate available).
    """
    if graph_info is None:
        return True
    if graph_info.get("reused"):
        return False
    diff = graph_info.get("diff")
    if diff is None:  # first version for this repo → review the initial architecture
        return True
    return bool(diff.get("changed"))


def _change_summary(diff: dict[str, Any] | None, *, limit: int = 20) -> dict[str, Any]:
    if not diff:
        return {}
    def cap(key: str) -> list[Any]:
        return list(diff.get(key, []))[:limit]
    return {
        "added_modules": cap("added_modules"),
        "removed_modules": cap("removed_modules"),
        "added_import_edges": cap("added_import_edges"),
        "removed_import_edges": cap("removed_import_edges"),
        "added_entry_points": cap("added_entry_points"),
        "removed_entry_points": cap("removed_entry_points"),
    }


def _top_imported(graph_doc: dict[str, Any], *, limit: int = 25) -> list[str]:
    """Modules with the highest import in-degree — the architecture's hubs."""
    counts: dict[str, int] = {}
    for edge in graph_doc.get("import_edges", []) or []:
        if isinstance(edge, (list, tuple)) and len(edge) >= 2:
            counts[str(edge[-1])] = counts.get(str(edge[-1]), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ranked[:limit]]


class DesignReviewer:
    """Advice-only, structural-change-triggered LLM design review (B.5)."""

    VERSION = DESIGN_REVIEWER_VERSION

    def __init__(
        self,
        llm: "LLMService | None" = None,
        *,
        max_findings: int = 8,
        timeout: float = 120.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._llm = llm
        self._max = max(1, int(max_findings))
        self._timeout = float(timeout)
        self._logger = logger or logging.getLogger("atlas.engineering.design_review")

    def available(self) -> bool:
        return self._llm is not None

    def review(
        self,
        *,
        distilled: dict[str, Any],
        graph_doc: dict[str, Any],
        diff: dict[str, Any] | None = None,
        repo_uid: str | None,
        asset_id: str | None = None,
        asset_version: int | None = None,
        reader: str = "code",
        reader_version: str = "1.0.0",
        mission_id: str | None = None,
        job_id: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return design/risk findings for a repo (empty if the LLM is unavailable/failed)."""
        if self._llm is None:
            self._logger.info("design review skipped: no LLM configured")
            return []
        try:
            client = self._llm.for_role("code")
            model = client.model
            context = self._build_context(distilled, graph_doc, diff)
            resp = client.chat(
                [
                    ChatMessage("system", _SYSTEM.replace("{max}", str(self._max))),
                    ChatMessage("user", context),
                ],
                timeout=self._timeout,
            )
            raw = (resp.text or "").strip()
        except Exception:  # noqa: BLE001 - design review is advisory; never crash a learn
            self._logger.exception("design review LLM call failed")
            return []
        return self._parse(
            raw, distilled=distilled, model=model, repo_uid=repo_uid,
            asset_id=asset_id, asset_version=asset_version,
            reader=reader, reader_version=reader_version,
            mission_id=mission_id, job_id=job_id, source=source,
        )

    # --- internals ------------------------------------------------------
    def _build_context(
        self, distilled: dict[str, Any], graph_doc: dict[str, Any], diff: dict[str, Any] | None
    ) -> str:
        counts = graph_doc.get("counts", {}) or {}
        payload = {
            "name": distilled.get("name", "repo"),
            "languages": distilled.get("languages", {}),
            "frameworks": distilled.get("frameworks", []),
            "entry_points": (graph_doc.get("entry_points", []) or [])[:20],
            "counts": counts,
            "hub_modules": _top_imported(graph_doc),
            "patterns": [
                {"name": p.get("name"), "description": p.get("description", "")}
                for p in (distilled.get("patterns", []) or [])[:8]
            ],
            "structural_change": _change_summary(diff),
        }
        return (
            "Review the architecture of this project and produce design/risk findings.\n\n"
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )

    def _parse(
        self,
        raw: str,
        *,
        distilled: dict[str, Any],
        model: str,
        repo_uid: str | None,
        asset_id: str | None,
        asset_version: int | None,
        reader: str,
        reader_version: str,
        mission_id: str | None = None,
        job_id: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except (ValueError, TypeError):
            return []
        if not isinstance(items, list):
            return []

        name = distilled.get("name", "repo")
        repo = distilled.get("root", "")
        findings: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            statement = str(item.get("statement", "")).strip()
            if not title or not statement:
                continue
            slug = _slug(title)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            claim_type = CLAIM_RISK if str(item.get("type", "")).lower() == "risk" else CLAIM_DESIGN
            label, score = _CONFIDENCE.get(str(item.get("confidence", "")).lower(), ("MEDIUM", 0.6))
            evidence = [str(e) for e in (item.get("evidence") or []) if str(e).strip()][:12]
            rejected = [
                str(a) for a in (item.get("rejected_alternatives") or []) if str(a).strip()
            ][:6]
            provenance: dict[str, Any] = {
                "repo_uid": repo_uid or "",
                "asset_id": asset_id or "",
                "asset_version": asset_version,
                "repo": repo,
                "path": "",
                "symbol": slug,  # stable identity so a re-review supersedes the same concern
                "reader": reader,
                "reader_version": reader_version,
                "extractor_version": DESIGN_REVIEWER_VERSION,
                "knowledge_type": "software",
                "model": model,  # P9: which model version produced this advice
            }
            # P12 provenance: who discovered this advice (never ownership); omitted when unknown.
            if mission_id:
                provenance["mission_id"] = mission_id
            if job_id:
                provenance["job_id"] = job_id
            if source:
                provenance["source"] = source
            findings.append({
                "statement": f"[{name}] {statement}"[:1000],
                "claim_type": claim_type,
                "domain": DOMAIN_CODE,
                "confidence": label,
                "confidence_score": score,
                "value": {
                    "kind": claim_type,
                    "title": title,
                    "evidence": evidence,
                    "rationale": str(item.get("rationale", "")).strip()[:1000],
                    "rejected_alternatives": rejected,  # P9: explainable, alternatives recorded
                },
                "provenance": provenance,
            })
            if len(findings) >= self._max:
                break
        self._logger.info("design review produced %d finding(s) for %s", len(findings), name)
        return findings
