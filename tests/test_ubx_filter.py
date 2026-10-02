"""The capture filter keeps evidence frames byte-exact and drops anything stating a place."""
import random

from tw.ubx import NAV_STATUS, RXM_SFRBX, TIM_TM2, encode
from tw.ubx_filter import CaptureFilter

GGA = b"$GNGGA,101530.00,4807.03812,N,01131.00012,E,1,08,0.9,545.4,M,46.9,M,,*47\r\n"
RMC = b"$GNRMC,101530.00,A,4807.03812,N,01131.00012,E,0.0,,021026,,,A*6B\r\n"
NAV_PVT = encode(0x01, 0x07, bytes(92))          # a UBX position message: never allowed
SFRBX = encode(*RXM_SFRBX, bytes([2, 11, 1, 0, 8, 0, 2, 0]) + bytes(range(32)))
TM2 = encode(*TIM_TM2, bytes(28))
STATUS = encode(*NAV_STATUS, bytes(16))


def _feed_in_pieces(data, seed=3):
    rng, f, out, i = random.Random(seed), CaptureFilter(), b"", 0
    while i < len(data):
        n = rng.randrange(1, 40)
        out += f.feed(data[i:i + n])
        i += n
    return out, f.stats()


def test_position_never_survives_and_evidence_is_byte_exact():
    stream = GGA + SFRBX + RMC + NAV_PVT + TM2 + b"\xb5" + GGA + STATUS + SFRBX
    kept, stats = _feed_in_pieces(stream)
    assert kept == SFRBX + TM2 + STATUS + SFRBX
    for leak in (b"4807", b"01131", b"GGA", b"RMC", b"$"):
        assert leak not in kept
    assert stats["dropped"]["01-07"] == 1                  # the UBX position message
    assert stats["dropped"]["non_ubx_bytes"] >= len(GGA) * 2 + len(RMC)
    assert stats["kept"] == {"01-03": 1, "02-13": 2, "0D-03": 1}


def test_a_frame_split_across_reads_is_released_whole_by_the_read_that_completes_it():
    f = CaptureFilter()
    assert f.feed(SFRBX[:5]) == b""
    assert f.feed(SFRBX[5:-1]) == b""
    assert f.feed(SFRBX[-1:]) == SFRBX


def test_a_corrupt_frame_and_a_false_sync_are_dropped_not_kept():
    bad = bytearray(TM2)
    bad[-1] ^= 0xFF                                         # checksum broken
    false_sync = b"\xb5\x62\x02\x13\xff\xff"                # absurd length
    kept, _ = _feed_in_pieces(bytes(bad) + false_sync + STATUS)
    assert kept == STATUS
