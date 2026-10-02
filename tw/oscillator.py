"""Measure a free-running oscillator from the receiver's time marks of its edges.

In OSC mode the oscillator makes an edge each second and the receiver stamps it
(UBX-TIM-TM2) against GNSS time. Read as a sequence, those stamps measure the
oscillator: if it ran perfectly at its nominal rate, edge n would land exactly n
seconds after edge 0. The difference -- the phase -- is what this module reports:

    frequency offset y   slope of phase against time (dimensionless; 1e-6 = 1 ppm)
    residual             what is left after removing that slope (jitter of the edge
                         plus the receiver's time-mark error)
    Allan deviation      the usual stability figure, at averaging times 1, 2, 4 ... s

Nothing here is a claim about time; it is a measurement of the oscillator against
the receiver, and the receiver's own estimate of each mark's accuracy (accEst) is
reported beside it so the two can be compared. Edges are numbered by the receiver's
edge counter, not by arrival order, so a missed time-mark message shows up as a gap
instead of silently stretching a second.

Integer nanoseconds are kept until the subtraction of the first edge; only the
differences, a few hundred seconds' worth of nanoseconds, become floating point.
"""
from __future__ import annotations

import math

from . import ubx

NS_PER_WEEK = 604_800 * 1_000_000_000


def rising_edges(data: bytes) -> tuple[list[dict], dict]:
    """GNSS-time rising edges from a raw capture, one per counter value.

    Kept only when the receiver flags a new rising edge with a valid GNSS (not
    receiver-local) time base. Repeated reports of the same edge are dropped."""
    out, seen = [], set()
    dropped = {"not_new_rising": 0, "time_invalid": 0, "not_gnss_base": 0, "repeat": 0}
    for _, f in ubx.split_stream(data):
        if f.key != ubx.TIM_TM2:
            continue
        d = ubx.tim_tm2(f)
        if not d["new_rising"]:
            dropped["not_new_rising"] += 1
            continue
        if not d["time_valid"]:
            dropped["time_invalid"] += 1
            continue
        if d["time_base"] != 1:
            dropped["not_gnss_base"] += 1
            continue
        t = d["wn_r"] * NS_PER_WEEK + d["tow_ms_r"] * 1_000_000 + d["tow_sub_ns_r"]
        if (d["count"], t) in seen:
            dropped["repeat"] += 1
            continue
        seen.add((d["count"], t))
        out.append({"count": d["count"], "t_ns": t, "acc_est_ns": d["acc_est_ns"]})
    return out, dropped


def _unwrap(counts: list[int]) -> list[int]:
    """The edge counter is 16 bits; make it monotonic."""
    out, base, prev = [], 0, None
    for c in counts:
        if prev is not None and c < prev:
            base += 1 << 16
        out.append(c + base)
        prev = c
    return out


def allan_deviation(phase_s: list[float], tau0_s: float = 1.0) -> dict[int, float]:
    """Overlapping Allan deviation from evenly spaced phase samples (seconds)."""
    out, n, m = {}, len(phase_s), 1
    while 2 * m < n:
        acc = sum((phase_s[i + 2 * m] - 2 * phase_s[i + m] + phase_s[i]) ** 2
                  for i in range(n - 2 * m))
        out[m] = math.sqrt(acc / (2 * (n - 2 * m) * (m * tau0_s) ** 2))
        m *= 2
    return out


def analyse(edges: list[dict], period_ns: int = 1_000_000_000) -> dict:
    if len(edges) < 3:
        raise ValueError("need at least three edges")
    edges = sorted(edges, key=lambda e: e["t_ns"])
    idx = _unwrap([e["count"] for e in edges])
    n0, t0 = idx[0], edges[0]["t_ns"]
    k = [i - n0 for i in idx]                                   # seconds since edge 0
    phase = [(e["t_ns"] - t0) - ki * period_ns for e, ki in zip(edges, k)]   # int ns
    if any(b <= a for a, b in zip(k, k[1:])):
        raise ValueError("edge counter does not increase with time")
    # least squares phase = a + y * (k * period)
    xs = [ki * period_ns / 1e9 for ki in k]                     # s
    ys = [p * 1e-9 for p in phase]                              # s
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    y = sum((x - mx) * (v - my) for x, v in zip(xs, ys)) / sxx
    a = my - y * mx
    resid = [v - (a + y * x) for x, v in zip(xs, ys)]
    gaps = [b - a_ - 1 for a_, b in zip(k, k[1:]) if b - a_ > 1]
    even = len(gaps) == 0
    acc = sorted(e["acc_est_ns"] for e in edges)
    return {
        "edges": len(edges), "span_s": k[-1], "missing_edges": sum(gaps),
        "frequency_offset": y, "frequency_offset_ppm": y * 1e6,
        "residual_rms_ns": math.sqrt(sum(r * r for r in resid) / len(resid)) * 1e9,
        "residual_max_ns": max(abs(r) for r in resid) * 1e9,
        "acc_est_ns_median": acc[len(acc) // 2],
        "allan_deviation": (allan_deviation(ys, period_ns / 1e9) if even else
                            "not computed: edges missing, samples not evenly spaced"),
        "phase_end_ns": phase[-1],
    }
