"""Galileo E1-B I/NAV pages out of u-blox UBX-RXM-SFRBX, with their GST.

Mapping. For Galileo I/NAV, RXM-SFRBX carries eight 32-bit words, each a
little-endian U4. Read as numbers and written MSB first, words 0-3 hold the even
page part in their first 120 bits and words 4-7 the odd part in theirs. This is how
galmon (github.com/berthubert/galmon, ubx.cc getInavFromSFRBXMsg, commit 9bd22436,
file sha256 61a69029...) extracts the page, the OSNMA field ("reserved1", odd bits
18-57) and the CRC it checks — an independent implementation used with u-blox
receivers on a public monitoring network. It is not yet pinned against bytes from a
receiver of our own; every page is CRC-checked before use, so a wrong mapping
produces rejected pages, not wrong ones.

Signal. OSNMA is carried on E1-B only. u-blox signal identifiers give Galileo E1-B
as gnssId 2, sigId 1 (interface description, "Signal Identifiers"); E5b I/NAV
(sigId 5) has a different page layout and is ignored here. u-blox 8 receivers track
only E1 for Galileo, and the M8 specification (UBX-13003221 R28) prints no signal
identifier table, so what an M8 puts in that byte is not documented; galmon treats
every M8 Galileo page that is not F/NAV as I/NAV. sigId 0 is therefore accepted as
E1-B as well. Pin it on the first M8 capture; the page CRC rejects anything else.

Time. SFRBX carries no timestamp. Each page's start time is taken from the
navigation data itself — word type 5 carries WN and TOW, and its TOW is the start of
the page carrying it (established on the official OSNMA vectors) — and the other
pages of the same satellite are placed 2 s apart by the host monotonic time at which
each frame arrived. Nothing here needs to be trusted: a page placed at the wrong
time makes its TESLA key fail verification, because every chain step hashes the
sub-frame time in. Errors fail closed.
"""
from __future__ import annotations

import bisect
import json
import struct

from . import ubx
from .osnma import Page, gst_seconds, u

GNSS_GALILEO = 2
SIG_E1B = 1
SIG_ACCEPTED = (SIG_E1B, 0)          # 0: what an M8 may report; see the module docstring
PAGE_NS = 2_000_000_000


def sfrbx_page(frame: ubx.Frame) -> tuple[int, str, str] | None:
    """(svid, even part, odd part) for a Galileo E1-B I/NAV SFRBX frame, else None."""
    d = ubx.rxm_sfrbx(frame)
    if d["gnss_id"] != GNSS_GALILEO or d["sig_id"] not in SIG_ACCEPTED or len(d["words"]) != 8:
        return None
    bits = "".join(format(w, "032b") for w in d["words"])
    return d["sv_id"], bits[0:120], bits[128:248]


def page_sfrbx(sv: int, even: str, odd: str, *, chn: int = 0, version: int = 2) -> bytes:
    """The inverse, for tests and synthetic captures: an SFRBX frame carrying a page."""
    bits = even + "0" * 8 + odd + "0" * 8
    words = [int(bits[32 * i:32 * (i + 1)], 2) for i in range(8)]
    payload = bytes([GNSS_GALILEO, sv, SIG_E1B, 0, 8, chn, version, 0]) + struct.pack("<8I", *words)
    return ubx.encode(*ubx.RXM_SFRBX, payload)


def timed_pages(captures: list[tuple[int, bytes]]) -> tuple[list[Page], dict]:
    """Pages with GST start times from (host monotonic ns, raw SFRBX frame) pairs."""
    items, dropped = [], {"not_e1b": 0}
    for mono, raw in captures:
        p = sfrbx_page(ubx.parse_frame(raw))
        if p is None:
            dropped["not_e1b"] += 1
            continue
        items.append((mono, *p))
    pages, more = place_pages(items)
    dropped.update(more)
    return pages, dropped


def place_pages(items: list[tuple[int, int, str, str]]) -> tuple[list[Page], dict]:
    """Give (arrival monotonic ns, svid, even, odd) pages their GST start times.

    Each satellite's own word-5 pages fix its time; the others are placed 2 s apart
    by arrival time. Satellites with no word 5 are dropped, and so is any page whose
    arrival sits more than 0.5 s off a page boundary: a guess would only produce a
    page that fails later, so it is not made.
    """
    by_sv: dict[int, list[tuple[int, str, str]]] = {}
    for mono, sv, even, odd in items:
        by_sv.setdefault(sv, []).append((mono, even, odd))
    dropped = {"no_time_anchor": 0, "ambiguous_placement": 0}
    out: list[Page] = []
    for sv, its in by_sv.items():
        its.sort()
        anchors = []
        for mono, even, odd in its:
            pg = Page(sv, 0, even, odd)
            if pg.crc_ok and pg.nominal and u(pg.word[:6]) == 5:
                anchors.append((mono, gst_seconds(u(pg.word[73:85]), u(pg.word[85:105]))))
        if not anchors:
            dropped["no_time_anchor"] += len(its)
            continue
        for mono, even, odd in its:
            a_mono, a_start = min(anchors, key=lambda a: abs(a[0] - mono))
            steps, rem = divmod(mono - a_mono + PAGE_NS // 2, PAGE_NS)
            if abs(rem - PAGE_NS // 2) > PAGE_NS // 4:
                dropped["ambiguous_placement"] += 1
                continue
            out.append(Page(sv, a_start + 2 * steps, even, odd))
    return out, dropped


def captures_from_ubx(raw: bytes, index_lines: list[str]) -> list[tuple[int, bytes]]:
    """(arrival monotonic ns, raw SFRBX frame) pairs from scripts/capture_ubx.py output.

    The index records the host monotonic time of each serial read and the stream
    offset it covered. A frame's arrival is the read that delivered its last byte:
    that is when the whole frame existed on the host. Frames whose end is not covered
    by any recorded read are dropped rather than given a guessed time. Only RXM-SFRBX
    frames are returned; a capture also carries time marks and status, read elsewhere."""
    reads = []
    for line in index_lines:
        if line.strip():
            r = json.loads(line)
            reads.append((r["offset"] + r["length"], r["mono_ns"]))
    reads.sort()
    ends = [e for e, _ in reads]
    out = []
    for off, f in ubx.split_stream(raw):
        if f.key != ubx.RXM_SFRBX:
            continue
        last = off + 8 + len(f.payload)                 # one past the frame's last byte
        i = bisect.bisect_left(ends, last)
        if i < len(reads):
            out.append((reads[i][1], f.raw()))
    return out
