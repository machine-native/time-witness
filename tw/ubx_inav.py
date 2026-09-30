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
(sigId 5) has a different page layout and is ignored here.

Time. SFRBX carries no timestamp. Each page's start time is taken from the
navigation data itself — word type 5 carries WN and TOW, and its TOW is the start of
the page carrying it (established on the official OSNMA vectors) — and the other
pages of the same satellite are placed 2 s apart by the host monotonic time at which
each frame arrived. Nothing here needs to be trusted: a page placed at the wrong
time makes its TESLA key fail verification, because every chain step hashes the
sub-frame time in. Errors fail closed.
"""
from __future__ import annotations

import struct

from . import ubx
from .osnma import Page, gst_seconds, u

GNSS_GALILEO = 2
SIG_E1B = 1
PAGE_NS = 2_000_000_000


def sfrbx_page(frame: ubx.Frame) -> tuple[int, str, str] | None:
    """(svid, even part, odd part) for a Galileo E1-B I/NAV SFRBX frame, else None."""
    d = ubx.rxm_sfrbx(frame)
    if d["gnss_id"] != GNSS_GALILEO or d["sig_id"] != SIG_E1B or len(d["words"]) != 8:
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
    """Pages with GST start times from (host monotonic ns, raw SFRBX frame) pairs.

    Returns the pages and a summary of what was dropped and why: frames that are not
    Galileo E1-B, satellites with no word type 5 to fix their time, and pages whose
    placement would need more than half a page of rounding.
    """
    by_sv: dict[int, list[tuple[int, str, str]]] = {}
    dropped = {"not_e1b": 0, "no_time_anchor": 0, "ambiguous_placement": 0}
    for mono, raw in captures:
        p = sfrbx_page(ubx.parse_frame(raw))
        if p is None:
            dropped["not_e1b"] += 1
            continue
        by_sv.setdefault(p[0], []).append((mono, p[1], p[2]))

    out: list[Page] = []
    for sv, items in by_sv.items():
        items.sort()
        anchors = []
        for mono, even, odd in items:
            pg = Page(sv, 0, even, odd)
            if pg.crc_ok and pg.nominal and u(pg.word[:6]) == 5:
                anchors.append((mono, gst_seconds(u(pg.word[73:85]), u(pg.word[85:105]))))
        if not anchors:
            dropped["no_time_anchor"] += len(items)
            continue
        for mono, even, odd in items:
            a_mono, a_start = min(anchors, key=lambda a: abs(a[0] - mono))
            steps, rem = divmod(mono - a_mono + PAGE_NS // 2, PAGE_NS)
            if abs(rem - PAGE_NS // 2) > PAGE_NS // 4:
                # jitter beyond +-0.5 s around a page boundary: do not guess
                dropped["ambiguous_placement"] += 1
                continue
            out.append(Page(sv, a_start + 2 * steps, even, odd))
    return out, dropped
