"""Time-scale projection and the holdover bound, checked against independent arithmetic.

Epoch facts are checked against Python's `datetime`, not against constants in
the module under test: GPS time began 1980-01-06, and GPS week 1024 — Galileo
week 0 — began on 1999-08-22 (the first GPS week rollover).
"""
from datetime import datetime, timezone

import pytest

from tw.holdover import drift_bound_ps, resolve_edges
from tw.timescale import (PS, day_origin, gnss_to_abs_utc_ps, gnss_week_ps,
                          tp_sub_ms_to_ps)


def _unix(*a):
    return int(datetime(*a, tzinfo=timezone.utc).timestamp())


def test_gps_epoch_and_galileo_week_zero():
    # With zero leap seconds the projection is plain elapsed GNSS time.
    assert gnss_to_abs_utc_ps(0, 0) == _unix(1980, 1, 6) * PS
    assert gnss_to_abs_utc_ps(gnss_week_ps("GAL", 0), 0) == _unix(1999, 8, 22) * PS
    assert gnss_week_ps("GAL", 1362) == gnss_week_ps("GPS", 2386)


def test_leap_seconds_move_utc_back():
    t = gnss_week_ps("GPS", 2386) + 345_600 * PS
    naive = _unix(1980, 1, 6) + 2386 * 604_800 + 345_600
    assert gnss_to_abs_utc_ps(t, 18) == (naive - 18) * PS


def test_tp_sub_ms_rounding_is_reported_not_dropped():
    assert tp_sub_ms_to_ps(1 << 31) == (500_000_000, 0)     # exactly 0.5 ms
    ps, residue = tp_sub_ms_to_ps(1)                        # 2^-32 ms ~ 0.23 ps
    assert (ps, residue) == (0, 1)


def test_day_origin():
    assert day_origin((_unix(2026, 9, 30) + 45_000) * PS + 7) == _unix(2026, 9, 30)


def test_drift_bound_hand_computed():
    # y = 1e-11 (10_000 ppq) over 1000 s -> 1e-8 s = 10 ns = 10_000 ps; aging 5e-12/day
    # (5_000 ppq/day) -> 5e-12 * 1000^2 / (2 * 86400) s = 28.935... ps -> 29 ps.
    assert drift_bound_ps(1000, 10_000, 0) == 10_000
    assert drift_bound_ps(1000, 0, 5_000) == 29
    assert drift_bound_ps(0, 10_000, 5_000) == 0
    with pytest.raises(ValueError):
        drift_bound_ps(-1, 0, 0)


def test_edge_count_resolves_through_counter_wrap():
    # 65530 -> 4 is 10 edges after wrapping the 16-bit counter.
    assert resolve_edges(65530, 4, 10_000_050_000, 50) == 10
    # Beyond one wrap: 65536 + 10 edges, host clock says ~65546 s is too long to
    # count at 50 ppm (tolerance ~3.4 s), so it is refused rather than guessed.
    with pytest.raises(ValueError, match="too long"):
        resolve_edges(65530, 4, 65_546 * 1_000_000_000, 50)


def test_edge_count_disagreeing_with_host_time_is_refused():
    with pytest.raises(ValueError, match="inconsistent"):
        resolve_edges(0, 10, 12_000_000_000, 10)   # counter says 10, host says 12


def test_non_advancing_monotonic_clock_is_refused():
    with pytest.raises(ValueError):
        resolve_edges(0, 1, 0, 10)
