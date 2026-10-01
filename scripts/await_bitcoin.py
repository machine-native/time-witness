#!/usr/bin/env python3
"""Upgrade pending OpenTimestamps proofs until Bitcoin attests, then bracket them.

    python scripts/await_bitcoin.py EVIDENCE [EVIDENCE ...] [--every-min 30] [--max-hours 12]

Every interval it runs chronology-protocol's scripts/ots_upgrade.py on each
<evidence>.ots; once a proof carries a Bitcoin attestation it runs
scripts/bracket.py on that evidence. Stops when all are attested or the time runs
out (calendars usually commit within a few hours, occasionally longer).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    import ctp  # noqa: F401
    CTP = Path(ctp.__file__).resolve().parents[1]
except ImportError:
    CTP = ROOT.parent / "chronology-protocol"
    sys.path.insert(0, str(CTP))

from ctp.ots import parse_file  # noqa: E402


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    every = float(argv[argv.index("--every-min") + 1]) if "--every-min" in argv else 30.0
    hours = float(argv[argv.index("--max-hours") + 1]) if "--max-hours" in argv else 12.0
    skip = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a.startswith("--")}
    todo = [Path(a) for a in argv if not a.startswith("--") and a not in skip]
    end = time.monotonic() + hours * 3600
    while todo and time.monotonic() < end:
        for ev in list(todo):
            ots = Path(str(ev) + ".ots")
            subprocess.run([sys.executable, str(CTP / "scripts" / "ots_upgrade.py"), str(ots)],
                           capture_output=True)
            if parse_file(ots).bitcoin:
                print(f"{ev}: Bitcoin attestation present", flush=True)
                subprocess.run([sys.executable, str(ROOT / "scripts" / "bracket.py"), str(ev)])
                todo.remove(ev)
        if todo:
            print(f"{time.strftime('%H:%M:%S')} still pending: {[t.name for t in todo]}", flush=True)
            time.sleep(every * 60)
    return 0 if not todo else 2


if __name__ == "__main__":
    raise SystemExit(main())
