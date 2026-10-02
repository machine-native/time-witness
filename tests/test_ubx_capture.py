"""A u-blox capture, end to end, on real Galileo pages.

The pages are the real ones from live/galmon-2026-10-01-a. Only the transport is
synthetic: each page is wrapped as a UBX-RXM-SFRBX frame the way a u-blox 8 sends it
(signal id 0), unrelated frames are mixed in, and the byte stream is cut into serial
reads at arbitrary points -- frames split across reads -- with an index in the form
scripts/capture_ubx.py writes. The u-blox path must then reproduce the bound the galmon
path recorded, exactly.
"""
import json
import random

from tw import osnma
from tw.galmon_feed import pages_from_stream
from tw.ubx import NAV_STATUS, encode, parse_frame
from tw.ubx_inav import captures_from_ubx, page_sfrbx, timed_pages

from test_galmon_feed import LIVE, _root, _sis_public_key

CAPTURE = LIVE / "galmon-2026-10-01-a"


def _ubx_capture(pages, seed=11):
    rng = random.Random(seed)
    frames = []
    for p in pages:
        raw = bytearray(page_sfrbx(p.sv, p.even, p.odd))
        payload = bytearray(parse_frame(bytes(raw)).payload)
        payload[2] = 0                                         # u-blox 8: no E1-B signal id
        arrival = (p.start + 2) * 10**9 + rng.randrange(50, 400) * 10**6   # page complete
        frames.append((arrival, encode(0x02, 0x13, bytes(payload))))
        if rng.random() < 0.3:
            frames.append((arrival + 1, encode(*NAV_STATUS, bytes(16))))
    frames.sort(key=lambda f: f[0])
    # The capture loop reads with a 0.2 s timeout, so each read holds what arrived in
    # at most 0.2 s and is timed when it returns. Model exactly that, and split frames
    # across reads: a read may stop a few bytes short, and the rest of that frame comes
    # with the very next read, which returns within the same timeout.
    stream = b"".join(f for _, f in frames)
    index, pos, end, i = [], 0, 0, 0
    while i < len(frames):
        window = frames[i][0] + 200_000_000
        while i < len(frames) and frames[i][0] < window:
            end += len(frames[i][1])
            i += 1
        cut = end - rng.randrange(0, 20)
        if cut > pos:
            index.append(json.dumps({"mono_ns": window, "offset": pos, "length": cut - pos}))
        if end > cut:
            index.append(json.dumps({"mono_ns": window + 50_000_000, "offset": cut,
                                     "length": end - cut}))
        pos = end
    return stream, index


def test_a_u_blox_capture_reproduces_the_recorded_bound_exactly():
    rec = json.loads((CAPTURE / "galileo-bound.json").read_text(encoding="utf-8"))
    real, _ = pages_from_stream((CAPTURE / "e1b-frames.bert").read_bytes())
    stream, index = _ubx_capture(real)
    pages, dropped = timed_pages(captures_from_ubx(stream, index))
    assert {(p.sv, p.start) for p in pages} == {(p.sv, p.start) for p in real}
    assert dropped["ambiguous_placement"] == 0 and dropped["no_time_anchor"] == 0
    rep = osnma.verify_stream(pages, _root(), extra_keys=[_sis_public_key()])
    assert rep.kroots and all(k["signature_ok"] for k in rep.kroots)
    assert osnma.galileo_lower_bound(rep) == rec["bound"]


def test_a_frame_whose_end_was_never_read_gets_no_time():
    raw = page_sfrbx(11, "0" * 120, "0" * 120)
    index = [json.dumps({"mono_ns": 5, "offset": 0, "length": len(raw) - 1})]
    assert captures_from_ubx(raw, index) == []
    index.append(json.dumps({"mono_ns": 9, "offset": len(raw) - 1, "length": 1}))
    assert captures_from_ubx(raw, index) == [(9, raw)]
