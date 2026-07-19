"""Draft a resume / LinkedIn summary **purely from the personal profile** (Phase C · §C.7, P10).

Retrieval, not action: these builders read the assembled profile (identity/skills/timeline/
professional) and render a Markdown draft. They never scan code and never post — a human takes the
draft from here. Rendering is deterministic; an optional LLM ``for_role("summarizer")`` step only
polishes the opening summary and is always best-effort (falls back to the deterministic text).
"""

from __future__ import annotations

import logging
from typing import Any

_LOG = logging.getLogger("atlas.personal.draft")

_SUMMARY_SYSTEM = (
    "You write concise, factual professional summaries. Use ONLY the facts provided. "
    "Do not invent employers, titles, dates, or skills. 2-4 sentences, first person singular."
)


def _skill_names(profile: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for f in profile.get("skills", []):
        val = f.get("value") or {}
        name = val.get("skill") or f.get("key")
        if name and name not in out:
            out.append(str(name))
    return out


def _deterministic_summary(profile: dict[str, Any]) -> str:
    identity = profile.get("identity") or []
    base = ""
    for f in identity:
        if f.get("key") == "engineering_profile" and f.get("statement"):
            base = str(f["statement"])
            break
    skills = _skill_names(profile)[:8]
    if skills:
        base = (base + " ").strip() + f"Core skills: {', '.join(skills)}."
    return base or "Professional profile."


def build_resume(
    profile: dict[str, Any], *, name: str | None = None, llm: Any = None
) -> dict[str, Any]:
    """Render a Markdown resume draft from the profile. Returns ``{markdown, sections, counts}``."""
    heading = name or "Professional Resume"
    summary = _polish(_deterministic_summary(profile), profile, llm)

    lines: list[str] = [f"# {heading}", "", "## Summary", "", summary, ""]

    skills = _skill_names(profile)
    if skills:
        lines += ["## Skills", "", ", ".join(skills), ""]

    timeline = profile.get("timeline") or []
    if timeline:
        lines += ["## Projects", ""]
        for f in timeline:
            val = f.get("value") or {}
            proj = val.get("project") or f.get("key")
            langs = val.get("languages") or {}
            top = ", ".join(sorted(langs, key=lambda k: -langs[k])[:3]) if langs else ""
            lines.append(f"- **{proj}**" + (f" — {top}" if top else ""))
        lines.append("")

    professional = profile.get("professional") or []
    if professional:
        lines += ["## Professional", ""]
        for f in professional:
            lines.append(f"- {f.get('statement') or f.get('key')}")
        lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    return {
        "markdown": markdown,
        "summary": summary,
        "counts": {
            "skills": len(skills),
            "timeline": len(timeline),
            "professional": len(professional),
        },
    }


def build_linkedin(profile: dict[str, Any], *, llm: Any = None) -> dict[str, Any]:
    """Render a short LinkedIn 'About' draft (summary + a skills line)."""
    summary = _polish(_deterministic_summary(profile), profile, llm)
    skills = _skill_names(profile)[:10]
    lines = [summary, ""]
    if skills:
        lines.append("Skills: " + " · ".join(skills))
    markdown = "\n".join(lines).strip() + "\n"
    return {"markdown": markdown, "summary": summary, "counts": {"skills": len(skills)}}


def _polish(summary: str, profile: dict[str, Any], llm: Any) -> str:
    """Optionally reword the summary with an LLM — best-effort, deterministic-first."""
    if llm is None:
        return summary
    try:
        from atlas.llm.provider import ChatMessage

        facts = _deterministic_summary(profile)
        resp = llm.for_role("summarizer").chat(
            [
                ChatMessage("system", _SUMMARY_SYSTEM),
                ChatMessage(
                    "user",
                    "Rewrite this into a polished 2-4 sentence professional summary, "
                    f"grounded ONLY in these facts:\n\n{facts}",
                ),
            ]
        )
        text = (resp.text or "").strip()
        return text or summary
    except Exception as exc:  # noqa: BLE001 - polish is optional; never fail the draft
        _LOG.warning("resume summary polish failed: %s", exc)
        return summary
