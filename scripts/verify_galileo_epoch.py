#!/usr/bin/env python3
"""Verify a Galileo capture anchored in a chronology-protocol epoch: both bounds.

    python scripts/verify_galileo_epoch.py BUNDLE CAPTURE [--kind galmon|android] [--out REPORT]

BUNDLE is the epoch's sandwich bundle (chronology-protocol vectors/valid/), CAPTURE
the exact bytes it commits to. The verdict is GALILEO_BOUND when the sandwich
verifies, commits to exactly these bytes, and the bytes contain a TESLA key that
verifies under the trust anchor:

    Galileo key release  <  capture  <  anchor block C  (< burial blocks)

The trust anchor is the Merkle root in trust/merkle-tree/*.authenticated.json
(authenticated through the EUSPA PKI), and the public key is the one the satellites
themselves broadcast in live/galmon-2026-10-01-pkr, checked against that root. Both
are public, so this needs no account with anyone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
except ImportError:
    sys.path.insert(0, str(ROOT.parent / "chronology-protocol"))

from tw import osnma  # noqa: E402
from tw.galileo_binding import verify_galileo_binding  # noqa: E402
from tw.galmon_feed import pages_from_stream  # noqa: E402

RECORD = next((ROOT / "trust" / "merkle-tree").glob("*.authenticated.json"))
PKR_CAPTURE = ROOT / "live" / "galmon-2026-10-01-pkr" / "e1b-frames.bert"


def trust_anchor():
    root = bytes.fromhex(json.loads(RECORD.read_text(encoding="utf-8"))["merkle_root"])
    pages, _ = pages_from_stream(PKR_CAPTURE.read_bytes())
    for d in osnma.collect_dsms(osnma.subframes(pages)):
        if d["dsm_id"] >= 12:
            v = osnma.verify_pkr(d["bits"], root)
            if v["merkle_ok"] and v["pdp_ok"]:
                return root, [v]
    raise SystemExit("no satellite-broadcast public key verifies against the root")


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    kind = argv[argv.index("--kind") + 1] if "--kind" in argv else "galmon"
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else None
    skip = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a.startswith("--")}
    bundle, capture = [Path(a) for a in argv if not a.startswith("--") and a not in skip]

    root, keys = trust_anchor()
    r = verify_galileo_binding(bundle.read_bytes(), capture.read_bytes(), kind, root, keys)
    r["merkle_root"] = root.hex().upper()
    text = json.dumps(r, indent=2, default=str) + "\n"
    if out:
        out.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")
    return 0 if r["verdict"] == "GALILEO_BOUND" else 1


if __name__ == "__main__":
    raise SystemExit(main())
