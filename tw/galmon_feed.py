"""Galileo E1-B pages from the galmon transport stream, rebuilt and CRC-checked.

galmon (github.com/berthubert/galmon) is a public network of GNSS receivers, most of
them u-blox; its aggregated stream is served openly (galileo-osnma documents
86.82.68.237, TCP 10000, for exactly this use). Transport, from galmon's README,
"Internals", confirmed on the live stream: repeats of a 4-byte magic `bert`, a
2-byte big-endian length, and a protobuf NavMonMessage (navmon.proto, galmon commit
9bd22436, sha256 6d74b382...).

For Galileo I/NAV (type 3, field `gi` = 5) galmon carries the 128-bit word
(`contents`), the 40-bit OSNMA field (`reserved1`), 24 bits from odd-page bit 58
(`sar`: SAR plus spare), the CRC (`crc`) and the SSP (`ssp`), with the GST of the
page start (`gnssWN`, `gnssTOW`), exactly as galmon's ubx.cc extracts them from
u-blox RXM-SFRBX. From those the whole 240-bit page is rebuilt and its CRC-24Q
checked, so a relay error is a rejected page, never a wrong one.

WHY A RELAY IS ACCEPTABLE HERE, AND WHAT IT CANNOT GIVE

The Galileo lower bound rests on possessing TESLA keys that Galileo kept secret
until broadcast. Nobody — galmon included — can produce such a key early, so the
bound holds whoever relayed the bytes. What a relay CANNOT give is anything about
when or where a page was received: those are the relay's word. Those fields are
recorded and never used for a claim.
"""
from __future__ import annotations

import socket
import time

from .osnma import Page, gst_seconds

MAGIC = b"bert"
GALILEO_INAV = 3
SIG_E1B = 1


def _varint(b: bytes, i: int) -> tuple[int, int]:
    v = s = 0
    while True:
        if i >= len(b):
            raise ValueError("truncated varint")
        c = b[i]
        i += 1
        v |= (c & 0x7F) << s
        if c < 0x80:
            return v, i
        s += 7
        if s > 70:
            raise ValueError("varint too long")


def protobuf_fields(b: bytes) -> dict[int, list]:
    """Field number -> list of values (ints or bytes). Only wire types 0, 1, 2, 5."""
    out: dict[int, list] = {}
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 2:
            n, i = _varint(b, i)
            if i + n > len(b):
                raise ValueError("truncated field")
            v, i = b[i:i + n], i + n
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wt}")
        out.setdefault(f, []).append(v)
    return out


def frames(stream: bytes):
    """Protobuf frames from a raw transport capture; resynchronises on the magic."""
    i = 0
    while True:
        j = stream.find(MAGIC, i)
        if j < 0 or j + 6 > len(stream):
            return
        n = int.from_bytes(stream[j + 4:j + 6], "big")
        if j + 6 + n > len(stream):
            return
        yield stream[j + 6:j + 6 + n]
        i = j + 6 + n


def _bits(b: bytes, n: int | None = None) -> str:
    s = "".join(format(x, "08b") for x in b)
    return s if n is None else s[:n]


def page_from_message(msg: bytes) -> Page | None:
    """A rebuilt E1-B page from one NavMonMessage, or None if it is not one."""
    top = protobuf_fields(msg)
    if top.get(2, [None])[0] != GALILEO_INAV or 5 not in top:
        return None
    gi = protobuf_fields(top[5][0])
    if gi.get(3, [None])[0] != 2 or gi.get(6, [SIG_E1B])[0] != SIG_E1B:
        return None
    try:
        word = _bits(gi[5][0], 128)
        osnma = _bits(gi[7][0], 40)
        sar_spare = _bits(gi[9][0], 24)
        crc = _bits(gi[11][0], 24)
        ssp = format(gi[12][0], "08b")
    except (KeyError, IndexError):
        return None
    if len(word) != 128 or len(osnma) != 40 or len(sar_spare) != 24 or len(crc) != 24:
        return None
    even = "00" + word[:112] + "000000"
    odd = "10" + word[112:] + osnma + sar_spare + crc + ssp + "000000"
    return Page(gi[4][0], gst_seconds(gi[1][0], gi[2][0]), even, odd)


def pages_from_stream(stream: bytes) -> tuple[list[Page], dict]:
    """Deduplicated, CRC-valid pages. Many receivers report the same page; identical
    copies collapse to one. Two different CRC-valid versions of one (satellite, time)
    are a conflict, and both are dropped rather than one being chosen."""
    seen: dict[tuple[int, int], Page] = {}
    conflicted: set[tuple[int, int]] = set()
    stats = {"messages": 0, "e1b": 0, "crc_rejected": 0, "duplicates": 0, "conflicts": 0}
    for m in frames(stream):
        stats["messages"] += 1
        try:
            p = page_from_message(m)
        except ValueError:
            continue
        if p is None:
            continue
        stats["e1b"] += 1
        if not p.crc_ok:
            stats["crc_rejected"] += 1
            continue
        k = (p.sv, p.start)
        if k in conflicted:
            continue
        if k in seen:
            if seen[k] == p:
                stats["duplicates"] += 1
            else:
                stats["conflicts"] += 1
                conflicted.add(k)
                del seen[k]
            continue
        seen[k] = p
    return sorted(seen.values(), key=lambda p: (p.start, p.sv)), stats


def capture(host: str, port: int, seconds: int) -> bytes:
    """The raw transport stream, byte-exact, for `seconds`."""
    out, end = bytearray(), time.monotonic() + seconds
    with socket.create_connection((host, port), timeout=30) as s:
        s.settimeout(5)
        while time.monotonic() < end:
            try:
                d = s.recv(65536)
            except socket.timeout:
                continue
            if not d:
                break
            out += d
    return bytes(out)
