"""The oscillator measurement recovers what a synthetic oscillator was built with.

Frames are made field by field from the TIM-TM2 layout tw/ubx.py decodes (itself
pinned against pyubx2), so these tests check the analysis, not the decoder.
"""
import random
import struct

import pytest

from tw import oscillator
from tw.ubx import TIM_TM2, encode

RISING_GNSS_VALID = 0x80 | 0x40 | (1 << 3) | 0x02 | 0x01   # new rising, valid, GNSS base


def tm2(count, t_ns, *, flags=RISING_GNSS_VALID, acc=20):
    wn, rest = divmod(t_ns, oscillator.NS_PER_WEEK)
    tow_ms, sub = divmod(rest, 1_000_000)
    return encode(*TIM_TM2, struct.pack("<BBHHHIIIII", 0, flags, count, wn, wn, tow_ms, sub,
                                        tow_ms, sub, acc))


def synthetic(n=300, y=12.5e-6, sigma_ns=20.0, count0=65_500, drop=(), seed=7):
    rng = random.Random(seed)
    t0 = 1414 * oscillator.NS_PER_WEEK + 400_000 * 1_000_000_000 + 123_456_789
    out = b""
    for i in range(n):
        if i in drop:
            continue
        t = t0 + i * 1_000_000_000 + round(i * 1e9 * y + rng.gauss(0, sigma_ns))
        out += tm2((count0 + i) & 0xFFFF, t)
    return out


def test_frequency_offset_and_jitter_are_recovered():
    edges, dropped = oscillator.rising_edges(synthetic())
    r = oscillator.analyse(edges)
    assert r["edges"] == 300 and r["missing_edges"] == 0 and r["span_s"] == 299
    assert abs(r["frequency_offset_ppm"] - 12.5) < 0.001
    assert 15 < r["residual_rms_ns"] < 25                    # sigma 20 ns
    adev1 = r["allan_deviation"][1]                          # white phase: ~sqrt(3)*sigma
    assert 0.8 * 34.6e-9 < adev1 < 1.2 * 34.6e-9
    assert r["acc_est_ns_median"] == 20


def test_the_16_bit_counter_wraps_and_lost_messages_show_as_gaps():
    edges, _ = oscillator.rising_edges(synthetic(drop=(50, 51)))
    r = oscillator.analyse(edges)
    assert r["missing_edges"] == 2 and r["span_s"] == 299     # counter wrapped at 65536
    assert abs(r["frequency_offset_ppm"] - 12.5) < 0.001
    assert isinstance(r["allan_deviation"], str)              # not faked across a gap


def test_marks_without_a_valid_gnss_time_are_not_used():
    t = 1414 * oscillator.NS_PER_WEEK
    data = (tm2(1, t, flags=RISING_GNSS_VALID & ~0x40)          # time not valid
            + tm2(2, t, flags=RISING_GNSS_VALID & ~(3 << 3))    # receiver time base
            + tm2(3, t, flags=RISING_GNSS_VALID & ~0x80)        # no new rising edge
            + tm2(4, t) + tm2(4, t))                            # same edge reported twice
    edges, dropped = oscillator.rising_edges(data)
    assert len(edges) == 1
    assert dropped == {"not_new_rising": 1, "time_invalid": 1, "not_gnss_base": 1, "repeat": 1}


def test_too_few_edges_is_an_error_not_a_number():
    edges, _ = oscillator.rising_edges(synthetic(n=2))
    with pytest.raises(ValueError):
        oscillator.analyse(edges)
