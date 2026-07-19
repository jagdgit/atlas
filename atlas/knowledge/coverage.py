"""Coverage & understanding rollups + targeted re-extraction (Phase C · §C.4, A10/CC15).

Two orthogonal metrics per domain:

* **coverage %** — how much was *read* (done / total attempts in ``knowledge.coverage``).
* **understanding %** — how well it is *understood* (a maturity/confidence-weighted rollup of active
  findings, discounted for contested/deprecated). Coverage ≠ comprehension: Atlas may have read
  everything yet hold low confidence ("Python: coverage 98%, understanding 82%").

Also enumerates assets processed by an older reader/extractor version so a version bump re-extracts
*only those* (the delta is attributable to *reader improved* vs *source evolved* — both are stamped).
"""

from __future__ import annotations

from typing import Any

from atlas.knowledge.lifecycle import (
    MATURITY_CANDIDATE,
    MATURITY_ESTABLISHED,
    MATURITY_VERIFIED,
    STATUS_ACTIVE,
    STATUS_CONTESTED,
    STATUS_DEPRECATED,
)

# How much each maturity level contributes to "understanding" (uncorroborated < corroborated < proven).
MATURITY_WEIGHT = {
    MATURITY_ESTABLISHED: 1.0,
    MATURITY_VERIFIED: 0.66,
    MATURITY_CANDIDATE: 0.33,
}
# Validity discount: a contested/deprecated head is understood less than a clean active one.
STATUS_FACTOR = {
    STATUS_ACTIVE: 1.0,
    STATUS_CONTESTED: 0.5,
    STATUS_DEPRECATED: 0.25,
}


def _pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 1)


class CoverageService:
    """Read-only rollups over ``knowledge.coverage`` + ``knowledge.findings`` (name: ``coverage``)."""

    name = "coverage"
    VERSION = "1.0.0"

    def __init__(self, coverage_repo: Any, finding_repo: Any, *, logger: Any = None) -> None:
        self._coverage = coverage_repo
        self._findings = finding_repo
        self._logger = logger

    # --- recording (used by ingest/learn wiring, C.4d) --------------------
    def record(
        self,
        asset_id: str,
        asset_version: int,
        reader: str,
        reader_version: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Passthrough to the coverage store; callers record at extraction completion points."""
        return self._coverage.record(asset_id, asset_version, reader, reader_version, **kwargs)

    # --- rollups ----------------------------------------------------------
    def _coverage_by_domain(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in self._coverage.summary(by="domain"):
            key = row["group_key"]
            total = int(row["total"])
            done = int(row["done"])
            out[key] = {
                "total": total,
                "done": done,
                "failed": int(row["failed"]),
                "unsupported": int(row["unsupported"]),
                "empty": int(row["empty"]),
                "pending": int(row["pending"]),
                "findings": int(row["findings"]),
                "coverage_pct": _pct(done, total),
            }
        return out

    def _understanding_by_domain(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in self._findings.understanding_by_domain():
            domain = row["domain"]
            n = int(row["n"])
            maturity = row["maturity"]
            status = row["status"]
            bucket = out.setdefault(
                domain,
                {
                    "total": 0,
                    MATURITY_ESTABLISHED: 0,
                    MATURITY_VERIFIED: 0,
                    MATURITY_CANDIDATE: 0,
                    "contested": 0,
                    "_weighted": 0.0,
                },
            )
            bucket["total"] += n
            bucket[maturity] = bucket.get(maturity, 0) + n
            if status == STATUS_CONTESTED:
                bucket["contested"] += n
            weight = MATURITY_WEIGHT.get(maturity, 0.33) * STATUS_FACTOR.get(status, 1.0)
            bucket["_weighted"] += weight * n
        for domain, bucket in out.items():
            total = bucket.pop("_weighted")
            bucket["understanding_pct"] = _pct(total, bucket["total"])
        return out

    def summary(self) -> dict[str, Any]:
        """Combined per-domain coverage % + understanding %, plus an overall rollup."""
        cov = self._coverage_by_domain()
        und = self._understanding_by_domain()
        domains = sorted(set(cov) | set(und))

        rows: list[dict[str, Any]] = []
        cov_done = cov_total = 0
        und_weighted = und_total = 0.0
        for domain in domains:
            c = cov.get(domain, {})
            u = und.get(domain, {})
            rows.append(
                {
                    "domain": domain,
                    "coverage_pct": c.get("coverage_pct", 0.0),
                    "understanding_pct": u.get("understanding_pct", 0.0),
                    "coverage": c or None,
                    "understanding": u or None,
                }
            )
            cov_done += int(c.get("done", 0))
            cov_total += int(c.get("total", 0))
            und_weighted += u.get("understanding_pct", 0.0) * int(u.get("total", 0))
            und_total += int(u.get("total", 0))

        return {
            "domains": rows,
            "overall": {
                "coverage_pct": _pct(cov_done, cov_total),
                "understanding_pct": round(und_weighted / und_total, 1) if und_total else 0.0,
                "assets_read": cov_done,
                "assets_total": cov_total,
                "findings": und_total and int(und_total),
            },
        }

    # --- targeted re-extraction (A10) -------------------------------------
    def stale_for_reader(
        self,
        reader: str,
        *,
        reader_version: str | None = None,
        extractor_version: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Coverage rows for ``reader`` processed by an OLDER version — the re-extraction worklist."""
        return self._coverage.stale(
            reader,
            reader_version=reader_version,
            extractor_version=extractor_version,
            limit=limit,
        )

    def mark_stale_for_reextraction(
        self,
        reader: str,
        *,
        reader_version: str | None = None,
        extractor_version: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Flag every stale row for ``reader`` as pending; leaves current-version rows untouched."""
        stale = self.stale_for_reader(
            reader, reader_version=reader_version, extractor_version=extractor_version, limit=limit
        )
        flagged = [self._coverage.mark_pending(row["id"]) for row in stale]
        if self._logger and flagged:
            self._logger.info(
                "coverage.reextraction_marked", extra={"reader": reader, "count": len(flagged)}
            )
        return [f for f in flagged if f]
