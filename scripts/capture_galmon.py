#!/usr/bin/env python3
"""Capture live Galileo E1-B I/NAV from the public galmon feed, for an OSNMA bound.

    python scripts/capture_galmon.py --minutes 16 --out live/galmon-<label>
    python scripts/capture_galmon.py --start-utc 2026-10-01T11:58:00 --minutes 35 --out ...

Writes <out>/e1b-frames.bert: the galmon transport frames (magic, length, protobuf)
that carry Galileo E1-B I/NAV, byte-exact and in arrival order, and nothing else.
Other frame types are dropped on purpose: galmon's stream also carries volunteer
stations' observer positions, which have no place in evidence. Also writes
<out>/capture.json: host, port, host UTC at start and end, counts, digests.

The relay is not trusted for anything that matters: pages are CRC-checked when
read, and the OSNMA bound rests on key possession, which no relay can forge early.
Host UTC is the capturing machine's clock and is recorded as such, not as evidence.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(ROOT.parent / "chronology-protocol"))

from tw.galmon_feed import MAGIC, capture, frames, page_from_message  # noqa: E402

HOST, PORT = "86.82.68.237", 10000


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start-utc", help="wait until this UTC time (ISO, no zone) to begin")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args(argv)
    out = Path(a.out)
    if (out / "e1b-frames.bert").exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 2
    if a.start_utc:
        t0 = datetime.datetime.fromisoformat(a.start_utc).replace(tzinfo=datetime.timezone.utc)
        wait = (t0 - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if wait > 0:
            print(f"waiting {wait:.0f} s until {a.start_utc} UTC", flush=True)
            time.sleep(wait)
    started = utc_now()
    raw = capture(a.host, a.port, int(a.minutes * 60))
    ended = utc_now()
    kept, total, e1b = bytearray(), 0, 0
    for m in frames(raw):
        total += 1
        try:
            p = page_from_message(m)
        except ValueError:
            continue
        if p is not None:
            e1b += 1
            kept += MAGIC + len(m).to_bytes(2, "big") + m
    out.mkdir(parents=True, exist_ok=True)
    (out / "e1b-frames.bert").write_bytes(bytes(kept))
    meta = {"type": "TW-GALMON-CAPTURE/v1", "host": a.host, "port": a.port,
            "host_utc_start": started, "host_utc_end": ended,
            "frames_received": total, "e1b_frames_kept": e1b,
            "raw_stream_sha256": hashlib.sha256(raw).hexdigest(),
            "e1b_frames_sha256": hashlib.sha256(bytes(kept)).hexdigest(),
            "note": "host UTC is the capturing machine's clock, not evidence"}
    (out / "capture.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
