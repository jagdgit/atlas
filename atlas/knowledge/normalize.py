"""Knowledge normalize seam (KV.0.5 / KV8).

Apply aliases and light text cleanup *before* VerificationEngine spends search
budget. Shared by media extraction and the finding→Claim adapter.
"""

from __future__ import annotations

import re
from typing import Iterable

from atlas.knowledge.lifecycle import normalize_statement

# Misspellings / variants → canonical *normalized* token (lower, no punctuation).
# Longer keys first when applying as phrases.
_ENTITY_ALIASES: dict[str, str] = {
    "robert kiosaki": "robert kiyosaki",
    "kiosaki": "kiyosaki",
    "ben bernaki": "ben bernanke",
    "bernaki": "bernanke",
    "bernanky": "bernanke",
}

_ENTITY_DISPLAY: dict[str, str] = {
    "robert kiyosaki": "Robert Kiyosaki",
    "kiyosaki": "Kiyosaki",
    "ben bernanke": "Ben Bernanke",
    "bernanke": "Bernanke",
}


def entity_aliases() -> dict[str, str]:
    """Copy of the alias table (tests / operators)."""
    return dict(_ENTITY_ALIASES)


def canonical_entity_key(name: str) -> str:
    """Normalize + resolve aliases to a stable entity key."""
    key = normalize_statement(name)
    if not key:
        return ""
    if key in _ENTITY_ALIASES:
        return _ENTITY_ALIASES[key]
    for alias in sorted(_ENTITY_ALIASES, key=len, reverse=True):
        if alias in key:
            return normalize_statement(key.replace(alias, _ENTITY_ALIASES[alias]))
    return key


def display_entity_name(name: str) -> str:
    """Human display form after alias resolution."""
    key = canonical_entity_key(name)
    if key in _ENTITY_DISPLAY:
        return _ENTITY_DISPLAY[key]
    # Title-case unknown multi-word names conservatively.
    raw = (name or "").strip()
    if not raw:
        return ""
    if key != normalize_statement(raw):
        # Alias remapped — prefer display table or title-case of key.
        return _ENTITY_DISPLAY.get(key, key.title())
    return raw


def apply_entity_aliases(text: str) -> str:
    """Rewrite known misspellings in free text (case-insensitive)."""
    body = text or ""
    if not body:
        return ""
    out = body
    for alias in sorted(_ENTITY_ALIASES, key=len, reverse=True):
        canon = _ENTITY_ALIASES[alias]
        display = _ENTITY_DISPLAY.get(canon, canon.title())
        pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)

        def _repl(_m: re.Match[str], *, _display: str = display) -> str:
            return _display

        out = pattern.sub(_repl, out)
    return out


def normalize_claim_statement(statement: str) -> str:
    """Normalize a claim statement for verification (aliases only; keep wording)."""
    return apply_entity_aliases((statement or "").strip())


def register_entity_aliases(pairs: Iterable[tuple[str, str]]) -> None:
    """Extend the alias table (tests / domain packs). Canonical values are display forms."""
    for alias, display in pairs:
        a = normalize_statement(alias)
        d_key = normalize_statement(display)
        if not a or not d_key:
            continue
        _ENTITY_ALIASES[a] = d_key
        _ENTITY_DISPLAY[d_key] = display.strip()
