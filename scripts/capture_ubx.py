#!/usr/bin/env python3
"""Record a receiver's raw serial output, byte-exact, with host monotonic times.

NOT HARDWARE-TESTED. Written before any receiver is on the bench; whatever the
first real run teaches is pinned here then (wire surprises are
pinned empirically, not argued about).

Writes two files and interprets nothing:

  <out>.ubx        every byte read from the port, in order, unmodified
  <out>.index.jsonl one line per read: {"mono_ns", "offset", "length"}

Keeping the raw stream whole matters: an evidence blob later carries individual
frames, and anyone holding the capture can confirm those frames were cut from it
at the recorded offsets rather than composed afterwards. Parsing, frame selection
and every derived number happen in tw/, never here.

Reads are short on purpose (0.2 s timeout): a Galileo page's time is placed from the
read that delivered it (tw/ubx_inav.captures_from_ubx), so a read must not hold
seconds of data. Do not lengthen the timeout.

    pip install pyserial
    python scripts/capture_ubx.py --port COM5 --baud 115200 --seconds 1200 --out live/cap1 --configure USB

--configure PORT first sends one UBX-CFG-VALSET (tw/ubx_config.py: Galileo E1 on, and
SFRBX, TIM-TM2, TIM-TP, NAV-TIMEGAL, NAV-TIMEGPS, NAV-STATUS once per epoch on the
receiver's USB or UART1 output), RAM layer only, so a power cycle undoes it. The
bytes sent are recorded in <out>.config.json; the receiver's ACK or NAK arrives in the
raw stream like everything else, and is checked there after the capture. Capture at
least 16 minutes: a Galileo bound needs a complete DSM-KROOT.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
    cfg_path = out.with_suffix(".config.json")
    if raw_path.exists() or idx_path.exists() or cfg_path.exists():
        print(f"refusing to overwrite an existing capture at {out}", file=sys.stderr)
        return 2
    offset = 0
    end = time.monotonic_ns() + a.seconds * 1_000_000_000
    with serial.Serial(a.port, a.baud, timeout=0.2) as port, \
            raw_path.open("xb") as raw, idx_path.open("x", encoding="utf-8") as idx:
        if a.configure:
            from tw import ubx_config as uc
            if a.receiver == "m8":
                items = [[n, 1] for n in uc.CAPTURE_MESSAGES]
                frames = uc.m8_capture_frames(a.configure)
            else:
                items = [[n, v] for n, v in uc.capture_config(a.configure)]
                frames = [uc.valset(uc.capture_config(a.configure))]
            for frame in frames:
                port.write(frame)
                port.flush()
                time.sleep(0.1)          # the receiver answers each before the next arrives
            cfg_path.write_text(json.dumps({
                "type": "TW-UBX-CONFIG/v1", "layer": "RAM", "output_port": a.configure,
                "receiver": a.receiver, "items": items, "frames_hex": [f.hex() for f in frames],
                "sent_mono_ns": time.monotonic_ns(),
                "note": "the receiver's ACK/NAK is in the raw capture, not here",
            }, indent=2) + "\n", encoding="utf-8", newline="\n")
        while time.monotonic_ns() < end:
            chunk = port.read(4096)
            t = time.monotonic_ns()
            if not chunk:
                continue
            raw.write(chunk)
            idx.write(json.dumps({"mono_ns": t, "offset": offset, "length": len(chunk)}) + "\n")
            offset += len(chunk)
    print(f"{offset} bytes -> {raw_path}")
    if a.configure:
        from tw import ubx_config as uc
        want = len(uc.CAPTURE_MESSAGES) if a.receiver == "m8" else 1
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
