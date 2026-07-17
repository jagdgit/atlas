"""Relevance filter — keep candidates on-topic before acquire (Stage 3.1).

Live soiling run (2026-07-14): queries containing ``solar`` pulled astronomy /
heliophysics arXiv papers (Solar Orbiter, FIP effect, solar atmosphere) which then
consumed the document cap. Relevance is a cheap, deterministic gate between search
and acquisition: score title + snippet against the objective's topical tokens and
drop clear off-topic hits.

This is *not* an LLM judge — keyword/token overlap + domain boosters/penalties,
fully offline and hermetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}")
_STOP = frozenset(
    "the a an of to in on for and or is are was were be been being with by at as "
    "that this these those from into over under about it its their our we they "
    "data driven study research estimate estimation method methods using via "
    "based analysis review paper".split()
)

# Tokens that strongly signal the *intended* engineering topic when present in the
# objective — a hit without any of these when the objective has them is demoted.
_TOPIC_ANCHORS = frozenset(
    "photovoltaic photovoltaics pv soiling dust panel panels module modules "
    "cleaning degradation irradiance inverter grid battery storage wind turbine "
    "farm plant array".split()
)

# Hard off-topic for PV/soiling jobs (astronomy / space weather).
_ASTRONOMY_PENALTY = frozenset(
    "heliosphere heliophysics astrophysics corona coronal chromosphere "
    "flare flares neutrino neutrinos orbiter probe stellar cosmic "
    "magnetosphere solar-wind solarwind sep fip".split()
)


@dataclass(frozen=True, slots=True)
class RelevanceScore:
    score: float
    reason: str

    @property
    def relevant(self) -> bool:
        return self.score >= 0.15


def _tokens(text: str) -> set[str]:
    return {
        w for w in _WORD_RE.findall((text or "").lower())
        if w not in _STOP and len(w) > 1
    }


def score_relevance(
    objective: str,
    *,
    title: str = "",
    snippet: str = "",
    url: str = "",
) -> RelevanceScore:
    """Return a relevance score in roughly [0, 1+] for a candidate source."""
    obj = _tokens(objective)
    doc = _tokens(f"{title} {snippet}")
    if not obj or not doc:
        return RelevanceScore(0.0, "empty title/snippet")

    overlap = obj & doc
    jaccard = len(overlap) / max(1, len(obj | doc))
    coverage = len(overlap) / max(1, len(obj))
    score = 0.55 * coverage + 0.45 * jaccard

    anchors_needed = obj & _TOPIC_ANCHORS
    anchors_hit = anchors_needed & doc
    if anchors_needed:
        if anchors_hit:
            score += 0.25 * (len(anchors_hit) / len(anchors_needed))
        else:
            score *= 0.25  # objective asks for PV/soiling; doc has none → crush
            return RelevanceScore(round(score, 3), "missing topic anchors")

    # Astronomy / space-weather docs are near-zero when the objective is terrestrial PV.
    low = f"{title} {snippet} {url}".lower()
    if any(p in low or p in doc for p in _ASTRONOMY_PENALTY):
        if not (doc & {"photovoltaic", "photovoltaics", "pv", "soiling", "panel"}):
            return RelevanceScore(0.0, "astronomy/space-weather off-topic")

    reason = f"overlap={sorted(overlap)[:6]}"
    return RelevanceScore(round(min(score, 1.5), 3), reason)


def filter_relevant(
    objective: str,
    items: Iterable,
    *,
    title_of=lambda x: getattr(x, "title", "") or "",
    snippet_of=lambda x: getattr(x, "snippet", "") or "",
    url_of=lambda x: getattr(x, "url", "") or "",
    min_score: float = 0.15,
) -> tuple[list, list]:
    """Split ``items`` into (kept, dropped) by relevance to ``objective``."""
    kept: list = []
    dropped: list = []
    for item in items:
        # Support Source / _Gathered / plain objects.
        src = getattr(item, "source", item)
        title = title_of(src) if src is not item else title_of(item)
        if not title and hasattr(src, "title"):
            title = src.title or ""
        snippet = ""
        if hasattr(item, "snippet"):
            snippet = item.snippet or ""
        elif hasattr(item, "full_text"):
            snippet = (item.full_text or "")[:400]
        url = ""
        if hasattr(src, "url"):
            url = src.url or ""
        elif hasattr(item, "url"):
            url = item.url or ""
        rel = score_relevance(objective, title=title, snippet=snippet, url=url)
        if rel.score >= min_score:
            kept.append(item)
        else:
            dropped.append((item, rel))
    return kept, dropped
