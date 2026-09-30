"""Oscillator holdover: how far a free-running reference can have drifted.

The witness's own tick is its oscillator's 1 PPS edge. Once one edge has been
timed against GNSS (the anchor), every later edge has a time predicted by the
oscillator alone:

    t_n = t_a + n seconds,  |error| <= u_a + |y| * n + (D / 2) * n^2 / 86400

where y is the fractional frequency offset bound and D the aging bound per day.
Both are DECLARED per device, in parts per 10^15, and carried in the evidence so
a verifier re-derives the bound instead of trusting it. A datasheet figure is a
declaration; only a measured Allan deviation from this unit would be evidence,
and nothing here pretends otherwise.

The point is separability (chronology-protocol invariant 5). A spoofer who moves
GNSS time moves it relative to the oscillator, and once the move exceeds the
holdover bound the two sources stop overlapping. A slow pull-off below the drift
rate is NOT detected — see THREAT-MODEL.md. The bound says when a disagreement
is proof of trouble; it does not say that agreement is proof of honesty.
"""
from __future__ import annotations

PS = 1_000_000_000_000
PPQ = 10 ** 15          # parts per quadrillion
DAY_S = 86_400
COUNT_MOD = 1 << 16     # TIM-TM2 edge counter is 16 bits
# Host timestamping jitter allowed when counting edges from monotonic time.
EDGE_JITTER_NS = 100_000_000


def _ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def drift_bound_ps(n_s: int, y_ppq: int, aging_ppq_per_day: int) -> int:
    """Upper bound on accumulated time error after n_s seconds, in ps (rounded up)."""
    if n_s < 0 or y_ppq < 0 or aging_ppq_per_day < 0:
        raise ValueError("holdover inputs must be non-negative")
    linear = _ceil_div(n_s * PS * y_ppq, PPQ)
    quad = _ceil_div(aging_ppq_per_day * n_s * n_s * PS, 2 * DAY_S * PPQ)
    return linear + quad


def resolve_edges(count_anchor: int, count_now: int, mono_elapsed_ns: int,
                  host_ppm: int) -> int:
    """Number of oscillator seconds between two TIM-TM2 edges.

    The receiver's 16-bit counter fixes n modulo 65536; the host's monotonic
    clock picks the one candidate consistent with elapsed wall time. The GNSS
    timestamps are deliberately NOT used — counting edges by GNSS time would let a
    spoofer choose n. If the host clock cannot pin n to a single second, this
    refuses rather than guessing.
    """
    if mono_elapsed_ns <= 0:
        raise ValueError("monotonic time did not advance")
    tol = mono_elapsed_ns * host_ppm // 1_000_000 + EDGE_JITTER_NS
    if tol >= 500_000_000:
        raise ValueError("holdover span too long for the host clock to count edges")
    base = (count_now - count_anchor) % COUNT_MOD
    approx = (mono_elapsed_ns + 500_000_000) // 1_000_000_000
    n = approx - ((approx - base) % COUNT_MOD)
    for cand in (n, n + COUNT_MOD):
        if cand >= 1 and abs(cand * 1_000_000_000 - mono_elapsed_ns) <= tol:
            return cand
    raise ValueError("edge count inconsistent with host monotonic time")
