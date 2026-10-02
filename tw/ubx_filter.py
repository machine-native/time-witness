"""Keep only the UBX frames a capture needs; drop everything else as it arrives.

A receiver's serial stream carries more than the evidence: NMEA sentences by
default, and some of them (GGA, GLL, RMC, GNS) state where the antenna is, as do
UBX position messages if anything enables them. A capture is evidence meant for
publication, so it must not hold the place it was taken. The galmon capture drops
every message type it does not need for the same reason; this is the same rule for
a receiver of our own.

The filter is an allowlist, not a blocklist: anything that is not a complete,
checksum-valid UBX frame of an allowed type is dropped and counted, never kept.
Allowed frames are passed through byte for byte, so a kept frame is exactly what the
receiver sent. Frames split across serial reads are held until complete and released
with the read that completed them, which is the arrival time page placement uses
(tw/ubx_inav.captures_from_ubx).
"""
from __future__ import annotations

import struct
from collections import Counter

from .ubx import (NAV_STATUS, NAV_TIMEGAL, NAV_TIMEGPS, RXM_SFRBX, SYNC, TIM_TM2, TIM_TP,
                  UBXError, parse_frame)

ACK_ACK = (0x05, 0x01)
ACK_NAK = (0x05, 0x00)
MON_VER = (0x0A, 0x04)

# None of these carries a position: SFRBX is satellite data, TIM-* and NAV-TIME* are
# times, NAV-STATUS is fix state and timing, ACK/NAK and MON-VER are receiver replies.
ALLOWED = frozenset({RXM_SFRBX, TIM_TM2, TIM_TP, NAV_TIMEGAL, NAV_TIMEGPS, NAV_STATUS,
                     ACK_ACK, ACK_NAK, MON_VER})
MAX_PAYLOAD = 1024          # longer than any allowed frame; a larger length is a false sync


class CaptureFilter:
    def __init__(self, allowed=ALLOWED):
        self.allowed = allowed
        self.buf = bytearray()
        self.kept = Counter()
        self.dropped = Counter()

    def feed(self, chunk: bytes) -> bytes:
        """Allowed, complete frames now available, byte-exact and in order."""
        self.buf += chunk
        out = bytearray()
        while True:
            j = self.buf.find(SYNC)
            if j < 0:
                keep = 1 if self.buf[-1:] == SYNC[:1] else 0       # a sync may straddle reads
                self.dropped["non_ubx_bytes"] += len(self.buf) - keep
                del self.buf[:len(self.buf) - keep]
                break
            if j:
                self.dropped["non_ubx_bytes"] += j
                del self.buf[:j]
            if len(self.buf) < 6:
                break
            n = struct.unpack("<H", self.buf[4:6])[0]
            if n > MAX_PAYLOAD:
                self.dropped["non_ubx_bytes"] += 1
                del self.buf[:1]
                continue
            if len(self.buf) < 8 + n:
                break
            raw = bytes(self.buf[:8 + n])
            try:
                f = parse_frame(raw)
            except UBXError:
                self.dropped["non_ubx_bytes"] += 1
                del self.buf[:1]
                continue
            del self.buf[:8 + n]
            name = f"{f.cls:02X}-{f.mid:02X}"
            if f.key in self.allowed:
                out += raw
                self.kept[name] += 1
            else:
                self.dropped[name] += 1
        return bytes(out)

    def stats(self) -> dict:
        return {"kept": dict(sorted(self.kept.items())),
                "dropped": dict(sorted(self.dropped.items())),
                "pending_bytes": len(self.buf)}
