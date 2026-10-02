#!/usr/bin/env python3
"""Measure the oscillator behind EXTINT from a capture's time marks.

    python scripts/oscillator_report.py live/<label>.ubx [--out live/<label>.oscillator.json]

Reads every UBX-TIM-TM2 rising-edge mark with a valid GNSS time base, numbers the
edges by the receiver's counter, and reports the oscillator's frequency offset, the
residual edge jitter, the Allan deviation and the receiver's own accuracy estimate
(tw/oscillator.py). A measurement of the oscillator against the receiver, not a claim
about time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tw import oscillator  # noqa: E402


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else None
    paths = [a for i, a in enumerate(argv) if not a.startswith("--")
             and (i == 0 or argv[i - 1] != "--out")]
    if len(paths) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    edges, dropped = oscillator.rising_edges(Path(paths[0]).read_bytes())
    try:
        r = oscillator.analyse(edges)
    except ValueError as e:
        print(f"no measurement: {e} ({len(edges)} usable edges; dropped {dropped})")
        return 1
    r = {"type": "TW-OSCILLATOR-REPORT/v1", "capture": Path(paths[0]).name,
         "dropped_marks": dropped, **r,
         "note": "oscillator measured against the receiver's time marks; not a claim about time"}
    text = json.dumps(r, indent=2) + "\n"
    if out:
        out.write_text(text, encoding="utf-8", newline="\n")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
