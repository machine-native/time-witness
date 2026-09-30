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

    pip install pyserial
    python scripts/capture_ubx.py --port COM5 --baud 115200 --seconds 600 --out live/cap1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=int, required=True)
    ap.add_argument("--out", required=True, help="output path prefix")
    a = ap.parse_args(argv)
    try:
        import serial
    except ImportError:
        print("pyserial is required: pip install pyserial", file=sys.stderr)
        return 2
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw_path, idx_path = out.with_suffix(".ubx"), out.with_suffix(".index.jsonl")
    if raw_path.exists() or idx_path.exists():
        print(f"refusing to overwrite an existing capture at {out}", file=sys.stderr)
        return 2
    offset = 0
    end = time.monotonic_ns() + a.seconds * 1_000_000_000
    with serial.Serial(a.port, a.baud, timeout=0.2) as port, \
            raw_path.open("xb") as raw, idx_path.open("x", encoding="utf-8") as idx:
        while time.monotonic_ns() < end:
            chunk = port.read(4096)
            t = time.monotonic_ns()
            if not chunk:
                continue
            raw.write(chunk)
            idx.write(json.dumps({"mono_ns": t, "offset": offset, "length": len(chunk)}) + "\n")
            offset += len(chunk)
    print(f"{offset} bytes -> {raw_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
