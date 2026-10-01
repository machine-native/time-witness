"""The galmon transport reader: framing, the minimal protobuf decoder, page rebuild.

Messages here are encoded by this test from official-vector pages, so a round trip
proves the reader and the rebuild agree with galmon's field layout (navmon.proto,
ubx.cc at commit 9bd22436) as this repository reads it. The live stream was checked
the same way when the reader was written: every Galileo E1-B page rebuilt from it
passed CRC-24Q.
"""
from pathlib import Path

import pytest

from tw.galmon_feed import (MAGIC, frames, page_from_message, pages_from_stream,
                            protobuf_fields)
from tw.osnma import Page, WEEK_S


def _varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _f(num, v):
    if isinstance(v, int):
        return _varint(num << 3) + _varint(v)
    return _varint(num << 3 | 2) + _varint(len(v)) + v


def _bytes(bits):
    bits = bits + "0" * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


def message_for(p: Page, *, sigid=1, gnss=2, crc_flip=False):
    word = p.even[2:114] + p.odd[2:18]
    crc = p.odd[82:106]
    if crc_flip:
        crc = ("1" if crc[0] == "0" else "0") + crc[1:]
    gi = (_f(1, p.start // WEEK_S) + _f(2, p.start % WEEK_S) + _f(3, gnss) + _f(4, p.sv)
          + _f(5, _bytes(word)) + _f(6, sigid) + _f(7, _bytes(p.odd[18:58]))
          + _f(8, _bytes(p.odd[106:114])) + _f(9, _bytes(p.odd[58:82]))
          + _f(10, _bytes(p.odd[80:82])) + _f(11, _bytes(crc)) + _f(12, int(p.odd[106:114], 2)))
    return _f(1, 7) + _f(2, 3) + _f(3, 1) + _f(4, 0) + _f(5, gi)


def framed(msgs):
    return b"".join(MAGIC + len(m).to_bytes(2, "big") + m for m in msgs)


@pytest.fixture(scope="module")
def official_pages():
    from pathlib import Path
    import csv, glob
    from tw.osnma import hex_to_bits, page_time_from_word5, pages_from_bits
    tv = Path(__file__).resolve().parents[1] / "vectors" / "osnma-official" / "Test_vectors"
    if not tv.is_dir():
        pytest.skip("official OSNMA test vectors not present; run scripts/fetch_osnma_vectors.py")
    (f,) = glob.glob(str(tv / "osnma_test_vectors" / "configuration_2" / "*.csv"))
    with open(f, newline="") as fh:
        row = next(csv.DictReader(fh))
    bits = hex_to_bits(row["NavBitsHEX"], int(row["NumNavBits"]))
    start = page_time_from_word5(pages_from_bits(int(row["SVID"]), bits, 0))
    return pages_from_bits(int(row["SVID"]), bits, start)[:60]


def test_protobuf_decoder_reads_varints_and_bytes():
    f = protobuf_fields(_f(1, 300) + _f(5, b"ab") + _f(1, 2))
    assert f == {1: [300, 2], 5: [b"ab"]}


def test_framing_resynchronises_after_garbage():
    m1, m2 = b"\x08\x01", b"\x08\x02"
    stream = b"noise" + framed([m1]) + b"xx" + framed([m2]) + MAGIC + b"\x00\x09ab"
    assert list(frames(stream)) == [m1, m2]


def test_page_round_trip_through_galmon_fields(official_pages):
    for p in official_pages:
        q = page_from_message(message_for(p))
        assert q == Page(p.sv, p.start, p.even[:114] + "000000", p.odd[:114] + "000000")
        assert q.crc_ok


def test_only_galileo_e1b_is_taken(official_pages):
    p = official_pages[0]
    assert page_from_message(message_for(p, sigid=5)) is None      # E5b I/NAV
    assert page_from_message(message_for(p, gnss=0)) is None       # not Galileo


def test_corrupt_duplicate_and_conflicting_copies(official_pages):
    p, q = official_pages[0], official_pages[1]
    other = Page(p.sv, p.start, q.even, q.odd)                     # different valid page, same slot
    msgs = [message_for(p), message_for(p), message_for(q, crc_flip=True), message_for(q),
            message_for(other)]
    pages, st = pages_from_stream(framed(msgs))
    assert st["crc_rejected"] == 1 and st["duplicates"] == 1 and st["conflicts"] == 1
    # p's slot is in conflict, so it is dropped rather than one version chosen
    assert [(x.sv, x.start) for x in pages] == [(q.sv, q.start)]


# ---- the first real-sky capture, 2026-10-01 ------------------------------------------
LIVE_A = Path(__file__).resolve().parents[1] / "live" / "galmon-2026-10-01-a"


def test_real_sky_capture_reproduces_its_recorded_bound():
    """Live Galileo E1-B relayed by galmon, 09:04-09:20 UTC 2026-10-01. Every page must
    pass CRC; the signed DSM-KROOT, every key and the bound must reproduce exactly
    what galileo-bound.json recorded. Needs the authenticated tree (registered GSC
    access, kept locally) for the public key; reports SKIPPED without it."""
    import json
    sys_path_scripts = Path(__file__).resolve().parents[1] / "scripts"
    import sys
    sys.path.insert(0, str(sys_path_scripts))
    mt = Path(__file__).resolve().parents[1] / "trust" / "merkle-tree"
    if not any(mt.glob("*.xml")):
        pytest.skip("authenticated Merkle tree not present locally")
    import galileo_bound
    from tw import osnma
    rec = json.loads((LIVE_A / "galileo-bound.json").read_text(encoding="utf-8"))
    auth, _ = galileo_bound.authenticated_tree()
    pages, stats = pages_from_stream((LIVE_A / "e1b-frames.bert").read_bytes())
    assert stats == rec["pages"] and stats["crc_rejected"] == 0
    rep = osnma.verify_stream(pages, auth["root"], extra_keys=auth["keys"])
    assert all(k["signature_ok"] for k in rep.kroots) and rep.key_failures == []
    assert osnma.galileo_lower_bound(rep) == rec["bound"]
    assert not rep.tags.get("TAG_MISMATCH") and not rep.tags.get("MACSEQ_MISMATCH")
