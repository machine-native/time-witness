#!/usr/bin/env python3
"""Make a publishable extract of a GnssLogger log: Galileo pages only, no position.

    python scripts/extract_android_galileo.py ORIGINAL_LOG OUT_DIR

A GnssLogger log reveals where it was recorded: `Fix` lines carry latitude and
longitude, and `Raw` lines carry pseudoranges from which a position can be computed.
None of that is needed for the Galileo bound, so none of it is kept. The extract has:

  - the `# Version:` header line (app version, phone model, GNSS chip);
  - `Raw,<ElapsedRealtimeMillis>` — the arrival-time field only — whenever it changes;
  - every Galileo I/NAV `Nav` line (type 1537), unchanged.

tw.android_nav reads the extract exactly as it reads the original, and the script
refuses to write unless both yield the same pages. OUT_DIR/extract.json records the
original's sha256 and the filter, so anyone holding the original can rebuild the
extract and compare.
"""
from __future__ import annotations

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

from tw.android_nav import TYPE_GAL_I, pages_from_log  # noqa: E402

FILTER = ("keep '# Version:' header; 'Raw,<ElapsedRealtimeMillis>' only, when it changes; "
          "Nav lines of type 1537 unchanged; drop everything else")


def extract(text: str) -> str:
    out, last_ms = [], None
    for line in text.splitlines():
        if line.startswith("# Version:"):
            out.append(line)
        elif line.startswith("Raw,"):
            ms = line.split(",")[1]
            if ms != last_ms:
                out.append("Raw," + ms)
                last_ms = ms
        elif line.startswith("Nav,"):
            f = line.split(",")
            if len(f) > 2 and f[2] == str(TYPE_GAL_I):
                out.append(line)
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    src, out = Path(argv[0]), Path(argv[1])
    raw = src.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    ex = extract(text)
    p_orig, s_orig = pages_from_log(text)
    p_ex, s_ex = pages_from_log(ex)
    if p_orig != p_ex:
        print("refusing: the extract does not yield the same pages as the original",
              file=sys.stderr)
        return 1
    assert "Fix," not in ex and not any(
        l.startswith("Raw,") and l.count(",") > 1 for l in ex.splitlines())
    out.mkdir(parents=True, exist_ok=True)
    (out / "galileo-extract.txt").write_text(ex, encoding="utf-8", newline="\n")
    meta = {"type": "TW-ANDROID-GALILEO-EXTRACT/v1",
            # GnssLogger names logs by LOCAL clock time, which reveals the recording's
            # time zone; the name is withheld and the digest identifies the original.
            "original_name": "(withheld: GnssLogger names files by local clock time)",
            "original_sha256": hashlib.sha256(raw).hexdigest(),
            "original_bytes": len(raw), "filter": FILTER,
            "extract_sha256": hashlib.sha256(ex.encode("utf-8")).hexdigest(),
            "pages": s_ex,
            "header": next((l for l in ex.splitlines() if l.startswith("# Version:")), None)}
    (out / "extract.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
