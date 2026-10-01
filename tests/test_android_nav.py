"""Android GnssLogger logs: format, page packing, placement.

Logs here are written by this test in GnssLogger's format (FileLogger.java at
commit 93c63870) from official-vector pages, with arrival times like a phone's.
They show the reader agrees with that format as read here; no phone has produced a
log for this repository yet.
"""
import pytest

from tw.android_nav import NAV_BYTES, TYPE_GAL_I, page_bits, pages_from_log, read_log


def _signed(bits):
    return [int(bits[i:i + 8], 2) - 256 if int(bits[i:i + 8], 2) > 127 else int(bits[i:i + 8], 2)
            for i in range(0, len(bits), 8)]


def nav_line(p, *, typ=TYPE_GAL_I):
    bits = p.even[:114] + p.odd[:114] + "0000"
    return "Nav,%d,%d,1,0,%d,%s" % (p.sv, typ, int(p.word[:6], 2),
                                   ",".join(map(str, _signed(bits))))


@pytest.fixture(scope="module")
def official_pages():
    from pathlib import Path
    import csv, glob
    from tw.osnma import hex_to_bits, page_time_from_word5, pages_from_bits
    tv = Path(__file__).resolve().parents[1] / "vectors" / "osnma-official" / "Test_vectors"
    if not tv.is_dir():
        pytest.skip("official OSNMA test vectors not present; run scripts/fetch_osnma_vectors.py")
    (f,) = glob.glob(str(tv / "osnma_test_vectors" / "configuration_2" / "*.csv"))
    out = []
    with open(f, newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            if i == 3:
                break
            bits = hex_to_bits(row["NavBitsHEX"], int(row["NumNavBits"]))
            start = page_time_from_word5(pages_from_bits(int(row["SVID"]), bits, 0))
            out += pages_from_bits(int(row["SVID"]), bits, start)[:45]
    return out


def test_29_bytes_hold_the_two_114_bit_parts():
    bits = "1" * 114 + "0" * 114 + "0000"
    even, odd = page_bits(_signed(bits))
    assert even == "1" * 114 + "0" * 6 and odd == "0" * 120
    assert page_bits([0] * (NAV_BYTES - 1)) is None


def test_a_phone_like_log_yields_crc_valid_pages_at_their_true_times(official_pages):
    t0 = official_pages[0].start
    lines = ["# Nav,Svid,Type,Status,MessageId,Sub-messageId,Data(Bytes)"]
    for p in sorted(official_pages, key=lambda p: (p.start, p.sv)):
        # a Raw epoch per second; the page's message arrives within it, ~0.3 s late
        ms = 5_000_000 + (p.start - t0 + 2) * 1000 + 300
        lines.append("Raw,%d,0,18,0,0" % ms)
        lines.append(nav_line(p))
    pages, stats = pages_from_log("\n".join(lines))
    assert stats["galileo_inav"] == len(official_pages) and stats["crc_ok"] == len(pages)
    assert {(p.sv, p.start) for p in pages} == {(p.sv, p.start) for p in official_pages}


def test_other_message_types_and_lines_before_any_raw_are_not_used(official_pages):
    p = official_pages[0]
    items, stats = read_log("\n".join([nav_line(p), "Raw,1000,0", nav_line(p, typ=0x0101)]))
    assert stats["before_first_raw"] == 1 and stats["galileo_inav"] == 1 and items == []


# ---- GNSS-SDR NavDataMonitor (the RTL-SDR route) ------------------------------------
def _pb(num, v):
    from test_galmon_feed import _f
    return _f(num, v)


def gnsssdr_datagram(prn, tow_ms, bits, system="E", signal="1B"):
    return (_pb(1, system.encode()) + _pb(2, signal.encode()) + _pb(3, prn)
            + _pb(4, tow_ms) + _pb(5, bits.encode()))


def test_gnsssdr_half_pages_pair_into_crc_valid_pages(official_pages):
    from tw.gnsssdr_nav import pages_from_datagrams
    dg = []
    for p in sorted(official_pages, key=lambda p: (p.start, p.sv)):
        tow0 = (p.start % 604800) * 1000
        dg.append(gnsssdr_datagram(p.sv, tow0 + 1000, p.even))   # even part done after 1 s
        dg.append(gnsssdr_datagram(p.sv, tow0 + 2000, p.odd))
    dg.append(gnsssdr_datagram(5, 1000, "0" * 120, signal="5X"))  # E5a: ignored
    pages, st = pages_from_datagrams(dg)
    assert st["crc_ok"] == len(pages) == len(official_pages) and st["unpaired"] == 0
    assert {(p.sv, p.start) for p in pages} == {(p.sv, p.start) for p in official_pages}


def test_gnsssdr_an_odd_part_without_its_even_part_is_not_a_page(official_pages):
    from tw.gnsssdr_nav import pages_from_datagrams
    p = official_pages[0]
    pages, st = pages_from_datagrams([gnsssdr_datagram(p.sv, 5000, p.odd)])
    assert pages == [] and st["unpaired"] == 1
