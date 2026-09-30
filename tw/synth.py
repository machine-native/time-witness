"""Synthetic UBX frames for tests and vectors. NOT EVIDENCE.

Every frame built here is produced by this repository's own encoder from this
repository's own reading of the layouts. A test that passes on them proves the
codec and the derivation agree with each other — nothing about any receiver.
Vectors built from them are labelled SYNTHETIC in their filenames and metadata,
and chronology-protocol invariant 14 applies: a simulator cannot establish a
GNSS or hardware claim.
"""
from __future__ import annotations

import struct

from . import ubx


def tim_tp(tow_ms, tow_sub_2p32, qerr_ps, week, *, time_base=0, utc=1, qerr_invalid=0,
           time_ref_gnss=ubx.GNSS_GPS, utc_standard=0):
    flags = time_base | (utc << 1) | (qerr_invalid << 4)
    ref = time_ref_gnss | (utc_standard << 4)
    return ubx.encode(*ubx.TIM_TP, struct.pack("<IIiHBB", tow_ms, tow_sub_2p32, qerr_ps,
                                               week, flags, ref))


def tim_tm2(count, wn_r, tow_ms_r, tow_sub_ns_r, acc_est_ns, *, ch=0, time_base=1,
            time_valid=1, new_rising=1):
    flags = (time_base << 3) | (time_valid << 6) | (new_rising << 7) | 0b10  # run=1
    return ubx.encode(*ubx.TIM_TM2, struct.pack("<BBHHHIIIII", ch, flags, count, wn_r, 0,
                                                tow_ms_r, tow_sub_ns_r, 0, 0, acc_est_ns))


def nav_timegps(itow_ms, ftow_ns, week, leap_s, tacc_ns, *, valid=0b111):
    return ubx.encode(*ubx.NAV_TIMEGPS, struct.pack("<IihbBI", itow_ms, ftow_ns, week,
                                                    leap_s, valid, tacc_ns))


def nav_timegal(itow_ms, tow_s, ftow_ns, week, leap_s, tacc_ns, *, valid=0b111):
    return ubx.encode(*ubx.NAV_TIMEGAL, struct.pack("<IIihbBI", itow_ms, tow_s, ftow_ns,
                                                    week, leap_s, valid, tacc_ns))


def nav_status(*, itow_ms=0, fix=3, fix_ok=1, spoof=1):
    flags = fix_ok | (1 << 2) | (1 << 3)
    return ubx.encode(*ubx.NAV_STATUS, struct.pack("<IBBBBII", itow_ms, fix, flags, 0,
                                                   spoof << 3, 30_000, 1_000_000))


def sec_osnma(*, enabled=1, num_svs=6):
    payload = bytes([2, 0b0000_0101, enabled | (num_svs << 1), 0]) + bytes(4)
    return ubx.encode(*ubx.SEC_OSNMA, payload)
