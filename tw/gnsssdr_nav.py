"""Galileo E1-B pages from GNSS-SDR's NavDataMonitor stream, for the OSNMA bound.

GNSS-SDR (gnss-sdr.org) is an open-source software receiver; with a cheap RTL-SDR
dongle it decodes Galileo E1. Its NavDataMonitor sends every decoded navigation
message over UDP as a protobuf `navMsg` (docs/protobuf/nav_message.proto, gnss-sdr
commit 15c3c812): system (1, "E"), signal (2, "1B"), prn (3), tow_at_current_symbol_ms
(4) and nav_message (5) — for Galileo I/NAV one decoded HALF page, 120 bits written
as a string of '0'/'1' (OS SIS ICD "I/NAV Page Part"). Enable it with

    NavDataMonitor.enable_monitor=true
    NavDataMonitor.client_addresses=127.0.0.1
    NavDataMonitor.port=1237

This module pairs each even part with the odd part that follows it from the same
satellite into a 240-bit page. Taking the bits, rather than GNSS-SDR's own OSNMA
verdict, means the verifier here checks them itself; GNSS-SDR is relied on only to
demodulate.

Timing: each page is placed by tw.ubx_inav.place_pages, using GNSS-SDR's TOW of the
even part as the arrival time and the satellite's own word-5 pages to fix it, so a
page that GNSS-SDR timestamped wrongly fails its key rather than moving the bound.
NOT YET PINNED against GNSS-SDR's real output; the first real capture does that.
"""
from __future__ import annotations

import socket
import time

from .galmon_feed import protobuf_fields
from .osnma import Page
from .ubx_inav import place_pages


def parse_datagram(d: bytes) -> dict | None:
    f = protobuf_fields(d)
    try:
        return {"system": f[1][0].decode(), "signal": f[2][0].decode(), "prn": f[3][0],
                "tow_ms": f[4][0], "bits": f[5][0].decode()}
    except (KeyError, IndexError, UnicodeDecodeError):
        return None


def pages_from_datagrams(datagrams: list[bytes]) -> tuple[list[Page], dict]:
    stats = {"datagrams": len(datagrams), "e1b_parts": 0, "unpaired": 0, "malformed": 0}
    pending: dict[int, dict] = {}
    items = []
    for d in datagrams:
        try:
            m = parse_datagram(d)
        except ValueError:
            m = None
        if m is None:
            stats["malformed"] += 1
            continue
        if m["system"] != "E" or m["signal"] != "1B":
            continue
        b = m["bits"]
        if len(b) != 120 or set(b) - {"0", "1"}:
            stats["malformed"] += 1
            continue
        stats["e1b_parts"] += 1
        if b[0] == "0":                                   # even part opens a page
            if m["prn"] in pending:
                stats["unpaired"] += 1
            pending[m["prn"]] = m
            continue
        even = pending.pop(m["prn"], None)
        if even is None or not 0 < m["tow_ms"] - even["tow_ms"] <= 1500:
            stats["unpaired"] += 1
            continue
        items.append((even["tow_ms"] * 1_000_000, m["prn"], even["bits"], b))
    stats["unpaired"] += len(pending)
    pages, dropped = place_pages(items)
    stats.update(dropped)
    stats["crc_ok"] = sum(p.crc_ok for p in pages)
    return pages, stats


def listen(port: int, seconds: int, host: str = "127.0.0.1") -> list[bytes]:
    """Every datagram GNSS-SDR sends to host:port for `seconds`, in arrival order."""
    out, end = [], time.monotonic() + seconds
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind((host, port))
        s.settimeout(1.0)
        while time.monotonic() < end:
            try:
                out.append(s.recv(65535))
            except socket.timeout:
                continue
    return out
