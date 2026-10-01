"""Galileo E1-B pages from an Android GnssLogger log, for the OSNMA bound.

Android exposes navigation-message bits through GnssNavigationMessage (API 24+). For
Galileo I/NAV (type 0x0601) each message is one page: the even and odd parts, 114
bits each with sync and tail removed, packed MSB first into 29 bytes (AOSP
frameworks/base location/java/android/location/GnssNavigationMessage.java, getData()).
Not every phone reports them: EUSPA's smartphone OSNMA guidelines say only some
chipsets do, so a log is the only way to know for a given phone.

GnssLogger (github.com/google/gps-measurement-tools, FileLogger.java at commit
93c63870) writes one line per message:

    Nav,Svid,Type,Status,MessageId,Sub-messageId,<data bytes as signed decimals>

with no timestamp. Arrival time is taken from the ElapsedRealtimeMillis of the most
recent `Raw` line, and pages are placed by tw.ubx_inav.place_pages: each satellite's
word-5 time fixes it, the rest go 2 s apart. Every page is CRC-checked and a page
placed at the wrong time fails its key check, so a mistake here costs coverage, not
correctness. How tightly a given phone's arrival times track page boundaries is a
property of that phone: it is measured on its first log, not assumed.
"""
from __future__ import annotations

from .osnma import Page
from .ubx_inav import place_pages

TYPE_GAL_I = 0x0601
NAV_BYTES = 29


def page_bits(data: list[int]) -> tuple[str, str] | None:
    if len(data) != NAV_BYTES:
        return None
    bits = "".join(format(b & 0xFF, "08b") for b in data)
    return bits[:114] + "000000", bits[114:228] + "000000"


def read_log(text: str) -> tuple[list[tuple[int, int, str, str]], dict]:
    """(arrival monotonic ns, svid, even, odd) for every Galileo I/NAV Nav line."""
    items, stats = [], {"nav_lines": 0, "galileo_inav": 0, "malformed": 0,
                        "before_first_raw": 0}
    mono_ms = None
    for line in text.splitlines():
        if line.startswith("Raw,"):
            f = line.split(",")
            try:
                mono_ms = int(f[1])
            except (IndexError, ValueError):
                pass
        elif line.startswith("Nav,"):
            stats["nav_lines"] += 1
            f = line.split(",")
            try:
                sv, typ = int(f[1]), int(f[2])
                data = [int(x) for x in f[6:]]
            except (IndexError, ValueError):
                stats["malformed"] += 1
                continue
            if typ != TYPE_GAL_I:
                continue
            stats["galileo_inav"] += 1
            pb = page_bits(data)
            if pb is None:
                stats["malformed"] += 1
                continue
            if mono_ms is None:
                stats["before_first_raw"] += 1
                continue
            items.append((mono_ms * 1_000_000, sv, *pb))
    return items, stats


def pages_from_log(text: str) -> tuple[list[Page], dict]:
    items, stats = read_log(text)
    pages, dropped = place_pages(items)
    stats.update(dropped)
    stats["crc_ok"] = sum(p.crc_ok for p in pages)
    return pages, stats
