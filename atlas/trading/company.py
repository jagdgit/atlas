"""Company / filings adapters (MI.5) — Market Program domain.

Official exchange + filings preferred (MI4); no indiscriminate scraping (MI5).
Default provider is hermetic ``config_seed`` (operator-supplied profiles). Live
SEC/NSE/BSE clients raise :class:`~atlas.decision.rules.CapabilityGap` until
API keys and ToS-compliant paths exist.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

from atlas.decision.rules import CapabilityGap


@dataclass(frozen=True)
class FilingRef:
    title: str
    kind: str = "filing"  # annual | quarterly | prospectus | other
    url: str = ""
    as_of: str = ""
    source: str = "config_seed"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompanyProfile:
    symbol: str
    name: str = ""
    sector: str = ""
    exchange: str = ""
    facts: tuple[str, ...] = ()
    filings: tuple[FilingRef, ...] = ()
    ratios: dict[str, float] = field(default_factory=dict)
    provider: str = "config_seed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "exchange": self.exchange,
            "facts": list(self.facts),
            "filings": [f.as_dict() for f in self.filings],
            "ratios": dict(self.ratios),
            "provider": self.provider,
            "metadata": dict(self.metadata),
        }

    def knowledge_text(self) -> str:
        """Prose blob for typed extraction (claims/concepts/entities)."""
        lines: list[str] = []
        label = self.name or self.symbol
        lines.append(f"{label} ({self.symbol}) is a listed company.")
        if self.sector:
            lines.append(f"{label} operates in the {self.sector} sector.")
        if self.exchange:
            lines.append(f"{label} trades on {self.exchange}.")
        for fact in self.facts:
            text = str(fact).strip()
            if text:
                lines.append(text if text.endswith(".") else text + ".")
        for key, val in (self.ratios or {}).items():
            lines.append(f"{label} reports {key.replace('_', ' ')} of {val}.")
        for filing in self.filings:
            bits = [filing.kind or "filing", filing.title]
            if filing.as_of:
                bits.append(f"as of {filing.as_of}")
            lines.append(f"{label} has { ' '.join(bits) }.")
        return " ".join(lines)


@runtime_checkable
class CompanyDataAdapter(Protocol):
    name: str

    def fetch_company(self, symbol: str, **kwargs: Any) -> CompanyProfile:
        ...


def _filing_from_dict(raw: dict[str, Any], *, default_source: str) -> FilingRef:
    return FilingRef(
        title=str(raw.get("title") or raw.get("name") or "Filing").strip(),
        kind=str(raw.get("kind") or "filing").strip(),
        url=str(raw.get("url") or "").strip(),
        as_of=str(raw.get("as_of") or raw.get("date") or "").strip(),
        source=str(raw.get("source") or default_source).strip(),
    )


def profile_from_dict(raw: dict[str, Any], *, provider: str = "config_seed") -> CompanyProfile:
    filings = tuple(
        _filing_from_dict(f, default_source=provider)
        for f in (raw.get("filings") or [])
        if isinstance(f, dict)
    )
    facts = tuple(str(x).strip() for x in (raw.get("facts") or []) if str(x).strip())
    ratios: dict[str, float] = {}
    for key, val in (raw.get("ratios") or {}).items():
        try:
            ratios[str(key)] = float(val)
        except (TypeError, ValueError):
            continue
    return CompanyProfile(
        symbol=str(raw.get("symbol") or "").strip(),
        name=str(raw.get("name") or "").strip(),
        sector=str(raw.get("sector") or "").strip(),
        exchange=str(raw.get("exchange") or "").strip(),
        facts=facts,
        filings=filings,
        ratios=ratios,
        provider=provider,
        metadata=dict(raw.get("metadata") or {}),
    )


class ConfigSeedCompanyAdapter:
    """Hermetic: profiles supplied in mission config (no network)."""

    name = "config_seed"

    def __init__(
        self,
        profiles: list[dict[str, Any]] | dict[str, dict[str, Any]] | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger("atlas.trading.company.config_seed")
        self._by_symbol: dict[str, CompanyProfile] = {}
        self.load(profiles or [])

    def load(self, profiles: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> None:
        rows: list[dict[str, Any]]
        if isinstance(profiles, dict):
            rows = []
            for sym, body in profiles.items():
                if isinstance(body, dict):
                    rows.append({**body, "symbol": body.get("symbol") or sym})
        else:
            rows = [p for p in profiles if isinstance(p, dict)]
        for raw in rows:
            profile = profile_from_dict(raw, provider=self.name)
            if profile.symbol:
                self._by_symbol[profile.symbol.upper()] = profile

    def fetch_company(self, symbol: str, **kwargs: Any) -> CompanyProfile:
        sym = (symbol or "").strip()
        if not sym:
            raise CapabilityGap("company_data:symbol", "symbol is required")
        profile = self._by_symbol.get(sym.upper())
        if profile is None:
            raise CapabilityGap(
                f"company_data:config_seed:{sym}",
                f"no config profile for {sym} — add companies[] entry (MI.5 hermetic path)",
            )
        return profile


class OfficialFilingAdapter:
    """Skeleton for SEC / NSE / BSE / exchange filings APIs."""

    def __init__(
        self,
        name: str,
        *,
        api_key_env: str,
        enabled: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self._api_key_env = api_key_env
        self._enabled = enabled
        self._logger = logger or logging.getLogger(f"atlas.trading.company.{name}")

    def fetch_company(self, symbol: str, **kwargs: Any) -> CompanyProfile:
        if not self._enabled:
            raise CapabilityGap(
                f"company_data:{self.name}",
                f"{self.name} provider disabled in config",
            )
        key = (os.environ.get(self._api_key_env) or "").strip()
        if not key:
            raise CapabilityGap(
                f"company_data:{self.name}",
                f"set {self._api_key_env} for ToS-compliant {self.name} filings (MI4/MI5)",
            )
        raise CapabilityGap(
            f"company_data:{self.name}",
            f"{self.name} adapter skeleton — key present; live filing client awaits exchange ToS path",
        )


class CompanyDataService:
    """Facade over company/filing adapters (Market Program)."""

    name = "company_data"
    VERSION = "mi.5"

    def __init__(
        self,
        *,
        default_provider: str = "config_seed",
        logger: logging.Logger | None = None,
    ) -> None:
        self._default = (default_provider or "config_seed").strip().lower()
        self._logger = logger or logging.getLogger("atlas.trading.company")
        self._adapters: dict[str, Any] = {
            "config_seed": ConfigSeedCompanyAdapter(logger=self._logger),
            "sec": OfficialFilingAdapter(
                "sec", api_key_env="ATLAS_SEC_API_KEY", logger=self._logger
            ),
            "nse": OfficialFilingAdapter(
                "nse_filings", api_key_env="ATLAS_NSE_API_KEY", logger=self._logger
            ),
            "bse": OfficialFilingAdapter(
                "bse_filings", api_key_env="ATLAS_BSE_API_KEY", logger=self._logger
            ),
        }

    def list_providers(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "default": name == self._default}
            for name in sorted(self._adapters)
        ]

    def load_config_profiles(
        self, profiles: list[dict[str, Any]] | dict[str, dict[str, Any]]
    ) -> None:
        seed = self._adapters.get("config_seed")
        if isinstance(seed, ConfigSeedCompanyAdapter):
            seed.load(profiles)

    def fetch(
        self,
        symbol: str,
        *,
        provider: str | None = None,
        companies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Fetch one company profile; never scrapes; never fabricates on gap (P15)."""
        if companies:
            self.load_config_profiles(companies)
        prov = (provider or self._default or "config_seed").strip().lower()
        adapter = self._adapters.get(prov)
        if adapter is None:
            raise CapabilityGap(
                f"company_data:{prov}",
                f"unknown company provider '{prov}' — known: {sorted(self._adapters)}",
            )
        profile = adapter.fetch_company(symbol)
        return {
            "provider": prov,
            "profile": profile.as_dict(),
            "knowledge_text": profile.knowledge_text(),
            "version": self.VERSION,
        }
