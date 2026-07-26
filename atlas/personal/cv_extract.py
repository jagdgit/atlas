"""Extract structured personal facts from resume / CV plain text.

Heuristic + deterministic (no LLM required). Facts are emitted as *inferred* proposals —
the operator Confirm/Rejects them on the Personal dashboard (P9/CC7). Never posts anywhere.
"""

from __future__ import annotations

import re
from typing import Any

# Section headers commonly seen on CVs (EN + a few IN variants).
_SECTION_RE = re.compile(
    r"(?im)^\s*(?:"
    r"professional\s+summary|summary|profile|about\s+me|"
    r"work\s+experience|professional\s+experience|experience|employment|"
    r"education|academic|academics|"
    r"skills|technical\s+skills|core\s+competenc(?:y|ies)|technologies|"
    r"projects|certifications?|awards|publications?"
    r")\s*:?\s*$"
)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,6}"
)
_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?", re.I
)
_DEGREE_RE = re.compile(
    r"(?i)\b("
    r"B\.?\s?Tech|B\.?\s?E\.?|Bachelor(?:'s)?(?:\s+of\s+[A-Za-z &]+)?"
    r"|M\.?\s?Tech|M\.?\s?S\.?|M\.?\s?Sc|Master(?:'s)?(?:\s+of\s+[A-Za-z &]+)?"
    r"|MBA|Ph\.?\s?D\.?|Diploma"
    r")\b([^\n]{0,80})"
)
_ROLE_LINE_RE = re.compile(
    r"(?im)^\s*(?P<title>[A-Z][A-Za-z0-9 /&+.-]{2,60}?)\s*"
    r"(?:[-–—@|]|at)\s*(?P<org>[A-Za-z0-9][A-Za-z0-9 &.,'-]{1,80})"
    r"(?:\s*[-–—|,]\s*(?P<dates>\d{4}.*))?$"
)
_ROLE_LOOSE_RE = re.compile(
    r"(?i)\b(?P<title>"
    r"(?:Senior|Staff|Principal|Lead|Junior|Associate)?\s*"
    r"(?:Software|Data|Backend|Frontend|Full[\s-]?Stack|DevOps|SRE|ML|AI)?\s*"
    r"(?:Engineer|Developer|Architect|Manager|Analyst|Consultant|Scientist)"
    r")\b(?:\s+(?:at|@)\s+(?P<org>[A-Z][A-Za-z0-9 &.,'-]{1,60}))?"
)
_NAME_LINE_RE = re.compile(r"^[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z.]*){0,4}$")
_SKILL_SPLIT_RE = re.compile(r"[,|/•·;]|\n")
_YEAR_RANGE_RE = re.compile(r"\b(19|20)\d{2}\b")


def extract_cv_facts(text: str, *, source_path: str | None = None) -> list[dict[str, Any]]:
    """Return fact dicts ready for PersonalService._upsert_fact (category/key/...)."""
    raw = (text or "").strip()
    if not raw:
        return []

    sections = _split_sections(raw)
    blob = raw
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        category: str,
        key: str,
        statement: str,
        *,
        value: dict[str, Any] | None = None,
        subject: str = "",
        confidence: str = "MEDIUM",
        score: float = 0.65,
    ) -> None:
        nk = f"{category}:{key}:{subject}".lower()
        if nk in seen or not statement.strip():
            return
        seen.add(nk)
        facts.append(
            {
                "category": category,
                "key": key[:120],
                "subject": subject,
                "statement": statement.strip()[:500],
                "value": value or {},
                "confidence": confidence,
                "confidence_score": score,
                "source": "cv",
                "provenance": {
                    "extractor": "cv_extract.v1",
                    "source_path": source_path,
                },
            }
        )

    # --- identity: name, email, linkedin --------------------------------
    name = _guess_name(raw, sections)
    if name:
        add(
            "identity",
            "full_name",
            f"Name: {name}.",
            value={"kind": "name", "name": name},
            confidence="HIGH",
            score=0.85,
        )

    emails = _EMAIL_RE.findall(raw)
    if emails:
        email = emails[0]
        add(
            "identity",
            "email",
            f"Email: {email}.",
            value={"kind": "email", "email": email},
            confidence="HIGH",
            score=0.9,
        )

    li = _LINKEDIN_RE.search(raw)
    if li:
        url = li.group(0)
        if not url.startswith("http"):
            url = "https://" + url
        add(
            "identity",
            "linkedin_url",
            f"LinkedIn: {url}.",
            value={"kind": "linkedin", "url": url.rstrip("/")},
            confidence="HIGH",
            score=0.9,
        )

    phones = _PHONE_RE.findall(raw[:800])
    if phones:
        phone = phones[0].strip()
        if len(re.sub(r"\D", "", phone)) >= 10:
            add(
                "identity",
                "phone",
                f"Phone on CV: {phone}.",
                value={"kind": "phone", "phone": phone},
                confidence="MEDIUM",
                score=0.55,
            )

    # --- education ------------------------------------------------------
    edu_text = sections.get("education") or sections.get("academic") or ""
    for m in _DEGREE_RE.finditer(edu_text or blob):
        degree = (m.group(1) or "").strip()
        rest = (m.group(2) or "").strip(" -,|")
        stmt = f"Education: {degree}" + (f" — {rest}" if rest else "") + "."
        key = f"edu:{(degree + ' ' + rest).lower()[:80]}"
        add(
            "timeline",
            key,
            stmt,
            value={"kind": "education", "degree": degree, "detail": rest},
            confidence="MEDIUM",
            score=0.7,
        )

    # --- roles / experience ---------------------------------------------
    exp_text = (
        sections.get("work experience")
        or sections.get("professional experience")
        or sections.get("experience")
        or sections.get("employment")
        or ""
    )
    role_src = exp_text or "\n".join(raw.splitlines()[:120])
    for m in _ROLE_LOOSE_RE.finditer(role_src):
        title = _clean_ws(m.group("title") or "")
        org = _clean_ws(m.groupdict().get("org") or "")
        if len(title) < 5 or not _looks_like_job_title(title):
            continue
        where = f" at {org}" if org else ""
        key = f"role:{(title + '@' + org).lower()[:100]}"
        add(
            "professional",
            key,
            f"Role: {title}{where}.",
            value={"kind": "role", "title": title, "org": org or None},
            confidence="MEDIUM" if org else "LOW",
            score=0.7 if org else 0.5,
        )
    # Structured "Title - Org - dates" lines (only when title looks real).
    for m in _ROLE_LINE_RE.finditer(role_src):
        title = _clean_ws(m.group("title") or "")
        org = _clean_ws(m.group("org") or "")
        dates = _clean_ws(m.groupdict().get("dates") or "")
        if not _looks_like_job_title(title) or len(org) < 2:
            continue
        where = f" at {org}"
        when = f" ({dates})" if dates else ""
        key = f"role:{(title + '@' + org).lower()[:100]}"
        add(
            "professional",
            key,
            f"Role: {title}{where}{when}.",
            value={"kind": "role", "title": title, "org": org, "dates": dates or None},
            confidence="MEDIUM",
            score=0.75,
        )

    # --- skills ---------------------------------------------------------
    skills_text = (
        sections.get("skills")
        or sections.get("technical skills")
        or sections.get("technologies")
        or ""
    )
    for skill in _parse_skills(skills_text):
        add(
            "skill",
            skill.lower(),
            f"Skilled in {skill} (from CV).",
            value={
                "skill": skill,
                "context": "cv",
                "proficiency": "stated",
                "kind": "cv_skill",
            },
            subject="cv",
            confidence="MEDIUM",
            score=0.6,
        )

    # --- summary as identity headline -----------------------------------
    summary = (
        sections.get("professional summary")
        or sections.get("summary")
        or sections.get("profile")
        or sections.get("about me")
        or ""
    ).strip()
    if summary:
        first = " ".join(summary.split())[:280]
        add(
            "identity",
            "headline",
            first if first.endswith(".") else first + ".",
            value={"kind": "headline", "text": first},
            confidence="MEDIUM",
            score=0.6,
        )

    return facts


def _split_sections(text: str) -> dict[str, str]:
    lines = text.splitlines()
    headers: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if _SECTION_RE.match(line.strip()):
            headers.append((i, line.strip().rstrip(":").lower()))
    if not headers:
        return {}
    out: dict[str, str] = {}
    for idx, (start, name) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        out[name] = body
    return out


def _guess_name(raw: str, sections: dict[str, str]) -> str | None:
    # Prefer first non-empty line before any section / contact noise.
    for line in raw.splitlines()[:12]:
        s = line.strip()
        if not s or len(s) > 60:
            continue
        if _EMAIL_RE.search(s) or _LINKEDIN_RE.search(s) or _PHONE_RE.search(s):
            continue
        if _SECTION_RE.match(s) or _looks_like_section(s):
            break
        if _NAME_LINE_RE.match(s) and len(s.split()) <= 4:
            return s
    return None


def _looks_like_section(s: str) -> bool:
    return bool(_SECTION_RE.match(s.strip()))


def _clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip(" .,;|-–—"))


def _looks_like_job_title(title: str) -> bool:
    t = _clean_ws(title)
    if len(t) < 5 or len(t) > 60:
        return False
    if _looks_like_section(t):
        return False
    low = t.lower()
    # Reject responsibility bullets / soft-skill fluff.
    bad = (
        "developing ", "reviewing ", "entering ", "planning ", "responsible",
        "detail", "communic", "oriented", "setting-up", "accommod",
    )
    if any(low.startswith(b) for b in bad):
        return False
    keywords = (
        "engineer", "developer", "architect", "manager", "analyst",
        "consultant", "scientist", "lead", "director", "intern", "sde",
    )
    return any(k in low for k in keywords)


def _parse_skills(text: str) -> list[str]:
    if not text.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in _SKILL_SPLIT_RE.split(text):
        skill = part.strip(" \t•·-–—")
        if not skill or len(skill) < 2 or len(skill) > 40:
            continue
        if _YEAR_RANGE_RE.search(skill) and len(skill.split()) > 4:
            continue
        if skill.lower() in seen:
            continue
        # Drop sentence-like fragments.
        if skill.count(" ") > 4:
            continue
        seen.add(skill.lower())
        out.append(skill)
        if len(out) >= 40:
            break
    return out
