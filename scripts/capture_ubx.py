#!/usr/bin/env python3
"""Record a receiver's evidence frames, byte-exact, with host monotonic times.

NOT HARDWARE-TESTED. Written before any receiver is on the bench; whatever the
first real run teaches is pinned here then (wire surprises are
pinned empirically, not argued about).

Writes three files and interprets nothing beyond framing:

  <out>.ubx          every allowed UBX frame, byte-exact, in arrival order
  <out>.index.jsonl  one line per read that yielded frames: {"mono_ns", "offset", "length"}
  <out>.capture.json what was kept and what was dropped, by message type

Only frames on the allowlist in tw/ubx_filter.py are kept: Galileo and GPS
sub-frames, time marks, time-pulse and navigation-time data, fix status, and the
receiver's replies. Everything else -- NMEA sentences, position messages, partial or
corrupt frames -- is dropped as it arrives and only counted, because a capture is
published and a receiver's default output states where its antenna is. Kept frames
are unmodified, so anyone holding the capture can confirm an evidence blob's frames
were cut from it rather than composed afterwards.

Reads are short on purpose (0.2 s timeout): a Galileo page's time is placed from the
read that completed it (tw/ubx_inav.captures_from_ubx), so a read must not hold
seconds of data. Do not lengthen the timeout. The port is read throughout, including
while configuration is being sent.

    pip install pyserial
    python scripts/capture_ubx.py --port COM5 --baud 115200 --seconds 1200 --out live/cap1 --configure USB
    python scripts/capture_ubx.py --port COM5 --baud 9600 --seconds 1800 --out live/cap1 --configure UART1 --receiver m8

--configure PORT first sends the capture configuration (tw/ubx_config.py), RAM only,
so a power cycle undoes it: for u-blox 9/10 one UBX-CFG-VALSET (Galileo E1 on, and
SFRBX, TIM-TM2, TIM-TP, NAV-TIMEGAL, NAV-TIMEGPS, NAV-STATUS once per epoch on that
output); for u-blox 8 (--receiver m8) one UBX-CFG-MSG per message, the default NMEA
sentences off first so 9600 baud carries the evidence. The bytes sent are recorded in
<out>.config.json; the receiver's ACK or NAK frames are kept in the capture and checked
there at the end. Capture at least 16 minutes: a Galileo bound needs a complete
DSM-KROOT.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tw.ubx_filter import ALLOWED, CaptureFilter  # noqa: E402


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=int, required=True)
    ap.add_argument("--out", required=True, help="output path prefix")
    ap.add_argument("--configure", choices=("USB", "UART1"),
                    help="send the capture configuration for this receiver output port first")
    ap.add_argument("--receiver", choices=("valset", "m8"), default="valset",
                    help="u-blox 9/10 (VALSET, default) or u-blox 8 (per-message CFG-MSG); "
                         "setup_receiver.py says which")
    a = ap.parse_args(argv)
    try:
        import serial
    except ImportError:
        print("pyserial is required: pip install pyserial", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_path, idx_path = out.with_suffix(".ubx"), out.with_suffix(".index.jsonl")
    cfg_path, sum_path = out.with_suffix(".config.json"), out.with_suffix(".capture.json")
    if any(p.exists() for p in (raw_path, idx_path, cfg_path, sum_path)):
        print(f"refusing to overwrite an existing capture at {out}", file=sys.stderr)
        return 2

    flt = CaptureFilter()
    offset = 0
    started = utc_now()
    with serial.Serial(a.port, a.baud, timeout=0.2) as port, \
            raw_path.open("xb") as raw, idx_path.open("x", encoding="utf-8") as idx:

        def pump(until_ns: int) -> None:
            nonlocal offset
            while time.monotonic_ns() < until_ns:
                chunk = port.read(4096)
                t = time.monotonic_ns()
                kept = flt.feed(chunk) if chunk else b""
                if kept:
                    raw.write(kept)
                    idx.write(json.dumps({"mono_ns": t, "offset": offset,
                                          "length": len(kept)}) + "\n")
                    offset += len(kept)

        frames = []
        if a.configure:
            from tw import ubx_config as uc
            if a.receiver == "m8":
                frames = uc.m8_capture_frames(a.configure)
            else:
                frames = [uc.valset(uc.capture_config(a.configure))]
            for frame in frames:
                port.write(frame)
                port.flush()
                pump(time.monotonic_ns() + 150_000_000)   # its answer, read and kept
            cfg_path.write_text(json.dumps({
                "type": "TW-UBX-CONFIG/v1", "layer": "RAM", "output_port": a.configure,
                "receiver": a.receiver, "frames_hex": [f.hex() for f in frames],
                "note": "the receiver's ACK/NAK frames are in the capture, not here",
            }, indent=2) + "\n", encoding="utf-8", newline="\n")
        pump(time.monotonic_ns() + a.seconds * 1_000_000_000)

    stats = flt.stats()
    sum_path.write_text(json.dumps({
        "type": "TW-UBX-CAPTURE/v1", "port_baud": a.baud, "seconds": a.seconds,
        "host_utc_start": started, "host_utc_end": utc_now(), "bytes_kept": offset,
        "allowed": sorted(f"{c:02X}-{m:02X}" for c, m in ALLOWED), **stats,
        "note": "only allowed UBX frames are kept; host UTC is this machine's clock, "
                "not evidence",
    }, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{offset} bytes kept -> {raw_path}; dropped {stats['dropped']}")
    if a.configure:
        from tw import ubx_config as uc
        want = len(frames)
        got = uc.acks(raw_path.read_bytes(), uc.CFG_MSG if a.receiver == "m8" else uc.VALSET)
        if got[:want] == [True] * want:
            print("configuration ACKed")
        elif False in got:
            print(f"configuration NAKed ({got.count(False)} of {want}): not applied as asked")
            return 1
        else:
            print(f"{len(got)} of {want} acknowledgements seen: check the port and baud rate")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
