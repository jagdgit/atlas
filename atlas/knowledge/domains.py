"""Knowledge Domains (§3b / D3.13) — two universes, one engine.

Stage 3 establishes the ``domain`` tag and fills three of them:

- ``external``  — world sources Atlas actually read (papers, pages, docs)
- ``research``  — verified claims + evidence graphs from research jobs
- ``experience``— governed Experience records (problem → solution)

``code`` / ``personal`` / ``professional`` are Stage 4–5. Retrieval is
domain-scoped so the Researcher stays in its universe.
"""

from __future__ import annotations

DOMAIN_EXTERNAL = "external"
DOMAIN_RESEARCH = "research"
DOMAIN_EXPERIENCE = "experience"
DOMAIN_CODE = "code"
DOMAIN_PERSONAL = "personal"
DOMAIN_PROFESSIONAL = "professional"

ALL_DOMAINS = (
    DOMAIN_EXTERNAL,
    DOMAIN_RESEARCH,
    DOMAIN_EXPERIENCE,
    DOMAIN_CODE,
    DOMAIN_PERSONAL,
    DOMAIN_PROFESSIONAL,
)

# Default retrieval universe for the Researcher (A3).
RESEARCHER_DOMAINS = (DOMAIN_EXTERNAL, DOMAIN_RESEARCH, DOMAIN_EXPERIENCE)

DEFAULT_DOMAIN = DOMAIN_EXTERNAL
