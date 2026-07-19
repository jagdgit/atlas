"""Hermetic tests for CoverageService rollups + targeted re-extraction (Phase C · §C.4)."""

from __future__ import annotations

from typing import Any

from atlas.knowledge.coverage import CoverageService


class FakeCoverageRepo:
    def __init__(self, summary_rows: list[dict[str, Any]], stale_rows: list[dict[str, Any]] | None = None):
        self._summary = summary_rows
        self._stale = stale_rows or []
        self.marked: list[str] = []

    def summary(self, *, by: str = "domain") -> list[dict[str, Any]]:
        return self._summary

    def stale(self, reader, *, reader_version=None, extractor_version=None, limit=500):
        return self._stale

    def mark_pending(self, coverage_id):
        self.marked.append(str(coverage_id))
        return {"id": coverage_id, "status": "pending"}


class FakeFindingRepo:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def understanding_by_domain(self) -> list[dict[str, Any]]:
        return self._rows


def _cov(group, total, done, failed=0, unsupported=0, empty=0, pending=0, findings=0):
    return {"group_key": group, "total": total, "done": done, "failed": failed,
            "unsupported": unsupported, "empty": empty, "pending": pending, "findings": findings}


def _und(domain, maturity, status, n, avg_score=0.5):
    return {"domain": domain, "maturity": maturity, "status": status, "n": n, "avg_score": avg_score}


def test_coverage_pct_is_done_over_total():
    cov = FakeCoverageRepo([_cov("code", total=10, done=8, failed=2, findings=40)])
    svc = CoverageService(cov, FakeFindingRepo([]))
    summary = svc.summary()
    code = next(d for d in summary["domains"] if d["domain"] == "code")
    assert code["coverage_pct"] == 80.0
    assert code["coverage"]["failed"] == 2


def test_understanding_weights_maturity_and_discounts_contested():
    # 1 established/active (1.0), 1 candidate/contested (0.33 * 0.5 = 0.165) → mean weight.
    findings = FakeFindingRepo([
        _und("code", "established", "active", 1),
        _und("code", "candidate", "contested", 1),
    ])
    svc = CoverageService(FakeCoverageRepo([]), findings)
    code = next(d for d in svc.summary()["domains"] if d["domain"] == "code")
    # (1.0 + 0.165) / 2 * 100 = 58.25 → 58.2 (banker-free round to 1dp)
    assert code["understanding_pct"] == 58.2
    assert code["understanding"]["contested"] == 1
    assert code["understanding"]["established"] == 1


def test_coverage_and_understanding_are_independent():
    # Read everything (100% coverage) but only verified maturity (< 100% understanding).
    cov = FakeCoverageRepo([_cov("python", total=5, done=5, findings=20)])
    findings = FakeFindingRepo([_und("python", "verified", "active", 4)])
    svc = CoverageService(cov, findings)
    py = next(d for d in svc.summary()["domains"] if d["domain"] == "python")
    assert py["coverage_pct"] == 100.0
    assert py["understanding_pct"] == 66.0  # verified weight 0.66


def test_domains_union_covers_read_but_no_findings_and_vice_versa():
    cov = FakeCoverageRepo([_cov("matlab", total=5, done=1)])  # read a little, no findings
    findings = FakeFindingRepo([_und("code", "established", "active", 2)])  # findings, no coverage row
    svc = CoverageService(cov, findings)
    domains = {d["domain"] for d in svc.summary()["domains"]}
    assert {"matlab", "code"} <= domains
    matlab = next(d for d in svc.summary()["domains"] if d["domain"] == "matlab")
    assert matlab["coverage_pct"] == 20.0
    assert matlab["understanding_pct"] == 0.0


def test_mark_stale_for_reextraction_flags_only_stale_rows():
    stale = [{"id": "cov-1"}, {"id": "cov-2"}]
    cov = FakeCoverageRepo([], stale_rows=stale)
    svc = CoverageService(cov, FakeFindingRepo([]))
    flagged = svc.mark_stale_for_reextraction("code", reader_version="2.0.0")
    assert cov.marked == ["cov-1", "cov-2"]
    assert len(flagged) == 2
