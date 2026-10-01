#!/usr/bin/env python3
"""Record GNSS-SDR's NavDataMonitor UDP stream for an OSNMA bound.

Run GNSS-SDR with NavDataMonitor enabled (see tw/gnsssdr_nav.py), then:

    python scripts/capture_gnsssdr.py --minutes 16 --out live/sdr-<label>
    python scripts/galileo_bound.py live/sdr-<label>

Writes <out>/gnsssdr-datagrams.bin (each datagram as 4-byte big-endian length +
bytes, in arrival order, byte-exact) and <out>/capture.json. NOT YET RUN against a
real GNSS-SDR; the first capture pins the timing assumptions in tw/gnsssdr_nav.py.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(ROOT.parent / "chronology-protocol"))

from tw.gnsssdr_nav import listen  # noqa: E402


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port", type=int, default=1237)
    a = ap.parse_args(argv)
    out = Path(a.out)
    if (out / "gnsssdr-datagrams.bin").exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 2
    started = utc_now()
    dgs = listen(a.port, int(a.minutes * 60))
    blob = b"".join(len(d).to_bytes(4, "big") + d for d in dgs)
    out.mkdir(parents=True, exist_ok=True)
    (out / "gnsssdr-datagrams.bin").write_bytes(blob)
    meta = {"type": "TW-GNSSSDR-CAPTURE/v1", "port": a.port, "host_utc_start": started,
            "host_utc_end": utc_now(), "datagrams": len(dgs),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "note": "host UTC is the capturing machine's clock, not evidence"}
    (out / "capture.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return 0


def read_datagrams(path: Path) -> list[bytes]:
    b, i, out = path.read_bytes(), 0, []
    while i + 4 <= len(b):
        n = int.from_bytes(b[i:i + 4], "big")
        out.append(b[i + 4:i + 4 + n])
        i += 4 + n
    return out


if __name__ == "__main__":
    raise SystemExit(main())
