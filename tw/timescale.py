"""GNSS time scales to the chronology's UTC frame, in exact integer picoseconds.

chronology-protocol SPEC §4: GPS weeks and leap-second counts MUST NOT determine
consensus. They are source metadata. This module is the projection that turns
them into the declared-origin UTC picosecond frame every other witness uses, so a
hardware witness can sit in the same quorum as NTP and Roughtime witnesses.

What the projection assumes, stated so it can be checked:

- GPS time began 1980-01-06T00:00:00Z, Unix second 315964800.
- Galileo System Time week 0 began at GPS week 1024, and GST tracks GPST to within
  tens of nanoseconds (the GGTO). GST seconds-of-week equal GPS seconds-of-week.
- UTC = GNSS time - leap seconds, with the leap-second count taken from the
  receiver's own message and used only when that message marks it valid.
- The remaining offset between GNSS time and UTC (a few ns to tens of ns, the
  broadcast A0/GGTO terms) is NOT modelled; it is covered by a declared
  uncertainty term (`timescale_unc_ps` in the device profile).

Absolute picoseconds since 1970 exceed the canonical-CBOR uint64 ceiling, so they
exist only as intermediate Python integers. Stored values are frame-relative.
"""
from __future__ import annotations

PS = 1_000_000_000_000
PS_PER_MS = 1_000_000_000
PS_PER_NS = 1_000
WEEK_S = 604_800
GPS_EPOCH_UNIX_S = 315_964_800
GST_WEEK_OFFSET = 1024

FRAME_PREFIX = "UTC-PS-ORIGIN-"


def frame_for_origin(origin_unix_s: int) -> str:
    """Same frame string as chronology-protocol's sandwich module."""
    return f"{FRAME_PREFIX}{origin_unix_s}/v1"


def day_origin(abs_utc_ps: int) -> int:
    """00:00:00Z of the UTC day containing the instant, as a Unix second."""
    s = abs_utc_ps // PS
    return s - s % 86_400


def gnss_week_ps(system: str, week: int) -> int:
    """Picoseconds of GPS time at the start of the given week of `system`."""
    if system == "GPS":
        return week * WEEK_S * PS
    if system == "GAL":
        return (week + GST_WEEK_OFFSET) * WEEK_S * PS
    raise ValueError(f"unsupported GNSS time system: {system}")


def tp_sub_ms_to_ps(sub_2p32: int) -> tuple[int, int]:
    """TIM-TP towSubMS (units of 2^-32 ms) -> (floor ps, rounding residue bound ps).

    2^-32 ms is ~0.23 ps, so the floor loses under 1 ps; the residue is reported
    so it can be added to the uncertainty rather than silently dropped.
    """
    num = sub_2p32 * PS_PER_MS
    return num >> 32, (1 if num & 0xFFFFFFFF else 0)


def gnss_to_abs_utc_ps(gnss_ps: int, leap_s: int) -> int:
    """GPS-time picoseconds since the GPS epoch -> absolute UTC Unix picoseconds."""
    return gnss_ps + (GPS_EPOCH_UNIX_S - leap_s) * PS
