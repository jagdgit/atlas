"""Small-sample statistics for the cognitive loop. Pure Python, no SciPy.

Thirty-odd episodes cannot carry a fixed hit-rate gap: a 0.5 gap almost never
appears, and a 0.2 gap is often noise. An exact test answers the question the
gap was standing in for — "could chance alone produce a split this uneven?" —
and false-discovery control keeps that answer honest when many splits are
scanned at once.
"""

from __future__ import annotations

from math import comb


def _hypergeom_pmf(k: int, n_total: int, k_total: int, n_draw: int) -> float:
    return comb(k_total, k) * comb(n_total - k_total, n_draw - k) / comb(n_total, n_draw)


def fisher_exact(
    a_hits: int,
    a_n: int,
    b_hits: int,
    b_n: int,
    *,
    alternative: str = "two-sided",
) -> float:
    """P-value for the 2x2 table [[a_hits, a_n-a_hits], [b_hits, b_n-b_hits]].

    ``alternative="greater"`` tests whether group A's hit rate exceeds group B's.
    """
    if min(a_n, b_n) <= 0 or not (0 <= a_hits <= a_n and 0 <= b_hits <= b_n):
        return 1.0
    n_total = a_n + b_n
    k_total = a_hits + b_hits
    lo = max(0, a_n - (n_total - k_total))
    hi = min(a_n, k_total)
    pmf = {k: _hypergeom_pmf(k, n_total, k_total, a_n) for k in range(lo, hi + 1)}
    if alternative == "greater":
        p = sum(v for k, v in pmf.items() if k >= a_hits)
    elif alternative == "less":
        p = sum(v for k, v in pmf.items() if k <= a_hits)
    else:
        observed = pmf[a_hits]
        p = sum(v for v in pmf.values() if v <= observed * (1 + 1e-9))
    return float(min(1.0, max(0.0, p)))


def benjamini_hochberg(pvalues: list[float], q: float) -> list[bool]:
    """Which of ``pvalues`` survive false-discovery-rate control at level ``q``."""
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    cutoff = -1
    for rank, idx in enumerate(order, start=1):
        if pvalues[idx] <= q * rank / m:
            cutoff = rank
    passed = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= cutoff:
            passed[idx] = True
    return passed
