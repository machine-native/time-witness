"""u-blox UBX frame codec and the timing messages this witness reads.

Layouts are those of the u-blox interface description, cross-checked field by
field against an independent implementation (pyubx2 1.3.8, commit 993f37d4 — see
docs/SOURCES.md). That is a cross-check, not the primary document: before any
hardware claim, each layout is pinned against bytes from a real receiver.

Parsing is strict. A frame with a bad checksum, a wrong length for its message,
or trailing bytes is an error, never a best-effort decode: the verifier re-parses
these exact bytes, and a lenient parser would let two readers disagree about what
the evidence says.

Bitfields are numbered from the least-significant bit, as pyubx2 and the
interface description both do.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SYNC = b"\xb5\x62"

TIM_TP = (0x0D, 0x01)
TIM_TM2 = (0x0D, 0x03)
NAV_STATUS = (0x01, 0x03)
NAV_TIMEGPS = (0x01, 0x20)
NAV_TIMEGAL = (0x01, 0x25)
RXM_SFRBX = (0x02, 0x13)
SEC_OSNMA = (0x27, 0x0A)

NAMES = {
    TIM_TP: "TIM-TP", TIM_TM2: "TIM-TM2", NAV_STATUS: "NAV-STATUS",
    NAV_TIMEGPS: "NAV-TIMEGPS", NAV_TIMEGAL: "NAV-TIMEGAL",
    RXM_SFRBX: "RXM-SFRBX", SEC_OSNMA: "SEC-OSNMA",
}

# timeRefGnss (TIM-TP refInfo bits 0-3)
GNSS_GPS = 0
GNSS_GALILEO = 3


class UBXError(ValueError):
    pass


def checksum(body: bytes) -> bytes:
    """8-bit Fletcher over class, id, length and payload."""
    a = b = 0
    for x in body:
        a = (a + x) & 0xFF
        b = (b + a) & 0xFF
    return bytes([a, b])


def encode(cls: int, mid: int, payload: bytes) -> bytes:
    body = bytes([cls, mid]) + struct.pack("<H", len(payload)) + payload
    return SYNC + body + checksum(body)


@dataclass(frozen=True)
class Frame:
    cls: int
    mid: int
    payload: bytes

    @property
    def key(self):
        return (self.cls, self.mid)

    @property
    def name(self):
        return NAMES.get(self.key, f"UBX-{self.cls:02X}-{self.mid:02X}")

    def raw(self) -> bytes:
        return encode(self.cls, self.mid, self.payload)


def parse_frame(raw: bytes) -> Frame:
    """Exactly one frame, nothing before or after it."""
    if len(raw) < 8 or raw[:2] != SYNC:
        raise UBXError("not a UBX frame")
    n = struct.unpack("<H", raw[4:6])[0]
    if len(raw) != 8 + n:
        raise UBXError(f"frame length {len(raw)} != 8 + declared {n}")
    body = raw[2:6 + n]
    if raw[6 + n:] != checksum(body):
        raise UBXError("checksum mismatch")
    return Frame(raw[2], raw[3], raw[6:6 + n])


def split_stream(data: bytes):
    """Frames found in a raw capture, in order, with each frame's offset.

    Bytes between frames (NMEA sentences, line noise) are skipped. A candidate
    frame whose checksum fails is skipped too, and resynchronisation restarts one
    byte after its sync word; the offsets let a capture log show what was dropped.
    """
    out, i = [], 0
    while True:
        j = data.find(SYNC, i)
        if j < 0 or j + 8 > len(data):
            return out
        n = struct.unpack("<H", data[j + 4:j + 6])[0]
        end = j + 8 + n
        if end <= len(data):
            try:
                out.append((j, parse_frame(data[j:end])))
                i = end
                continue
            except UBXError:
                pass
        i = j + 1


def _need(f: Frame, key, size):
    if f.key != key:
        raise UBXError(f"expected {NAMES[key]}, got {f.name}")
    if len(f.payload) != size:
        raise UBXError(f"{NAMES[key]} payload {len(f.payload)} != {size}")


def _bits(v: int, lo: int, width: int) -> int:
    return (v >> lo) & ((1 << width) - 1)


def tim_tp(f: Frame) -> dict:
    """Time of the NEXT time pulse. towSubMS is in units of 2^-32 ms; qErr in ps."""
    _need(f, TIM_TP, 16)
    tow_ms, tow_sub, qerr, week, flags, ref = struct.unpack("<IIiHBB", f.payload)
    return {
        "tow_ms": tow_ms, "tow_sub_ms_2p32": tow_sub, "qerr_ps": qerr, "week": week,
        "time_base": _bits(flags, 0, 1),        # 0 = GNSS, 1 = UTC
        "utc_available": _bits(flags, 1, 1),
        "raim": _bits(flags, 2, 2),
        "qerr_invalid": _bits(flags, 4, 1),
        "time_ref_gnss": _bits(ref, 0, 4),
        "utc_standard": _bits(ref, 4, 4),
    }


def tim_tm2(f: Frame) -> dict:
    """Time mark on an external input. Sub-millisecond fields and accEst are in ns."""
    _need(f, TIM_TM2, 28)
    (ch, flags, count, wn_r, wn_f, tow_ms_r, tow_sub_r, tow_ms_f, tow_sub_f,
     acc) = struct.unpack("<BBHHHIIIII", f.payload)
    return {
        "channel": ch, "count": count,
        "mode": _bits(flags, 0, 1), "run": _bits(flags, 1, 1),
        "new_falling": _bits(flags, 2, 1),
        "time_base": _bits(flags, 3, 2),        # 0 receiver, 1 GNSS, 2 UTC
        "utc": _bits(flags, 5, 1), "time_valid": _bits(flags, 6, 1),
        "new_rising": _bits(flags, 7, 1),
        "wn_r": wn_r, "tow_ms_r": tow_ms_r, "tow_sub_ns_r": tow_sub_r,
        "wn_f": wn_f, "tow_ms_f": tow_ms_f, "tow_sub_ns_f": tow_sub_f,
        "acc_est_ns": acc,
    }


def nav_timegps(f: Frame) -> dict:
    _need(f, NAV_TIMEGPS, 16)
    itow, ftow, week, leap, valid, tacc = struct.unpack("<IihbBI", f.payload)
    return {"itow_ms": itow, "ftow_ns": ftow, "week": week, "leap_s": leap,
            "tow_valid": _bits(valid, 0, 1), "week_valid": _bits(valid, 1, 1),
            "leap_valid": _bits(valid, 2, 1), "tacc_ns": tacc}


def nav_timegal(f: Frame) -> dict:
    _need(f, NAV_TIMEGAL, 20)
    itow, gtow, fgtow, wno, leap, valid, tacc = struct.unpack("<IIihbBI", f.payload)
    return {"itow_ms": itow, "tow_s": gtow, "ftow_ns": fgtow, "week": wno, "leap_s": leap,
            "tow_valid": _bits(valid, 0, 1), "week_valid": _bits(valid, 1, 1),
            "leap_valid": _bits(valid, 2, 1), "tacc_ns": tacc}


def nav_status(f: Frame) -> dict:
    _need(f, NAV_STATUS, 16)
    itow, fix, flags, fixstat, flags2, ttff, msss = struct.unpack("<IBBBBII", f.payload)
    return {"itow_ms": itow, "gps_fix": fix, "fix_ok": _bits(flags, 0, 1),
            "wkn_set": _bits(flags, 2, 1), "tow_set": _bits(flags, 3, 1),
            # 0 unknown/off, 1 no spoofing indicated, 2 indicated, 3 multiple indications
            "spoof_det_state": _bits(flags2, 3, 2), "ttff_ms": ttff, "msss_ms": msss}


def rxm_sfrbx(f: Frame) -> dict:
    if f.key != RXM_SFRBX or len(f.payload) < 8:
        raise UBXError("not an RXM-SFRBX frame")
    gnss, sv, sig, freq, nwords, chn, ver, _ = f.payload[:8]
    if len(f.payload) != 8 + 4 * nwords:
        raise UBXError("RXM-SFRBX numWords disagrees with length")
    words = list(struct.unpack(f"<{nwords}I", f.payload[8:]))
    return {"gnss_id": gnss, "sv_id": sv, "sig_id": sig, "freq_id": freq,
            "channel": chn, "version": ver, "words": words}


def sec_osnma_header(f: Frame) -> dict:
    """Only the leading bytes are decoded. Everything this returns is the
    RECEIVER'S OWN CLAIM about OSNMA; it is recorded, never treated as verified."""
    if f.key != SEC_OSNMA or len(f.payload) < 4:
        raise UBXError("not a SEC-OSNMA frame")
    ver, nma, mon = f.payload[0], f.payload[1], f.payload[2]
    return {"version": ver,
            "header_auth_status": _bits(nma, 0, 1), "nma_status": _bits(nma, 1, 2),
            "chain_in_force": _bits(nma, 3, 2), "cpks": _bits(nma, 5, 3),
            "osnma_enabled": _bits(mon, 0, 1), "num_svs": _bits(mon, 1, 5)}


DECODERS = {TIM_TP: tim_tp, TIM_TM2: tim_tm2, NAV_STATUS: nav_status,
            NAV_TIMEGPS: nav_timegps, NAV_TIMEGAL: nav_timegal,
            RXM_SFRBX: rxm_sfrbx, SEC_OSNMA: sec_osnma_header}
