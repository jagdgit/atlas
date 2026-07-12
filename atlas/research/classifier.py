"""Source Classifier — domain/metadata → source type + evidence level (§5c, C3).

Stage 3, Step 1. A small, fully-deterministic, offline classifier that fixes the
§2.2 bug: before this, every web hit was hardcoded to L2 (technical blog), throwing
away the peer-reviewed / government / preprint signal that the Verification Engine's
Evidence Budget depends on.

Input: a URL (+ optional DOI / metadata). Output: a :class:`Classification` with the
machine ``kind`` and ``evidence_level`` used by ``evidence.models.Source``, a
human-readable ``source_type``, and an ``access_method`` hint the Acquisition Service
(a later step) uses to decide whether full text is likely fetchable.

Design (D3.4 / §13 A10): ship a **static domain map first** — no network, no DOI
resolution — so classification is instant, reproducible, and unit-testable. DOI/Crossref
enrichment is a later, network-gated upgrade; nothing here depends on it. A DOI *presence*
is still used as a weak peer-reviewed signal when the domain is otherwise unknown.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from atlas.evidence.models import (
    LEVEL_FIELD_DATA,
    LEVEL_FORUM,
    LEVEL_GOVERNMENT,
    LEVEL_PEER_REVIEWED,
    LEVEL_TECHNICAL,
    level_name,
)

# --- access methods: a hint for the (later) Acquisition Service ----------
ACCESS_OPEN = "open"        # full text is likely freely downloadable (arXiv, .gov, OA)
ACCESS_PAYWALL = "paywall"  # full text likely behind a login/paywall (publishers)
ACCESS_HTML = "html"        # an ordinary web page (blogs, forums, unknown)
ACCESS_VIDEO = "video"      # a video platform (transcript, not download)
ACCESS_DATASET = "dataset"  # a dataset/record repository

# --- machine kinds (mirror evidence.models.Source.kind conventions) ------
KIND_PEER_REVIEWED = "peer_reviewed"
KIND_PREPRINT = "preprint"
KIND_GOVERNMENT = "government"
KIND_FIELD_DATA = "field_data"
KIND_PRESENTATION = "presentation"
KIND_BLOG = "technical_blog"
KIND_DISCUSSION = "discussion"


@dataclass(frozen=True, slots=True)
class Classification:
    """The classifier's verdict for one source."""

    source_type: str      # human label, e.g. "peer-reviewed paper"
    kind: str             # machine kind for Source.kind
    evidence_level: int   # L1..L5 (evidence.models)
    access_method: str    # ACCESS_*
    matched: str = ""     # which rule/domain matched (for debugging/notes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "kind": self.kind,
            "evidence_level": self.evidence_level,
            "level_name": level_name(self.evidence_level),
            "access_method": self.access_method,
            "matched": self.matched,
        }


# A rule is (host-substring, Classification-without-`matched`). Rules are evaluated
# in order; the first whose substring is contained in the (lowercased, de-www'd)
# hostname wins. Order matters: more specific domains precede broad suffixes so, e.g.,
# `data.gov` classifies as a dataset (L5) before the generic `.gov` government rule.
_PEER = (KIND_PEER_REVIEWED, LEVEL_PEER_REVIEWED, ACCESS_PAYWALL, "peer-reviewed paper")
_PREPRINT = (KIND_PREPRINT, LEVEL_GOVERNMENT, ACCESS_OPEN, "preprint")
_GOV = (KIND_GOVERNMENT, LEVEL_GOVERNMENT, ACCESS_OPEN, "government/lab report")
_DATA = (KIND_FIELD_DATA, LEVEL_FIELD_DATA, ACCESS_DATASET, "dataset / field data")
_VIDEO = (KIND_PRESENTATION, LEVEL_TECHNICAL, ACCESS_VIDEO, "presentation / talk")
_BLOG = (KIND_BLOG, LEVEL_TECHNICAL, ACCESS_HTML, "technical blog")
_FORUM = (KIND_DISCUSSION, LEVEL_FORUM, ACCESS_HTML, "discussion / forum")

# (host substring, (kind, level, access, source_type))
_RULES: list[tuple[str, tuple[str, int, str, str]]] = [
    # --- dataset / field-data repositories (checked before .gov) ---------
    ("data.gov", _DATA),
    ("zenodo.org", _DATA),
    ("figshare.com", _DATA),
    ("datadryad.org", _DATA),
    ("dryad.org", _DATA),
    ("data.mendeley.com", _DATA),
    ("osf.io", _DATA),
    ("kaggle.com", _DATA),
    ("nsrdb.nrel.gov", _DATA),
    ("pvwatts.nrel.gov", _DATA),
    # --- preprint servers (checked before generic publisher/edu) ---------
    ("arxiv.org", _PREPRINT),
    ("ar5iv.org", _PREPRINT),
    ("ar5iv.labs.arxiv.org", _PREPRINT),
    ("biorxiv.org", _PREPRINT),
    ("medrxiv.org", _PREPRINT),
    ("chemrxiv.org", _PREPRINT),
    ("techrxiv.org", _PREPRINT),
    ("preprints.org", _PREPRINT),
    ("ssrn.com", _PREPRINT),
    ("researchsquare.com", _PREPRINT),
    # --- peer-reviewed publishers / journal platforms --------------------
    ("ieeexplore.ieee.org", _PEER),
    ("sciencedirect.com", _PEER),
    ("onlinelibrary.wiley.com", _PEER),
    ("wiley.com", _PEER),
    ("nature.com", _PEER),
    ("link.springer.com", _PEER),
    ("springer.com", _PEER),
    ("springeropen.com", (KIND_PEER_REVIEWED, LEVEL_PEER_REVIEWED, ACCESS_OPEN,
                          "peer-reviewed paper (open access)")),
    ("mdpi.com", (KIND_PEER_REVIEWED, LEVEL_PEER_REVIEWED, ACCESS_OPEN,
                  "peer-reviewed paper (open access)")),
    ("tandfonline.com", _PEER),
    ("pubs.acs.org", _PEER),
    ("pubs.rsc.org", _PEER),
    ("iopscience.iop.org", _PEER),
    ("aip.org", _PEER),
    ("ascelibrary.org", _PEER),
    ("asmedigitalcollection.asme.org", _PEER),
    ("sagepub.com", _PEER),
    ("cambridge.org", _PEER),
    ("academic.oup.com", _PEER),
    ("dl.acm.org", _PEER),
    ("ncbi.nlm.nih.gov", (KIND_PEER_REVIEWED, LEVEL_PEER_REVIEWED, ACCESS_OPEN,
                          "peer-reviewed paper (PMC)")),
    ("pmc.ncbi.nlm.nih.gov", (KIND_PEER_REVIEWED, LEVEL_PEER_REVIEWED, ACCESS_OPEN,
                              "peer-reviewed paper (PMC)")),
    ("plos.org", (KIND_PEER_REVIEWED, LEVEL_PEER_REVIEWED, ACCESS_OPEN,
                  "peer-reviewed paper (open access)")),
    # --- video / presentations -------------------------------------------
    ("youtube.com", _VIDEO),
    ("youtu.be", _VIDEO),
    ("vimeo.com", _VIDEO),
    ("slideshare.net", _VIDEO),
    # --- discussion / social ---------------------------------------------
    ("reddit.com", _FORUM),
    ("linkedin.com", _FORUM),
    ("quora.com", _FORUM),
    ("stackoverflow.com", _FORUM),
    ("stackexchange.com", _FORUM),
    ("news.ycombinator.com", _FORUM),
    ("twitter.com", _FORUM),
    ("x.com", _FORUM),
    ("facebook.com", _FORUM),
    # --- known blogging platforms ----------------------------------------
    ("medium.com", _BLOG),
    ("substack.com", _BLOG),
    ("dev.to", _BLOG),
    ("blogspot.com", _BLOG),
    ("wordpress.com", _BLOG),
    ("researchgate.net", _BLOG),
    ("semanticscholar.org", _BLOG),
]

# Suffix-based fallbacks (checked after exact-ish domain rules).
_SUFFIX_RULES: list[tuple[str, tuple[str, int, str, str]]] = [
    (".gov", _GOV),
    (".mil", _GOV),
    (".int", _GOV),
]

# Default for anything unmatched: a technical blog (L2) — honest "unknown web page".
_DEFAULT = (KIND_BLOG, LEVEL_TECHNICAL, ACCESS_HTML, "web page (unclassified)")


def _hostname(url: str) -> str:
    if not url:
        return ""
    raw = url.strip()
    # urlsplit needs a scheme to populate netloc; add one if missing.
    if "://" not in raw:
        raw = "http://" + raw
    host = (urlsplit(raw).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def classify(
    url: str,
    *,
    doi: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Classification:
    """Classify a source from its URL (+ optional DOI / metadata).

    Deterministic and offline. The first matching domain rule wins; unmatched hosts
    fall back to suffix rules (``.gov``), then to a weak DOI signal (peer-reviewed),
    then to the honest default (unclassified web page, L2).
    """
    host = _hostname(url)
    if host:
        for needle, spec in _RULES:
            if needle in host:
                kind, level, access, label = spec
                return Classification(label, kind, level, access, matched=needle)
        for suffix, spec in _SUFFIX_RULES:
            if host.endswith(suffix):
                kind, level, access, label = spec
                return Classification(label, kind, level, access, matched=suffix)

    # A DOI (in metadata or explicit) is a weak "this is a real publication" signal
    # when the domain told us nothing — treat as peer-reviewed but paywalled.
    has_doi = bool(doi) or bool((metadata or {}).get("doi"))
    if has_doi:
        kind, level, access, label = _PEER
        return Classification(label, kind, level, access, matched="doi")

    kind, level, access, label = _DEFAULT
    return Classification(label, kind, level, access, matched="default")
