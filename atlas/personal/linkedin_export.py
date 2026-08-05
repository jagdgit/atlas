"""LinkedIn data-export ingest (CI.0/CI.1) — read-only, suggestions only.

Operator downloads LinkedIn "Get a copy of your data" (often arrives after ~24h).
Atlas unpacks Profile/Skills/Positions/Jobs text for coaching and Career Observer —
never logs in, never writes back to LinkedIn (P10/P14 / CAREER_INTELLIGENCE_PLAN L-P14).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

_LOG = logging.getLogger("atlas.personal.linkedin_export")

# Prefer these so truncation under max_chars keeps career signal.
_PREFERRED_MEMBERS = (
    "Profile.csv",
    "Profile.html",
    "Profile Summary.csv",
    "Skills.csv",
    "Skills.html",
    "Positions.csv",
    "Positions.html",
    "Education.csv",
    "Education.html",
    "Certifications.csv",
    "Publications.csv",
    "Jobs/Job Seeker Preferences.csv",
    "Jobs/Saved Jobs.csv",
    "Jobs/Job Applications.csv",
    "SavedJobAlerts.csv",
    "Company Follows.csv",
    "Summary.csv",
    "About.csv",
)

# Skip inbox / ads / PII dumps that crowd out profile + jobs under max_chars.
_SKIP_BASENAMES = frozenset(
    {
        "messages.csv",
        "ad_targeting.csv",
        "email addresses.csv",
        "phonenumbers.csv",
        "whatsapp phone numbers.csv",
        "receipts_v2.csv",
        "guide_messages.csv",
        "learning_coach_messages.csv",
        "learning_role_play_messages.csv",
        "registration.csv",
        "rich_media.csv",
        "endorsement_given_info.csv",
        "job applicant saved screening question responses.csv",
        "job applicant saved screening question responses_1.csv",
        "job applicant saved answers.csv",
    }
)

_JOB_ID_RE = re.compile(r"/jobs/view/(\d+)", re.I)


def extract_linkedin_export_text(path: str | Path, *, max_chars: int = 120_000) -> dict[str, Any]:
    """Load LinkedIn export path → concatenated text for the coach / Observer.

    Accepts a ``.zip`` archive, a directory of extracted files, or a single
    ``.html``/``.csv``/``.txt`` file. Returns ``{ok, text, files, path, reason?}``.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "text": "", "files": [], "path": str(p), "reason": "path not found"}

    files_used: list[str] = []
    chunks: list[str] = []

    try:
        if p.is_dir():
            chunks, files_used = _from_directory(p)
        elif p.suffix.lower() == ".zip" or p.name.lower().endswith(".zip"):
            chunks, files_used = _from_zip(p)
        elif p.is_file():
            text = _read_text_file(p)
            if text.strip():
                chunks = [text]
                files_used = [p.name]
        else:
            return {
                "ok": False,
                "text": "",
                "files": [],
                "path": str(p.resolve()),
                "reason": "unsupported path type",
            }
    except Exception as exc:  # noqa: BLE001 - operator path must never crash the API
        _LOG.warning("linkedin export extract failed (%s): %s", p, exc)
        return {
            "ok": False,
            "text": "",
            "files": [],
            "path": str(p),
            "reason": f"extract failed: {exc}",
        }

    text = "\n\n".join(c.strip() for c in chunks if c and c.strip())
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…[truncated]"
    if not text.strip():
        return {
            "ok": False,
            "text": "",
            "files": files_used,
            "path": str(p.resolve()),
            "reason": (
                "no Profile/Skills/Positions text found — wait for LinkedIn email, "
                "unzip the archive, or share the .zip path"
            ),
        }
    return {
        "ok": True,
        "text": text,
        "files": files_used,
        "path": str(p.resolve()),
        "chars": len(text),
        "policy": "suggestions_only",
        "can_write_linkedin": False,
    }


def load_linkedin_export_bundle(path: str | Path, *, max_chars: int = 120_000) -> dict[str, Any]:
    """CI.1 — text extract plus structured skills / positions / job rows from the same path."""
    base = extract_linkedin_export_text(path, max_chars=max_chars)
    p = Path(path).expanduser()
    skills: list[str] = []
    positions: list[dict[str, str]] = []
    postings: list[dict[str, Any]] = []
    companies_followed: list[str] = []
    if base.get("ok") and p.exists():
        try:
            members = _member_texts(p)
            skills = _parse_skills(members.get("Skills.csv") or members.get("skills.csv") or "")
            positions = _parse_positions(
                members.get("Positions.csv") or members.get("positions.csv") or ""
            )
            postings.extend(
                _parse_saved_jobs(
                    members.get("Jobs/Saved Jobs.csv")
                    or members.get("Saved Jobs.csv")
                    or ""
                )
            )
            postings.extend(
                _parse_applications(
                    members.get("Jobs/Job Applications.csv")
                    or members.get("Job Applications.csv")
                    or ""
                )
            )
            companies_followed = _parse_company_follows(
                members.get("Company Follows.csv") or ""
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("linkedin structured parse failed (%s): %s", p, exc)
            base = dict(base)
            base["structured_error"] = str(exc)[:200]
    out = dict(base)
    out["skills"] = skills
    out["positions"] = positions
    out["postings"] = _dedupe_postings(postings)
    out["companies_followed"] = companies_followed
    return out


def _member_texts(path: Path) -> dict[str, str]:
    """Map relative/basename → decoded text for known CSV members."""
    out: dict[str, str] = {}
    if path.is_dir():
        for p in path.rglob("*"):
            if not p.is_file():
                continue
            if _should_skip(p.name):
                continue
            rel = str(p.relative_to(path)).replace("\\", "/")
            text = _read_text_file(p)
            if text.strip():
                out[rel] = text
                out[p.name] = text
        return out
    if path.suffix.lower() == ".zip" or path.name.lower().endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/") or _should_skip(Path(name).name):
                    continue
                try:
                    raw = zf.read(name)
                except Exception:  # noqa: BLE001
                    continue
                text = _decode_bytes(raw, name)
                if not text.strip():
                    continue
                norm = name.replace("\\", "/")
                out[norm] = text
                out[Path(name).name] = text
        return out
    if path.is_file():
        out[path.name] = _read_text_file(path)
    return out


def _from_zip(path: Path) -> tuple[list[str], list[str]]:
    chunks: list[str] = []
    used: list[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        ordered = _prefer_members(names)
        for name in ordered:
            try:
                raw = zf.read(name)
            except Exception:  # noqa: BLE001
                continue
            text = _decode_bytes(raw, name)
            if text.strip():
                chunks.append(f"## {Path(name).name}\n{text}")
                used.append(name)
    return chunks, used


def _from_directory(root: Path) -> tuple[list[str], list[str]]:
    chunks: list[str] = []
    used: list[str] = []
    files = [p for p in root.rglob("*") if p.is_file() and not _should_skip(p.name)]
    preferred: list[Path] = []
    other: list[Path] = []
    preferred_names = {m.lower() for m in _PREFERRED_MEMBERS}
    preferred_basenames = {Path(m).name.lower() for m in _PREFERRED_MEMBERS}
    for p in files:
        rel = str(p.relative_to(root)).replace("\\", "/").lower()
        if rel in preferred_names or p.name.lower() in preferred_basenames:
            preferred.append(p)
        elif p.suffix.lower() in {".csv", ".html", ".htm", ".txt", ".json"}:
            other.append(p)
    # Stable preferred order matching _PREFERRED_MEMBERS.
    ordered_pref: list[Path] = []
    for want in _PREFERRED_MEMBERS:
        want_l = want.lower()
        for p in preferred:
            rel = str(p.relative_to(root)).replace("\\", "/").lower()
            if (rel == want_l or p.name.lower() == Path(want).name.lower()) and p not in ordered_pref:
                ordered_pref.append(p)
                break
    for p in ordered_pref + sorted(other, key=lambda x: str(x).lower())[:24]:
        text = _read_text_file(p)
        if text.strip():
            chunks.append(f"## {p.name}\n{text}")
            used.append(str(p.relative_to(root)))
    return chunks, used


def _prefer_members(names: list[str]) -> list[str]:
    """Order zip members: preferred LinkedIn files first, then other text-ish paths."""
    preferred: list[str] = []
    other: list[str] = []
    by_rel = {n.replace("\\", "/"): n for n in names}
    by_base = {Path(n).name.lower(): n for n in names if not n.endswith("/")}
    for want in _PREFERRED_MEMBERS:
        hit = by_rel.get(want) or by_rel.get(want.replace("\\", "/"))
        if hit is None:
            hit = by_base.get(Path(want).name.lower())
        if hit and hit not in preferred and not _should_skip(Path(hit).name):
            preferred.append(hit)
    for n in names:
        if n in preferred or n.endswith("/"):
            continue
        if _should_skip(Path(n).name):
            continue
        suf = Path(n).suffix.lower()
        if suf in {".csv", ".html", ".htm", ".txt", ".json"}:
            other.append(n)
    return preferred + other[:24]


def _should_skip(basename: str) -> bool:
    return basename.lower() in _SKIP_BASENAMES


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    return _decode_bytes(raw, path.name)


def _decode_bytes(raw: bytes, name: str) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = ""
    else:
        text = raw.decode("utf-8", errors="replace")
    # Strip crude HTML tags for coach lexical matching (keep words).
    if Path(name).suffix.lower() in {".html", ".htm"}:
        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return text


def _csv_dicts(text: str) -> list[dict[str, str]]:
    if not (text or "").strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for row in reader:
        if not isinstance(row, dict):
            continue
        rows.append({str(k or "").strip(): str(v or "").strip() for k, v in row.items()})
    return rows


def _parse_skills(text: str) -> list[str]:
    skills: list[str] = []
    for row in _csv_dicts(text):
        name = row.get("Name") or row.get("Skill") or row.get("Skills") or ""
        if name and name not in skills:
            skills.append(name)
    return skills


def _parse_positions(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in _csv_dicts(text):
        company = row.get("Company Name") or row.get("Company") or ""
        title = row.get("Title") or ""
        if not (company or title):
            continue
        out.append(
            {
                "company": company,
                "title": title,
                "description": row.get("Description") or "",
                "location": row.get("Location") or "",
                "started_on": row.get("Started On") or "",
                "finished_on": row.get("Finished On") or "",
            }
        )
    return out


def _parse_saved_jobs(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _csv_dicts(text):
        title = row.get("Job Title") or row.get("Title") or ""
        company = row.get("Company Name") or row.get("Company") or ""
        url = row.get("Job Url") or row.get("Job URL") or row.get("Url") or ""
        if not (title or company or url):
            continue
        out.append(
            _normalize_posting(
                title=title,
                company=company,
                url=url,
                source="linkedin_export_saved",
                extra={"saved_date": row.get("Saved Date") or ""},
            )
        )
    return out


def _parse_applications(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in _csv_dicts(text):
        title = row.get("Job Title") or row.get("Title") or ""
        company = row.get("Company Name") or row.get("Company") or ""
        url = row.get("Job Url") or row.get("Job URL") or row.get("Url") or ""
        if not (title or company or url):
            continue
        # Drop long Q&A PII from description — keep a short marker only.
        out.append(
            _normalize_posting(
                title=title,
                company=company,
                url=url,
                source="linkedin_export_applied",
                extra={
                    "application_date": row.get("Application Date") or "",
                    "operator_status": "applied",
                },
            )
        )
    return out


def _parse_company_follows(text: str) -> list[str]:
    names: list[str] = []
    for row in _csv_dicts(text):
        org = row.get("Organization") or row.get("Company") or ""
        if org and org not in names:
            names.append(org)
    return names


def _normalize_posting(
    *,
    title: str,
    company: str,
    url: str,
    source: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_id = ""
    m = _JOB_ID_RE.search(url or "")
    if m:
        job_id = m.group(1)
    digest = hashlib.sha256(f"{title}|{company}|{url}".encode("utf-8")).hexdigest()[:12]
    pid = f"linkedin-{job_id}" if job_id else f"linkedin-{digest}"
    row: dict[str, Any] = {
        "id": pid,
        "title": title,
        "company": company,
        "url": url,
        "source": source,
        "location": "",
        "skills": [],
        "description": f"{title} at {company}".strip(" at"),
    }
    if extra:
        row.update(extra)
    return row


def _dedupe_postings(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        pid = str(row.get("id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(row)
    return out
